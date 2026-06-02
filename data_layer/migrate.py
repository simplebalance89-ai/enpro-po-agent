#!/usr/bin/env python3
"""
EnPro PO Agent — Data Migration Script
Migrates flat JSON + CSV files into SQLite.

Usage:
    python data_layer/migrate.py

What it does:
    1. Creates SQLite DB at data/po_store.db (if not exists)
    2. Reads all data/po_store/*.json files
    3. Inserts into SQLite po_store + po_lines tables
    4. Reads all crosswalk CSVs from data/crosswalks/
    5. Inserts into SQLite crosswalk_* tables
    6. Validates: row counts match, key fields present
    7. Archives old JSON files (renames to .json.bak)

Safe to run multiple times — uses INSERT OR REPLACE.
"""

import csv
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "po_store.db"
PO_STORE_DIR = Path(settings.po_store_dir) if hasattr(settings, "po_store_dir") else PROJECT_ROOT / "data" / "po_store"
CROSSWALK_DIR = Path(settings.crosswalk_dir) if hasattr(settings, "crosswalk_dir") else PROJECT_ROOT / "data" / "crosswalks"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db() -> sqlite3.Connection:
    """Create DB and run schema if tables don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        logger.info(f"Schema applied from {SCHEMA_PATH}")
    else:
        logger.warning(f"Schema file not found: {SCHEMA_PATH}")

    return conn


def migrate_po_store(conn: sqlite3.Connection) -> dict:
    """Migrate all JSON PO files into SQLite."""
    po_dir = Path(PO_STORE_DIR)
    if not po_dir.exists():
        logger.warning(f"PO store directory not found: {po_dir}")
        return {"po_files": 0, "po_rows": 0, "line_rows": 0}

    json_files = list(po_dir.glob("*.json"))
    logger.info(f"Found {len(json_files)} PO JSON files")

    po_count = 0
    line_count = 0

    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                po = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse {jf.name}: {e}")
            continue

        header = po.get("header", {})
        result = po.get("result_data", {})
        cust_match = result.get("customer_match", {})
        confidence = result.get("confidence", {})

        # Insert PO header
        conn.execute(
            """
            INSERT OR REPLACE INTO po_store (
                intake_id, po_number, source_system, format, received_at,
                status, overall_confidence, review_required, classification_confidence,
                cism_blob_path, supplier_name, supplier_email,
                ship2_name, ship2_add1, ship2_city, ship2_state, ship2_zip,
                buyer, buyer_email, po_desc, terms, order_date, currency_id,
                customer_id_p21, customer_name_p21, customer_match_score,
                customer_match_method, shipto_score,
                reviewer, reviewed_at, reviewer_notes,
                p21_so_number, p21_submitted_at, p21_submit_result, p21_import_status,
                raw_payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po.get("intake_id", ""),
                header.get("po_no", ""),
                po.get("source", ""),
                po.get("format", ""),
                po.get("received_at", ""),
                po.get("status", "RECEIVED"),
                po.get("overall_confidence", ""),
                1 if po.get("review_required") else 0,
                po.get("classification_confidence", 0.0),
                po.get("cism_blob_path", ""),
                header.get("supplier_name", ""),
                header.get("supplier_email", ""),
                header.get("ship2_name", ""),
                header.get("ship2_add1", ""),
                header.get("ship2_city", ""),
                header.get("ship2_state", ""),
                header.get("ship2_zip", ""),
                header.get("buyer", ""),
                header.get("buyer_email", ""),
                header.get("po_desc", ""),
                header.get("terms", ""),
                header.get("order_date", ""),
                header.get("currency_id", "USD"),
                header.get("customer_id_p21", ""),
                cust_match.get("name", header.get("customer_name_p21", "")),
                cust_match.get("score", 0.0),
                cust_match.get("method", ""),
                cust_match.get("shipto_score", confidence.get("shipto_score", 0.0)),
                po.get("reviewer", ""),
                po.get("reviewed_at", ""),
                po.get("reviewer_notes", ""),
                po.get("p21_so_number", ""),
                po.get("p21_submitted_at", ""),
                po.get("p21_submit_result", ""),
                po.get("p21_import_status", "pending"),
                json.dumps(po),
                po.get("received_at", datetime.now().isoformat()),
                datetime.now().isoformat(),
            ),
        )

        # Insert lines
        for line in po.get("lines", []):
            conn.execute(
                """
                INSERT OR REPLACE INTO po_lines (
                    intake_id, line_no, supplier_part_id, item_description,
                    qty_ordered, unit_price, unit_of_measure, item_id_p21,
                    crosswalk_match_score, confidence, date_due, required_date,
                    ship_to_name, ship_to_address, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    po.get("intake_id", ""),
                    line.get("line_no", 0),
                    line.get("supplier_part_id", ""),
                    line.get("item_description", ""),
                    line.get("qty_ordered", 0),
                    line.get("unit_price", 0),
                    line.get("unit_of_measure", "EA"),
                    line.get("item_id_p21", ""),
                    line.get("crosswalk_match_score", None),
                    line.get("confidence", ""),
                    line.get("date_due", ""),
                    line.get("required_date", ""),
                    line.get("ship_to_name", ""),
                    line.get("ship_to_address", ""),
                    line.get("notes", ""),
                ),
            )
            line_count += 1

        po_count += 1
        if po_count % 100 == 0:
            logger.info(f"  Migrated {po_count} POs...")

    conn.commit()
    logger.info(f"PO migration complete: {po_count} POs, {line_count} lines")
    return {"po_files": len(json_files), "po_rows": po_count, "line_rows": line_count}


def _read_csv_rows(filename: str) -> list[dict]:
    """Read CSV from crosswalk dir with BOM handling."""
    path = CROSSWALK_DIR / filename
    if not path.exists():
        logger.warning(f"Crosswalk file not found: {path}")
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def migrate_crosswalks(conn: sqlite3.Connection) -> dict:
    """Migrate all crosswalk CSVs into SQLite."""
    stats = {}

    # 1. customer_crosswalk.csv → crosswalk_customers
    rows = _read_csv_rows("customer_crosswalk.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO crosswalk_customers (
                    source_system, source_customer_id, source_customer_name,
                    ship2_name, ship2_name_normalized, ship2_add1, ship2_add1_normalized,
                    ship2_city, ship2_state, ship2_zip,
                    p21_customer_id, p21_customer_name, match_score, match_method,
                    is_active, last_seen, seen_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("source_system", "P21"),
                    r.get("source_customer_id", ""),
                    r.get("source_customer_name", ""),
                    r.get("ship2_name", ""),
                    r.get("ship2_name_normalized", ""),
                    r.get("ship2_add1", ""),
                    r.get("ship2_add1_normalized", ""),
                    r.get("ship2_city", ""),
                    r.get("ship2_state", ""),
                    r.get("ship2_zip", ""),
                    r.get("p21_customer_id", ""),
                    r.get("p21_customer_name", ""),
                    float(r.get("match_score", "1.0") or "1.0"),
                    r.get("match_method", "seed"),
                    int(r.get("is_active", "1") or "1"),
                    r.get("last_seen", ""),
                    int(r.get("seen_count", "1") or "1"),
                ),
            )
        conn.commit()
        logger.info(f"Crosswalk customers: {len(rows)} rows migrated")
        stats["crosswalk_customers"] = len(rows)

    # 2. customer_item_crosswalk.csv → crosswalk_items
    rows = _read_csv_rows("customer_item_crosswalk.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO crosswalk_items (
                    p21_customer_id, customer_part_number, p21_inv_mast_uid,
                    p21_item_id, p21_item_desc, unit_of_measure, product_group_id,
                    unit_price_last, unit_price_avg, unit_price_min, unit_price_max,
                    last_seen, seen_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("p21_customer_id", ""),
                    r.get("customer_part_number", ""),
                    r.get("p21_inv_mast_uid", ""),
                    r.get("p21_item_id", ""),  # may be empty in old CSVs
                    r.get("p21_item_desc", ""),
                    r.get("unit_of_measure", ""),
                    r.get("product_group_id", ""),
                    float(r.get("unit_price_last", "0") or "0") or None,
                    float(r.get("unit_price_avg", "0") or "0") or None,
                    float(r.get("unit_price_min", "0") or "0") or None,
                    float(r.get("unit_price_max", "0") or "0") or None,
                    r.get("last_seen", ""),
                    int(r.get("seen_count", "1") or "1"),
                ),
            )
        conn.commit()
        logger.info(f"Crosswalk items: {len(rows)} rows migrated")
        stats["crosswalk_items"] = len(rows)

    # 3. customer_po_history.csv → po_history
    rows = _read_csv_rows("customer_po_history.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO po_history (
                    p21_customer_id, customer_po_no, p21_order_no,
                    order_date, completed, approved, ship2_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("p21_customer_id", ""),
                    r.get("customer_po_no", ""),
                    r.get("p21_order_no", ""),
                    r.get("order_date", ""),
                    r.get("completed", ""),
                    r.get("approved", ""),
                    r.get("ship2_name", ""),
                ),
            )
        conn.commit()
        logger.info(f"PO history: {len(rows)} rows migrated")
        stats["po_history"] = len(rows)

    # 4. item_master_index.csv → item_master
    rows = _read_csv_rows("item_master_index.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO item_master (
                    p21_inv_mast_uid, p21_part_number, p21_item_desc,
                    p21_item_desc_normalized, default_selling_unit, product_group,
                    default_supplier_id, supplier_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("p21_inv_mast_uid", ""),
                    r.get("p21_part_number", ""),
                    r.get("p21_item_desc", ""),
                    r.get("p21_item_desc_normalized", ""),
                    r.get("default_selling_unit", ""),
                    r.get("product_group", ""),
                    r.get("default_supplier_id", ""),
                    r.get("supplier_name", ""),
                ),
            )
        conn.commit()
        logger.info(f"Item master: {len(rows)} rows migrated")
        stats["item_master"] = len(rows)

    # 5. customers_p21.csv → p21_customers
    rows = _read_csv_rows("customers_p21.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO p21_customers (
                    customer_id, customer_name, address, city, state, zip,
                    country, phone, email, default_terms, default_carrier_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("customer_id", ""),
                    r.get("customer_name", ""),
                    r.get("address", ""),
                    r.get("city", ""),
                    r.get("state", ""),
                    r.get("zip", ""),
                    r.get("country", "US"),
                    r.get("phone", ""),
                    r.get("email", ""),
                    r.get("default_terms", ""),
                    r.get("default_carrier_id", ""),
                ),
            )
        conn.commit()
        logger.info(f"P21 customers: {len(rows)} rows migrated")
        stats["p21_customers"] = len(rows)

    # 6. customer_defaults.csv → customer_defaults
    rows = _read_csv_rows("customer_defaults.csv")
    if rows:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO customer_defaults (
                    customer_id, customer_name, default_contact_id,
                    default_address_id, default_terms, default_carrier_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("customer_id", ""),
                    r.get("customer_name", ""),
                    r.get("default_contact_id", ""),
                    r.get("default_address_id", ""),
                    r.get("default_terms", ""),
                    r.get("default_carrier_id", ""),
                ),
            )
        conn.commit()
        logger.info(f"Customer defaults: {len(rows)} rows migrated")
        stats["customer_defaults"] = len(rows)

    return stats


def validate_migration(conn: sqlite3.Connection, results: dict):
    """Validate that migration counts match expectations."""
    logger.info("\n=== Validation ===")

    # PO count
    po_db = conn.execute("SELECT COUNT(*) FROM po_store").fetchone()[0]
    po_files = results["po_store"]["po_files"]
    logger.info(f"PO files: {po_files} | PO rows in DB: {po_db}")
    if po_db != po_files:
        logger.warning(f"  MISMATCH: {po_files} files vs {po_db} DB rows")
    else:
        logger.info(f"  ✓ PO counts match")

    # Crosswalk counts
    for table, expected in results.get("crosswalks", {}).items():
        actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.info(f"{table}: CSV={expected} | DB={actual}")
        if actual != expected:
            logger.warning(f"  MISMATCH in {table}")
        else:
            logger.info(f"  ✓ {table} counts match")

    # Sample query
    logger.info("\n=== Sample Queries ===")
    sample = conn.execute(
        "SELECT intake_id, po_number, customer_id_p21, overall_confidence FROM po_store LIMIT 3"
    ).fetchall()
    for row in sample:
        logger.info(f"  PO {row['po_number']} | Customer: {row['customer_id_p21']} | Confidence: {row['overall_confidence']}")


def archive_json_files():
    """Rename migrated JSON files to .json.bak (don't delete)."""
    po_dir = Path(PO_STORE_DIR)
    if not po_dir.exists():
        return

    archived = 0
    for jf in po_dir.glob("*.json"):
        bak = jf.with_suffix(".json.bak")
        jf.rename(bak)
        archived += 1

    if archived > 0:
        logger.info(f"Archived {archived} JSON files to .json.bak")


def main():
    logger.info("=" * 60)
    logger.info("EnPro PO Agent — Data Migration to SQLite")
    logger.info("=" * 60)

    conn = init_db()

    # Migrate POs
    po_results = migrate_po_store(conn)

    # Migrate crosswalks
    cw_results = migrate_crosswalks(conn)

    # Validate
    results = {"po_store": po_results, "crosswalks": cw_results}
    validate_migration(conn, results)

    # Archive old files
    archive_json_files()

    conn.close()
    logger.info(f"\nMigration complete. Database: {DB_PATH}")
    logger.info("Run 'po_store.db' is now the primary data store.")
    logger.info("JSON files have been archived to .json.bak")


if __name__ == "__main__":
    main()

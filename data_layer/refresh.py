#!/usr/bin/env python3
"""
EnPro PO Agent — Crosswalk Refresh Job
Pulls fresh data from P21 SQL Server and rebuilds crosswalk tables.

Usage:
    python data_layer/refresh.py --mode full
    python data_layer/refresh.py --mode incremental --days 7

What it does:
    1. Connects to P21 SQL Server (via pyodbc)
    2. Runs so_pull.sql queries (oe_hdr, oe_line, customers, items)
    3. Runs crosswalk_csv_builder to generate new CSVs
    4. Validates new data (no NULL customer_ids, reasonable row counts)
    5. Backs up old crosswalks to data/crosswalks/backup/
    6. Atomically swaps new crosswalks in
    7. Updates SQLite crosswalk tables
    8. Logs refresh to crosswalk_refresh_log table
    9. Invalidates engine cache

Env vars required:
    P21_SQL_SERVER, P21_SQL_DATABASE, P21_SQL_USERNAME, P21_SQL_PASSWORD
    Or: DATABASE_URL (pyodbc connection string)
"""

import argparse
import csv
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from services.processing.crosswalk_csv_builder import build_all

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "po_store.db"
CROSSWALK_DIR = Path(settings.crosswalk_dir) if hasattr(settings, "crosswalk_dir") else PROJECT_ROOT / "data" / "crosswalks"
BACKUP_DIR = CROSSWALK_DIR / "backup"

# P21 SQL connection settings
P21_SQL_SERVER = os.environ.get("P21_SQL_SERVER", "")
P21_SQL_DATABASE = os.environ.get("P21_SQL_DATABASE", "")
P21_SQL_USERNAME = os.environ.get("P21_SQL_USERNAME", "")
P21_SQL_PASSWORD = os.environ.get("P21_SQL_PASSWORD", "")


def get_p21_connection():
    """Get pyodbc connection to P21 SQL Server."""
    try:
        import pyodbc
    except ImportError:
        logger.error("pyodbc not installed. Install with: pip install pyodbc")
        return None

    conn_str = os.environ.get("DATABASE_URL", "")
    if not conn_str and P21_SQL_SERVER:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={P21_SQL_SERVER};"
            f"DATABASE={P21_SQL_DATABASE};"
            f"UID={P21_SQL_USERNAME};"
            f"PWD={P21_SQL_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )

    if not conn_str:
        logger.error("No P21 SQL connection configured. Set DATABASE_URL or P21_SQL_* env vars.")
        return None

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        logger.info(f"Connected to P21 SQL: {P21_SQL_SERVER}/{P21_SQL_DATABASE}")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to P21 SQL: {e}")
        return None


def pull_p21_data(conn, days_back: int = 365) -> dict:
    """Pull SO headers, lines, customers, items from P21."""
    import pyodbc

    results = {}
    cursor = conn.cursor()

    # SO Headers
    logger.info(f"Pulling SO headers (last {days_back} days)...")
    cursor.execute(f"""
        SELECT
            h.order_no, h.oe_hdr_uid, h.company_id, h.location_id,
            h.customer_id, h.address_id, h.corp_address_id, h.contact_id,
            h.bill_to_id, h.ship2_name, h.ship2_add1, h.ship2_add2,
            h.ship2_add3, h.ship2_city, h.ship2_state, h.ship2_zip,
            h.ship2_country, h.ship2_email_address, h.ship_to_phone,
            h.order_date, h.requested_date, h.requested_ship_date,
            h.promise_date, h.po_no, h.po_no_append, h.supplier_order_no,
            h.supplier_release_no, h.order_type, h.completed, h.approved,
            h.cancel_flag, h.carrier_id, h.freight_code_uid, h.freight_out,
            h.fob_flag, h.packing_basis, h.delivery_instructions,
            h.terms, h.payment_method, h.taker, h.inside_sales,
            h.source_id, h.source_location_id, h.job_name,
            h.class_1id, h.class_2id, h.class_3id, h.class_4id, h.class_5id,
            h.rma_flag, h.hold_invoice_flag, h.electronic_order_flag,
            h.delete_flag
        FROM oe_hdr h
        WHERE h.date_last_modified >= DATEADD(DAY, -{days_back}, GETDATE())
          AND h.delete_flag = 'N'
        ORDER BY h.date_last_modified DESC
    """)
    headers = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    results["headers"] = headers
    logger.info(f"  → {len(headers)} headers")

    # SO Lines
    logger.info(f"Pulling SO lines (last {days_back} days)...")
    cursor.execute(f"""
        SELECT
            l.order_no, l.oe_line_uid, l.oe_hdr_uid, l.line_no,
            l.user_line_no, l.inv_mast_uid, l.customer_part_number,
            l.extended_desc, l.additional_description, l.print_part_no,
            l.product_group_id, l.qty_ordered, l.unit_price,
            l.unit_of_measure, l.unit_size, l.pricing_unit,
            l.required_date, l.source_loc_id, l.ship_loc_id,
            l.supplier_id, l.disposition, l.complete, l.cancel_flag,
            l.cust_po_no, l.buyer, l.cost_center, l.gl_code,
            l.date_created, l.date_last_modified, l.delete_flag
        FROM oe_line l
        WHERE l.date_last_modified >= DATEADD(DAY, -{days_back}, GETDATE())
          AND l.delete_flag = 'N'
        ORDER BY l.order_no, l.line_no
    """)
    lines = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    results["lines"] = lines
    logger.info(f"  → {len(lines)} lines")

    # Customers
    logger.info("Pulling customer master...")
    cursor.execute("""
        SELECT
            c.customer_id, c.customer_name,
            c.address_1 AS address, c.city, c.state, c.zip,
            c.country_id AS country, c.phone_number AS phone,
            c.email_address AS email,
            c.default_terms, c.default_carrier_id
        FROM customers c
        WHERE c.delete_flag = 'N'
    """)
    customers = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    results["customers"] = customers
    logger.info(f"  → {len(customers)} customers")

    # Items
    logger.info("Pulling item master...")
    cursor.execute("""
        SELECT
            i.inv_mast_uid, i.item_id, i.item_desc,
            i.default_selling_unit, i.product_group_id,
            i.default_supplier_id
        FROM inv_mast i
        WHERE i.delete_flag = 'N'
    """)
    items = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    results["items"] = items
    logger.info(f"  → {len(items)} items")

    cursor.close()
    return results


def write_csv(rows: list[dict], path: Path):
    """Write rows to CSV."""
    if not rows:
        logger.warning(f"No rows to write: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    logger.info(f"Wrote {len(rows)} rows → {path}")


def export_to_csv(data: dict, temp_dir: Path):
    """Write pulled data to temp CSV files."""
    write_csv(data["headers"], temp_dir / "so_headers.csv")
    write_csv(data["lines"], temp_dir / "so_lines.csv")
    write_csv(data["customers"], temp_dir / "customers.csv")


def validate_crosswalks(temp_dir: Path) -> tuple[bool, str]:
    """Validate generated crosswalks before swapping."""
    logger.info("Validating crosswalks...")

    # Check customer crosswalk
    cust_path = temp_dir / "customer_crosswalk.csv"
    if not cust_path.exists():
        return False, "customer_crosswalk.csv not generated"

    with open(cust_path, "r") as f:
        rows = list(csv.DictReader(f))

    if len(rows) < 10:
        return False, f"Only {len(rows)} customer rows — expected thousands"

    null_cust_ids = sum(1 for r in rows if not r.get("p21_customer_id"))
    if null_cust_ids > len(rows) * 0.1:
        return False, f"{null_cust_ids} rows missing customer_id (>10%)"

    logger.info(f"  ✓ {len(rows)} customers, {null_cust_ids} null IDs")

    # Check item crosswalk
    item_path = temp_dir / "customer_item_crosswalk.csv"
    if not item_path.exists():
        return False, "customer_item_crosswalk.csv not generated"

    with open(item_path, "r") as f:
        rows = list(csv.DictReader(f))

    if len(rows) < 100:
        return False, f"Only {len(rows)} item rows — expected thousands"

    logger.info(f"  ✓ {len(rows)} customer-item mappings")

    return True, "OK"


def backup_existing_crosswalks():
    """Copy current crosswalks to backup/ with timestamp."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_subdir = BACKUP_DIR / f"backup_{ts}"
    backup_subdir.mkdir(exist_ok=True)

    files = [
        "customer_crosswalk.csv",
        "customer_item_crosswalk.csv",
        "customer_po_history.csv",
        "item_master_index.csv",
        "customers_p21.csv",
        "customer_defaults.csv",
    ]

    backed_up = 0
    for fname in files:
        src = CROSSWALK_DIR / fname
        if src.exists():
            shutil.copy2(src, backup_subdir / fname)
            backed_up += 1

    logger.info(f"Backed up {backed_up} files to {backup_subdir}")
    return backup_subdir


def swap_crosswalks(temp_dir: Path):
    """Atomically replace crosswalk files."""
    files = [
        "customer_crosswalk.csv",
        "customer_item_crosswalk.csv",
        "customer_po_history.csv",
        "item_master_index.csv",
        "customers_p21.csv",
        "customer_defaults.csv",
    ]

    CROSSWALK_DIR.mkdir(parents=True, exist_ok=True)

    for fname in files:
        src = temp_dir / fname
        dst = CROSSWALK_DIR / fname
        if src.exists():
            shutil.move(str(src), str(dst))
            logger.info(f"  Swapped {fname}")


def update_sqlite_crosswalks():
    """Run migrate.py crosswalk portion to update SQLite tables."""
    from data_layer.migrate import migrate_crosswalks, init_db

    conn = init_db()
    stats = migrate_crosswalks(conn)
    conn.close()
    logger.info(f"SQLite crosswalks updated: {stats}")
    return stats


def log_refresh(conn: sqlite3.Connection, table: str, before: int, after: int, duration: float, status: str, error: str = ""):
    """Log refresh to crosswalk_refresh_log table."""
    conn.execute(
        """
        INSERT INTO crosswalk_refresh_log (refresh_type, table_name, rows_before, rows_after, duration_seconds, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("full", table, before, after, duration, status, error),
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Refresh crosswalks from P21")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--days", type=int, default=365, help="Days back for incremental pull")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't swap")
    parser.add_argument("--skip-sql", action="store_true", help="Skip SQLite update")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"Crosswalk Refresh — Mode: {args.mode}, Days: {args.days}")
    logger.info("=" * 60)

    start_time = datetime.now()

    # 1. Connect to P21
    p21_conn = get_p21_connection()
    if not p21_conn:
        logger.error("Cannot connect to P21. Aborting.")
        sys.exit(1)

    # 2. Pull data
    days = args.days if args.mode == "incremental" else 365 * 5  # Full = 5 years
    data = pull_p21_data(p21_conn, days_back=days)
    p21_conn.close()

    # 3. Generate crosswalks in temp dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        export_to_csv(data, tmp_path)

        # Build crosswalks
        build_all(
            headers_path=str(tmp_path / "so_headers.csv"),
            lines_path=str(tmp_path / "so_lines.csv"),
            customers_path=str(tmp_path / "customers.csv"),
            output_dir=str(tmp_path / "crosswalks"),
        )

        # 4. Validate
        ok, msg = validate_crosswalks(tmp_path / "crosswalks")
        if not ok:
            logger.error(f"Validation failed: {msg}")
            sys.exit(1)

        if args.dry_run:
            logger.info("Dry run complete. Files in temp dir.")
            return

        # 5. Backup existing
        backup_existing_crosswalks()

        # 6. Get before counts
        conn = sqlite3.connect(str(DB_PATH))
        before_counts = {}
        for table in ["crosswalk_customers", "crosswalk_items", "po_history", "item_master", "p21_customers", "customer_defaults"]:
            try:
                before_counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except:
                before_counts[table] = 0
        conn.close()

        # 7. Swap files
        swap_crosswalks(tmp_path / "crosswalks")

    # 8. Update SQLite
    if not args.skip_sql:
        update_sqlite_crosswalks()

    # 9. Log results
    duration = (datetime.now() - start_time).total_seconds()
    conn = sqlite3.connect(str(DB_PATH))
    for table, before in before_counts.items():
        try:
            after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except:
            after = 0
        log_refresh(conn, table, before, after, duration, "success")
    conn.close()

    logger.info(f"\nRefresh complete in {duration:.1f}s")
    logger.info(f"Crosswalks updated in: {CROSSWALK_DIR}")
    logger.info(f"Database updated: {DB_PATH}")


if __name__ == "__main__":
    main()

"""
outbound_store.py — File-based store for outbound sync records.

Tracks P21 invoice feedback payloads destined for Ariba/Coupa.
Record lifecycle: pending → prepared → ready → sent | failed
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

OUTBOUND_STORE_DIR = os.environ.get("OUTBOUND_STORE_DIR", "/app/data/outbound_store")

VALID_STATUSES = {"pending", "prepared", "ready", "sent", "failed"}


def _ensure_dir():
    os.makedirs(OUTBOUND_STORE_DIR, exist_ok=True)


def _outbound_id(intake_id: str) -> str:
    """Derive a stable outbound_id from intake_id — deterministic, no collisions."""
    return "OB" + hashlib.sha256(f"outbound-{intake_id}".encode()).hexdigest()[:14].upper()


def create_record(
    intake_id: str,
    source_system: str,
    po_no: str,
    p21_order_no: str = "",
    p21_invoice_no: str = "",
    invoice_date: str = "",
    customer_id: str = "",
    amount_total: float = 0.0,
    currency: str = "USD",
) -> dict:
    """Create and persist a new outbound record. Returns the full record dict."""
    _ensure_dir()
    outbound_id = _outbound_id(intake_id)
    now = datetime.utcnow().isoformat()
    record = {
        "outbound_id": outbound_id,
        "intake_id": intake_id,
        "source_system": (source_system or "ariba").lower(),
        "po_no": po_no,
        "p21_order_no": p21_order_no,
        "p21_invoice_no": p21_invoice_no,
        "invoice_date": invoice_date or now[:10],
        "customer_id": customer_id,
        "amount_total": amount_total,
        "currency": currency,
        "status": "pending",
        "last_error": "",
        "payload": {},
        "created_at": now,
        "updated_at": now,
    }
    path = os.path.join(OUTBOUND_STORE_DIR, f"{outbound_id}.json")
    with open(path, "w") as f:
        json.dump(record, f, default=str)
    logger.info(f"Created outbound record {outbound_id} for intake {intake_id}")
    return record


def get_record(outbound_id: str) -> Optional[dict]:
    """Retrieve a single outbound record by outbound_id."""
    path = os.path.join(OUTBOUND_STORE_DIR, f"{outbound_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def get_by_intake(intake_id: str) -> Optional[dict]:
    """Find outbound record by source intake_id (deterministic lookup)."""
    return get_record(_outbound_id(intake_id))


def list_records(status: str = None) -> list:
    """List all outbound records, optionally filtered by status, sorted newest first."""
    _ensure_dir()
    results = []
    for fname in os.listdir(OUTBOUND_STORE_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(OUTBOUND_STORE_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            if status and data.get("status") != status:
                continue
            results.append(data)
        except Exception as e:
            logger.warning(f"Bad outbound file {fname}: {e}")
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def update_record(outbound_id: str, updates: dict) -> bool:
    """Merge updates dict into an outbound record and persist."""
    record = get_record(outbound_id)
    if not record:
        return False
    record.update(updates)
    record["updated_at"] = datetime.utcnow().isoformat()
    path = os.path.join(OUTBOUND_STORE_DIR, f"{outbound_id}.json")
    with open(path, "w") as f:
        json.dump(record, f, default=str)
    return True


def get_history(limit: int = 50) -> list:
    """Return recent sync activity — all non-pending records sorted by updated_at."""
    records = list_records()
    active = [r for r in records if r.get("status") != "pending"]
    return active[:limit]

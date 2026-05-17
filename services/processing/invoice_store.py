"""
invoice_store.py -- File-based invoice store for sandbox/Render (no SQL dependency).

Stores invoices as JSON files in /app/data/invoices/.
Provides lookup by invoice_id, SO number, and PO number.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

STORE_DIR = os.environ.get("INVOICE_STORE_DIR", "/app/data/invoices")


def _ensure_dir():
    os.makedirs(STORE_DIR, exist_ok=True)


def save_invoice(invoice_id: str, data: dict):
    """Save an invoice to local store."""
    _ensure_dir()
    data["_stored_at"] = datetime.utcnow().isoformat()
    path = os.path.join(STORE_DIR, f"{invoice_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, default=str)
    logger.info(f"Stored invoice {invoice_id} -> {path}")


def get_invoice(invoice_id: str) -> Optional[dict]:
    """Get a single invoice by invoice_id."""
    path = os.path.join(STORE_DIR, f"{invoice_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def list_invoices() -> list[dict]:
    """List all stored invoices."""
    _ensure_dir()
    results = []
    for fname in os.listdir(STORE_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(STORE_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            results.append(data)
        except Exception as e:
            logger.warning(f"Bad invoice file {fname}: {e}")
    results.sort(key=lambda x: x.get("_stored_at", ""), reverse=True)
    return results


def get_invoices_by_so(so_number: str) -> list[dict]:
    """Get invoices linked to a given Sales Order number."""
    return [
        inv for inv in list_invoices()
        if inv.get("so_number") == so_number
    ]


def get_invoices_by_po(po_no: str) -> list[dict]:
    """Get invoices linked to a given PO number."""
    return [
        inv for inv in list_invoices()
        if inv.get("po_no") == po_no
    ]


def update_invoice(invoice_id: str, updates: dict):
    """Update fields on a stored invoice."""
    data = get_invoice(invoice_id)
    if not data:
        return False
    data.update(updates)
    data["_updated_at"] = datetime.utcnow().isoformat()
    path = os.path.join(STORE_DIR, f"{invoice_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, default=str)
    return True

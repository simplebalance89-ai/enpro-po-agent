"""
local_store.py — PO store backed by Supabase PostgreSQL.

Replaces the previous JSON file store (./data/po_store/).
All function signatures are identical so no callers need to change.

Supabase table required (run once in Supabase SQL editor):

    CREATE TABLE IF NOT EXISTS po_records (
        intake_id    TEXT PRIMARY KEY,
        po_no        TEXT,
        source       TEXT,
        confidence   TEXT,
        review_status TEXT DEFAULT 'pending',
        stored_at    TEXT,
        updated_at   TEXT,
        data         JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_po_records_status ON po_records(review_status);
    CREATE INDEX IF NOT EXISTS idx_po_records_confidence ON po_records(confidence);
    CREATE INDEX IF NOT EXISTS idx_po_records_po_source ON po_records(po_no, source);
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_TABLE = "po_records"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        logger.warning("SUPABASE_URL / SUPABASE_KEY not set — PO store disabled")
        return None
    try:
        from supabase import create_client
        _client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
        logger.info("Supabase PO store client initialised")
    except Exception as exc:
        logger.error(f"Failed to initialise Supabase client: {exc}")
        _client = None
    return _client


# ── public API (same signatures as the old JSON file store) ──────────────────

def save_po(intake_id: str, data: dict):
    """Save or update a processed PO."""
    client = _get_client()
    if client is None:
        return

    data["_stored_at"] = datetime.utcnow().isoformat()
    row = {
        "intake_id": intake_id,
        "po_no": data.get("po_no", ""),
        "source": data.get("source", ""),
        "confidence": data.get("confidence", ""),
        "review_status": data.get("review_status", "pending"),
        "stored_at": data["_stored_at"],
        "data": data,
    }
    try:
        client.table(_TABLE).upsert(row).execute()
        logger.info(f"Saved PO {intake_id} to Supabase")
    except Exception as exc:
        logger.error(f"save_po failed for {intake_id}: {exc}")


def get_po(intake_id: str) -> Optional[dict]:
    """Fetch a single PO by intake_id. Returns None if not found."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = (
            client.table(_TABLE)
            .select("data")
            .eq("intake_id", intake_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]["data"]
        return None
    except Exception as exc:
        logger.error(f"get_po failed for {intake_id}: {exc}")
        return None


def list_pos(status: str = None, confidence: str = None) -> list:
    """List all POs, optionally filtered by review_status and/or confidence."""
    client = _get_client()
    if client is None:
        return []
    try:
        query = client.table(_TABLE).select("data, stored_at").order(
            "stored_at", desc=True
        )
        if status:
            query = query.eq("review_status", status)
        if confidence:
            query = query.eq("confidence", confidence)
        resp = query.execute()
        return [row["data"] for row in resp.data]
    except Exception as exc:
        logger.error(f"list_pos failed: {exc}")
        return []


def update_po(intake_id: str, updates: dict) -> bool:
    """Merge updates into a stored PO and persist."""
    data = get_po(intake_id)
    if not data:
        return False
    data.update(updates)
    data["_updated_at"] = datetime.utcnow().isoformat()
    client = _get_client()
    if client is None:
        return False
    try:
        client.table(_TABLE).update({
            "review_status": data.get("review_status", "pending"),
            "confidence": data.get("confidence", ""),
            "updated_at": data["_updated_at"],
            "data": data,
        }).eq("intake_id", intake_id).execute()
        return True
    except Exception as exc:
        logger.error(f"update_po failed for {intake_id}: {exc}")
        return False


def is_duplicate(intake_id: str, po_no: str, source: str) -> bool:
    """Return True if this PO was already processed."""
    client = _get_client()
    if client is None:
        return False
    try:
        # Check by intake_id (fastest)
        r = (
            client.table(_TABLE)
            .select("intake_id")
            .eq("intake_id", intake_id)
            .limit(1)
            .execute()
        )
        if r.data:
            return True
        # Check by po_no + source
        r = (
            client.table(_TABLE)
            .select("intake_id")
            .eq("po_no", po_no)
            .eq("source", source)
            .limit(1)
            .execute()
        )
        return bool(r.data)
    except Exception as exc:
        logger.error(f"is_duplicate check failed: {exc}")
        return False


def get_stats() -> dict:
    """Return counts by confidence and review status."""
    all_pos = list_pos()
    total = len(all_pos)
    return {
        "total": total,
        "green":    sum(1 for p in all_pos if p.get("confidence") == "green"),
        "yellow":   sum(1 for p in all_pos if p.get("confidence") == "yellow"),
        "red":      sum(1 for p in all_pos if p.get("confidence") == "red"),
        "approved": sum(1 for p in all_pos if p.get("review_status") == "approved"),
        "rejected": sum(1 for p in all_pos if p.get("review_status") == "rejected"),
        "pending":  sum(1 for p in all_pos if p.get("review_status") == "pending"),
    }

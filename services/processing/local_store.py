"""
local_store.py — PO store with Supabase PostgreSQL primary and JSON-file fallback.

Priority:
  1. Supabase PostgreSQL  — when SUPABASE_URL + SUPABASE_KEY are set
  2. JSON files on disk   — fallback; uses PO_STORE_DIR (default: ./data/po_store)
                            This is the original behaviour and keeps the Fly.io
                            persistent volume working even before Supabase is wired up.

All public function signatures are identical so no callers need to change.

Supabase table (run once if/when you move to Supabase):
    CREATE TABLE IF NOT EXISTS po_records (
        intake_id     TEXT PRIMARY KEY,
        po_no         TEXT,
        source        TEXT,
        confidence    TEXT,
        review_status TEXT DEFAULT 'pending',
        stored_at     TEXT,
        updated_at    TEXT,
        data          JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_po_records_status     ON po_records(review_status);
    CREATE INDEX IF NOT EXISTS idx_po_records_confidence ON po_records(confidence);
    CREATE INDEX IF NOT EXISTS idx_po_records_po_source  ON po_records(po_no, source);
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Supabase config (optional) ────────────────────────────────────────────────
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_TABLE = "po_records"

# ── JSON-file fallback config ─────────────────────────────────────────────────
STORE_DIR = os.environ.get("PO_STORE_DIR", "./data/po_store")

# Lazy Supabase client — None means "not available / not configured"
_supabase_client = None
_supabase_checked = False   # set True after first init attempt so we don't retry on every call


def _get_supabase():
    """Return the Supabase client if configured, else None (uses file store)."""
    global _supabase_client, _supabase_checked
    if _supabase_checked:
        return _supabase_client
    _supabase_checked = True

    if not _SUPABASE_URL or not _SUPABASE_KEY:
        logger.info("SUPABASE_URL/KEY not set — using JSON file store (data/po_store/)")
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
        logger.info("local_store: Supabase client initialised")
    except Exception as exc:
        logger.error(f"local_store: Supabase init failed — falling back to file store: {exc}")
        _supabase_client = None

    return _supabase_client


# ── File-store helpers ────────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(STORE_DIR, exist_ok=True)


def _atomic_write(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _file_path(intake_id: str) -> str:
    return os.path.join(STORE_DIR, f"{intake_id}.json")


# ── Public API ────────────────────────────────────────────────────────────────

def save_po(intake_id: str, data: dict):
    """Save or update a processed PO."""
    data["_stored_at"] = datetime.utcnow().isoformat()

    client = _get_supabase()
    if client is not None:
        try:
            client.table(_TABLE).upsert({
                "intake_id":    intake_id,
                "po_no":        data.get("po_no", ""),
                "source":       data.get("source", ""),
                "confidence":   data.get("confidence", ""),
                "review_status":data.get("review_status", "pending"),
                "stored_at":    data["_stored_at"],
                "data":         data,
            }).execute()
            logger.debug(f"save_po [{intake_id}] → Supabase")
            return
        except Exception as exc:
            logger.error(f"save_po Supabase error, falling back to file: {exc}")

    # File fallback
    _ensure_dir()
    _atomic_write(_file_path(intake_id), data)
    logger.debug(f"save_po [{intake_id}] → {STORE_DIR}/{intake_id}.json")


def get_po(intake_id: str) -> Optional[dict]:
    """Fetch a single PO by intake_id. Returns None if not found."""
    client = _get_supabase()
    if client is not None:
        try:
            resp = (
                client.table(_TABLE)
                .select("data")
                .eq("intake_id", intake_id)
                .limit(1)
                .execute()
            )
            return resp.data[0]["data"] if resp.data else None
        except Exception as exc:
            logger.error(f"get_po Supabase error, falling back to file: {exc}")

    # File fallback
    path = _file_path(intake_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning(f"get_po: bad file {intake_id}.json: {exc}")
        return None


def list_pos(status: str = None, confidence: str = None) -> list:
    """List all POs, optionally filtered by review_status and/or confidence."""
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table(_TABLE).select("data, stored_at").order("stored_at", desc=True)
            if status:
                query = query.eq("review_status", status)
            if confidence:
                query = query.eq("confidence", confidence)
            resp = query.execute()
            return [row["data"] for row in resp.data]
        except Exception as exc:
            logger.error(f"list_pos Supabase error, falling back to file: {exc}")

    # File fallback
    _ensure_dir()
    results = []
    for fname in os.listdir(STORE_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(STORE_DIR, fname)) as f:
                data = json.load(f)
            if status and data.get("review_status") != status:
                continue
            if confidence and data.get("confidence") != confidence:
                continue
            results.append(data)
        except Exception as exc:
            logger.warning(f"list_pos: skipping bad file {fname}: {exc}")
    results.sort(key=lambda x: x.get("_stored_at", ""), reverse=True)
    return results


def update_po(intake_id: str, updates: dict) -> bool:
    """Merge updates into a stored PO and persist."""
    data = get_po(intake_id)
    if not data:
        return False
    data.update(updates)
    data["_updated_at"] = datetime.utcnow().isoformat()

    client = _get_supabase()
    if client is not None:
        try:
            client.table(_TABLE).update({
                "review_status": data.get("review_status", "pending"),
                "confidence":    data.get("confidence", ""),
                "updated_at":    data["_updated_at"],
                "data":          data,
            }).eq("intake_id", intake_id).execute()
            return True
        except Exception as exc:
            logger.error(f"update_po Supabase error, falling back to file: {exc}")

    # File fallback
    _ensure_dir()
    _atomic_write(_file_path(intake_id), data)
    return True


def is_duplicate(intake_id: str, po_no: str, source: str) -> bool:
    """Return True if this PO was already processed."""
    client = _get_supabase()
    if client is not None:
        try:
            r = (
                client.table(_TABLE)
                .select("intake_id")
                .eq("intake_id", intake_id)
                .limit(1)
                .execute()
            )
            if r.data:
                return True
            r2 = (
                client.table(_TABLE)
                .select("intake_id")
                .eq("po_no", po_no)
                .eq("source", source)
                .limit(1)
                .execute()
            )
            return bool(r2.data)
        except Exception as exc:
            logger.error(f"is_duplicate Supabase error, falling back to file: {exc}")

    # File fallback
    if os.path.exists(_file_path(intake_id)):
        return True
    for po in list_pos():
        if po.get("po_no") == po_no and po.get("source") == source:
            return True
    return False


def get_stats() -> dict:
    """Return counts grouped by confidence and review status."""
    all_pos = list_pos()
    return {
        "total":    len(all_pos),
        "green":    sum(1 for p in all_pos if p.get("confidence")    == "green"),
        "yellow":   sum(1 for p in all_pos if p.get("confidence")    == "yellow"),
        "red":      sum(1 for p in all_pos if p.get("confidence")    == "red"),
        "approved": sum(1 for p in all_pos if p.get("review_status") == "approved"),
        "rejected": sum(1 for p in all_pos if p.get("review_status") == "rejected"),
        "pending":  sum(1 for p in all_pos if p.get("review_status") == "pending"),
    }

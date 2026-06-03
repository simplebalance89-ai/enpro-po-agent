"""
blob_uploader.py — CISM file storage and crosswalk sync via Supabase Storage.

Replaces the previous Azure Blob Storage implementation.
All public function signatures are identical so no callers need to change.

Supabase Storage buckets required (create in Supabase dashboard):
  - cism-files      (private) — approved/rejected CISM CSV uploads
  - crosswalk-data  (private) — crosswalk CSVs and P21 master data

Bucket folder structure mirrors the old Azure Blob layout:
  cism-files/
    approved/{timestamp}_{po_no}_{intake_id}_{filename}
    rejected/{timestamp}_{po_no}_{intake_id}_{filename}
  crosswalk-data/
    p21/customers_latest.csv   → p21_data/p21_customers.csv
    p21/items_latest.csv       → p21_data/p21_items.csv
    p21/so_headers_latest.csv  → p21_data/p21_headers.csv
    p21/so_lines_latest.csv    → p21_data/p21_lines.csv
    p21/ship_tos_latest.csv    → p21_data/p21_ship_tos.csv
    quotes/{file}              → quote_data/{file}
    {top-level file}           → crosswalks/{file}
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

CISM_BUCKET   = os.environ.get("SUPABASE_CISM_BUCKET",      "cism-files")
XWALK_BUCKET  = os.environ.get("SUPABASE_CROSSWALK_BUCKET", "crosswalk-data")
APPROVED_PREFIX = os.environ.get("SUPABASE_APPROVED_PREFIX", "approved")
REJECTED_PREFIX = os.environ.get("SUPABASE_REJECTED_PREFIX", "rejected")

_P21_FILE_RENAMES = {
    "so_headers_latest.csv": "p21_headers.csv",
    "so_lines_latest.csv":   "p21_lines.csv",
    "customers_latest.csv":  "p21_customers.csv",
    "ship_tos_latest.csv":   "p21_ship_tos.csv",
    "items_latest.csv":      "p21_items.csv",
}


class BlobUploader:
    """Supabase Storage uploader — drop-in replacement for the Azure BlobUploader."""

    def __init__(self):
        self._client = None
        self._connected = False

        if not _SUPABASE_URL or not _SUPABASE_KEY:
            logger.warning("SUPABASE_URL / SUPABASE_KEY not set — blob upload disabled")
            return

        try:
            from supabase import create_client
            self._client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
            self._connected = True
            logger.info("BlobUploader (Supabase) initialised")
        except Exception as exc:
            logger.error(f"Failed to initialise Supabase storage client: {exc}")

    def is_configured(self) -> bool:
        return self._connected and self._client is not None

    def upload_cism(
        self,
        local_file_path: str,
        po_number: str,
        intake_id: str,
        status: str = "approved",
    ) -> dict:
        """Upload a CISM CSV file to Supabase Storage."""
        if not self.is_configured():
            return {"success": False, "error": "Supabase storage not configured",
                    "blob_url": None, "blob_name": None}

        try:
            prefix   = APPROVED_PREFIX if status == "approved" else REJECTED_PREFIX
            ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = Path(local_file_path).name
            blob_name = f"{prefix}/{ts}_{po_number}_{intake_id}_{filename}"

            with open(local_file_path, "rb") as fh:
                data = fh.read()

            self._client.storage.from_(CISM_BUCKET).upload(
                path=blob_name,
                file=data,
                file_options={"content-type": "text/csv", "upsert": "true"},
            )

            # Build a signed URL (60-min validity) so callers get a usable link
            try:
                url_resp = self._client.storage.from_(CISM_BUCKET).create_signed_url(
                    blob_name, expires_in=3600
                )
                blob_url = url_resp.get("signedURL", "")
            except Exception:
                blob_url = f"{_SUPABASE_URL}/storage/v1/object/{CISM_BUCKET}/{blob_name}"

            logger.info(f"Uploaded CISM to Supabase: {blob_name}")
            return {
                "success":   True,
                "blob_url":  blob_url,
                "blob_name": blob_name,
                "container": CISM_BUCKET,
                "error":     None,
            }

        except Exception as exc:
            logger.error(f"Supabase upload error: {exc}")
            return {"success": False, "error": str(exc),
                    "blob_url": None, "blob_name": None}

    def list_cism_files(self, prefix: str = None) -> list:
        """List CISM files in Supabase Storage."""
        if not self.is_configured():
            return []
        folder = prefix or APPROVED_PREFIX
        try:
            items = self._client.storage.from_(CISM_BUCKET).list(folder)
            result = []
            for item in items or []:
                name = item.get("name", "")
                full_path = f"{folder}/{name}"
                try:
                    url_resp = self._client.storage.from_(CISM_BUCKET).create_signed_url(
                        full_path, expires_in=3600
                    )
                    url = url_resp.get("signedURL", "")
                except Exception:
                    url = ""
                result.append({
                    "name":    full_path,
                    "size":    item.get("metadata", {}).get("size", 0),
                    "created": item.get("created_at", ""),
                    "url":     url,
                })
            return sorted(result, key=lambda x: x["created"], reverse=True)
        except Exception as exc:
            logger.error(f"list_cism_files error: {exc}")
            return []

    def download_cism(self, blob_name: str, local_path: str) -> bool:
        """Download a CISM file from Supabase Storage to local disk."""
        if not self.is_configured():
            return False
        try:
            data = self._client.storage.from_(CISM_BUCKET).download(blob_name)
            with open(local_path, "wb") as fh:
                fh.write(data)
            logger.info(f"Downloaded {blob_name} -> {local_path}")
            return True
        except Exception as exc:
            logger.error(f"download_cism error: {exc}")
            return False


# ── Singleton ────────────────────────────────────────────────────────────────

_uploader: Optional[BlobUploader] = None


def get_uploader() -> BlobUploader:
    global _uploader
    if _uploader is None:
        _uploader = BlobUploader()
    return _uploader


# ── Public convenience functions (unchanged signatures) ───────────────────────

def upload_approved_cism(local_file_path: str, po_number: str, intake_id: str) -> dict:
    return get_uploader().upload_cism(local_file_path, po_number, intake_id, status="approved")


def upload_rejected_cism(local_file_path: str, po_number: str, intake_id: str) -> dict:
    return get_uploader().upload_cism(local_file_path, po_number, intake_id, status="rejected")


# ── Crosswalk sync (Supabase Storage → local disk) ───────────────────────────

def _local_path_for_storage(rel_path: str) -> Optional[str]:
    """
    Map a crosswalk-data bucket path to a local filesystem path.
    Returns None for paths that should not be synced.
    """
    if not rel_path or rel_path.endswith("/"):
        return None

    # p21/{file} → p21_data/{mapped-or-same}
    if rel_path.startswith("p21/"):
        fname  = rel_path.split("/", 1)[1]
        mapped = _P21_FILE_RENAMES.get(fname, fname)
        return os.path.join(
            os.environ.get("P21_DATA_DIR", "/app/data/p21_data"), mapped
        )

    # quotes/{file} → quote_data/{file}
    if rel_path.startswith("quotes/"):
        fname = rel_path.split("/", 1)[1]
        return os.path.join(
            os.environ.get("QUOTE_DATA_DIR", "/app/data/quote_data"), fname
        )

    # top-level file → crosswalks/{file}
    if "/" not in rel_path:
        return os.path.join(
            os.environ.get("CROSSWALK_DIR", "/app/data/crosswalks"), rel_path
        )

    return None


def _list_all_bucket_files(client, bucket: str, folders: list) -> list:
    """List files in each folder of a bucket, returning (rel_path, size) tuples."""
    files = []
    # Top-level files
    try:
        for item in client.storage.from_(bucket).list("") or []:
            name = item.get("name", "")
            if name and not name.endswith("/"):
                files.append((name, item.get("metadata", {}).get("size", 0)))
    except Exception as exc:
        logger.warning(f"Could not list root of {bucket}: {exc}")

    for folder in folders:
        try:
            for item in client.storage.from_(bucket).list(folder) or []:
                name = item.get("name", "")
                if name and not name.endswith("/"):
                    files.append((f"{folder}/{name}", item.get("metadata", {}).get("size", 0)))
        except Exception as exc:
            logger.warning(f"Could not list {bucket}/{folder}: {exc}")

    return files


def sync_crosswalks_from_blob() -> dict:
    """
    Download every file from the crosswalk-data Supabase Storage bucket
    to the matching local directory on disk. Mirrors the old Azure Blob sync.

    Safe to call on cold start or on demand via /api/v1/crosswalk/sync-from-blob.
    """
    uploader = get_uploader()
    result = {
        "downloaded": [],
        "skipped":    [],
        "errors":     [],
        "container":  XWALK_BUCKET,
    }

    if not uploader.is_configured():
        result["errors"].append(
            "Supabase client not configured (missing SUPABASE_URL / SUPABASE_KEY?)"
        )
        return result

    client = uploader._client
    all_files = _list_all_bucket_files(client, XWALK_BUCKET, ["p21", "quotes"])

    for rel_path, size in all_files:
        local_path = _local_path_for_storage(rel_path)
        if not local_path:
            result["skipped"].append(rel_path)
            continue
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            data = client.storage.from_(XWALK_BUCKET).download(rel_path)
            with open(local_path, "wb") as fh:
                fh.write(data)
            result["downloaded"].append({
                "blob":  rel_path,
                "local": local_path,
                "size":  size,
            })
            logger.info(f"Synced {XWALK_BUCKET}/{rel_path} -> {local_path} ({size} bytes)")
        except Exception as exc:
            result["errors"].append(f"{rel_path}: {exc}")
            logger.error(f"Failed to sync {rel_path}: {exc}")

    return result

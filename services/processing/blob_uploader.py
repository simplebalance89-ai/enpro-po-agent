"""
blob_uploader.py — Upload CISM files to Azure Blob Storage.
Handles approved POs destined for P21 import via SQL Agent job.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from azure.core.exceptions import ResourceNotFoundError, AzureError
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logging.warning("Azure Storage SDK not installed. Blob upload disabled.")

logger = logging.getLogger(__name__)

# Configuration from environment
BLOB_CONNECTION_STRING = os.environ.get("AZURE_BLOB_CONNECTION_STRING", "")
BLOB_CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER_NAME", "fm-data")
BLOB_APPROVED_PREFIX = os.environ.get("AZURE_BLOB_APPROVED_PREFIX", "cism/approved")
BLOB_REJECTED_PREFIX = os.environ.get("AZURE_BLOB_REJECTED_PREFIX", "cism/rejected")


class BlobUploader:
    """Azure Blob Storage uploader for CISM files."""
    
    def __init__(self):
        self.client: Optional[BlobServiceClient] = None
        self._connected = False
        
        if not AZURE_AVAILABLE:
            logger.error("Azure Storage SDK not available. Install: pip install azure-storage-blob")
            return
            
        if not BLOB_CONNECTION_STRING:
            logger.warning("AZURE_BLOB_CONNECTION_STRING not set. Blob upload disabled.")
            return
            
        try:
            self.client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
            self._connected = True
            logger.info("BlobUploader initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize BlobServiceClient: {e}")
    
    def is_configured(self) -> bool:
        """Check if blob upload is properly configured."""
        return self._connected and AZURE_AVAILABLE
    
    def upload_cism(
        self,
        local_file_path: str,
        po_number: str,
        intake_id: str,
        status: str = "approved"
    ) -> dict:
        """
        Upload a CISM file to blob storage.
        
        Args:
            local_file_path: Path to local CISM file
            po_number: Purchase order number
            intake_id: Intake ID for tracking
            status: 'approved' or 'rejected'
            
        Returns:
            dict with blob_url, blob_name, success status
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Blob upload not configured",
                "blob_url": None,
                "blob_name": None,
            }
        
        try:
            # Determine blob path
            prefix = BLOB_APPROVED_PREFIX if status == "approved" else BLOB_REJECTED_PREFIX
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = Path(local_file_path).name
            blob_name = f"{prefix}/{timestamp}_{po_number}_{intake_id}_{filename}"
            
            # Get blob client
            blob_client = self.client.get_blob_client(
                container=BLOB_CONTAINER_NAME,
                blob=blob_name
            )
            
            # Upload file
            with open(local_file_path, "rb") as data:
                blob_client.upload_blob(
                    data,
                    overwrite=True,
                    content_settings=ContentSettings(
                        content_type="text/plain",
                        content_encoding="utf-8",
                    )
                )
            
            blob_url = blob_client.url
            logger.info(f"Uploaded CISM to blob: {blob_name}")
            
            return {
                "success": True,
                "blob_url": blob_url,
                "blob_name": blob_name,
                "container": BLOB_CONTAINER_NAME,
                "error": None,
            }
            
        except ResourceNotFoundError as e:
            logger.error(f"Blob container not found: {BLOB_CONTAINER_NAME}")
            return {
                "success": False,
                "error": f"Container not found: {e}",
                "blob_url": None,
                "blob_name": None,
            }
        except AzureError as e:
            logger.error(f"Azure error uploading blob: {e}")
            return {
                "success": False,
                "error": f"Azure error: {e}",
                "blob_url": None,
                "blob_name": None,
            }
        except Exception as e:
            logger.error(f"Unexpected error uploading blob: {e}")
            return {
                "success": False,
                "error": str(e),
                "blob_url": None,
                "blob_name": None,
            }
    
    def list_cism_files(self, prefix: str = None) -> list:
        """List CISM files in blob storage."""
        if not self.is_configured():
            return []
        
        try:
            container_client = self.client.get_container_client(BLOB_CONTAINER_NAME)
            prefix = prefix or BLOB_APPROVED_PREFIX
            blobs = []
            
            for blob in container_client.list_blobs(name_starts_with=prefix):
                blobs.append({
                    "name": blob.name,
                    "size": blob.size,
                    "created": blob.creation_time.isoformat() if blob.creation_time else None,
                    "url": f"{container_client.url}/{blob.name}",
                })
            
            return sorted(blobs, key=lambda x: x["created"] or "", reverse=True)
            
        except Exception as e:
            logger.error(f"Error listing blobs: {e}")
            return []
    
    def download_cism(self, blob_name: str, local_path: str) -> bool:
        """Download a CISM file from blob storage."""
        if not self.is_configured():
            return False
        
        try:
            blob_client = self.client.get_blob_client(
                container=BLOB_CONTAINER_NAME,
                blob=blob_name
            )
            
            with open(local_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
            
            logger.info(f"Downloaded blob to: {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading blob: {e}")
            return False


# Global instance
_uploader: Optional[BlobUploader] = None


def get_uploader() -> BlobUploader:
    """Get or create singleton BlobUploader instance."""
    global _uploader
    if _uploader is None:
        _uploader = BlobUploader()
    return _uploader


def upload_approved_cism(local_file_path: str, po_number: str, intake_id: str) -> dict:
    """Convenience function to upload an approved CISM file."""
    return get_uploader().upload_cism(
        local_file_path=local_file_path,
        po_number=po_number,
        intake_id=intake_id,
        status="approved"
    )


# ── Blob → Disk sync for crosswalks / P21 data ──────────────────────────────

# Maps blob key under the "crosswalk/" prefix to the local filesystem path the
# rest of the app expects. Missing blobs are silently skipped; extra blobs
# under the prefix fall through the default mapping below.
_P21_FILE_RENAMES = {
    "so_headers_latest.csv": "p21_headers.csv",
    "so_lines_latest.csv": "p21_lines.csv",
    "customers_latest.csv": "p21_customers.csv",
    # ship_tos / items aren't required by build_all but sync them anyway for
    # anything downstream that might want them.
    "ship_tos_latest.csv": "p21_ship_tos.csv",
    "items_latest.csv": "p21_items.csv",
}


def _local_path_for_blob(blob_name: str) -> Optional[str]:
    """
    Map a blob name under the 'crosswalk/' prefix to a local path on the
    persistent disk. Returns None for blobs that shouldn't be synced.
    """
    if not blob_name.startswith("crosswalk/"):
        return None
    rel = blob_name[len("crosswalk/"):]
    if not rel or rel.endswith("/"):
        return None

    # crosswalk/p21/<file> → /app/data/p21_data/<mapped-or-same>
    if rel.startswith("p21/"):
        fname = rel.split("/", 1)[1]
        mapped = _P21_FILE_RENAMES.get(fname, fname)
        return os.path.join(os.environ.get("P21_DATA_DIR", "/app/data/p21_data"), mapped)

    # crosswalk/quotes/<file> → /app/data/quote_data/<file>
    if rel.startswith("quotes/"):
        fname = rel.split("/", 1)[1]
        return os.path.join(os.environ.get("QUOTE_DATA_DIR", "/app/data/quote_data"), fname)

    # crosswalk/<file> (top level pre-built crosswalk CSVs) → /app/data/crosswalks/<file>
    if "/" not in rel:
        return os.path.join(os.environ.get("CROSSWALK_DIR", "/app/data/crosswalks"), rel)

    # Anything else under crosswalk/ — ignore (nested dirs we don't know about)
    return None


def sync_crosswalks_from_blob() -> dict:
    """
    Download every file under the blob 'crosswalk/' prefix into the matching
    local directory on the persistent disk. Returns a summary dict.

    Safe to call on a cold start with an empty disk, or on demand via the
    /api/v1/crosswalk/sync-from-blob endpoint.
    """
    uploader = get_uploader()
    result = {
        "downloaded": [],
        "skipped": [],
        "errors": [],
        "container": BLOB_CONTAINER_NAME,
    }

    if not uploader.is_configured():
        result["errors"].append("Blob client not configured (missing AZURE_BLOB_CONNECTION_STRING?)")
        return result

    try:
        container_client = uploader.client.get_container_client(BLOB_CONTAINER_NAME)
        blobs = list(container_client.list_blobs(name_starts_with="crosswalk/"))
    except Exception as e:
        result["errors"].append(f"list_blobs failed: {e}")
        return result

    for blob in blobs:
        local_path = _local_path_for_blob(blob.name)
        if not local_path:
            result["skipped"].append(blob.name)
            continue
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            blob_client = container_client.get_blob_client(blob.name)
            with open(local_path, "wb") as f:
                f.write(blob_client.download_blob().readall())
            result["downloaded"].append({
                "blob": blob.name,
                "local": local_path,
                "size": blob.size,
            })
            logger.info(f"Synced blob {blob.name} -> {local_path} ({blob.size} bytes)")
        except Exception as e:
            result["errors"].append(f"{blob.name}: {e}")
            logger.error(f"Failed to sync blob {blob.name}: {e}")

    return result


def upload_rejected_cism(local_file_path: str, po_number: str, intake_id: str) -> dict:
    """Convenience function to upload a rejected CISM file."""
    return get_uploader().upload_cism(
        local_file_path=local_file_path,
        po_number=po_number,
        intake_id=intake_id,
        status="rejected"
    )

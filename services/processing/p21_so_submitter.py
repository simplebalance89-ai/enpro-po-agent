"""
p21_so_submitter.py — Submit approved POs to P21 as Sales Orders via Transaction API.
Falls back to CISM file generation if P21 API is not configured.
"""

import logging
from config import get_settings

logger = logging.getLogger(__name__)

_client = None

def get_p21_client():
    """Lazy-init the P21 API client. Returns None if not configured."""
    global _client
    settings = get_settings()
    if not settings.p21_base_url:
        return None
    if _client is None:
        from services.processing.p21_api_client import P21ApiClient
        _client = P21ApiClient(
            base_url=settings.p21_base_url,
            username=settings.p21_api_username,
            password=settings.p21_api_password,
            verify_ssl=settings.p21_verify_ssl,
        )
    return _client


async def submit_to_p21(po_data: dict) -> dict:
    """
    Submit an approved PO to P21 as a Sales Order.

    If P21 API is configured (p21_base_url is set), creates SO via Transaction API.
    Otherwise, falls back to CISM file generation.

    Args:
        po_data: dict with keys: header, lines, customer_match, customer_defaults, cism (optional)

    Returns:
        dict with keys:
            method: "api" or "cism"
            order_no: P21 order number (API only)
            status: "success" or "error"
            message: human-readable result
            cism_path: path to CISM files (CISM only)
    """
    client = get_p21_client()

    if client is not None:
        # API path
        try:
            result = await client.create_sales_order(po_data)
            order_no = result.get("order_no", "")
            if result.get("status") == "Passed":
                logger.info(f"P21 SO created: order_no={order_no} for PO {po_data.get('header', {}).get('po_no', '?')}")
                return {
                    "method": "api",
                    "order_no": order_no,
                    "status": "success",
                    "message": f"Sales Order {order_no} created in P21",
                }
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"P21 API failed for PO {po_data.get('header', {}).get('po_no', '?')}: {error_msg}")
                return {
                    "method": "api",
                    "order_no": "",
                    "status": "error",
                    "message": f"P21 API error: {error_msg}",
                }
        except Exception as e:
            logger.exception(f"P21 API exception: {e}")
            return {
                "method": "api",
                "order_no": "",
                "status": "error",
                "message": f"P21 API connection failed: {e}",
            }
    else:
        # CISM fallback
        logger.info("P21 API not configured — falling back to CISM file generation")
        from services.processing.cism_so_generator import generate_cism_so
        from services.processing.cism_batch import add_to_batch
        settings = get_settings()

        cism_result = generate_cism_so(
            po_data=po_data,
            output_dir=settings.cism_so_output_dir,
        )

        # Add to batch
        add_to_batch(po_data)

        return {
            "method": "cism",
            "order_no": "",
            "status": "success",
            "message": "CISM files generated (P21 API not configured)",
            "cism_path": cism_result.get("output_dir", ""),
        }

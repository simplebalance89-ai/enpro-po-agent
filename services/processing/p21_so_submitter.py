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

        header = po_data.get("header", {}) or {}
        customer_match = po_data.get("customer_match", {}) or {}
        customer_defaults = po_data.get("customer_defaults", {}) or {}
        lines = po_data.get("lines", []) or []

        cism_lines = []
        for line in lines:
            cism_lines.append({
                "item_id": line.get("item_id_p21") or line.get("inv_mast_uid") or line.get("supplier_part_id", ""),
                "qty_ordered": line.get("qty_ordered", 0),
                "unit_of_measure": line.get("unit_of_measure", "EA"),
                "unit_price": line.get("unit_price", 0),
                "item_description": line.get("item_description", ""),
                "product_group": line.get("product_group", ""),
                "required_date": line.get("required_date", "") or line.get("date_due", ""),
                "supplier_part_id": line.get("supplier_part_id", ""),
                "inv_mast_uid": line.get("item_id_p21") or line.get("inv_mast_uid", ""),
                "line_no": line.get("line_no", 0),
            })

        cism_result = generate_cism_so(
            p21_customer_id=customer_match.get("p21_id", ""),
            p21_customer_name=customer_match.get("name", ""),
            p21_ship_to_id=customer_defaults.get("address_id", ""),
            po_no=header.get("po_no", ""),
            order_date=header.get("order_date", ""),
            requested_date=header.get("date_due", ""),
            ship2_name=header.get("ship2_name", ""),
            ship2_add1=header.get("ship2_add1", ""),
            ship2_add2=header.get("ship2_add2", ""),
            ship2_city=header.get("ship2_city", ""),
            ship2_state=header.get("ship2_state", ""),
            ship2_zip=header.get("ship2_zip", ""),
            ship2_country=header.get("ship2_country", "US"),
            ship2_email=header.get("buyer_email", ""),
            contact_id=customer_defaults.get("contact_id", ""),
            contact_name=header.get("buyer", "") or customer_match.get("name", ""),
            taker=settings.p21_default_taker,
            terms=customer_defaults.get("terms_id", ""),
            carrier_id=customer_defaults.get("carrier_id", ""),
            delivery_instructions=header.get("comments", "") or header.get("po_desc", ""),
            approved="Y",
            class_1=customer_defaults.get("class_1id", ""),
            source_id=po_data.get("source", ""),
            lines=cism_lines,
            output_dir=settings.cism_so_output_dir,
        )

        # Add to batch
        add_to_batch(po_data)

        return {
            "method": "cism",
            "order_no": "",
            "status": "success",
            "message": "CISM files generated (P21 API not configured)",
            "cism_path": cism_result.get("header_path", ""),
        }

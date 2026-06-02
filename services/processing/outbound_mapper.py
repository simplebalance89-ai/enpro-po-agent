"""
outbound_mapper.py — Map P21 invoice data to outbound Ariba/Coupa sync payloads.

Stub schemas for foundation phase. Real field population is added when live
credentials and target endpoint contracts are confirmed.

Ariba: cXML-flavored JSON envelope.
Coupa: REST JSON envelope matching Coupa Invoice API shape.
"""

from datetime import datetime


def _build_ariba_payload(outbound_record: dict, po_data: dict) -> dict:
    """Build Ariba-compatible cXML invoice sync payload (stub schema)."""
    lines = po_data.get("lines", [])
    currency = outbound_record.get("currency", "USD")

    ariba_lines = []
    for i, line in enumerate(lines, 1):
        qty = line.get("qty_ordered") or 0
        price = line.get("unit_price") or 0
        ariba_lines.append({
            "lineNumber": i,
            "supplierPartID": line.get("supplier_part_id", ""),
            "description": line.get("item_description", ""),
            "quantity": qty,
            "unitPrice": {"amount": price, "currency": currency},
            "uom": line.get("unit_of_measure", "EA"),
            "p21InvMastUID": line.get("item_id_p21", ""),
            "lineTotal": round(qty * price, 4) if qty and price else 0,
        })

    return {
        "schema": "ariba-invoice-sync-v1",
        "generatedAt": datetime.utcnow().isoformat(),
        "extrinsics": {
            "PurchaseOrderNumber": outbound_record.get("po_no", ""),
            "P21OrderNumber": outbound_record.get("p21_order_no", ""),
            "InvoiceNumber": outbound_record.get("p21_invoice_no", ""),
            "InvoiceDate": outbound_record.get("invoice_date", ""),
            "OutboundSyncID": outbound_record.get("outbound_id", ""),
        },
        "header": {
            "buyerCookie": outbound_record.get("customer_id", ""),
            "currency": currency,
            "paymentTerms": po_data.get("terms", "") or (po_data.get("header") or {}).get("terms", ""),
        },
        "invoiceDetail": {
            "invoiceID": outbound_record.get("p21_invoice_no", "") or outbound_record.get("p21_order_no", ""),
            "invoiceDate": outbound_record.get("invoice_date", ""),
            "totalAmount": outbound_record.get("amount_total", 0.0),
            "currency": currency,
            "lineItems": ariba_lines,
        },
    }


def _build_coupa_payload(outbound_record: dict, po_data: dict) -> dict:
    """Build Coupa-compatible REST invoice sync payload (stub schema)."""
    lines = po_data.get("lines", [])
    currency = outbound_record.get("currency", "USD")

    coupa_lines = []
    for i, line in enumerate(lines, 1):
        qty = line.get("qty_ordered") or 0
        price = line.get("unit_price") or 0
        coupa_lines.append({
            "line-num": i,
            "description": line.get("item_description", ""),
            "supplier-part-num": line.get("supplier_part_id", ""),
            "p21-inv-mast-uid": line.get("item_id_p21", ""),
            "quantity": qty,
            "price": price,
            "total": round(qty * price, 4) if qty and price else 0,
            "uom": {"code": line.get("unit_of_measure", "EA")},
            "account-type": {"name": "Expense"},
        })

    return {
        "schema": "coupa-invoice-sync-v1",
        "generated-at": datetime.utcnow().isoformat(),
        "po-number": outbound_record.get("po_no", ""),
        "order-id": outbound_record.get("p21_order_no", ""),
        "invoice-number": outbound_record.get("p21_invoice_no", "") or outbound_record.get("p21_order_no", ""),
        "invoice-date": outbound_record.get("invoice_date", ""),
        "outbound-sync-id": outbound_record.get("outbound_id", ""),
        "customer-id": outbound_record.get("customer_id", ""),
        "currency": {"code": currency},
        "total-amount": outbound_record.get("amount_total", 0.0),
        "payment-terms": po_data.get("terms", "") or (po_data.get("header") or {}).get("terms", ""),
        "invoice-lines": coupa_lines,
    }


def build_payload(source_system: str, outbound_record: dict, po_data: dict) -> dict:
    """Select mapper by source_system and return shaped outbound payload."""
    src = (source_system or "ariba").lower().strip()
    if src == "coupa":
        return _build_coupa_payload(outbound_record, po_data)
    return _build_ariba_payload(outbound_record, po_data)

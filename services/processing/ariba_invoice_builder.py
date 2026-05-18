"""
ariba_invoice_builder.py -- Build Ariba cXML InvoiceDetailRequest from P21 invoice data.

Uses xml.etree.ElementTree to construct valid cXML 1.2.050 for Ariba Network.
Ariba-specific differences from Coupa:
  - Extrinsic fields for PO number, SO number, terms
  - DocumentReference for PO linkage
  - Tax uses TaxDetail with Description
  - Shipping uses Distribution with AccountingSegment
"""

import re
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring


def build_ariba_invoice_xml(invoice: dict, po_data: dict = None) -> str:
    """Build Ariba cXML InvoiceDetailRequest from P21 invoice data.

    Args:
        invoice: dict from invoice_store / p21_invoice_pull
        po_data: optional linked PO data for PO references

    Returns:
        cXML string ready to POST to Ariba Network
    """
    invoice_no = str(invoice.get("invoice_no", ""))
    invoice_date_raw = invoice.get("invoice_date", "")
    customer_id = str(invoice.get("customer_id", ""))
    ship_to = invoice.get("ship_to", {})
    lines = invoice.get("lines", [])
    po_no = str(invoice.get("po_no") or po_data.get("header", {}).get("po_no", "") if po_data else (invoice.get("po_no") or "N/A"))
    so_number = str(invoice.get("so_number", ""))

    # Parse invoice date to YYYY-MM-DD
    invoice_date = ""
    if invoice_date_raw:
        try:
            dt = datetime.fromisoformat(str(invoice_date_raw).replace("Z", "+00:00"))
            invoice_date = dt.strftime("%Y-%m-%d")
        except Exception:
            invoice_date = str(invoice_date_raw)[:10]
    if not invoice_date:
        invoice_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Terms days
    terms_id = str(invoice.get("terms_id", ""))
    terms_days = 30
    if terms_id:
        m = re.search(r"\d+", terms_id)
        if m:
            terms_days = int(m.group())

    freight_amount = round(float(invoice.get("freight_amount", 0) or 0), 2)
    tax_amount = round(float(invoice.get("tax_amount", 0) or 0), 2)
    invoice_amount = round(float(invoice.get("invoice_amount", 0) or 0), 2)

    # Compute subtotal from lines
    subtotal = 0.0
    for line in lines:
        subtotal += float(line.get("extended_price", 0) or 0)
    if subtotal == 0:
        subtotal = round(invoice_amount - tax_amount - freight_amount, 2)

    customer_name = str(ship_to.get("name") or "EnPro Industries")
    ship_to_name = str(ship_to.get("name") or "")
    address1 = str(ship_to.get("address1") or "")
    city = str(ship_to.get("city") or "")
    state = str(ship_to.get("state") or "")
    zip_code = str(ship_to.get("zip") or "")

    ts = datetime.utcnow().isoformat()

    # Root
    root = Element("cXML")
    root.set("version", "1.2.050")
    root.set("xml:lang", "en-US")
    root.set("timestamp", ts)
    root.set("payloadID", f"INV-{invoice_no}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")

    # Header
    header = SubElement(root, "Header")
    from_ = SubElement(header, "From")
    from_cred = SubElement(from_, "Credential")
    from_cred.set("domain", "NetworkId")
    from_identity = SubElement(from_cred, "Identity")
    from_identity.text = "ENPRO_INDUSTRIES"

    to = SubElement(header, "To")
    to_cred = SubElement(to, "Credential")
    to_cred.set("domain", "NetworkId")
    to_identity = SubElement(to_cred, "Identity")
    to_identity.text = "ARIBA_NETWORK"

    sender = SubElement(header, "Sender")
    sender_cred = SubElement(sender, "Credential")
    sender_cred.set("domain", "NetworkId")
    sender_identity = SubElement(sender_cred, "Identity")
    sender_identity.text = "ENPRO_INDUSTRIES"
    shared_secret = SubElement(sender_cred, "SharedSecret")
    shared_secret.text = ""
    user_agent = SubElement(sender, "UserAgent")
    user_agent.text = "EnPro PO Agent"

    # Request
    request = SubElement(root, "Request")
    request.set("deploymentMode", "production")

    inv_req = SubElement(request, "InvoiceDetailRequest")

    # InvoiceDetailRequestHeader
    inv_hdr = SubElement(inv_req, "InvoiceDetailRequestHeader")
    inv_hdr.set("invoiceID", invoice_no)
    inv_hdr.set("purpose", "standard")
    inv_hdr.set("operation", "new")
    inv_hdr.set("invoiceDate", invoice_date)

    SubElement(inv_hdr, "InvoiceDetailHeaderIndicator")

    line_indicator = SubElement(inv_hdr, "InvoiceDetailLineIndicator")
    line_indicator.set("isAccountingInLine", "yes")
    line_indicator.set("isTaxInLine", "yes")
    line_indicator.set("isShippingInLine", "yes")

    # Extrinsics (Ariba-specific)
    ext_po = SubElement(inv_hdr, "Extrinsic")
    ext_po.set("name", "PurchaseOrderNumber")
    ext_po.text = po_no

    ext_so = SubElement(inv_hdr, "Extrinsic")
    ext_so.set("name", "SalesOrderNumber")
    ext_so.text = so_number

    ext_terms = SubElement(inv_hdr, "Extrinsic")
    ext_terms.set("name", "PaymentTerms")
    ext_terms.text = terms_id or f"NET{terms_days}"

    # remitTo
    partner1 = SubElement(inv_hdr, "InvoicePartner")
    contact1 = SubElement(partner1, "Contact")
    contact1.set("role", "remitTo")
    contact1.set("addressID", customer_id)
    name1 = SubElement(contact1, "Name")
    name1.set("xml:lang", "en-US")
    name1.text = customer_name

    # billTo
    partner2 = SubElement(inv_hdr, "InvoicePartner")
    contact2 = SubElement(partner2, "Contact")
    contact2.set("role", "billTo")
    name2 = SubElement(contact2, "Name")
    name2.set("xml:lang", "en-US")
    name2.text = "EnPro Industries"

    # shipTo
    partner3 = SubElement(inv_hdr, "InvoicePartner")
    contact3 = SubElement(partner3, "Contact")
    contact3.set("role", "shipTo")
    name3 = SubElement(contact3, "Name")
    name3.set("xml:lang", "en-US")
    name3.text = ship_to_name
    postal = SubElement(contact3, "PostalAddress")
    street = SubElement(postal, "Street")
    street.text = address1
    city_el = SubElement(postal, "City")
    city_el.text = city
    state_el = SubElement(postal, "State")
    state_el.text = state
    zip_el = SubElement(postal, "PostalCode")
    zip_el.text = zip_code
    country = SubElement(postal, "Country")
    country.set("isoCountryCode", "US")
    country.text = "United States"

    # Shipping
    shipping = SubElement(inv_hdr, "InvoiceDetailShipping")
    ship_from = SubElement(shipping, "Contact")
    ship_from.set("role", "shipFrom")
    ship_from.set("addressID", "10")
    ship_from_name = SubElement(ship_from, "Name")
    ship_from_name.set("xml:lang", "en-US")
    ship_from_name.text = "EnPro Industries"

    # Payment terms
    payment_term = SubElement(inv_hdr, "PaymentTerm")
    payment_term.set("payInNumberOfDays", str(terms_days))

    # InvoiceDetailOrder with lines
    order = SubElement(inv_req, "InvoiceDetailOrder")
    order_info = SubElement(order, "InvoiceDetailOrderInfo")

    # OrderID
    order_id = SubElement(order_info, "OrderID")
    order_id.text = po_no

    # DocumentReference for PO (Ariba likes this)
    doc_ref = SubElement(order_info, "DocumentReference")
    doc_ref.set("payloadID", po_no)

    for line in lines:
        line_no = str(line.get("line_no", ""))
        qty = float(line.get("qty_invoiced", 0) or 0)
        unit_price = round(float(line.get("unit_price", 0) or 0), 2)
        extended_price = round(float(line.get("extended_price", 0) or 0), 2)
        description = str(line.get("description", "") or line.get("item_description", ""))
        item_id = str(line.get("item_id", ""))

        item = SubElement(order, "InvoiceDetailItem")
        item.set("invoiceLineNumber", line_no)
        item.set("quantity", str(qty))

        uom = SubElement(item, "UnitOfMeasure")
        uom.text = "EA"

        unit_price_el = SubElement(item, "UnitPrice")
        up_money = SubElement(unit_price_el, "Money")
        up_money.set("currency", "USD")
        up_money.text = f"{unit_price:.2f}"

        item_ref = SubElement(item, "InvoiceDetailItemReference")
        item_ref.set("lineNumber", line_no)
        # Ariba likes SupplierPartID
        sup_part = SubElement(item_ref, "SupplierPartID")
        sup_part.text = item_id
        desc = SubElement(item_ref, "Description")
        desc.set("xml:lang", "en-US")
        desc.text = description

        subtotal_el = SubElement(item, "SubtotalAmount")
        sub_money = SubElement(subtotal_el, "Money")
        sub_money.set("currency", "USD")
        sub_money.text = f"{extended_price:.2f}"

    # Summary
    summary = SubElement(inv_req, "InvoiceDetailSummary")

    subtotal_amt = SubElement(summary, "SubtotalAmount")
    subtotal_money = SubElement(subtotal_amt, "Money")
    subtotal_money.set("currency", "USD")
    subtotal_money.text = f"{subtotal:.2f}"

    # Tax with TaxDetail (Ariba-specific)
    if tax_amount > 0:
        tax = SubElement(summary, "Tax")
        tax_money = SubElement(tax, "Money")
        tax_money.set("currency", "USD")
        tax_money.text = f"{tax_amount:.2f}"
        tax_desc = SubElement(tax, "Description")
        tax_desc.set("xml:lang", "en-US")
        tax_desc.text = "Sales Tax"
        tax_detail = SubElement(tax, "TaxDetail")
        tax_detail.set("category", "sales")
        tax_detail.set("percentageRate", "0")
        td_money = SubElement(tax_detail, "TaxableAmount")
        td_money_el = SubElement(td_money, "Money")
        td_money_el.set("currency", "USD")
        td_money_el.text = f"{subtotal:.2f}"
        td_tax = SubElement(tax_detail, "TaxAmount")
        td_tax_money = SubElement(td_tax, "Money")
        td_tax_money.set("currency", "USD")
        td_tax_money.text = f"{tax_amount:.2f}"

    # Shipping
    if freight_amount > 0:
        ship_amt = SubElement(summary, "ShippingAmount")
        ship_money = SubElement(ship_amt, "Money")
        ship_money.set("currency", "USD")
        ship_money.text = f"{freight_amount:.2f}"
        ship_desc = SubElement(ship_amt, "Description")
        ship_desc.set("xml:lang", "en-US")
        ship_desc.text = "Freight"

    # GrossAmount (Ariba likes this)
    gross = SubElement(summary, "GrossAmount")
    gross_money = SubElement(gross, "Money")
    gross_money.set("currency", "USD")
    gross_money.text = f"{invoice_amount:.2f}"

    net = SubElement(summary, "NetAmount")
    net_money = SubElement(net, "Money")
    net_money.set("currency", "USD")
    net_money.text = f"{invoice_amount:.2f}"

    xml_body = tostring(root, encoding="unicode")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.050/InvoiceDetail.dtd">\n'
        f"{xml_body}"
    )

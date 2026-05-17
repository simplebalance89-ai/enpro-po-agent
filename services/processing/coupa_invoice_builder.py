"""
coupa_invoice_builder.py -- Build Coupa cXML InvoiceDetailRequest from P21 invoice data.

Uses xml.etree.ElementTree to construct valid cXML 1.2.050.
"""

import re
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

try:
    import defusedxml.ElementTree as DET  # noqa: F401
except ImportError:
    DET = None


def build_coupa_invoice_xml(invoice: dict, po_data: dict = None) -> str:
    """Build Coupa cXML InvoiceDetailRequest from P21 invoice data.

    Args:
        invoice: dict from invoice_store / p21_invoice_pull
        po_data: optional linked PO data for PO references

    Returns:
        cXML string ready to POST to Coupa
    """
    invoice_no = invoice.get("invoice_no", "")
    invoice_date_raw = invoice.get("invoice_date", "")
    customer_id = invoice.get("customer_id", "")
    ship_to = invoice.get("ship_to", {})
    lines = invoice.get("lines", [])
    po_no = invoice.get("po_no") or "N/A"

    # Parse invoice date to YYYY-MM-DD
    invoice_date = ""
    if invoice_date_raw:
        try:
            dt = datetime.fromisoformat(invoice_date_raw.replace("Z", "+00:00"))
            invoice_date = dt.strftime("%Y-%m-%d")
        except Exception:
            invoice_date = invoice_date_raw[:10]
    if not invoice_date:
        invoice_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Terms days — extract digits from terms_id, default 30
    terms_id = invoice.get("terms_id", "")
    terms_days = 30
    if terms_id:
        m = re.search(r"\d+", str(terms_id))
        if m:
            terms_days = int(m.group())

    source_location_id = 10

    # Money helpers
    def _money(val):
        return str(round(float(val or 0), 2))

    freight_amount = _money(invoice.get("freight_amount", 0))
    tax_amount = _money(invoice.get("tax_amount", 0))
    invoice_amount = _money(invoice.get("invoice_amount", 0))

    # Compute subtotal from lines if possible, otherwise invoice_amount - tax - freight
    subtotal = 0.0
    for line in lines:
        subtotal += float(line.get("extended_price", 0) or 0)
    if subtotal == 0:
        subtotal = float(invoice_amount) - float(tax_amount) - float(freight_amount)
    subtotal = round(subtotal, 2)

    net_amount = round(
        float(invoice_amount),
        2,
    )

    customer_name = ship_to.get("name") or "EnPro Industries"
    ship_to_name = ship_to.get("name") or ""
    address1 = ship_to.get("address1") or ""
    city = ship_to.get("city") or ""
    state = ship_to.get("state") or ""
    zip_code = ship_to.get("zip") or ""

    ts = datetime.utcnow().isoformat()

    # Root
    root = Element("cXML")
    root.set("version", "1.2.050")
    root.set("xml:lang", "en-US")
    root.set("timestamp", ts)

    # Header
    header = SubElement(root, "Header")
    from_ = SubElement(header, "From")
    from_cred = SubElement(from_, "Credential")
    from_cred.set("domain", "DUNS")
    from_identity = SubElement(from_cred, "Identity")
    from_identity.text = "ENPRO"

    to = SubElement(header, "To")
    to_cred = SubElement(to, "Credential")
    to_cred.set("domain", "DUNS")
    to_identity = SubElement(to_cred, "Identity")
    to_identity.text = "COUPA"

    sender = SubElement(header, "Sender")
    sender_cred = SubElement(sender, "Credential")
    sender_cred.set("domain", "DUNS")
    sender_identity = SubElement(sender_cred, "Identity")
    sender_identity.text = "ENPRO"
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
    inv_hdr.set("invoiceID", str(invoice_no))
    inv_hdr.set("purpose", "standard")
    inv_hdr.set("operation", "new")
    inv_hdr.set("invoiceDate", invoice_date)

    SubElement(inv_hdr, "InvoiceDetailHeaderIndicator")

    line_indicator = SubElement(inv_hdr, "InvoiceDetailLineIndicator")
    line_indicator.set("isAccountingInLine", "yes")
    line_indicator.set("isTaxInLine", "yes")
    line_indicator.set("isShippingInLine", "yes")

    # remitTo
    partner1 = SubElement(inv_hdr, "InvoicePartner")
    contact1 = SubElement(partner1, "Contact")
    contact1.set("role", "remitTo")
    contact1.set("addressID", str(customer_id))
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
    ship_from.set("addressID", str(source_location_id))
    ship_from_name = SubElement(ship_from, "Name")
    ship_from_name.set("xml:lang", "en-US")
    ship_from_name.text = "EnPro Industries"

    # Payment terms
    payment_term = SubElement(inv_hdr, "PaymentTerm")
    payment_term.set("payInNumberOfDays", str(terms_days))

    # InvoiceDetailOrder with lines
    order = SubElement(inv_req, "InvoiceDetailOrder")
    order_info = SubElement(order, "OrderInfo")
    order_id = SubElement(order_info, "OrderID")
    order_id.text = po_no

    for line in lines:
        line_no = line.get("line_no", "")
        qty = line.get("qty_invoiced", 0)
        unit_price = _money(line.get("unit_price", 0))
        extended_price = _money(line.get("extended_price", 0))
        description = line.get("description", "")

        item = SubElement(order, "InvoiceDetailItem")
        item.set("invoiceLineNumber", str(line_no))
        item.set("quantity", str(qty))

        uom = SubElement(item, "UnitOfMeasure")
        uom.text = "EA"

        unit_price_el = SubElement(item, "UnitPrice")
        up_money = SubElement(unit_price_el, "Money")
        up_money.set("currency", "USD")
        up_money.text = unit_price

        item_ref = SubElement(item, "InvoiceDetailItemReference")
        item_ref.set("lineNumber", str(line_no))
        desc = SubElement(item_ref, "Description")
        desc.set("xml:lang", "en-US")
        desc.text = description

        subtotal_el = SubElement(item, "SubtotalAmount")
        sub_money = SubElement(subtotal_el, "Money")
        sub_money.set("currency", "USD")
        sub_money.text = extended_price

    # Summary
    summary = SubElement(inv_req, "InvoiceDetailSummary")

    subtotal_amt = SubElement(summary, "SubtotalAmount")
    subtotal_money = SubElement(subtotal_amt, "Money")
    subtotal_money.set("currency", "USD")
    subtotal_money.text = str(subtotal)

    tax = SubElement(summary, "Tax")
    tax_money = SubElement(tax, "Money")
    tax_money.set("currency", "USD")
    tax_money.text = tax_amount
    tax_desc = SubElement(tax, "Description")
    tax_desc.set("xml:lang", "en-US")
    tax_desc.text = "Tax"

    ship_amt = SubElement(summary, "ShippingAmount")
    ship_money = SubElement(ship_amt, "Money")
    ship_money.set("currency", "USD")
    ship_money.text = freight_amount
    ship_desc = SubElement(ship_amt, "Description")
    ship_desc.set("xml:lang", "en-US")
    ship_desc.text = "Freight"

    net = SubElement(summary, "NetAmount")
    net_money = SubElement(net, "Money")
    net_money.set("currency", "USD")
    net_money.text = str(net_amount)

    xml_body = tostring(root, encoding="unicode")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.050/InvoiceDetail.dtd">\n'
        f"{xml_body}"
    )

"""
po_parser.py — Parse cXML and PDF purchase orders into structured models.
Handles Ariba cXML OrderRequest, Coupa cXML, and PDF via pdfplumber + regex.
MRO-specific: blanket POs, releases, line-level ShipTo, GL codes, Extrinsics.

Models aligned to real P21 po_hdr/po_line schema (validated March 2026).
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

from models import POHeader, POLineItem, OrderType, SourceSystem, VEGA_SOURCE_TYPE


def parse_cxml(content: str) -> tuple[POHeader, list[POLineItem], str]:
    """Parse Ariba/Coupa cXML OrderRequest into structured header + lines."""
    root = ET.fromstring(content)

    orh = root.find('.//OrderRequestHeader')
    if orh is None:
        raise ValueError("No OrderRequestHeader found in cXML")

    # ── Header ───────────────────────────────────────────────────────────
    order_type_raw = orh.get('orderType', 'regular')
    order_type = OrderType.REGULAR
    if order_type_raw == 'blanket':
        order_type = OrderType.BLANKET
    elif order_type_raw == 'release':
        order_type = OrderType.RELEASE

    header = POHeader(
        po_no=orh.get('orderID', ''),
        order_date=orh.get('orderDate', '')[:10],
        order_type=order_type,
        order_version=orh.get('orderVersion', '1'),
        source_system=SourceSystem.EMAIL,  # Primary inflow is orders@enpro inbox
        # P21 defaults for Vega
        po_type='D',
        source_type=VEGA_SOURCE_TYPE,
        company_no=1,
        location_id=10,
        branch_id='000',
        ship2_country='US',
        approved='Y',
    )

    # Currency
    total_money = orh.find('.//Total/Money')
    if total_money is not None:
        header.currency_id = total_money.get('currency', 'USD')

    # Release info (blanket PO reference)
    release_info = orh.find('.//ReleaseInfo')
    if release_info is not None:
        header.blanket_po_no = release_info.get('masterOrderID', '')
        header.release_no = release_info.get('releaseNumber', '')

    # Ship To (header level) — maps to po_hdr ship2_* columns
    ship_to = orh.find('.//ShipTo/Address')
    if ship_to is not None:
        header.ship2_name = _get_text(ship_to, 'Name')
        postal = ship_to.find('.//PostalAddress')
        if postal is not None:
            streets = postal.findall('Street')
            if len(streets) >= 1:
                header.ship2_add1 = (streets[0].text or '').strip()
            if len(streets) >= 2:
                header.ship2_add2 = (streets[1].text or '').strip()
            if len(streets) >= 3:
                header.ship2_add3 = (streets[2].text or '').strip()
            header.ship2_city = _get_text(postal, 'City')
            header.ship2_state = _get_text(postal, 'State')
            header.ship2_zip = _get_text(postal, 'PostalCode')
            country = _get_text(postal, 'Country')
            if country:
                header.ship2_country = country

    # Buyer / Purchasing Agent — stored in notes (not direct po_hdr columns)
    buyer_contact = orh.find('.//Contact[@role="purchasingAgent"]')
    if buyer_contact is not None:
        header.buyer = _get_text(buyer_contact, 'Name')
        header.buyer_email = _get_text(buyer_contact, 'Email')
        phone = buyer_contact.find('.//TelephoneNumber')
        if phone is not None:
            area = _get_text(phone, 'AreaOrCityCode')
            number = _get_text(phone, 'Number')
            header.buyer_phone = f"{area}-{number}" if area else number

    # Delivery Terms → maps to fob / freight_terms
    tod = orh.find('.//TermsOfDelivery/TransportTerms')
    if tod is not None:
        header.freight_terms = (tod.get('value', '') + ' - ' + (tod.text or '')).strip(' -')
    fob_elem = orh.find('.//TermsOfDelivery/ShippingPaymentMethod')
    if fob_elem is not None:
        header.fob = fob_elem.get('value', '')

    # Extrinsics (MRO-specific fields)
    for ext in orh.findall('Extrinsic'):
        name = ext.get('name', '')
        val = ext.text or ''
        if name == 'AribaNetwork.PaymentTermsExplanation':
            header.terms = val
        elif name in ('ContractID', 'AgreementNumber', 'ContractNumber'):
            header.contract_no = val
        elif name == 'ExternalPONumber':
            header.external_po_no = val

    # Comments → po_desc (shipping instructions)
    comments = orh.find('Comments')
    if comments is not None:
        comment_text = (comments.text or '').strip()
        header.po_desc = comment_text  # shipping instructions go in po_desc
        header.comments = comment_text

    # Supplier info
    correspondent = root.find('.//To/Correspondent/Contact')
    if correspondent is not None:
        header.supplier_name = _get_text(correspondent, 'Name')
        header.supplier_email = _get_text(correspondent, 'Email')

    # ── Line Items ───────────────────────────────────────────────────────
    lines: list[POLineItem] = []
    for item_out in root.findall('.//ItemOut'):
        line = POLineItem(
            line_no=int(item_out.get('lineNumber', '0')),
            qty_ordered=float(item_out.get('quantity', '0')),
            date_due=item_out.get('requestedDeliveryDate', '')[:10] if item_out.get('requestedDeliveryDate') else '',
            # P21 defaults for Vega lines
            source_type=VEGA_SOURCE_TYPE,
            calc_type='MULTIPLIER',
            calc_value=1.0,
            unit_size=1.0,
            unit_quantity=1.0,
            pricing_unit_size=1.0,
            inventory_flag='N',
        )

        # Set required_date = date_due if present
        if line.date_due:
            line.required_date = line.date_due

        # Item ID
        item_id = item_out.find('.//ItemID')
        if item_id is not None:
            line.supplier_part_id = _get_text(item_id, 'SupplierPartID')

        # Item Detail
        detail = item_out.find('.//ItemDetail')
        if detail is not None:
            price_money = detail.find('.//UnitPrice/Money')
            if price_money is not None:
                line.unit_price = float(price_money.text or 0)
                line.unit_price_display = line.unit_price
                line.base_ut_price = line.unit_price

            line.item_description = _get_text(detail, 'Description')
            line.unit_of_measure = _get_text(detail, 'UnitOfMeasure') or 'EA'
            line.pricing_unit = line.unit_of_measure

            mfg_part = detail.find('ManufacturerPartID')
            if mfg_part is not None:
                line.mfg_part_no = mfg_part.text or ''

        # Line-level Ship To (MRO override)
        line_ship = item_out.find('.//ShipTo/Address')
        if line_ship is not None:
            line.ship_to_name = _get_text(line_ship, 'Name')
            line_postal = line_ship.find('.//PostalAddress')
            if line_postal is not None:
                line.ship_to_address = _get_text(line_postal, 'Street')
                line.ship_to_city = _get_text(line_postal, 'City')
                line.ship_to_state = _get_text(line_postal, 'State')
                line.ship_to_zip = _get_text(line_postal, 'PostalCode')

        # Accounting / Distribution (MRO GL codes) → maps to account_no
        accounting = item_out.find('.//Accounting')
        if accounting is not None:
            for seg in accounting.findall('.//AccountingSegment'):
                seg_type = seg.get('type', '')
                seg_val = _get_text(seg, 'Name') or _get_text(seg, 'Description')
                if seg_type == 'CostCenter':
                    line.cost_center = seg_val
                elif seg_type in ('Account', 'GLAccount'):
                    line.gl_account = seg_val
                    line.account_no = seg_val  # direct P21 mapping

        # Line Extrinsics (MRO work orders, asset IDs)
        for ext in item_out.findall('Extrinsic'):
            name = ext.get('name', '')
            val = ext.text or ''
            if name in ('WorkOrderNumber', 'MaintenanceOrder'):
                line.work_order = val
            elif name in ('AssetID', 'EquipmentID'):
                line.asset_id = val

        # Line Comments → extended_desc
        line_comments = item_out.find('Comments')
        if line_comments is not None:
            comment_text = (line_comments.text or '').strip()
            line.notes = comment_text
            line.extended_desc = comment_text

        lines.append(line)

    return header, lines, content


def parse_pdf(file_path: str, _endpoint: str = "", _key: str = "") -> tuple[POHeader, list[POLineItem], str]:
    """
    Parse PO PDF using pdfplumber (text + table extraction) and regex heuristics.

    Args:
        file_path: Path to the PDF file.
        _endpoint, _key: Ignored — kept for backward-compatible call sites.

    Returns:
        (POHeader, list[POLineItem], raw_text)

    Raises:
        ValueError if the PDF cannot be opened or yields no text at all.
    """
    import os
    import re
    import pdfplumber

    all_text_pages: list[str] = []
    all_tables: list[list] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_text_pages.append(text)
            for tbl in (page.extract_tables() or []):
                if tbl:
                    all_tables.append(tbl)

    full_text = "\n".join(all_text_pages)
    if not full_text.strip():
        raise ValueError("PDF produced no extractable text — may be a scanned image without OCR.")

    raw_text = full_text[:8000]

    # ── Helper: safe float ──────────────────────────────────────────────────
    def _f(s) -> float:
        try:
            return float(str(s or "").replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return 0.0

    # ── PO Number ───────────────────────────────────────────────────────────
    # Strategy 1: table column lookup — most reliable for columnar PDFs
    # (e.g. "Customer PO Number" header with value in same column next row)
    po_no = ""
    _PO_COL_RE = re.compile(
        r'\b(?:customer\s+)?(?:purchase\s+order|p\.?o\.?)\s*(?:number|no\.?|#)?\b',
        re.IGNORECASE,
    )
    for table in all_tables:
        for row_idx, row in enumerate(table):
            for col_idx, cell in enumerate(row):
                if cell and _PO_COL_RE.search(str(cell)):
                    # Value is in same column of the very next row
                    if row_idx + 1 < len(table) and col_idx < len(table[row_idx + 1]):
                        val = str(table[row_idx + 1][col_idx] or "").strip()
                        if len(val) >= 5 and re.match(r"[A-Z0-9]", val, re.I):
                            po_no = val
                            break
            if po_no:
                break
        if po_no:
            break

    # Strategy 2: regex over full text — ordered most-specific first.
    # All require ≥5-char result and avoid matching mid-word "po" substrings.
    if not po_no:
        for pat in [
            # "Customer PO Number" header; value appears later on the same line or next line
            # Handles: "Customer PO Number\nMOREC00 06/01/2026 4710632741"
            r"Customer\s+PO\s+(?:Number|No\.?)\s*:?\s*\n[^\n]*?(\d{6,12})",
            # Explicit single-line labeled fields with colon/hash separator
            r"PO\s+No\.?\s*[:#]\s*([A-Z0-9][A-Z0-9\-\/]{4,29})",
            r"PO\s*#\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]{4,29})",
            r"P\.O\.\s*(?:Number|No\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]{4,29})",
            r"Purchase\s+Order\s*(?:No\.?|#|Number)\s*[:#]\s*([A-Z0-9][A-Z0-9\-\/]{4,29})",
            r"Order\s+(?:No\.?|Number|#)\s*[:#]\s*([A-Z0-9][A-Z0-9\-\/]{4,29})",
            # Line starting with PO + digits: "PO34526211"
            r"^(PO\d{4,12})\b",
            # "PO Number" without colon — but only grab a pure-digit or clearly PO-shaped value
            # (avoids grabbing taker codes like MOREC00 that precede the real number)
            r"PO\s+Number\s*\n[^\n]*?(\d{6,12})",
            r"PO\s+Number\s*:?\s*(\d{6,12})",
        ]:
            m = re.search(pat, full_text, re.IGNORECASE | re.MULTILINE)
            if m:
                candidate = m.group(1).strip().rstrip(".")
                if len(candidate) >= 5 and not re.match(
                    r"^(Date|Terms|Ship|Bill|To|Net|Page|Rev|Corp|Inc|LLC|From|Attn|Taker)$",
                    candidate, re.IGNORECASE,
                ):
                    po_no = candidate
                    break

    # Fallback: filename stem when nothing matched or result is too short
    if not po_no or len(po_no) < 5:
        po_no = os.path.splitext(os.path.basename(file_path))[0][:40]

    # ── Order Date ──────────────────────────────────────────────────────────
    order_date = ""
    for pat in [
        r"(?:Order\s+Date|PO\s+Date|Date\s+Issued|Issue\s+Date)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(?:Order\s+Date|PO\s+Date|Date\s+Issued|Issue\s+Date)\s*:?\s*(\d{4}-\d{2}-\d{2})",
        r"(?:^|\s)Date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
    ]:
        m = re.search(pat, full_text, re.IGNORECASE | re.MULTILINE)
        if m:
            order_date = m.group(1).strip()
            break

    # ── Ship-To Name ────────────────────────────────────────────────────────
    ship2_name = ""
    for pat in [
        r"Ship\s*(?:To|To:)\s*\n?\s*(.{3,60})",
        r"Deliver\s*(?:To|To:)\s*\n?\s*(.{3,60})",
        r"Shipping\s*Address\s*:?\s*\n?\s*(.{3,60})",
        r"Sold\s*To\s*:?\s*\n?\s*(.{3,60})",
    ]:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            candidate = m.group(1).split("\n")[0].strip()
            if len(candidate) >= 3 and not re.match(r"^\d", candidate):
                ship2_name = candidate[:60]
                break

    # ── Street Address ──────────────────────────────────────────────────────
    ship2_add1 = ""
    addr_m = re.search(
        r"\b(\d{1,6}\s+[A-Z][a-zA-Z\s]{3,40}(?:St(?:reet)?|Ave(?:nue)?|Blvd|Dr(?:ive)?|Rd|Road|Way|Lane?|Ln|Pkwy|Pl(?:ace)?|Ct|Court|Hwy|Highway)\.?)",
        full_text,
    )
    if addr_m:
        ship2_add1 = addr_m.group(1).strip()[:80]

    # ── City, State, ZIP ────────────────────────────────────────────────────
    ship2_city, ship2_state, ship2_zip = "", "", ""
    csz_m = re.search(
        r"([A-Za-z][A-Za-z\s\.]{2,30}),?\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
        full_text,
    )
    if csz_m:
        ship2_city  = csz_m.group(1).strip()
        ship2_state = csz_m.group(2)
        ship2_zip   = csz_m.group(3)

    # ── Build header ────────────────────────────────────────────────────────
    header = POHeader(
        po_no=po_no,
        order_date=order_date,
        ship2_name=ship2_name,
        ship2_add1=ship2_add1,
        ship2_city=ship2_city,
        ship2_state=ship2_state,
        ship2_zip=ship2_zip,
        ship2_country="US",
    )

    # ── Line items: table extraction ────────────────────────────────────────
    lines: list[POLineItem] = []
    line_counter = 10

    for table in all_tables:
        if not table or len(table) < 2:
            continue
        header_row = [str(c or "").lower().strip() for c in (table[0] or [])]

        # Locate columns by header keyword
        def _col(*keywords):
            for kw in keywords:
                for i, h in enumerate(header_row):
                    if kw in h:
                        return i
            return None

        c_part  = _col("part", "item #", "item#", "product code", "catalog", "sku")
        c_desc  = _col("desc", "item desc", "product", "name", "material")
        c_qty   = _col("qty", "quantity", "ordered", "order qty")
        c_price = _col("unit price", "unit cost", "price each", "u/p", "price")
        c_ext   = _col("extended", "ext price", "amount", "total", "ext. price")
        c_uom   = _col("uom", "u/m", "unit of measure", "unit")
        c_date  = _col("required", "need by", "deliver", "due date", "ship date")

        for row in table[1:]:
            if not row or all(not str(c or "").strip() for c in row):
                continue

            def _cell(idx):
                if idx is not None and idx < len(row):
                    return str(row[idx] or "").strip()
                return ""

            part  = _cell(c_part)[:40]
            desc  = _cell(c_desc)[:80]
            qty   = _f(_cell(c_qty))
            price = _f(_cell(c_price))
            ext   = _f(_cell(c_ext))
            uom   = _cell(c_uom) or "EA"
            req   = _cell(c_date)[:10]

            # Derive price from extended if missing
            if price == 0 and ext > 0 and qty > 0:
                price = round(ext / qty, 4)

            # Skip header-like or empty rows
            if not desc and not part:
                continue
            if qty == 0 and price == 0:
                continue

            lines.append(POLineItem(
                line_no=line_counter,
                supplier_part_id=part,
                item_description=desc,
                qty_ordered=max(qty, 1.0),
                unit_price=price,
                unit_of_measure=uom[:10],
                required_date=req or order_date,
            ))
            line_counter += 10

    # ── Line items: regex fallback when tables empty ─────────────────────────
    if not lines:
        row_pat = re.compile(
            r"^\s*(\d+)\s+"
            r"([A-Z0-9][\w\-\.\/]{1,38})\s+"
            r"(.{5,60}?)\s{2,}"
            r"(\d+(?:\.\d+)?)\s+"
            r"\$?\s*(\d[\d,]*(?:\.\d{1,4})?)",
            re.MULTILINE,
        )
        for m in row_pat.finditer(full_text):
            try:
                lines.append(POLineItem(
                    line_no=int(m.group(1)) * 10,
                    supplier_part_id=m.group(2).strip(),
                    item_description=m.group(3).strip(),
                    qty_ordered=_f(m.group(4)),
                    unit_price=_f(m.group(5)),
                    unit_of_measure="EA",
                    required_date=order_date,
                ))
            except Exception:
                continue

    return header, lines, raw_text


def generate_cxml_response(payload_id: str, status_code: int = 200, status_text: str = "OK") -> str:
    """Generate a cXML Response document for Ariba Network.
    Must be returned within 60 seconds of receiving the OrderRequest.
    """
    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S+00:00')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.069/cXML.dtd">
<cXML payloadID="{payload_id}_response" timestamp="{timestamp}" version="1.2.069">
  <Response>
    <Status code="{status_code}" text="{status_text}">
      {status_text}
    </Status>
  </Response>
</cXML>"""


def _get_text(element, tag: str) -> str:
    """Safely get text from child element, handling namespaces."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    for child in element:
        if child.tag.endswith(tag) and child.text:
            return child.text.strip()
    return ''

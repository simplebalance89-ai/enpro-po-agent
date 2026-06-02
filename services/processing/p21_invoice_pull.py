"""
p21_invoice_pull.py -- Pull invoice headers and lines from P21 SQL database by SO number.

Queries dbo.oe_invoice_hdr and dbo.oe_invoice_line via pyodbc.
Falls back to empty list with a warning if pyodbc is not available.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_HEADER_SQL = """
SELECT
    i.invoice_no,
    i.order_no,
    i.customer_id,
    i.invoice_date,
    i.ship_date,
    i.terms_id,
    i.carrier_id,
    i.freight_amount,
    i.tax_amount,
    i.invoice_amount,
    i.ship2_name,
    i.ship2_add1,
    i.ship2_city,
    i.ship2_state,
    i.ship2_zip
FROM dbo.oe_invoice_hdr i
WHERE i.order_no = ?
"""

_LINE_SQL = """
SELECT
    l.invoice_no,
    l.line_no,
    l.item_id,
    l.qty_invoiced,
    l.unit_price,
    l.extended_price,
    l.item_description
FROM dbo.oe_invoice_line l
WHERE l.invoice_no = ?
ORDER BY l.line_no
"""


async def pull_invoices_for_so(
    so_number: str,
    p21_sql_server: str,
    p21_sql_database: str,
    p21_sql_uid: str,
    p21_sql_pwd: str,
    p21_sql_driver: str = "{ODBC Driver 17 for SQL Server}",
) -> list[dict]:
    """Pull invoice headers and lines from P21 for a given SO number.
    Returns list of invoice dicts."""

    try:
        import pyodbc
    except ImportError:
        logger.warning("pyodbc is not installed — cannot pull invoices from P21 SQL")
        return []

    conn_str = (
        f"DRIVER={p21_sql_driver};"
        f"SERVER={p21_sql_server};"
        f"DATABASE={p21_sql_database};"
        f"UID={p21_sql_uid};"
        f"PWD={p21_sql_pwd}"
    )

    invoices = {}

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Fetch headers
        cursor.execute(_HEADER_SQL, (so_number,))
        header_rows = cursor.fetchall()

        for row in header_rows:
            (
                invoice_no,
                order_no,
                customer_id,
                invoice_date,
                ship_date,
                terms_id,
                carrier_id,
                freight_amount,
                tax_amount,
                invoice_amount,
                ship2_name,
                ship2_add1,
                ship2_city,
                ship2_state,
                ship2_zip,
            ) = row

            inv_id = f"INV_{invoice_no}"
            invoices[inv_id] = {
                "invoice_id": inv_id,
                "invoice_no": str(invoice_no),
                "so_number": str(so_number),
                "po_no": "",  # will be filled from linked PO later
                "customer_id": str(customer_id),
                "invoice_date": invoice_date.isoformat() if invoice_date else "",
                "ship_date": ship_date.isoformat() if ship_date else "",
                "terms_id": str(terms_id or ""),
                "carrier_id": str(carrier_id or ""),
                "freight_amount": float(freight_amount or 0),
                "tax_amount": float(tax_amount or 0),
                "invoice_amount": float(invoice_amount or 0),
                "ship_to": {
                    "name": str(ship2_name or ""),
                    "address1": str(ship2_add1 or ""),
                    "city": str(ship2_city or ""),
                    "state": str(ship2_state or ""),
                    "zip": str(ship2_zip or ""),
                },
                "lines": [],
                "status": "pulled",
                "source": "p21",
                "pulled_at": datetime.utcnow().isoformat(),
            }

        # Fetch lines per invoice
        for inv_id, inv in invoices.items():
            cursor.execute(_LINE_SQL, (inv["invoice_no"],))
            line_rows = cursor.fetchall()
            for line in line_rows:
                (
                    _invoice_no,
                    line_no,
                    item_id,
                    qty_invoiced,
                    unit_price,
                    extended_price,
                    item_description,
                ) = line
                inv["lines"].append({
                    "line_no": int(line_no),
                    "item_id": str(item_id),
                    "description": str(item_description or ""),
                    "qty_invoiced": float(qty_invoiced or 0),
                    "unit_price": float(unit_price or 0),
                    "extended_price": float(extended_price or 0),
                })

        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"P21 SQL invoice pull failed for SO {so_number}: {e}")
        raise

    return list(invoices.values())

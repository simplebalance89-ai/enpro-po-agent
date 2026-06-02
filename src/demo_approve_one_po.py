"""
demo_approve_one_po.py — End-to-end demo: fix a red PO, approve it,
and verify CISM + P21 payload generation.

Run this after starting the server locally (start_local.ps1),
or run standalone to test the generators directly.

Usage:
    python demo_approve_one_po.py
"""

import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.processing.local_store import get_po, update_po, list_pos
from services.processing.cism_so_generator import generate_cism_so
from services.processing.cism_batch import add_to_batch, get_batch_status
from services.processing.p21_api_client import build_p21_payload
from services.processing.customer_crosswalk_engine import CustomerCrosswalkEngine
from config import get_settings

settings = get_settings()


def find_pending_red_po():
    """Find the first pending red PO with lines."""
    pos = list_pos()
    for po in pos:
        if po.get("review_status") == "pending" and po.get("confidence") == "red":
            return po
    # Fallback: any pending PO
    for po in pos:
        if po.get("review_status") == "pending":
            return po
    return None


def fix_po_for_demo(po: dict) -> dict:
    """Manually map customer and items so the PO becomes approvable."""
    intake_id = po["intake_id"]
    hdr = po.get("header", {})
    lines = po.get("lines", [])

    # Set a demo customer mapping
    customer_id = "207620"
    customer_name = "Stepan Chemical"
    hdr["customer_id_p21"] = customer_id
    hdr["customer_name_p21"] = customer_name
    hdr["customer_match_method"] = "manual_demo"
    hdr["customer_match_score"] = 1.0

    cm = po.get("customer_match", {})
    cm["p21_id"] = customer_id
    cm["name"] = customer_name
    cm["score"] = 1.0
    cm["method"] = "manual_demo"

    # Set item mappings on each line
    for i, line in enumerate(lines):
        line["item_id_p21"] = line.get("supplier_part_id", f"DEMO-ITEM-{i+1}")
        line["item_match_method"] = "manual_demo"
        line["item_match_score"] = 1.0

    po["confidence"] = "green"
    po["reason"] = "Demo fix — manual customer + item mapping"

    update_po(intake_id, po)
    print(f"[FIX] PO {po.get('po_no')} -> customer={customer_id}, {len(lines)} lines mapped")
    return po


def generate_cism_and_payload(po: dict) -> dict:
    """Generate CISM files + P21 payload for the PO."""
    intake_id = po["intake_id"]
    hdr = po.get("header", {})
    lines = po.get("lines", [])
    cust = po.get("customer_match", {})

    # 1. CISM SO generation
    cism_result = generate_cism_so(
        p21_customer_id=cust.get("p21_id", ""),
        p21_customer_name=cust.get("name", ""),
        p21_ship_to_id=hdr.get("ship_to_id_p21", ""),
        po_no=hdr.get("po_no", ""),
        order_date=hdr.get("order_date", ""),
        requested_date=hdr.get("order_date", ""),
        ship2_name=hdr.get("ship2_name", ""),
        ship2_add1=hdr.get("ship2_add1", ""),
        ship2_add2=hdr.get("ship2_add2", ""),
        ship2_city=hdr.get("ship2_city", ""),
        ship2_state=hdr.get("ship2_state", ""),
        ship2_zip=hdr.get("ship2_zip", ""),
        ship2_country=hdr.get("ship2_country", "US"),
        ship2_email=hdr.get("ship2_email", ""),
        ship2_phone=hdr.get("ship2_phone", ""),
        contact_id=hdr.get("contact_id", ""),
        contact_name=hdr.get("buyer", ""),
        taker=hdr.get("taker", "") or settings.p21_default_taker,
        terms=hdr.get("terms", ""),
        carrier_id=hdr.get("carrier_id", ""),
        carrier_name=hdr.get("carrier_name", ""),
        delivery_instructions=hdr.get("comments", ""),
        approved="Y",
        lines=[{
            "item_id": l.get("item_id_p21", l.get("supplier_part_id", "")),
            "qty_ordered": l.get("qty_ordered", 0),
            "unit_of_measure": l.get("unit_of_measure", "EA"),
            "unit_price": l.get("unit_price", 0),
            "item_description": l.get("item_description", ""),
            "product_group": l.get("product_group", ""),
            "supplier_id": l.get("supplier_id", ""),
            "disposition": l.get("disposition", "B"),
            "required_date": l.get("required_date", ""),
        } for l in lines],
        output_dir=settings.cism_so_output_dir,
    )
    print(f"[CISM] Generated: import_set={cism_result['import_set_no']}")
    print(f"       Header: {cism_result['header_path']}")
    print(f"       Lines:  {cism_result['lines_path']}")

    # 2. Add to batch
    po["cism"] = cism_result
    add_to_batch(po)
    print(f"[BATCH] Added to CISM batch")

    # 3. P21 payload
    try:
        engine = CustomerCrosswalkEngine(settings.crosswalk_dir)
        po["customer_defaults"] = engine.get_customer_defaults(cust.get("p21_id", ""))
    except Exception:
        po["customer_defaults"] = {}

    p21_payload = build_p21_payload(po)
    print(f"[P21] Payload built: {len(p21_payload['Transactions'][0]['DataElements'])} data elements")

    # Persist back to store
    po["review_status"] = "approved"
    po["approved"] = True
    po["reviewed_by"] = "demo"
    po["reviewed_at"] = "2026-05-17T00:00:00"
    po["p21_payload"] = p21_payload
    update_po(intake_id, po)
    print(f"[STORE] PO {po.get('po_no')} saved as approved with CISM + payload")

    return po


def show_batch():
    """Print current batch status."""
    status = get_batch_status()
    print(f"\n[BATCH STATUS]")
    print(f"  Headers: {status['header_count']} | Lines: {status['line_count']}")
    print(f"  Header file: {status['header_file']}")
    print(f"  Lines file:  {status['lines_file']}")


def main():
    print("=" * 60)
    print("  EnPro PO Agent — One-PO Demo")
    print("=" * 60)

    # Find a PO to process
    po = find_pending_red_po()
    if not po:
        print("No pending PO found. Checking for any PO...")
        all_pos = list_pos()
        if not all_pos:
            print("ERROR: No POs in local store.")
            return
        po = all_pos[0]
        print(f"Using existing PO: {po.get('po_no')} (status={po.get('review_status')})")
    else:
        print(f"Found pending PO: {po.get('po_no')}")

    # Fix if needed
    if po.get("confidence") != "green" or not po.get("header", {}).get("customer_id_p21"):
        po = fix_po_for_demo(po)

    # Generate CISM + payload
    generate_cism_and_payload(po)

    # Show batch
    show_batch()

    # Show file listing
    print(f"\n[LOCAL FILES]")
    for root, dirs, files in os.walk("./data"):
        for f in sorted(files):
            if f.endswith(".csv") or f.endswith(".json"):
                path = os.path.join(root, f)
                size = os.path.getsize(path)
                print(f"  {path} ({size} bytes)")

    print("\n" + "=" * 60)
    print("  Demo complete.")
    print("  Open http://localhost:8000 and go to CISM Batch tab.")
    print("=" * 60)


if __name__ == "__main__":
    main()

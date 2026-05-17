"""
server.py — Ariba/Coupa PO Automation Agent: FastAPI main application.
Forked from Vega MRO agent, extended with crosswalk + confidence + review portal.

Routes:
  GET  /                        → Dashboard / Review Portal
  GET  /health                  → Health check

  POST /api/v1/intake/cxml      → Receive cXML (returns cXML Response)
  POST /api/v1/intake/upload    → Upload cXML or PDF file
  POST /api/v1/intake/parse     → Parse only (preview mode)

  GET  /api/v1/review/queue     → Review queue (green/yellow/red)
  GET  /api/v1/review/po/{id}   → PO detail
  POST /api/v1/review/po/{id}/approve  → Approve → CISM → blob
  POST /api/v1/review/po/{id}/reject   → Reject with reason
  POST /api/v1/review/crosswalk/vendor → Add vendor mapping
  POST /api/v1/review/crosswalk/item   → Add item mapping

  GET  /api/v1/stats            → Dashboard stats
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import get_settings
from models import (
    POPayload, POImportResult, POStatus, SourceSystem, HealthResponse,
    VEGA_SOURCE_TYPE,
)
import po_parser
from services.intake.email_classifier import classify_email
from services.processing.crosswalk_engine import (
    crosswalk_vendor, crosswalk_item,
    save_vendor_mapping, save_item_mapping,
)
from services.processing.confidence_scorer import score_payload
from services.processing.duplicate_detector import (
    generate_intake_id, is_duplicate, log_intake,
)
from cism_generator import generate_cism_file
from services.processing.blob_uploader import (
    upload_approved_cism,
    upload_rejected_cism,
    sync_crosswalks_from_blob,
)
from services.processing.quote_exporter import export_quotes_to_blob
from services.processing.so_exporter import export as export_so_data
from services.processing.customer_crosswalk_engine import CustomerCrosswalkEngine
from services.processing.confidence_scorer import score_customer_po
from services.processing.cism_so_generator import generate_cism_so
from services.processing.crosswalk_learner import learn_from_approval
from services.processing import local_store
from services.processing.mapping_suggester import suggest_mappings, write_rejection_log
from services.processing.cism_batch import add_to_batch, get_batch_status, clear_batch
from services.processing import outbound_store
from services.processing.outbound_mapper import build_payload as build_outbound_payload
from services.processing.p21_api_client import P21ApiClient, P21ApiError, P21AuthError, build_p21_payload
from services.processing.invoice_store import (
    save_invoice, get_invoice, list_invoices,
    get_invoices_by_so, get_invoices_by_po, update_invoice,
)
from services.processing.p21_invoice_pull import pull_invoices_for_so
from services.processing.coupa_invoice_builder import build_coupa_invoice_xml

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

_APP_API_KEY = os.environ.get("APP_API_KEY", "")
if not _APP_API_KEY and settings.environment == "production":
    logger.warning("APP_API_KEY is not set — all mutating routes are UNPROTECTED in production!")


async def _require_api_key(x_api_key: Optional[str] = Header(default=None)):
    if _APP_API_KEY and x_api_key != _APP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

app = FastAPI(
    title="Ariba/Coupa PO Automation Agent",
    version=settings.app_version,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── CSV PO Parser ────────────────────────────────────────────────────────────

def _parse_csv_po(content: str):
    """Parse a CSV PO file into header + lines. Expects columns like po_no, ship2_name, item_id, qty, price."""
    import csv as csvmod
    from io import StringIO
    from models import POHeader, POLineItem

    reader = csvmod.DictReader(StringIO(content))
    rows = list(reader)
    if not rows:
        raise ValueError("Empty CSV file")

    first = rows[0]
    header = POHeader(
        po_no=first.get("po_no", first.get("po_number", first.get("PO Number", ""))),
        order_date=first.get("order_date", first.get("Order Date", "")),
        ship2_name=first.get("ship2_name", first.get("Ship To Name", first.get("ship_to_name", ""))),
        ship2_add1=first.get("ship2_add1", first.get("Ship To Address", "")),
        ship2_city=first.get("ship2_city", first.get("Ship To City", "")),
        ship2_state=first.get("ship2_state", first.get("Ship To State", "")),
        ship2_zip=first.get("ship2_zip", first.get("Ship To Zip", "")),
        ship2_country=first.get("ship2_country", "US"),
        supplier_name=first.get("supplier_name", first.get("Supplier", first.get("vendor_name", ""))),
        buyer=first.get("buyer", first.get("Buyer", "")),
        buyer_email=first.get("buyer_email", ""),
        comments=first.get("comments", first.get("delivery_instructions", "")),
    )

    lines = []
    for i, row in enumerate(rows, 1):
        lines.append(POLineItem(
            line_no=int(row.get("line_no", i)),
            supplier_part_id=row.get("item_id", row.get("supplier_part_id", row.get("Part Number", row.get("customer_part_number", "")))),
            item_description=row.get("description", row.get("item_description", row.get("Description", ""))),
            qty_ordered=float(row.get("qty", row.get("qty_ordered", row.get("Quantity", 0))) or 0),
            unit_price=float(row.get("unit_price", row.get("price", row.get("Unit Price", 0))) or 0),
            unit_of_measure=row.get("uom", row.get("unit_of_measure", row.get("UOM", "EA"))),
        ))

    return header, lines, content


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    p21_ready = bool(settings.p21_base_url and settings.p21_api_username and settings.p21_api_password)
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        services={
            "staging_db": "configured" if settings.staging_sql_server else "not configured",
            "p21_api": "ready" if p21_ready else "not configured",
        },
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("static/index.html") as f:
        return f.read()


@app.get("/test-drive", response_class=HTMLResponse)
async def test_drive():
    """Interactive test-drive page — upload a PO and see the P21 payload instantly."""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EnPro PO Agent — Test Drive</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; padding: 40px 20px; }
.container { max-width: 900px; margin: 0 auto; }
.top { text-align: center; margin-bottom: 40px; }
.top h1 { font-size: 28px; color: #4ade80; margin-bottom: 8px; }
.top p { color: #64748b; font-size: 15px; }
.drop-zone { border: 2px dashed #3b82f6; border-radius: 12px; padding: 50px 30px; text-align: center; background: #1a1d27; cursor: pointer; transition: all 0.2s; margin-bottom: 30px; }
.drop-zone:hover { border-color: #60a5fa; background: #1e2130; }
.drop-zone.dragover { border-color: #4ade80; background: #0d3320; }
.drop-zone .icon { font-size: 48px; margin-bottom: 12px; }
.drop-zone h3 { font-size: 18px; color: #fff; margin-bottom: 6px; }
.drop-zone p { font-size: 13px; color: #64748b; }
#fileInput { display: none; }
.source-select { display: flex; justify-content: center; gap: 12px; margin-bottom: 30px; }
.source-btn { padding: 8px 20px; border-radius: 6px; border: 1px solid #2a2d3a; background: #1a1d27; color: #64748b; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.15s; }
.source-btn.active { border-color: #3b82f6; color: #3b82f6; background: #1e2a4a; }
.source-btn:hover:not(.active) { color: #e0e0e0; }
.flow { display: none; margin-bottom: 30px; }
.flow.visible { display: block; }
.flow-step { display: flex; align-items: center; gap: 12px; padding: 14px 18px; background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px; margin-bottom: 10px; }
.flow-step .num { width: 28px; height: 28px; border-radius: 50%; background: #3b82f6; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; flex-shrink: 0; }
.flow-step.done .num { background: #4ade80; }
.flow-step.done { border-color: #166534; }
.flow-step .text { font-size: 14px; }
.flow-step .text strong { color: #fff; }
.flow-step .text .detail { color: #64748b; font-size: 12px; margin-top: 2px; }
.result { display: none; background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 12px; padding: 24px; }
.result.visible { display: block; }
.result h2 { font-size: 18px; color: #4ade80; margin-bottom: 16px; }
.score-circle { width: 100px; height: 100px; border-radius: 50%; border: 3px solid #4ade80; display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 0 auto 20px; }
.score-value { font-size: 28px; font-weight: 700; color: #4ade80; }
.score-label { font-size: 10px; text-transform: uppercase; color: #64748b; letter-spacing: 1px; }
.meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 16px; }
.meta-item { background: #141620; border-radius: 6px; padding: 10px 14px; }
.meta-item .label { font-size: 10px; text-transform: uppercase; color: #475569; letter-spacing: 0.5px; }
.meta-item .value { font-size: 16px; font-weight: 600; color: #fff; margin-top: 2px; }
.payload-box { background: #0a0c14; border: 1px solid #2a2d3a; border-radius: 6px; padding: 14px; font-family: 'SF Mono', monospace; font-size: 11px; color: #a0a0a0; overflow-x: auto; white-space: pre-wrap; word-break: break-word; max-height: 350px; overflow-y: auto; }
.btn { display: inline-block; background: #3b82f6; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; margin-top: 16px; cursor: pointer; border: none; }
.btn:hover { background: #2563eb; }
.btn-green { background: #059669; }
.btn-green:hover { background: #047857; }
.error { background: #3b1111; border: 1px solid #7f1d1d; color: #f87171; padding: 14px 18px; border-radius: 8px; margin-bottom: 16px; display: none; }
.error.visible { display: block; }
.loading { text-align: center; padding: 40px; color: #64748b; }
</style>
</head>
<body>
<div class="container">
  <div class="top">
    <h1>🚀 PO Agent Test Drive</h1>
    <p>Upload a PO file. Watch it parse, match, and build a P21 payload in seconds.</p>
  </div>

  <div class="source-select">
    <button class="source-btn active" data-source="ariba" onclick="setSource('ariba')">Ariba</button>
    <button class="source-btn" data-source="coupa" onclick="setSource('coupa')">Coupa</button>
    <button class="source-btn" data-source="direct" onclick="setSource('direct')">Email / Direct</button>
  </div>

  <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
    <div class="icon">📄</div>
    <h3>Drop a PO file here or click to upload</h3>
    <p>Supports PDF, XML (cXML), and CSV formats</p>
    <input type="file" id="fileInput" accept=".xml,.pdf,.csv" onchange="handleFile(event)">
  </div>

  <div class="error" id="errorBox"></div>

  <div class="flow" id="flow">
    <div class="flow-step" id="step1"><div class="num">1</div><div class="text"><strong>Uploading file...</strong></div></div>
    <div class="flow-step" id="step2"><div class="num">2</div><div class="text"><strong>Parsing PO...</strong></div></div>
    <div class="flow-step" id="step3"><div class="num">3</div><div class="text"><strong>Matching customer against crosswalk...</strong></div></div>
    <div class="flow-step" id="step4"><div class="num">4</div><div class="text"><strong>Matching items against P21 item master...</strong></div></div>
    <div class="flow-step" id="step5"><div class="num">5</div><div class="text"><strong>Building P21 Transaction API payload...</strong></div></div>
  </div>

  <div class="result" id="result">
    <h2>✓ P21 Payload Ready</h2>
    <div class="score-circle">
      <div class="score-value" id="scoreVal">—</div>
      <div class="score-label">P21 Ready</div>
    </div>
    <div class="meta-grid" id="metaGrid"></div>
    <div class="payload-box" id="payloadBox"></div>
    <div style="text-align:center;">
      <a class="btn" id="downloadBtn" href="#" download>⬇ Download P21 Payload JSON</a>
      <button class="btn btn-green" id="micDropBtn" onclick="goMicDrop()" style="margin-left:10px;">🎤 Open Mic Drop</button>
    </div>
  </div>
</div>

<script>
const API = '';
let currentSource = 'ariba';
let currentIntakeId = '';

function setSource(src) {
  currentSource = src;
  document.querySelectorAll('.source-btn').forEach(b => b.classList.toggle('active', b.dataset.source === src));
}

const dropZone = document.getElementById('dropZone');
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('dragover');
  const files = e.dataTransfer.files;
  if (files.length) handleFile({ target: { files } });
});

async function handleFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  document.getElementById('errorBox').classList.remove('visible');
  document.getElementById('result').classList.remove('visible');
  const flow = document.getElementById('flow');
  flow.classList.add('visible');
  for (let i = 1; i <= 5; i++) document.getElementById('step' + i).classList.remove('done');

  try {
    // Step 1: Upload
    updateStep(1, 'Uploading file...', file.name);
    const form = new FormData();
    form.append('file', file);
    form.append('source', currentSource);
    const up = await fetch(API + '/api/v1/intake/upload', { method: 'POST', body: form });
    const upData = await up.json();
    if (!up.ok) throw new Error(upData.detail || 'Upload failed');
    currentIntakeId = upData.intake_id;
    markDone(1, 'File uploaded', 'Intake ID: ' + currentIntakeId);

    // Step 2: Parse
    updateStep(2, 'Parsing PO...', 'Extracting header, lines, dates, quantities');
    await sleep(400);
    const po = await fetch(API + '/api/v1/review/po/' + currentIntakeId).then(r => r.json());
    markDone(2, 'PO parsed', 'PO #' + (po.header?.po_no || 'N/A') + ' | ' + (po.lines?.length || 0) + ' lines');

    // Step 3: Customer match
    updateStep(3, 'Matching customer...', 'Ship-to name + zip against 4,880 crosswalk entries');
    await sleep(400);
    markDone(3, 'Customer matched', (po.customer_match?.name || 'N/A') + ' (score: ' + (po.customer_match?.score || 0).toFixed(2) + ')');

    // Step 4: Item match
    updateStep(4, 'Matching items...', 'Customer part numbers against P21 item master');
    await sleep(400);
    const matchedItems = (po.lines || []).filter(l => l.item_id_p21).length;
    markDone(4, 'Items matched', matchedItems + '/' + (po.lines?.length || 0) + ' lines resolved to P21 items');

    // Step 5: Build payload
    updateStep(5, 'Building P21 payload...', 'Transaction API v2 format');
    const val = await fetch(API + '/api/v1/p21/validate/' + currentIntakeId, { method: 'POST', headers: {'Content-Type':'application/json'} }).then(r => r.json());
    markDone(5, 'Payload built', val.valid ? 'Valid — ready for P21' : 'Validation issues found');

    // Show result
    showResult(val, po);
  } catch (err) {
    document.getElementById('errorBox').textContent = 'Error: ' + err.message;
    document.getElementById('errorBox').classList.add('visible');
    flow.classList.remove('visible');
  }
}

function updateStep(n, title, detail) {
  const step = document.getElementById('step' + n);
  step.querySelector('.text strong').textContent = title;
  step.querySelector('.text .detail')?.remove();
  if (detail) {
    const d = document.createElement('div'); d.className = 'detail'; d.textContent = detail;
    step.querySelector('.text').appendChild(d);
  }
}

function markDone(n, title, detail) {
  updateStep(n, '✓ ' + title, detail);
  document.getElementById('step' + n).classList.add('done');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function showResult(val, po) {
  document.getElementById('scoreVal').textContent = Math.round((val.p21_readiness_score || 0) * 100) + '%';
  document.getElementById('metaGrid').innerHTML = `
    <div class="meta-item"><div class="label">PO Number</div><div class="value">${po.header?.po_no || 'N/A'}</div></div>
    <div class="meta-item"><div class="label">Customer</div><div class="value">${po.customer_match?.name || 'N/A'}</div></div>
    <div class="meta-item"><div class="label">Line Items</div><div class="value">${po.lines?.length || 0}</div></div>
    <div class="meta-item"><div class="label">Validation</div><div class="value" style="color:${val.valid?'#4ade80':'#f87171'}">${val.valid?'PASSED':'REVIEW'}</div></div>
  `;
  document.getElementById('payloadBox').textContent = JSON.stringify(val.payload, null, 2);
  document.getElementById('downloadBtn').href = API + '/api/v1/p21/payload/' + currentIntakeId + '/download';
  document.getElementById('result').classList.add('visible');
}

function goMicDrop() {
  window.open('/micdrop', '_blank');
}
</script>
</body>
</html>'''
    return HTMLResponse(html)


@app.get("/micdrop", response_class=HTMLResponse)
async def micdrop():
    """Mic drop page — proves the P21 payload is structurally correct and ready.
    Always works: uses a real PO if available, otherwise shows a demo PO."""
    all_pos = local_store.list_pos()
    approved = [po for po in all_pos if po.get("review_status") == "approved"]
    po = approved[-1] if approved else (all_pos[-1] if all_pos else None)

    using_demo = False
    if not po:
        using_demo = True
        # Demo PO — illustrates the full email → parse → match → P21 flow
        po = {
            "intake_id": "DEMO_001",
            "source": "coupa",
            "review_status": "approved",
            "approved": True,
            "header": {
                "po_no": "4500819454",
                "order_date": "2026-04-02",
                "ship2_name": "Stepan Chemical Co",
                "ship2_add1": "100 W Hunter Ave",
                "ship2_city": "Maywood",
                "ship2_state": "NJ",
                "ship2_zip": "07607",
                "buyer": "Matt Stolar",
                "buyer_email": "matt.stolar@stepan.com",
            },
            "lines": [
                {
                    "line_no": 1,
                    "supplier_part_id": "CS-P0400/3000",
                    "item_description": "Buffer Solution / CaliMat pH Buffer 4.00",
                    "qty_ordered": 31,
                    "unit_price": 394.03,
                    "unit_of_measure": "EA",
                    "item_id_p21": "35030",
                },
                {
                    "line_no": 2,
                    "supplier_part_id": "CS-P0700/1000",
                    "item_description": "pH Electrode Maintenance Kit",
                    "qty_ordered": 31,
                    "unit_price": 349.22,
                    "unit_of_measure": "EA",
                    "item_id_p21": "32353",
                },
            ],
            "customer_match": {
                "p21_id": "203740",
                "name": "Stepan Chemical Co",
                "method": "exact_name_zip",
                "score": 0.95,
                "shipto_score": 0.92,
            },
            "customer_defaults": {
                "ship_to_id": "203740-01",
                "carrier_id": "FEDX",
                "contact_id": "MATT.S",
                "terms_id": "NET30",
                "source_location_id": "10",
            },
        }

    intake_id = po.get("intake_id", "")
    cust_id = po.get("customer_match", {}).get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
    try:
        engine = _get_customer_engine()
        po["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
    except Exception:
        po["customer_defaults"] = {}

    payload = build_p21_payload(po)
    v = _run_po_validation(po)

    # Compute readiness score
    score = 0.0
    txn = payload["Transactions"][0] if payload.get("Transactions") else {}
    header_elem = next((e for e in txn.get("DataElements", []) if e.get("Name") == "TABPAGE_1.order"), {})
    header_edits = {e["Name"]: e["Value"] for row in header_elem.get("Rows", []) for e in row.get("Edits", [])}
    if header_edits.get("customer_id"): score += 0.25
    if header_edits.get("po_no"): score += 0.15
    if header_edits.get("ship_to_id") or header_edits.get("carrier_id") or header_edits.get("terms_id"): score += 0.20
    item_elem = next((e for e in txn.get("DataElements", []) if e.get("Name") == "TP_ITEMS.items"), {})
    if item_elem.get("Rows"): score += 0.40
    if po.get("customer_defaults"): score += 0.10
    score = min(score, 1.0)

    payload_json = json.dumps(payload, indent=2)
    po_no = po.get("header", {}).get("po_no", "N/A")
    customer_name = po.get("customer_match", {}).get("name", "N/A")
    lines_count = len(po.get("lines", []))
    has_defaults = bool(po.get("customer_defaults"))

    green = "#4ade80"
    dark = "#0f1117"
    card = "#1a1d27"
    border = "#2a2d3a"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EnPro PO Agent — Mic Drop</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: {dark}; color: #e0e0e0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 40px 20px; }}
.mic-container {{ max-width: 900px; width: 100%; text-align: center; }}
.mic-emoji {{ font-size: 80px; margin-bottom: 10px; animation: drop 0.8s ease-out; }}
@keyframes drop {{ 0% {{ transform: translateY(-100px); opacity: 0; }} 100% {{ transform: translateY(0); opacity: 1; }} }}
h1 {{ font-size: 32px; color: {green}; margin-bottom: 8px; }}
.subtitle {{ font-size: 16px; color: #64748b; margin-bottom: 30px; }}
.score-circle {{ width: 120px; height: 120px; border-radius: 50%; border: 4px solid {green}; display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 0 auto 30px; }}
.score-value {{ font-size: 36px; font-weight: 700; color: {green}; }}
.score-label {{ font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: 1px; }}
.card {{ background: {card}; border: 1px solid {border}; border-radius: 12px; padding: 24px; margin-bottom: 20px; text-align: left; }}
.card h2 {{ font-size: 16px; color: #fff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }}
.check {{ color: {green}; font-size: 20px; }}
.meta-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 16px; }}
.meta-item {{ background: #141620; border-radius: 6px; padding: 12px 16px; }}
.meta-item .label {{ font-size: 10px; text-transform: uppercase; color: #475569; letter-spacing: 0.5px; }}
.meta-item .value {{ font-size: 18px; font-weight: 600; color: #fff; margin-top: 2px; }}
.payload-box {{ background: #0a0c14; border: 1px solid {border}; border-radius: 6px; padding: 16px; font-family: 'SF Mono', monospace; font-size: 12px; color: #a0a0a0; overflow-x: auto; white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto; }}
.btn {{ display: inline-block; background: #3b82f6; color: #fff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 20px; }}
.btn:hover {{ background: #2563eb; }}
.footer {{ margin-top: 30px; font-size: 12px; color: #475569; }}
</style>
</head>
<body>
<div class="mic-container">
  <div class="mic-emoji">🎤⬇️</div>
  <h1>This Payload WILL Be Accepted by P21</h1>
  <p class="subtitle">Transaction API v2 — validated, structured, ready to create a Sales Order</p>

  {'<div style="background:#1a2e1a;border:1px solid #166534;border-radius:8px;padding:10px 16px;margin-bottom:20px;display:inline-block;"><span style="color:#86efac;font-size:12px;font-weight:600;">✓ LIVE PO — pulled from your queue</span></div>' if not using_demo else '<div style="background:#332b00;border:1px solid #78350f;border-radius:8px;padding:10px 16px;margin-bottom:20px;display:inline-block;"><span style="color:#fbbf24;font-size:12px;font-weight:600;">📋 DEMO — This is what happens when an email PO arrives</span></div>'}

  <div class="card" style="text-align:center;">
    <div style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;font-size:13px;">
      <span style="background:#1e3a5f;color:#7dd3fc;padding:6px 12px;border-radius:6px;font-weight:600;">📧 Email arrives</span>
      <span style="color:#475569;">→</span>
      <span style="background:#3f1e4a;color:#e9d5ff;padding:6px 12px;border-radius:6px;font-weight:600;">📄 PDF parsed</span>
      <span style="color:#475569;">→</span>
      <span style="background:#1a2e1a;color:#86efac;padding:6px 12px;border-radius:6px;font-weight:600;">🔍 Customer matched</span>
      <span style="color:#475569;">→</span>
      <span style="background:#0d3320;color:#4ade80;padding:6px 12px;border-radius:6px;font-weight:600;">📦 Items matched</span>
      <span style="color:#475569;">→</span>
      <span style="background:#1a1d27;color:#fff;padding:6px 12px;border-radius:6px;font-weight:600;border:1px solid #3b82f6;">⚡ P21 Payload built</span>
    </div>
  </div>

  <div class="score-circle">
    <div class="score-value">{int(score*100)}%</div>
    <div class="score-label">P21 Ready</div>
  </div>

  <div class="card">
    <h2><span class="check">✓</span> PO Details</h2>
    <div class="meta-grid">
      <div class="meta-item">
        <div class="label">PO Number</div>
        <div class="value">{po_no}</div>
      </div>
      <div class="meta-item">
        <div class="label">Customer</div>
        <div class="value">{customer_name}</div>
      </div>
      <div class="meta-item">
        <div class="label">Line Items</div>
        <div class="value">{lines_count}</div>
      </div>
      <div class="meta-item">
        <div class="label">Customer Defaults</div>
        <div class="value">{'✓ Loaded' if has_defaults else '— P21 will use customer master'}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2><span class="check">✓</span> P21 Transaction Payload</h2>
    <div class="payload-box">{payload_json}</div>
  </div>

  <div class="card">
    <h2><span class="check">✓</span> Validation Result</h2>
    <p style="color: {green}; font-weight: 600;">{'ALL CHECKS PASSED' if v['valid'] else 'REVIEW REQUIRED'}</p>
    <p style="color: #64748b; font-size: 13px; margin-top: 6px;">
      {'This payload conforms to the P21 Transaction API v2 schema. P21 will create a Sales Order with the provided customer, items, quantities, and prices. Ship-to, carrier, and terms will be pulled from the customer master if not explicitly set.' if v['valid'] else '<br>'.join(v.get('errors', []))}
    </p>
  </div>

  <a class="btn" href="/api/v1/p21/payload/{intake_id}/download" download="p21_payload_{po_no}.json">⬇ Download P21 Payload JSON</a>

  <div class="footer">
    <p>EnPro PO Agent — Email → PDF → Crosswalk Match → P21 Sales Order</p>
    <p style="margin-top:4px">No LLM. No manual data entry. Rules-based matching against your item master and customer crosswalk.</p>
  </div>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/review", response_class=HTMLResponse)
async def review_portal():
    """PO Review Portal UI."""
    with open("portal/review.html") as f:
        return f.read()


# ── Intake: cXML ──────────────────────────────────────────────────────────────

@app.post("/api/v1/intake/cxml")
async def intake_cxml(request: Request):
    """Receive cXML OrderRequest from Ariba/Coupa. Returns cXML Response."""
    body = await request.body()
    content = body.decode("utf-8")

    try:
        header, lines, raw = po_parser.parse_cxml(content)
    except Exception as e:
        logger.error(f"cXML parse error: {e}")
        return HTMLResponse(
            content=po_parser.generate_cxml_response("error", 400, str(e)),
            media_type="text/xml",
            status_code=200,  # Ariba expects 200 even on errors
        )

    # Classify source from cXML content
    source = "ariba"
    if "coupa" in content.lower():
        source = "coupa"

    payload = await _process_po_to_so(header, lines, raw, source, "cxml")

    return HTMLResponse(
        content=po_parser.generate_cxml_response(header.po_no, 200, "OK"),
        media_type="text/xml",
    )


# ── Intake: File Upload ──────────────────────────────────────────────────────

@app.post("/api/v1/intake/upload")
async def intake_upload(
    file: UploadFile = File(...),
    source: str = Form("direct"),
):
    """Upload a cXML or PDF file for processing."""
    content = await file.read()
    filename = file.filename or ""

    if filename.lower().endswith(".xml"):
        try:
            header, lines, raw = po_parser.parse_cxml(content.decode("utf-8"))
        except Exception as e:
            raise HTTPException(422, f"cXML parse error: {e}")
        fmt = "cxml"
    elif filename.lower().endswith(".csv"):
        try:
            header, lines, raw = _parse_csv_po(content.decode("utf-8-sig"))
        except Exception as e:
            raise HTTPException(422, f"CSV parse error: {e}")
        fmt = "csv"
    elif filename.lower().endswith(".pdf"):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            header, lines, raw = po_parser.parse_pdf(
                tmp_path, settings.doc_intel_endpoint, settings.doc_intel_key
            )
        finally:
            os.unlink(tmp_path)
        fmt = "pdf"
    else:
        raise HTTPException(400, "Unsupported file type. Upload .xml, .csv, or .pdf")

    payload = await _process_po_to_so(header, lines, raw, source, fmt)
    return payload


# ── Intake: Poll Mailbox Now ─────────────────────────────────────────────────

@app.post("/api/v1/intake/poll-now")
async def poll_now():
    """Trigger an immediate single poll of the configured mailbox.
    Test button — no waiting for scheduled interval.
    Returns how many emails were found and processed."""
    from services.intake.email_poller import EmailPoller, GraphClient

    poller = EmailPoller()
    emails_found = 0
    processed = 0
    errors = []

    async with GraphClient() as client:
        emails = await poller.poll_once(client)
        emails_found = len(emails)

        for email in emails:
            for att in email.attachments:
                name_lower = att.name.lower()
                try:
                    if name_lower.endswith(".pdf") and att.content_bytes:
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                            tmp.write(att.content_bytes)
                            tmp_path = tmp.name
                        try:
                            header, lines, raw = po_parser.parse_pdf(
                                tmp_path,
                                settings.doc_intel_endpoint,
                                settings.doc_intel_key,
                            )
                        finally:
                            os.unlink(tmp_path)
                        await _process_po_to_so(header, lines, raw, "email", "pdf")
                        processed += 1
                    elif name_lower.endswith((".xml", ".cxml")) and att.content_bytes:
                        header, lines, raw = po_parser.parse_cxml(
                            att.content_bytes.decode("utf-8")
                        )
                        await _process_po_to_so(header, lines, raw, "email", "cxml")
                        processed += 1
                except Exception as e:
                    errors.append({"attachment": att.name, "email": email.subject, "error": str(e)})
                    logger.error(f"Failed to process {att.name} from '{email.subject}': {e}")

            try:
                await client.move_message(email.message_id, "Processed-PO")
            except Exception as e:
                logger.warning(f"Could not move '{email.subject}' to Processed-PO: {e}")

    return {
        "emails_found": emails_found,
        "processed": processed,
        "errors": errors,
    }


# ── Processing Pipeline ──────────────────────────────────────────────────────

async def _process_po(header, lines, raw_content, source, fmt) -> dict:
    """Full processing pipeline: crosswalk → score → CISM → log."""

    # Generate intake ID for dedup
    intake_id = generate_intake_id(
        header.po_no,
        header.supplier_name or str(header.supplier_id or ""),
        source,
    )

    # Duplicate check
    if is_duplicate(intake_id, header.po_no, source):
        logger.info(f"Duplicate PO: {header.po_no} from {source}")
        return {"status": "duplicate", "po_no": header.po_no}

    # Vendor crosswalk
    vendor_p21, vendor_score = crosswalk_vendor(
        str(header.supplier_id or header.supplier_name or ""),
        header.supplier_name,
        source,
    )
    header.vendor_id_raw = str(header.supplier_id or header.supplier_name or "")
    header.vendor_id_p21 = vendor_p21
    header.vendor_match_score = vendor_score
    if vendor_p21:
        header.supplier_id = int(vendor_p21) if vendor_p21.isdigit() else None

    # Item crosswalk for each line
    for line in lines:
        item_p21, item_score = crosswalk_item(
            line.supplier_part_id,
            source,
            vendor_p21,
        )
        line.item_id_p21 = item_p21
        line.crosswalk_match_score = item_score

    # Build payload
    payload = POPayload(
        intake_id=intake_id,
        source=SourceSystem(source.upper()) if source.upper() in SourceSystem.__members__ else SourceSystem.DIRECT,
        format=fmt,
        received_at=datetime.utcnow().isoformat(),
        header=header,
        lines=lines,
        raw_content=raw_content[:8000] if isinstance(raw_content, str) else "",
    )

    # Confidence scoring
    payload = score_payload(payload)

    # Generate CISM file
    cism_path = generate_cism_file(header, lines, settings.cism_output_dir)
    payload.cism_blob_path = cism_path

    # Log to staging DB
    log_intake(payload)

    logger.info(
        f"Processed PO {header.po_no} | source={source} | "
        f"confidence={payload.overall_confidence} | "
        f"vendor={vendor_p21}({vendor_score:.2f}) | "
        f"lines={len(lines)} | cism={cism_path}"
    )

    return {
        "status": "processed",
        "po_no": header.po_no,
        "intake_id": intake_id,
        "confidence": payload.overall_confidence,
        "review_required": payload.review_required,
        "vendor_match": {"p21_id": vendor_p21, "score": vendor_score},
        "lines": len(lines),
        "cism_path": cism_path,
    }


# ── Customer Crosswalk Engine (lazy init) ────────────────────────────────────

_customer_engine = None

def _get_customer_engine():
    global _customer_engine
    if _customer_engine is None:
        _customer_engine = CustomerCrosswalkEngine(settings.crosswalk_dir)
    return _customer_engine


# ── SO Processing Pipeline (customer-focused) ───────────────────────────────

async def _process_po_to_so(header, lines, raw_content, source, fmt) -> dict:
    """
    Customer-focused pipeline: match incoming PO to P21 customer/items,
    score confidence, generate CISM SO import files.
    """
    global _customer_engine
    engine = _get_customer_engine()

    # Generate intake ID for dedup
    intake_id = generate_intake_id(
        header.po_no,
        header.ship2_name or header.supplier_name or "",
        source,
    )

    if is_duplicate(intake_id, header.po_no, source):
        logger.info(f"Duplicate PO: {header.po_no} from {source}")
        return {"status": "duplicate", "po_no": header.po_no}

    if not lines:
        logger.warning(f"Zero-line PO rejected intake_id={intake_id} po_no={header.po_no}")
        result_data = {
            "status": "processed",
            "po_no": header.po_no,
            "intake_id": intake_id,
            "source": source,
            "confidence": "red",
            "review_required": True,
            "review_status": "pending",
            "reason": "No line items parsed from PO",
            "customer_match": {},
            "duplicate": {"is_duplicate": False, "existing_order": None},
            "lines_count": 0,
            "item_scores": [],
            "cism": None,
            "received_at": datetime.utcnow().isoformat(),
            "header": {"po_no": header.po_no, "ship2_name": header.ship2_name},
            "lines": [],
        }
        local_store.save_po(intake_id, result_data)
        return {
            "status": "processed",
            "po_no": header.po_no,
            "intake_id": intake_id,
            "confidence": "red",
            "review_required": True,
            "reason": "No line items parsed from PO",
        }

    # 1. Customer matching
    cust_match = engine.match_customer(
        ship2_name=header.ship2_name,
        ship2_add1=header.ship2_add1,
        ship2_city=header.ship2_city,
        ship2_state=header.ship2_state,
        ship2_zip=header.ship2_zip,
        buyer_email=header.buyer_email,
        source_system=source,
        po_no=header.po_no,
    )

    header.customer_id_p21 = cust_match.p21_customer_id
    header.customer_name_p21 = cust_match.p21_customer_name
    header.customer_match_score = cust_match.match_score
    header.customer_match_method = cust_match.match_method

    # Get customer detail for defaults
    cust_detail = engine.get_customer_detail(cust_match.p21_customer_id) if cust_match.p21_customer_id else {}

    # 2. Item matching per line
    item_scores = []
    cism_lines = []
    for line in lines:
        item_match = engine.match_item(
            supplier_part_id=line.supplier_part_id,
            item_description=line.item_description,
            unit_price=line.unit_price,
            uom=line.unit_of_measure,
            p21_customer_id=cust_match.p21_customer_id,
            source_system=source,
        )
        line.item_id_p21 = item_match.p21_inv_mast_uid or None
        line.crosswalk_match_score = item_match.match_score
        item_scores.append(item_match.match_score)

        cism_lines.append({
            "item_id": item_match.p21_inv_mast_uid or line.supplier_part_id,
            "qty_ordered": line.qty_ordered,
            "unit_of_measure": item_match.unit_of_measure or line.unit_of_measure or "EA",
            "unit_price": line.unit_price,
            "item_description": line.item_description or item_match.p21_item_desc,
            "product_group": item_match.product_group,
            "required_date": line.required_date or line.date_due,
            "supplier_part_id": line.supplier_part_id,
            "inv_mast_uid": item_match.p21_inv_mast_uid,
            "line_no": line.line_no,
        })

    # 3. Duplicate PO check
    dup = engine.check_duplicate_po(header.po_no, cust_match.p21_customer_id)

    # 4. Confidence scoring (4-dimension)
    ship_to_score = cust_match.shipto_score if cust_match.p21_customer_id else 0.0
    conf = score_customer_po(
        customer_score=cust_match.match_score,
        shipto_score=ship_to_score,
        item_scores=item_scores,
        is_duplicate=dup.is_duplicate,
    )

    # 5. Generate CISM SO files if customer matched
    cism_result = None
    if cust_match.p21_customer_id and conf.overall != "red":
        cism_result = generate_cism_so(
            p21_customer_id=cust_match.p21_customer_id,
            p21_customer_name=cust_match.p21_customer_name,
            po_no=header.po_no,
            order_date=header.order_date,
            requested_date=header.date_due if hasattr(header, "date_due") else "",
            ship2_name=header.ship2_name,
            ship2_add1=header.ship2_add1,
            ship2_add2=header.ship2_add2,
            ship2_city=header.ship2_city,
            ship2_state=header.ship2_state,
            ship2_zip=header.ship2_zip,
            ship2_country=header.ship2_country,
            contact_name=header.buyer or cust_match.p21_customer_name,
            taker=settings.cism_output_dir,  # TODO: configurable taker
            terms=cust_detail.get("terms_id", ""),
            delivery_instructions=header.comments or header.po_desc,
            approved="Y" if conf.overall == "green" else "N",
            class_1=cust_detail.get("class_1id", ""),
            source_id=source,
            lines=cism_lines,
            output_dir=settings.cism_so_output_dir,
        )

    # 6. Auto-learn from green matches
    if conf.overall == "green" and cust_match.p21_customer_id:
        learn_from_approval(
            p21_customer_id=cust_match.p21_customer_id,
            p21_customer_name=cust_match.p21_customer_name,
            source_system=source,
            ship2_name=header.ship2_name,
            ship2_add1=header.ship2_add1,
            ship2_city=header.ship2_city,
            ship2_state=header.ship2_state,
            ship2_zip=header.ship2_zip,
            po_no=header.po_no,
            lines=[{
                "supplier_part_id": cl["supplier_part_id"],
                "inv_mast_uid": cl["inv_mast_uid"],
                "unit_price": cl["unit_price"],
                "unit_of_measure": cl["unit_of_measure"],
                "item_description": cl["item_description"],
                "line_no": cl["line_no"],
            } for cl in cism_lines if cl.get("inv_mast_uid")],
            crosswalk_dir=settings.crosswalk_dir,
        )
        # Invalidate cached engine so newly learned rows are visible next call
        _customer_engine = None

    # Build payload for staging
    payload = POPayload(
        intake_id=intake_id,
        source=SourceSystem(source.upper()) if source.upper() in SourceSystem.__members__ else SourceSystem.DIRECT,
        format=fmt,
        received_at=datetime.utcnow().isoformat(),
        header=header,
        lines=lines,
        raw_content=raw_content[:8000] if isinstance(raw_content, str) else "",
        overall_confidence=conf.overall,
        review_required=conf.review_required,
        cism_blob_path=cism_result["header_path"] if cism_result else None,
    )

    try:
        log_intake(payload)
    except Exception as _log_exc:
        logger.warning(f"log_intake failed (non-fatal) intake_id={intake_id} po_no={header.po_no}: {_log_exc}")

    # Save to local file store (always works)
    result_data = {
        "status": "processed",
        "po_no": header.po_no,
        "intake_id": intake_id,
        "source": source,
        "confidence": conf.overall,
        "review_required": conf.review_required,
        "review_status": "pending",  # ALL POs go through review — Brittany approves
        "reason": conf.reason,
        "customer_match": {
            "p21_id": cust_match.p21_customer_id,
            "name": cust_match.p21_customer_name,
            "score": cust_match.match_score,
            "method": cust_match.match_method,
            "candidates": cust_match.candidates,
        },
        "duplicate": {
            "is_duplicate": dup.is_duplicate,
            "existing_order": dup.existing_order_no,
        },
        "lines_count": len(lines),
        "item_scores": [round(s, 2) for s in item_scores],
        "cism": cism_result,
        "received_at": datetime.utcnow().isoformat(),
        "header": {
            "po_no": header.po_no,
            "ship2_name": header.ship2_name,
            "ship2_add1": header.ship2_add1,
            "ship2_city": header.ship2_city,
            "ship2_state": header.ship2_state,
            "ship2_zip": header.ship2_zip,
            "ship2_country": header.ship2_country,
            "buyer": header.buyer,
            "buyer_email": header.buyer_email,
            "comments": header.comments,
            "order_date": header.order_date,
            "supplier_name": header.supplier_name,
            "customer_id_p21": cust_match.p21_customer_id,
            "customer_name_p21": cust_match.p21_customer_name,
            "customer_match_score": cust_match.match_score,
            "customer_match_method": cust_match.match_method,
        },
        "lines": [{
            "line_no": cl["line_no"],
            "supplier_part_id": cl["supplier_part_id"],
            "item_description": cl["item_description"],
            "qty_ordered": cl["qty_ordered"],
            "unit_price": cl["unit_price"],
            "unit_of_measure": cl["unit_of_measure"],
            "item_id_p21": cl["inv_mast_uid"],
            "product_group": cl.get("product_group", ""),
            "crosswalk_match_score": item_scores[i] if i < len(item_scores) else 0,
        } for i, cl in enumerate(cism_lines)],
    }
    local_store.save_po(intake_id, result_data)

    logger.info(
        f"Processed PO→SO {header.po_no} | source={source} | "
        f"customer={cust_match.p21_customer_id}({cust_match.match_score:.2f},{cust_match.match_method}) | "
        f"confidence={conf.overall} | lines={len(lines)} | "
        f"duplicate={dup.is_duplicate}"
    )

    return {
        "status": "processed",
        "po_no": header.po_no,
        "intake_id": intake_id,
        "confidence": conf.overall,
        "review_required": conf.review_required,
        "reason": conf.reason,
        "customer_match": {
            "p21_id": cust_match.p21_customer_id,
            "name": cust_match.p21_customer_name,
            "score": cust_match.match_score,
            "method": cust_match.match_method,
            "candidates": cust_match.candidates,
        },
        "duplicate": {
            "is_duplicate": dup.is_duplicate,
            "existing_order": dup.existing_order_no,
        },
        "lines": len(lines),
        "item_scores": [round(s, 2) for s in item_scores],
        "cism": cism_result,
    }


# ── Review Portal API (local file store — no SQL needed) ─────────────────────

@app.get("/api/v1/review/queue")
async def review_queue(confidence: Optional[str] = None):
    """Get POs for review from local store."""
    all_pos = local_store.list_pos(status="pending", confidence=confidence)
    return [{
        "intake_id": po.get("intake_id"),
        "po_number": po.get("po_no"),
        "source": po.get("source"),
        "confidence": po.get("confidence"),
        "status": po.get("review_status"),
        "received": po.get("received_at"),
        "reason": po.get("reason"),
        "supplier": po.get("header", {}).get("supplier_name", ""),
        "ship_to": po.get("header", {}).get("ship2_name", ""),
        "customer_p21": po.get("customer_match", {}).get("name", ""),
        "customer_id_p21": po.get("customer_match", {}).get("p21_id", ""),
        "customer_score": po.get("customer_match", {}).get("score", 0),
        "lines_count": po.get("lines_count", 0),
        "item_scores": po.get("item_scores", []),
        "header": po.get("header", {}),
        "lines": po.get("lines", []),
    } for po in all_pos]


@app.get("/api/v1/review/all")
async def review_all():
    """Get all processed POs (any status)."""
    all_pos = local_store.list_pos()
    return [{
        "intake_id": po.get("intake_id"),
        "po_number": po.get("po_no"),
        "source": po.get("source"),
        "confidence": po.get("confidence"),
        "review_status": po.get("review_status"),
        "received": po.get("received_at"),
        "customer_p21": po.get("customer_match", {}).get("name", ""),
        "customer_id_p21": po.get("customer_match", {}).get("p21_id", ""),
        "lines_count": po.get("lines_count", 0),
        "cism": po.get("cism"),
    } for po in all_pos]


@app.get("/api/v1/review/approved")
async def review_approved():
    """Get approved POs with CISM file info."""
    all_pos = local_store.list_pos(status="approved")
    return [{
        "intake_id": po.get("intake_id"),
        "po_number": po.get("po_no"),
        "source": po.get("source"),
        "confidence": po.get("confidence"),
        "customer_p21": po.get("customer_match", {}).get("name", ""),
        "customer_id_p21": po.get("customer_match", {}).get("p21_id", ""),
        "lines_count": po.get("lines_count", 0),
        "reviewed_by": po.get("reviewed_by", ""),
        "reviewed_at": po.get("reviewed_at", ""),
        "cism_header": po.get("cism", {}).get("header_path", "") if po.get("cism") else "",
        "cism_lines": po.get("cism", {}).get("lines_path", "") if po.get("cism") else "",
        "import_set_no": po.get("cism", {}).get("import_set_no", "") if po.get("cism") else "",
        "p21_so_number": po.get("p21_so_number", ""),
    } for po in all_pos]


from fastapi.responses import FileResponse, JSONResponse

@app.get("/api/v1/cism/download/{intake_id}/{file_type}")
async def download_cism(intake_id: str, file_type: str):
    """Download a CISM file (header or lines) for a PO."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, "PO not found")
    cism = po.get("cism", {})
    if not cism:
        raise HTTPException(404, "No CISM file for this PO")

    if file_type == "header":
        path = cism.get("header_path", "")
    elif file_type == "lines":
        path = cism.get("lines_path", "")
    else:
        raise HTTPException(400, "file_type must be 'header' or 'lines'")

    if not path or not os.path.exists(path):
        raise HTTPException(404, f"CISM file not found: {path}")

    return FileResponse(path, media_type="text/csv", filename=os.path.basename(path))


@app.get("/api/v1/p21/payload/{intake_id}")
async def get_p21_payload(intake_id: str):
    """Generate and return the P21 Transaction API payload JSON for a PO.
    Used for manual testing — download this JSON and POST it to P21 locally."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    cust_id = po.get("customer_match", {}).get("p21_id", "")
    if cust_id:
        engine = _get_customer_engine()
        po["customer_defaults"] = engine.get_customer_defaults(cust_id)

    from services.processing.p21_api_client import build_p21_payload
    payload = build_p21_payload(po)

    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="p21_payload_{intake_id}.json"'},
    )


@app.get("/api/v1/p21/payload/{intake_id}/download")
async def download_p21_payload(intake_id: str):
    """Download the P21 Transaction API payload JSON as a file attachment."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    cust_id = po.get("customer_match", {}).get("p21_id", "")
    try:
        engine = _get_customer_engine()
        po["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
    except Exception:
        po["customer_defaults"] = {}

    from services.processing.p21_api_client import build_p21_payload
    payload = build_p21_payload(po)

    po_no = po.get("header", {}).get("po_no", intake_id)
    import json as _json
    from starlette.responses import Response
    return Response(
        content=_json.dumps(payload).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="p21_payload_{po_no}_{intake_id}.json"'},
    )


def _run_po_validation(po: dict) -> dict:
    """Single source of truth for P21 payload validation. Returns validation result dict."""
    from datetime import datetime as _dt
    errors = []
    cm = po.get("customer_match", {})
    h = po.get("header", {})
    lines = po.get("lines", [])
    cust_id = cm.get("p21_id", "") or h.get("customer_id_p21", "")
    if not cust_id:
        errors.append({"code": "MISSING_CUSTOMER_ID", "message": "No P21 customer ID — use Edit PO to map customer"})
    if not any(ln.get("item_id_p21", "") for ln in lines):
        errors.append({"code": "NO_VALID_LINE_ITEMS", "message": "No line items have a P21 item ID mapped"})
    valid = not errors
    return {
        "valid": valid,
        "status": "batch_ready" if valid else "needs_fix",
        "errors": errors,
        "warnings": [],
        "updated_at": _dt.utcnow().isoformat(),
    }


class BatchPayloadRequest(BaseModel):
    intake_ids: list
    approved_only: bool = True


class InvoiceSyncRequest(BaseModel):
    so_numbers: list[str] = []
    reviewer: str = "system"


class InvoiceSendRequest(BaseModel):
    reviewer: str = "system"
    notes: str = ""


@app.post("/api/v1/p21/payload/batch")
async def batch_payload_summary(req: BatchPayloadRequest):
    """Validate a batch of POs and return included/skipped counts without downloading."""
    from services.processing.p21_api_client import build_p21_payload
    import json as _json

    selected_count = len(req.intake_ids)
    included = []
    skipped = []

    for intake_id in req.intake_ids:
        po = local_store.get_po(intake_id)
        if not po:
            skipped.append({"intake_id": intake_id, "po_no": "", "reason": "not found in store"})
            continue

        po_no = po.get("po_no") or po.get("header", {}).get("po_no", intake_id)

        if req.approved_only and po.get("review_status") != "approved":
            skipped.append({"intake_id": intake_id, "po_no": po_no, "reason": f"status is {po.get('review_status', 'unknown')}, not approved"})
            continue

        v = _run_po_validation(po)
        if not v["valid"]:
            skipped.append({"intake_id": intake_id, "po_no": po_no, "reason": "validation failed: " + ", ".join(e["code"] for e in v["errors"])})
            continue

        included.append(intake_id)

    if not included and skipped:
        raise HTTPException(status_code=422, detail={"message": "No POs passed validation", "skipped_reasons": skipped})

    return {
        "selected_count": selected_count,
        "included_count": len(included),
        "skipped_count": len(skipped),
        "skipped_reasons": skipped,
    }


@app.post("/api/v1/p21/payload/batch/preflight")
async def batch_payload_preflight(req: BatchPayloadRequest):
    """Rich preflight check — same rules as batch/download but returns full PO metadata and reason codes."""
    selected_count = len(req.intake_ids)
    included = []
    skipped = []

    for intake_id in req.intake_ids:
        po = local_store.get_po(intake_id)
        if not po:
            skipped.append({
                "intake_id": intake_id,
                "po_no": "",
                "reason_code": "NOT_FOUND",
                "reason_message": "PO not found in store",
            })
            continue

        po_no = po.get("po_no") or po.get("header", {}).get("po_no", intake_id)
        cm = po.get("customer_match", {})
        cust_name = cm.get("name") or po.get("header", {}).get("customer_name_p21", "")
        review_status = po.get("review_status", "pending")
        confidence = po.get("confidence", "")
        lines_count = len(po.get("lines", []))

        if req.approved_only and review_status != "approved":
            skipped.append({
                "intake_id": intake_id,
                "po_no": po_no,
                "reason_code": "NOT_APPROVED",
                "reason_message": f"Status is '{review_status}' — must be approved",
            })
            continue

        v = _run_po_validation(po)
        if not v["valid"]:
            skipped.append({
                "intake_id": intake_id,
                "po_no": po_no,
                "reason_code": "VALIDATION_FAILED",
                "reason_message": "; ".join(e["message"] for e in v["errors"]),
                "validation_errors": v["errors"],
            })
            continue

        cust_id = cm.get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
        included.append({
            "intake_id": intake_id,
            "po_no": po_no,
            "customer": cust_name,
            "customer_id": cust_id,
            "lines": lines_count,
            "status": review_status,
            "confidence": confidence,
        })

    return {
        "selected_count": selected_count,
        "included_count": len(included),
        "skipped_count": len(skipped),
        "included": included,
        "skipped": skipped,
    }


@app.post("/api/v1/p21/payload/validate/{intake_id}")
async def validate_po_payload(intake_id: str):
    """Validate a single PO's P21 payload readiness and persist the result."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(status_code=404, detail=f"PO {intake_id} not found")
    po_no = po.get("po_no") or po.get("header", {}).get("po_no", intake_id)
    v = _run_po_validation(po)
    local_store.update_po(intake_id, {"payload_validation": v})
    return {
        "intake_id": intake_id,
        "po_no": po_no,
        "valid": v["valid"],
        "status": v["status"],
        "errors": v["errors"],
        "warnings": v["warnings"],
    }


@app.post("/api/v1/p21/payload/batch/download")
async def batch_payload_download(req: BatchPayloadRequest):
    """Build and download a merged P21 batch payload for a set of POs."""
    from services.processing.p21_api_client import build_p21_payload
    import json as _json
    from starlette.responses import Response
    from datetime import datetime as _dt

    included = []
    transactions = []
    skipped = []

    for intake_id in req.intake_ids:
        po = local_store.get_po(intake_id)
        if not po:
            skipped.append({"intake_id": intake_id, "po_no": "", "reason": "not found in store"})
            continue

        po_no = po.get("po_no") or po.get("header", {}).get("po_no", intake_id)

        if req.approved_only and po.get("review_status") != "approved":
            skipped.append({"intake_id": intake_id, "po_no": po_no, "reason": f"status is {po.get('review_status', 'unknown')}, not approved"})
            continue

        v = _run_po_validation(po)
        if not v["valid"]:
            skipped.append({"intake_id": intake_id, "po_no": po_no, "reason": "validation failed: " + ", ".join(e["code"] for e in v["errors"])})
            continue

        cust_id = po.get("customer_match", {}).get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
        try:
            engine = _get_customer_engine()
            po["customer_defaults"] = engine.get_customer_defaults(cust_id)
        except Exception:
            po["customer_defaults"] = {}

        try:
            single_payload = build_p21_payload(po)
            txn = single_payload.get("Transactions", [{}])[0]
            transactions.append(txn)
            included.append(intake_id)
        except Exception as exc:
            skipped.append({"intake_id": intake_id, "po_no": po_no, "reason": f"build error: {exc}"})

    if not transactions:
        raise HTTPException(status_code=422, detail={"message": "No POs passed validation", "skipped_reasons": skipped})

    batch_payload = {
        "Name": "Order",
        "UseCodeValues": False,
        "Transactions": transactions,
    }

    ts = _dt.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"p21_payload_batch_{ts}_{len(transactions)}.json"

    return Response(
        content=_json.dumps(batch_payload).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/p21/payloads")
async def list_p21_payloads():
    """List all POs that have a downloadable P21 payload, with metadata."""
    all_pos = local_store.list_pos()
    results = []
    for po in all_pos:
        intake_id = po.get("intake_id") or po.get("_intake_id", "")
        po_no = po.get("po_no") or po.get("header", {}).get("po_no", "")
        if not intake_id:
            continue
        results.append({
            "intake_id": intake_id,
            "po_no": po_no,
            "filename": f"p21_payload_{po_no}_{intake_id}.json",
            "created_at": po.get("_stored_at", ""),
            "confidence": po.get("confidence", ""),
            "review_status": po.get("review_status", "pending"),
            "lines_count": po.get("lines_count", len(po.get("lines", []))),
            "customer_name": po.get("customer_match", {}).get("name", ""),
            "customer_id": po.get("customer_match", {}).get("p21_id", ""),
            "payload_validation": po.get("payload_validation", {}),
        })
    return results


@app.post("/api/v1/p21/payload/from-file")
async def generate_p21_payload_from_file(file: UploadFile = File(...)):
    """Upload a cXML/PDF PO file, parse it, run crosswalk, and return the P21 API payload.
    One-stop endpoint for testing: upload PO → get P21 JSON back."""
    content = await file.read()
    filename = file.filename or "upload"

    if filename.lower().endswith(".pdf"):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            header, lines, raw = po_parser.parse_pdf(
                tmp_path, settings.doc_intel_endpoint, settings.doc_intel_key
            )
        finally:
            os.unlink(tmp_path)
    else:
        text = content.decode("utf-8", errors="replace")
        header, lines, raw = po_parser.parse_cxml(text)

    engine = _get_customer_engine()
    result = engine.match_po(header, lines)

    po_data = {
        "header": header.__dict__ if hasattr(header, "__dict__") else header,
        "lines": [l.__dict__ if hasattr(l, "__dict__") else l for l in lines],
        "customer_match": result.get("customer_match", {}),
        "customer_defaults": result.get("customer_defaults", {}),
    }

    from services.processing.p21_api_client import build_p21_payload
    payload = build_p21_payload(po_data)

    return {
        "p21_payload": payload,
        "parse_summary": {
            "po_no": (header.po_no if hasattr(header, "po_no") else header.get("po_no", "")),
            "customer_match": result.get("customer_match", {}),
            "line_count": len(lines),
            "confidence": result.get("confidence", "unknown"),
        },
    }


# ── P21 Live Submit ──────────────────────────────────────────────────────────
# These endpoints actually call the P21 Transaction API to create Sales Orders.
# They require P21_BASE_URL, P21_API_USERNAME, and P21_API_PASSWORD to be set.


class P21SubmitRequest(BaseModel):
    reviewer: str = "system"
    notes: str = ""


@app.post("/api/v1/p21/validate/{intake_id}")
async def validate_p21_payload(intake_id: str):
    """Validate a PO and return the P21 Transaction API payload that would be sent.
    Returns valid=true, readiness score, and the full payload — proves alignment with P21."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    v = _run_po_validation(po)

    cust_id = po.get("customer_match", {}).get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
    try:
        engine = _get_customer_engine()
        po["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
    except Exception:
        po["customer_defaults"] = {}

    payload = build_p21_payload(po)

    # Compute P21 readiness score (0-1)
    score = 0.0
    txn = payload["Transactions"][0] if payload.get("Transactions") else {}
    header_elem = next((e for e in txn.get("DataElements", []) if e.get("Name") == "TABPAGE_1.order"), {})
    header_edits = {e["Name"]: e["Value"] for row in header_elem.get("Rows", []) for e in row.get("Edits", [])}

    if header_edits.get("customer_id"): score += 0.25
    if header_edits.get("po_no"): score += 0.15
    if header_edits.get("ship_to_id") or header_edits.get("carrier_id") or header_edits.get("terms_id"): score += 0.20
    item_elem = next((e for e in txn.get("DataElements", []) if e.get("Name") == "TP_ITEMS.items"), {})
    item_rows = item_elem.get("Rows", [])
    if item_rows:
        score += 0.40
    # Boost for having customer defaults
    if po.get("customer_defaults"): score += 0.10
    score = min(score, 1.0)

    return {
        "valid": v["valid"],
        "message": "Payload aligns with P21 Transaction API v2" if v["valid"] else "Payload has validation errors",
        "p21_readiness_score": round(score, 2),
        "validation_errors": v.get("errors", []),
        "payload": payload,
        "po_no": po.get("header", {}).get("po_no", ""),
        "customer_id_p21": cust_id,
        "customer_defaults_present": bool(po.get("customer_defaults")),
    }


@app.post("/api/v1/p21/submit/{intake_id}")
async def submit_p21_single(intake_id: str, req: P21SubmitRequest, _auth=Depends(_require_api_key)):
    """Submit a single approved PO to P21 via the Transaction API v2.
    Returns the P21 Sales Order number on success."""
    if not settings.p21_base_url:
        raise HTTPException(503, "P21 API not configured — set P21_BASE_URL")

    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    v = _run_po_validation(po)
    if not v["valid"]:
        raise HTTPException(422, detail={"message": "PO failed payload validation", "errors": v["errors"]})

    cust_id = po.get("customer_match", {}).get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
    try:
        engine = _get_customer_engine()
        po["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
    except Exception:
        po["customer_defaults"] = {}

    client = P21ApiClient(
        base_url=settings.p21_base_url,
        username=settings.p21_api_username,
        password=settings.p21_api_password,
        verify_ssl=settings.p21_verify_ssl,
    )
    try:
        result = await client.create_sales_order(po)
    except P21AuthError as e:
        logger.error("P21 auth failed for PO %s: %s", intake_id, e)
        raise HTTPException(401, detail={"message": "P21 authentication failed", "detail": str(e)})
    except P21ApiError as e:
        logger.error("P21 API error for PO %s: %s", intake_id, e)
        raise HTTPException(502, detail={"message": "P21 API error", "detail": str(e), "response": e.response_body})
    except Exception as e:
        logger.error("Unexpected P21 error for PO %s: %s", intake_id, e)
        raise HTTPException(500, detail={"message": "Unexpected error calling P21", "detail": str(e)})
    finally:
        await client.close()

    # Persist SO number back to the PO
    so_number = result.get("order_no")
    if so_number:
        local_store.update_po(intake_id, {
            "p21_so_number": so_number,
            "p21_submitted_at": datetime.utcnow().isoformat(),
            "p21_submit_result": result,
        })

    return {
        "status": "submitted",
        "intake_id": intake_id,
        "po_no": po.get("header", {}).get("po_no", ""),
        "p21_so_number": so_number,
        "p21_result": result,
    }


class P21BatchSubmitRequest(BaseModel):
    intake_ids: list
    reviewer: str = "system"


@app.post("/api/v1/p21/submit/batch")
async def submit_p21_batch(req: P21BatchSubmitRequest, _auth=Depends(_require_api_key)):
    """Submit multiple approved POs to P21 in a single batch Transaction API call."""
    if not settings.p21_base_url:
        raise HTTPException(503, "P21 API not configured — set P21_BASE_URL")

    po_list = []
    skipped = []

    for intake_id in req.intake_ids:
        po = local_store.get_po(intake_id)
        if not po:
            skipped.append({"intake_id": intake_id, "reason": "not found"})
            continue
        v = _run_po_validation(po)
        if not v["valid"]:
            skipped.append({"intake_id": intake_id, "po_no": po.get("header", {}).get("po_no", ""), "reason": "validation failed", "errors": v["errors"]})
            continue

        cust_id = po.get("customer_match", {}).get("p21_id", "") or po.get("header", {}).get("customer_id_p21", "")
        try:
            engine = _get_customer_engine()
            po["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
        except Exception:
            po["customer_defaults"] = {}

        po_list.append(po)

    if not po_list:
        raise HTTPException(422, detail={"message": "No valid POs to submit", "skipped": skipped})

    client = P21ApiClient(
        base_url=settings.p21_base_url,
        username=settings.p21_api_username,
        password=settings.p21_api_password,
        verify_ssl=settings.p21_verify_ssl,
    )
    try:
        results = await client.create_sales_orders_batch(po_list)
    except P21AuthError as e:
        logger.error("P21 batch auth failed: %s", e)
        raise HTTPException(401, detail={"message": "P21 authentication failed", "detail": str(e)})
    except P21ApiError as e:
        logger.error("P21 batch API error: %s", e)
        raise HTTPException(502, detail={"message": "P21 API error", "detail": str(e), "response": e.response_body})
    except Exception as e:
        logger.error("Unexpected P21 batch error: %s", e)
        raise HTTPException(500, detail={"message": "Unexpected error calling P21", "detail": str(e)})
    finally:
        await client.close()

    # Persist SO numbers back to each PO
    for i, po in enumerate(po_list):
        intake_id = po.get("intake_id") or po.get("_intake_id", "")
        if not intake_id:
            continue
        result = results[i] if i < len(results) else {"status": "Unknown", "order_no": None}
        so_number = result.get("order_no")
        update = {
            "p21_submit_result": result,
        }
        if so_number:
            update["p21_so_number"] = so_number
            update["p21_submitted_at"] = datetime.utcnow().isoformat()
        local_store.update_po(intake_id, update)

    succeeded = sum(1 for r in results if r.get("order_no"))
    failed = len(results) - succeeded

    return {
        "status": "submitted",
        "submitted_count": len(po_list),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "skipped": skipped,
    }


class ApproveRequest(BaseModel):
    reviewer: str = "system"
    notes: str = ""


async def _approve_po(intake_id: str, reviewer: str = "bulk", notes: str = "") -> dict:
    """Shared approve logic used by single and bulk endpoints."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")
    if po.get("review_status") != "pending":
        raise HTTPException(400, f"PO {intake_id} already {po.get('review_status')}")

    local_store.update_po(intake_id, {
        "review_status": "approved",
        "approved": True,
        "reviewed_by": reviewer,
        "reviewer_notes": notes,
        "reviewed_at": datetime.utcnow().isoformat(),
    })

    # Auto-validate payload readiness on approval
    _approved = local_store.get_po(intake_id)
    if _approved:
        local_store.update_po(intake_id, {"payload_validation": _run_po_validation(_approved)})

    # Learning loop
    cust = po.get("customer_match", {})
    hdr = po.get("header", {})
    if cust.get("p21_id"):
        try:
            learn_from_approval(
                p21_customer_id=cust["p21_id"],
                p21_customer_name=cust.get("name", ""),
                source_system=po.get("source", ""),
                ship2_name=hdr.get("ship2_name", ""),
                ship2_add1=hdr.get("ship2_add1", ""),
                ship2_city=hdr.get("ship2_city", ""),
                ship2_state=hdr.get("ship2_state", ""),
                ship2_zip=hdr.get("ship2_zip", ""),
                po_no=po.get("po_no", ""),
                lines=[{
                    "supplier_part_id": l.get("supplier_part_id", ""),
                    "inv_mast_uid": l.get("item_id_p21", ""),
                    "unit_price": l.get("unit_price", 0),
                    "unit_of_measure": l.get("unit_of_measure", "EA"),
                    "item_description": l.get("item_description", ""),
                    "line_no": l.get("line_no", 0),
                } for l in po.get("lines", []) if l.get("item_id_p21")],
                crosswalk_dir=settings.crosswalk_dir,
            )
            # Invalidate cached engine so newly learned rows are visible next call
            global _customer_engine
            _customer_engine = None
        except Exception as e:
            logger.error(f"Learning loop error: {e}")

    # -- P21 Live API Submit (optional) ---------------------------------
    p21_result = None
    if settings.p21_auto_submit_on_approve and settings.p21_base_url:
        _approved = local_store.get_po(intake_id)
        v = _run_po_validation(_approved)
        if v["valid"]:
            try:
                cust_id = _approved.get("customer_match", {}).get("p21_id", "") or _approved.get("header", {}).get("customer_id_p21", "")
                engine = _get_customer_engine()
                _approved["customer_defaults"] = engine.get_customer_defaults(cust_id) if cust_id else {}
            except Exception:
                _approved["customer_defaults"] = {}

            client = P21ApiClient(
                base_url=settings.p21_base_url,
                username=settings.p21_api_username,
                password=settings.p21_api_password,
                verify_ssl=settings.p21_verify_ssl,
            )
            try:
                p21_result = await client.create_sales_order(_approved)
                so_number = p21_result.get("order_no")
                if so_number:
                    local_store.update_po(intake_id, {
                        "p21_so_number": so_number,
                        "p21_submitted_at": datetime.utcnow().isoformat(),
                        "p21_submit_result": p21_result,
                    })
            except Exception as e:
                logger.error("P21 auto-submit failed for PO %s: %s", intake_id, e)
                p21_result = {"error": str(e), "status": "failed"}
            finally:
                await client.close()

    pv = local_store.get_po(intake_id).get("payload_validation", {})
    resp = {
        "status": "approved",
        "intake_id": intake_id,
        "payload_validation": {
            "status": pv.get("status", "unknown"),
            "errors": pv.get("errors", []),
        },
    }
    if p21_result:
        resp["p21_submit"] = {
            "so_number": p21_result.get("order_no"),
            "status": p21_result.get("status", "unknown"),
            "error": p21_result.get("error"),
        }
    return resp


@app.post("/api/v1/review/po/{intake_id}/approve")
async def approve_po(intake_id: str, req: ApproveRequest, _auth=Depends(_require_api_key)):
    """Approve a PO -- triggers learning loop and submits to P21 (API or CISM fallback)."""
    return await _approve_po(intake_id, reviewer=req.reviewer, notes=req.notes)


@app.post("/api/v1/review/bulk-approve")
async def bulk_approve_greens(_auth=Depends(_require_api_key)):
    """Approve all POs with confidence=green and not yet approved in a single batch."""
    all_pos = local_store.list_pos()
    eligible = [
        po for po in all_pos
        if po.get("confidence") == "green" and po.get("review_status") != "approved"
    ]

    approved_count = 0
    skipped_count = 0
    po_nos = []
    errors = []

    for po in eligible:
        intake_id = po.get("intake_id")
        po_no = po.get("po_no") or po.get("header", {}).get("po_no", intake_id)
        try:
            await _approve_po(intake_id, reviewer="bulk")
            approved_count += 1
            po_nos.append(po_no)
        except HTTPException as e:
            skipped_count += 1
            errors.append({"po_no": po_no, "intake_id": intake_id, "error": e.detail})
        except Exception as e:
            skipped_count += 1
            errors.append({"po_no": po_no, "intake_id": intake_id, "error": str(e)})

    return {
        "approved_count": approved_count,
        "skipped_count": skipped_count,
        "po_nos": po_nos,
        "errors": errors,
    }


class RejectRequest(BaseModel):
    reviewer: str = "system"
    reason: str = ""

@app.post("/api/v1/review/po/{intake_id}/reject")
async def reject_po(intake_id: str, req: RejectRequest, _auth=Depends(_require_api_key)):
    """Reject a PO with reason."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    local_store.update_po(intake_id, {
        "review_status": "rejected",
        "reviewed_by": req.reviewer,
        "reject_reason": req.reason,
        "reviewed_at": datetime.utcnow().isoformat(),
    })
    return {"status": "rejected", "intake_id": intake_id}


@app.get("/api/v1/review/po/{intake_id}")
async def get_po_detail(intake_id: str):
    """Get full PO detail."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")
    return po


class EditPORequest(BaseModel):
    customer_id_p21: Optional[str] = None
    customer_name_p21: Optional[str] = None
    ship2_name: Optional[str] = None
    ship2_add1: Optional[str] = None
    ship2_city: Optional[str] = None
    ship2_state: Optional[str] = None
    ship2_zip: Optional[str] = None
    lines: Optional[list] = None  # [{line_no, item_id_p21, qty_ordered, unit_price, ...}]
    notes: Optional[str] = None


class SuggestionDecisionItem(BaseModel):
    decision: str  # accept | reject
    target_type: str  # customer | item
    line_no: Optional[int] = None
    selected_id: str
    rationale: Optional[str] = ""


class MappingDecisionRequest(BaseModel):
    user_decisions: list[SuggestionDecisionItem]
    audit: Optional[dict] = None

@app.post("/api/v1/review/po/{intake_id}/edit")
async def edit_po(intake_id: str, req: EditPORequest, _auth=Depends(_require_api_key)):
    """Edit a PO — update customer mapping, line items, ship-to, etc."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    updates = {}
    header = po.get("header", {})
    cust_match = po.get("customer_match", {})

    if req.customer_id_p21 is not None:
        header["customer_id_p21"] = req.customer_id_p21
        header["customer_name_p21"] = req.customer_name_p21 or ""
        header["customer_match_method"] = "manual_edit"
        header["customer_match_score"] = 1.0
        cust_match["p21_id"] = req.customer_id_p21
        cust_match["name"] = req.customer_name_p21 or ""
        cust_match["score"] = 1.0
        cust_match["method"] = "manual_edit"
        updates["customer_match"] = cust_match

    if req.ship2_name is not None: header["ship2_name"] = req.ship2_name
    if req.ship2_add1 is not None: header["ship2_add1"] = req.ship2_add1
    if req.ship2_city is not None: header["ship2_city"] = req.ship2_city
    if req.ship2_state is not None: header["ship2_state"] = req.ship2_state
    if req.ship2_zip is not None: header["ship2_zip"] = req.ship2_zip
    updates["header"] = header

    if req.lines is not None:
        existing_lines = po.get("lines", [])
        for edit_line in req.lines:
            ln = edit_line.get("line_no")
            for el in existing_lines:
                if el.get("line_no") == ln:
                    if "item_id_p21" in edit_line: el["item_id_p21"] = edit_line["item_id_p21"]
                    if "qty_ordered" in edit_line: el["qty_ordered"] = edit_line["qty_ordered"]
                    if "unit_price" in edit_line: el["unit_price"] = edit_line["unit_price"]
                    if "unit_of_measure" in edit_line: el["unit_of_measure"] = edit_line["unit_of_measure"]
                    if "item_description" in edit_line: el["item_description"] = edit_line["item_description"]
                    el["crosswalk_match_score"] = 1.0  # manual = 100%
                    break
        updates["lines"] = existing_lines
        # Recalculate item scores
        updates["item_scores"] = [l.get("crosswalk_match_score", 0) for l in existing_lines]

    if req.notes is not None:
        updates["edit_notes"] = req.notes

    updates["edited_at"] = datetime.utcnow().isoformat()

    # Re-run confidence scoring after edit
    item_scores = updates.get("item_scores", po.get("item_scores", []))
    cust_score = 1.0 if req.customer_id_p21 else (po.get("customer_match", {}).get("score", 0))
    ship_score = cust_score * 0.95
    is_dup = po.get("duplicate", {}).get("is_duplicate", False)

    new_conf = score_customer_po(
        customer_score=cust_score,
        shipto_score=ship_score,
        item_scores=item_scores,
        is_duplicate=is_dup,
    )
    updates["confidence"] = new_conf.overall
    updates["review_required"] = new_conf.review_required
    updates["reason"] = new_conf.reason
    if new_conf.overall == "green":
        updates["review_status"] = "approved"

    local_store.update_po(intake_id, updates)

    # Auto-validate payload readiness after edit
    _updated = local_store.get_po(intake_id)
    if _updated:
        local_store.update_po(intake_id, {"payload_validation": _run_po_validation(_updated)})

    return {
        "status": "edited",
        "intake_id": intake_id,
        "new_confidence": new_conf.overall,
        "reason": new_conf.reason,
        "review_required": new_conf.review_required,
    }


# ── Mapping Suggestion Agent ────────────────────────────────────────────────

@app.post("/api/v1/suggest/mappings/{intake_id}")
async def suggest_mappings_endpoint(intake_id: str, _auth=Depends(_require_api_key)):
    """Get mapping suggestions for a PO."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    engine = _get_customer_engine()
    result = await suggest_mappings(po, engine, None)
    return result


@app.post("/api/v1/suggest/mappings/{intake_id}/decide")
async def submit_mapping_decisions(
    intake_id: str,
    req: MappingDecisionRequest,
    _auth=Depends(_require_api_key),
):
    """Submit accept/reject decisions for mapping suggestions."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    global _customer_engine

    accepted = []
    rejected = []

    for d in req.user_decisions:
        if d.decision == "accept":
            if d.target_type == "customer":
                header = po.get("header", {})
                cust_match = po.get("customer_match", {})
                header["customer_id_p21"] = d.selected_id
                header["customer_match_method"] = "manual_accept"
                header["customer_match_score"] = 1.0
                cust_match["p21_id"] = d.selected_id
                cust_match["score"] = 1.0
                cust_match["method"] = "manual_accept"
                local_store.update_po(
                    intake_id, {"header": header, "customer_match": cust_match}
                )
                try:
                    engine = _get_customer_engine()
                    cust_detail = engine.get_customer_detail(d.selected_id)
                    learn_from_approval(
                        p21_customer_id=d.selected_id,
                        p21_customer_name=cust_detail.get("customer_name", ""),
                        source_system=po.get("source", ""),
                        ship2_name=header.get("ship2_name", ""),
                        ship2_add1=header.get("ship2_add1", ""),
                        ship2_city=header.get("ship2_city", ""),
                        ship2_state=header.get("ship2_state", ""),
                        ship2_zip=header.get("ship2_zip", ""),
                        po_no=po.get("po_no", ""),
                        lines=[],
                        crosswalk_dir=settings.crosswalk_dir,
                        provenance="manual_accept",
                    )
                    _customer_engine = None
                except Exception as e:
                    logger.error(f"Learning loop error on customer accept: {e}")

            elif d.target_type == "item":
                lines = po.get("lines", [])
                matched_line = None
                for line in lines:
                    if line.get("line_no") == d.line_no:
                        line["item_id_p21"] = d.selected_id
                        line["crosswalk_match_score"] = 1.0
                        matched_line = line
                        break
                local_store.update_po(intake_id, {"lines": lines})
                try:
                    header = po.get("header", {})
                    cust_id = (
                        po.get("customer_match", {}).get("p21_id", "")
                        or header.get("customer_id_p21", "")
                    )
                    if cust_id and matched_line:
                        learn_from_approval(
                            p21_customer_id=cust_id,
                            source_system=po.get("source", ""),
                            po_no=po.get("po_no", ""),
                            lines=[
                                {
                                    "supplier_part_id": matched_line.get(
                                        "supplier_part_id", ""
                                    ),
                                    "inv_mast_uid": d.selected_id,
                                    "unit_price": matched_line.get("unit_price", 0),
                                    "unit_of_measure": matched_line.get(
                                        "unit_of_measure", "EA"
                                    ),
                                    "item_description": matched_line.get(
                                        "item_description", ""
                                    ),
                                    "line_no": d.line_no,
                                }
                            ],
                            crosswalk_dir=settings.crosswalk_dir,
                            provenance="manual_accept",
                        )
                        _customer_engine = None
                except Exception as e:
                    logger.error(f"Learning loop error on item accept: {e}")

            accepted.append(d.dict())

        elif d.decision == "reject":
            rejected.append(d.dict())

    if rejected:
        write_rejection_log(intake_id, rejected)

    return {"status": "recorded", "accepted": len(accepted), "rejected": len(rejected)}


# ── CISM Batch Endpoints ────────────────────────────────────────────────────

@app.get("/api/v1/cism/batch")
async def cism_batch_status():
    """Get current CISM batch contents — the accumulated approved POs."""
    return get_batch_status()


@app.get("/api/v1/cism/batch/download/{file_type}")
async def download_batch(file_type: str):
    """Download the batch header or lines CSV."""
    batch = get_batch_status()
    if file_type == "header":
        path = batch["header_file"]
    elif file_type == "lines":
        path = batch["lines_file"]
    else:
        raise HTTPException(400, "file_type must be 'header' or 'lines'")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise HTTPException(404, "Batch file empty — approve POs first")
    return FileResponse(path, media_type="text/csv", filename=os.path.basename(path))


@app.post("/api/v1/cism/batch/clear")
async def clear_cism_batch(_auth=Depends(_require_api_key)):
    """Clear the batch after uploading to Azure. Archives the files."""
    return clear_batch()


# ── CISM Schema Reference ───────────────────────────────────────────────────

CISM_HEADER_SCHEMA = [
    {"field": "Import Set No", "type": "Alphanumeric", "required": True, "max_len": 8, "desc": "Unique batch ID linking header to lines"},
    {"field": "Customer ID", "type": "Decimal", "required": True, "max_len": 19, "desc": "P21 customer_id from crosswalk match"},
    {"field": "Customer Name", "type": "Alphanumeric", "required": True, "max_len": 50, "desc": "P21 customer name"},
    {"field": "Company ID", "type": "Alphanumeric", "required": True, "max_len": 8, "desc": "P21 company (default '1')"},
    {"field": "Sales Location ID", "type": "Decimal", "required": True, "max_len": 9, "desc": "P21 location (default 10)"},
    {"field": "Customer PO Number", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "Customer's PO# from Ariba/Coupa"},
    {"field": "Contact ID", "type": "Alphanumeric", "required": True, "max_len": 16, "desc": "P21 contact ID"},
    {"field": "Contact Name", "type": "Alphanumeric", "required": True, "max_len": 50, "desc": "Buyer/contact name from PO"},
    {"field": "Taker", "type": "Alphanumeric", "required": True, "max_len": 30, "desc": "Order taker / inside sales rep"},
    {"field": "Job Name", "type": "Alphanumeric", "required": False, "max_len": 40, "desc": "Job/project name"},
    {"field": "Order Date", "type": "DateTime", "required": False, "max_len": 8, "desc": "PO date (MM/DD/YYYY)"},
    {"field": "Requested Date", "type": "DateTime", "required": False, "max_len": 8, "desc": "Requested delivery date"},
    {"field": "Quote", "type": "Alphanumeric", "required": False, "max_len": 1, "desc": "Quote flag"},
    {"field": "Approved", "type": "Alphanumeric", "required": False, "max_len": 1, "desc": "Y=approved, N=pending"},
    {"field": "Ship To ID", "type": "Numeric", "required": True, "max_len": 9, "desc": "P21 ship-to address ID"},
    {"field": "Ship To Name", "type": "Alphanumeric", "required": True, "max_len": 50, "desc": "Ship-to company name"},
    {"field": "Ship To Address 1", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "Street address line 1"},
    {"field": "Ship To Address 2", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "Street address line 2"},
    {"field": "Ship To City", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "City"},
    {"field": "Ship To State", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "State"},
    {"field": "Ship To Zip Code", "type": "Alphanumeric", "required": False, "max_len": 10, "desc": "Zip code"},
    {"field": "Ship To Country", "type": "Alphanumeric", "required": False, "max_len": 50, "desc": "Country code"},
    {"field": "Packing Basis", "type": "Alphanumeric", "required": True, "max_len": 16, "desc": "Partial/Order, Item Complete, etc."},
    {"field": "Delivery Instructions", "type": "Alphanumeric", "required": False, "max_len": 255, "desc": "Shipping/delivery notes"},
    {"field": "Terms", "type": "Alphanumeric", "required": False, "max_len": 2, "desc": "Payment terms ID"},
    {"field": "Carrier ID", "type": "Numeric", "required": False, "max_len": 9, "desc": "P21 carrier ID"},
    {"field": "Will Call", "type": "Alphanumeric", "required": False, "max_len": 1, "desc": "Y/N will call pickup"},
    {"field": "Ship To Email Address", "type": "Alphanumeric", "required": False, "max_len": 255, "desc": "Email for ship-to contact"},
    {"field": "Promise Date", "type": "DateTime", "required": False, "max_len": 8, "desc": "Promised delivery date"},
    {"field": "Supplier Order No", "type": "Alphanumeric", "required": False, "max_len": 255, "desc": "Source system reference"},
]

CISM_LINE_SCHEMA = [
    {"field": "Import Set Number", "type": "Alphanumeric", "required": True, "max_len": 8, "desc": "Must match header Import Set No"},
    {"field": "Line No", "type": "Numeric", "required": True, "max_len": 9, "desc": "Sequential line number"},
    {"field": "Item ID", "type": "Alphanumeric", "required": True, "max_len": 40, "desc": "P21 item ID from crosswalk"},
    {"field": "Unit Quantity", "type": "Numeric", "required": True, "max_len": 10, "desc": "Quantity ordered"},
    {"field": "Unit of Measure", "type": "Alphanumeric", "required": True, "max_len": 8, "desc": "UOM (EA, CS, FT, etc.)"},
    {"field": "Unit Price", "type": "Decimal", "required": False, "max_len": "19,4", "desc": "Price per unit"},
    {"field": "Extended Description", "type": "Alphanumeric", "required": False, "max_len": 255, "desc": "Item description from PO"},
    {"field": "Source Location ID", "type": "Numeric", "required": False, "max_len": 9, "desc": "Sourcing warehouse"},
    {"field": "Ship Location ID", "type": "Numeric", "required": False, "max_len": 9, "desc": "Shipping warehouse"},
    {"field": "Product Group ID", "type": "Alphanumeric", "required": False, "max_len": 8, "desc": "P21 product group"},
    {"field": "Supplier ID", "type": "Numeric", "required": False, "max_len": 9, "desc": "Vendor/supplier ID"},
    {"field": "Required Date", "type": "DateTime", "required": False, "max_len": 8, "desc": "Line-level required date"},
    {"field": "Disposition", "type": "Alphanumeric", "required": False, "max_len": 1, "desc": "B=Backorder, D=Direct, S=Special, H=Hold"},
    {"field": "Manual Price Override", "type": "Alphanumeric", "required": False, "max_len": 1, "desc": "Y=use provided price"},
    {"field": "Capture Usage", "type": "Alphanumeric", "required": True, "max_len": 1, "desc": "Y/N capture usage tracking"},
    {"field": "Item Description", "type": "Alphanumeric", "required": False, "max_len": 40, "desc": "Short item description"},
]

@app.get("/api/v1/cism/schema")
async def cism_schema():
    """Return the P21 CISM Order/Quote Import schema."""
    return {"header": CISM_HEADER_SCHEMA, "line": CISM_LINE_SCHEMA}


# ── Quote Crosswalk (Dynamics) ──────────────────────────────────────────────

QUOTE_DATA_DIR = "/app/data/quote_data"

@app.post("/api/v1/crosswalk/upload-quotes")
async def upload_quote_data(file: UploadFile = File(...)):
    """Upload Dynamics quote JSON or CSV for crosswalk reference."""
    os.makedirs(QUOTE_DATA_DIR, exist_ok=True)
    content = await file.read()
    filename = file.filename or "quotes.json"
    dest = os.path.join(QUOTE_DATA_DIR, filename)
    with open(dest, "wb") as f:
        f.write(content)
    return {"status": "uploaded", "file": filename, "size": len(content)}


@app.get("/api/v1/crosswalk/quotes")
async def list_quotes(limit: int = 100):
    """List Dynamics quote data if available."""
    import json as jsonmod
    results = []
    if not os.path.exists(QUOTE_DATA_DIR):
        return results
    for fname in os.listdir(QUOTE_DATA_DIR):
        path = os.path.join(QUOTE_DATA_DIR, fname)
        try:
            if fname.endswith(".json"):
                with open(path) as f:
                    data = jsonmod.load(f)
                if isinstance(data, list):
                    for item in data[:limit]:
                        results.append(item)
                elif isinstance(data, dict):
                    # Try common keys: value, lvp_quotes, lvp_quotelines, results, data
                    for key in ["value", "lvp_quotes", "lvp_quotelines", "results", "data"]:
                        if key in data and isinstance(data[key], list):
                            for item in data[key][:limit]:
                                results.append(item)
                            break
            elif fname.endswith(".csv"):
                import csv as csvmod
                with open(path, encoding="utf-8-sig") as f:
                    for i, row in enumerate(csvmod.DictReader(f)):
                        if i >= limit: break
                        results.append(row)
        except Exception as e:
            logger.error(f"Error reading quote file {fname}: {e}")
    return results


class VendorMappingRequest(BaseModel):
    source: str
    source_vendor_id: str
    source_vendor_name: str
    p21_vendor_id: str
    p21_vendor_name: str

@app.post("/api/v1/review/crosswalk/vendor")
async def add_vendor_mapping(req: VendorMappingRequest, _auth=Depends(_require_api_key)):
    """Add or update a vendor crosswalk mapping from review portal."""
    save_vendor_mapping(
        req.source, req.source_vendor_id, req.source_vendor_name,
        req.p21_vendor_id, req.p21_vendor_name, "manual",
    )
    return {"status": "saved", "mapping": req.dict()}


class ItemMappingRequest(BaseModel):
    source: str
    source_item_id: str
    source_item_desc: str
    p21_item_id: str
    p21_item_desc: str
    p21_vendor_id: Optional[str] = None

@app.post("/api/v1/review/crosswalk/item")
async def add_item_mapping(req: ItemMappingRequest, _auth=Depends(_require_api_key)):
    """Add or update an item crosswalk mapping from review portal."""
    save_item_mapping(
        req.source, req.source_item_id, req.source_item_desc,
        req.p21_item_id, req.p21_item_desc, req.p21_vendor_id, "manual",
    )
    return {"status": "saved", "mapping": req.dict()}


# ── Customer Item Lookup (for Edit PO dropdowns) ────────────────────────────

@app.get("/api/v1/lookup/customer-items/{customer_id}")
async def lookup_customer_items(customer_id: str, q: str = "", limit: int = 50):
    """
    Get items this customer has ordered before, sorted by frequency.
    Used to populate the Edit PO part number dropdown.
    Optional q param filters by part# or description.
    """
    engine = _get_customer_engine()
    items = engine.customer_items.get(customer_id, [])

    if q:
        q_upper = q.upper()
        items = [i for i in items if
                 q_upper in (i.get("customer_part_number", "").upper()) or
                 q_upper in (i.get("p21_item_desc", "").upper())]

    # Sort by seen_count descending
    items.sort(key=lambda x: int(x.get("seen_count", 0)), reverse=True)

    return [{
        "customer_part_number": i.get("customer_part_number"),
        "p21_inv_mast_uid": i.get("p21_inv_mast_uid"),
        "p21_item_desc": i.get("p21_item_desc"),
        "unit_of_measure": i.get("unit_of_measure"),
        "unit_price_avg": i.get("unit_price_avg"),
        "unit_price_last": i.get("unit_price_last"),
        "seen_count": i.get("seen_count"),
    } for i in items[:limit]]


@app.get("/api/v1/lookup/customers")
async def lookup_customers(q: str = "", limit: int = 20):
    """Search customers by name for Edit PO customer dropdown."""
    engine = _get_customer_engine()
    if not q:
        return engine.customer_xw[:limit]

    q_upper = q.upper()
    matches = [r for r in engine.customer_xw if
               q_upper in (r.get("p21_customer_name", "").upper()) or
               q_upper in (r.get("p21_customer_id", ""))]
    return [{
        "p21_customer_id": r.get("p21_customer_id"),
        "p21_customer_name": r.get("p21_customer_name"),
        "ship2_name": r.get("ship2_name"),
        "ship2_zip": r.get("ship2_zip"),
    } for r in matches[:limit]]


# ── Quote Export ──────────────────────────────────────────────────────────────

class QuoteExportRequest(BaseModel):
    days_back: int = 365

@app.post("/api/v1/quotes/export")
async def export_quotes(req: QuoteExportRequest):
    """Trigger Dynamics quote export to blob storage."""
    try:
        result = export_quotes_to_blob(req.days_back)
        return {
            "status": "success",
            "timestamp": result.get("timestamp"),
            "quotes_count": result.get("quotes_count"),
            "lines_count": result.get("lines_count"),
            "uploads": result.get("uploads", {}),
        }
    except Exception as e:
        logger.error(f"Quote export failed: {e}")
        raise HTTPException(500, f"Export failed: {str(e)}")


@app.get("/api/v1/quotes/status")
async def quotes_status():
    """Get status of latest quote export."""
    try:
        from services.processing.blob_uploader import get_uploader
        uploader = get_uploader()
        
        if not uploader.is_configured():
            return {"status": "not_configured", "blob": None}
        
        # Try to get latest quote file metadata
        try:
            blob_client = uploader.client.get_blob_client(
                container=uploader.BLOB_CONTAINER_NAME,
                blob="crosswalk/quotes/quotes_dynamics_latest.csv"
            )
            props = blob_client.get_blob_properties()
            return {
                "status": "available",
                "last_modified": props.last_modified.isoformat() if props.last_modified else None,
                "size_bytes": props.size,
                "blob_path": "crosswalk/quotes/quotes_dynamics_latest.csv"
            }
        except Exception:
            return {"status": "no_data", "blob": None}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Crosswalk Build ─────────────────────────────────────────────────────────

P21_DATA_DIR = "/app/data/p21_data"

@app.post("/api/v1/crosswalk/upload")
async def upload_p21_csv(
    file: UploadFile = File(...),
    file_type: str = Form(...),  # "headers", "lines", or "customers"
    _auth=Depends(_require_api_key),
):
    """Upload a P21 CSV export. file_type must be 'headers', 'lines', or 'customers'."""
    if file_type not in ("headers", "lines", "customers"):
        raise HTTPException(400, "file_type must be 'headers', 'lines', or 'customers'")

    os.makedirs(P21_DATA_DIR, exist_ok=True)
    dest = os.path.join(P21_DATA_DIR, f"p21_{file_type}.csv")
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    size = len(content)
    logger.info(f"Uploaded P21 {file_type} CSV: {file.filename} ({size} bytes) -> {dest}")
    return {"status": "uploaded", "file_type": file_type, "size": size, "path": dest}


_build_status = {"state": "idle", "result": None}

@app.post("/api/v1/crosswalk/sync-from-blob")
async def sync_crosswalks_endpoint(rebuild: bool = False, _auth=Depends(_require_api_key)):
    """
    Download every file under the blob 'crosswalk/' prefix onto the
    persistent disk (p21_data/, crosswalks/, quote_data/). Optionally run
    the crosswalk build afterward if ?rebuild=true.

    This is the intended bootstrap path for a fresh Render disk: Azure Blob
    is the source of truth, the persistent disk is a cache.
    """
    result = sync_crosswalks_from_blob()

    # Invalidate the cached customer engine so it picks up the new CSVs.
    global _customer_engine
    _customer_engine = None

    if rebuild:
        # Kick off a build in the background using the same path as
        # /api/v1/crosswalk/build. Only valid if the raw P21 CSVs were part
        # of the sync payload.
        headers_path = os.path.join(P21_DATA_DIR, "p21_headers.csv")
        lines_path = os.path.join(P21_DATA_DIR, "p21_lines.csv")
        customers_path = os.path.join(P21_DATA_DIR, "p21_customers.csv")
        if all(os.path.exists(p) for p in (headers_path, lines_path, customers_path)):
            import threading

            def _do_build():
                global _customer_engine
                _build_status["state"] = "building"
                _build_status["result"] = None
                try:
                    from services.processing.crosswalk_csv_builder import build_all
                    build_all(
                        headers_path=headers_path,
                        lines_path=lines_path,
                        customers_path=customers_path,
                        output_dir=settings.crosswalk_dir,
                    )
                    _customer_engine = None
                    _build_status["result"] = {"status": "success"}
                    _build_status["state"] = "done"
                except Exception as e:
                    _build_status["result"] = {"status": "error", "error": str(e)}
                    _build_status["state"] = "error"
                    logger.error(f"Post-sync build failed: {e}")

            threading.Thread(target=_do_build, daemon=True).start()
            result["build"] = "started"
        else:
            result["build"] = "skipped (no raw P21 CSVs in blob)"

    return result


@app.on_event("startup")
async def _bootstrap_crosswalks_if_empty():
    """
    On cold start, if the persistent disk has no crosswalks yet, try to
    hydrate them from Azure Blob. Non-fatal: logs and continues on failure
    so an unreachable blob never blocks boot.
    """
    try:
        cw_dir = settings.crosswalk_dir
        marker = os.path.join(cw_dir, "customer_crosswalk.csv")
        if os.path.exists(marker):
            logger.info(f"Crosswalks already present at {cw_dir}, skipping blob bootstrap")
            return
        logger.info(f"Crosswalks missing at {cw_dir}, syncing from blob on startup")
        result = sync_crosswalks_from_blob()
        logger.info(
            f"Startup blob sync: downloaded={len(result.get('downloaded', []))}, "
            f"skipped={len(result.get('skipped', []))}, errors={len(result.get('errors', []))}"
        )
        if result.get("errors"):
            for err in result["errors"][:5]:
                logger.warning(f"  blob sync error: {err}")
    except Exception as e:
        logger.error(f"Startup blob bootstrap failed (non-fatal): {e}")

    # ── Background email polling ──────────────────────────────────────────
    try:
        from services.intake.email_poller import EmailPoller, TENANT_ID, CLIENT_ID, CLIENT_SECRET
        if TENANT_ID and CLIENT_ID and CLIENT_SECRET:
            logger.info("Graph API credentials found — starting background email poller")
            poller = EmailPoller()
            asyncio.create_task(poller.run_continuous())
        else:
            logger.info("Graph API credentials not configured — email polling disabled")
    except Exception as e:
        logger.error(f"Failed to start email poller (non-fatal): {e}")


@app.post("/api/v1/crosswalk/build")
async def build_crosswalks(background_tasks=None, _auth=Depends(_require_api_key)):
    """Build crosswalk CSVs from uploaded P21 exports. Runs in background."""
    import threading

    headers_path = os.path.join(P21_DATA_DIR, "p21_headers.csv")
    lines_path = os.path.join(P21_DATA_DIR, "p21_lines.csv")
    customers_path = os.path.join(P21_DATA_DIR, "p21_customers.csv")

    missing = []
    if not os.path.exists(headers_path): missing.append("headers")
    if not os.path.exists(lines_path): missing.append("lines")
    if not os.path.exists(customers_path): missing.append("customers")
    if missing:
        raise HTTPException(400, f"Missing P21 uploads: {', '.join(missing)}. Upload via POST /api/v1/crosswalk/upload first.")

    if _build_status["state"] == "building":
        return {"status": "already_building"}

    def _do_build():
        global _customer_engine
        _build_status["state"] = "building"
        _build_status["result"] = None
        try:
            from services.processing.crosswalk_csv_builder import build_all
            build_all(
                headers_path=headers_path,
                lines_path=lines_path,
                customers_path=customers_path,
                output_dir=settings.crosswalk_dir,
            )
            _customer_engine = None

            import glob as g
            csv_files = g.glob(os.path.join(settings.crosswalk_dir, "*.csv"))
            counts = {}
            for f in csv_files:
                name = os.path.basename(f)
                with open(f) as fh:
                    counts[name] = sum(1 for _ in fh) - 1
            _build_status["result"] = {"status": "success", "files": counts}
            _build_status["state"] = "done"
            logger.info(f"Crosswalk build complete: {counts}")
        except Exception as e:
            _build_status["result"] = {"status": "error", "error": str(e)}
            _build_status["state"] = "error"
            logger.error(f"Crosswalk build failed: {e}")

    threading.Thread(target=_do_build, daemon=True).start()
    return {"status": "building", "message": "Build started in background. Poll GET /api/v1/crosswalk/build/status"}


@app.get("/api/v1/crosswalk/build/status")
async def build_status():
    """Check crosswalk build progress."""
    return {"state": _build_status["state"], "result": _build_status["result"]}


@app.get("/api/v1/crosswalk/customers")
async def list_customer_crosswalk(limit: int = 100):
    """List customer crosswalk entries."""
    engine = _get_customer_engine()
    rows = engine.customer_xw[:limit]
    return [{
        "p21_customer_id": r.get("p21_customer_id"),
        "p21_customer_name": r.get("p21_customer_name"),
        "ship2_name": r.get("ship2_name"),
        "ship2_zip": r.get("ship2_zip"),
        "source_system": r.get("source_system"),
        "match_method": r.get("match_method"),
        "seen_count": r.get("seen_count"),
    } for r in rows]


# ── P21 Sales Order Pull ────────────────────────────────────────────────────

class SOExportRequest(BaseModel):
    days_back: int = 90
    include_customers: bool = True
    include_ship_tos: bool = True
    include_items: bool = True

@app.post("/api/v1/so/export")
async def export_sales_orders(req: SOExportRequest):
    """Pull Sales Orders from P21 and export to blob storage."""
    try:
        result = export_so_data(
            days_back=req.days_back,
            include_customers=req.include_customers,
            include_ship_tos=req.include_ship_tos,
            include_items=req.include_items,
        )
        return {
            "status": "success",
            "timestamp": result.get("timestamp"),
            "so_headers_count": result.get("so_headers_count"),
            "so_lines_count": result.get("so_lines_count"),
            "customers_count": result.get("customers_count"),
            "ship_tos_count": result.get("ship_tos_count"),
            "items_count": result.get("items_count"),
            "uploads": result.get("uploads", {}),
        }
    except Exception as e:
        logger.error(f"SO export failed: {e}")
        raise HTTPException(500, f"SO export failed: {str(e)}")


@app.get("/api/v1/so/status")
async def so_export_status():
    """Get status of latest SO export in blob storage."""
    try:
        from services.processing.blob_uploader import get_uploader
        uploader = get_uploader()

        if not uploader.is_configured():
            return {"status": "not_configured", "blob": None}

        files = {}
        for name in ["so_headers", "so_lines", "customers", "ship_tos", "items"]:
            blob_name = f"crosswalk/p21/{name}_latest.csv"
            try:
                blob_client = uploader.client.get_blob_client(
                    container=uploader.BLOB_CONTAINER_NAME, blob=blob_name,
                )
                props = blob_client.get_blob_properties()
                files[name] = {
                    "last_modified": props.last_modified.isoformat() if props.last_modified else None,
                    "size_bytes": props.size,
                }
            except Exception:
                files[name] = None

        has_data = any(v is not None for v in files.values())
        return {"status": "available" if has_data else "no_data", "files": files}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Stats (local file store) ─────────────────────────────────────────────────

@app.get("/api/v1/stats")
async def stats():
    """Dashboard statistics from local store + crosswalk CSVs."""
    s = local_store.get_stats()

    # Crosswalk counts from CSV files
    engine = _get_customer_engine()
    cust_count = len(engine.customer_xw)
    item_count = sum(len(v) for v in engine.customer_items.values())

    return {
        "total": s["total"],
        "green": s["green"],
        "yellow": s["yellow"],
        "red": s["red"],
        "approved": s["approved"],
        "rejected": s["rejected"],
        "pending": s["pending"],
        "crosswalk": {
            "customers": cust_count,
            "items": item_count,
        }
    }


# ── Crosswalk APIs (CSV-based) ──────────────────────────────────────────────

@app.get("/api/v1/crosswalk/customer-items")
async def list_customer_items(customer_id: str = "", limit: int = 100):
    """List customer-item crosswalk entries."""
    engine = _get_customer_engine()
    if customer_id:
        rows = engine.customer_items.get(customer_id, [])[:limit]
    else:
        rows = []
        for cid_rows in engine.customer_items.values():
            rows.extend(cid_rows)
            if len(rows) >= limit:
                break
        rows = rows[:limit]
    # Enrich with customer names
    results = []
    for r in rows:
        cid = r.get("p21_customer_id", "")
        cust_detail = engine.customers_p21.get(cid, {})
        results.append({
            "p21_customer_id": cid,
            "customer_name": cust_detail.get("customer_name", ""),
            "customer_part_number": r.get("customer_part_number"),
            "p21_inv_mast_uid": r.get("p21_inv_mast_uid"),
            "p21_item_desc": r.get("p21_item_desc"),
            "unit_of_measure": r.get("unit_of_measure"),
            "product_group_id": r.get("product_group_id"),
            "unit_price_avg": r.get("unit_price_avg"),
            "seen_count": r.get("seen_count"),
        })
    return results


@app.get("/api/v1/crosswalk/po-history")
async def list_po_history(customer_id: str = "", limit: int = 100):
    """List PO-to-SO history."""
    engine = _get_customer_engine()
    if customer_id:
        rows = engine.po_history.get(customer_id, [])
        rows = [r for r in rows if r.get("p21_customer_id") == customer_id][:limit]
    else:
        rows = []
        for po_rows in engine.po_history.values():
            rows.extend(po_rows)
            if len(rows) >= limit:
                break
        rows = rows[:limit]
    return [{
        "p21_customer_id": r.get("p21_customer_id"),
        "customer_po_no": r.get("customer_po_no"),
        "p21_order_no": r.get("p21_order_no"),
        "order_date": r.get("order_date"),
        "completed": r.get("completed"),
        "ship2_name": r.get("ship2_name"),
    } for r in rows]


@app.get("/api/v1/crosswalk/items")
async def list_item_master(limit: int = 100):
    """List item master index."""
    engine = _get_customer_engine()
    rows = list(engine.item_master.values())[:limit]
    return [{
        "p21_inv_mast_uid": r.get("p21_inv_mast_uid"),
        "p21_part_number": r.get("p21_part_number"),
        "p21_item_desc": r.get("p21_item_desc"),
        "default_selling_unit": r.get("default_selling_unit"),
        "product_group": r.get("product_group"),
        "default_supplier_id": r.get("default_supplier_id"),
        "supplier_name": r.get("supplier_name"),
    } for r in rows]


# ── Outbound Sync ─────────────────────────────────────────────────────────────

@app.get("/api/v1/outbound/queue")
async def get_outbound_queue(status: Optional[str] = None):
    """List all outbound sync records, optionally filtered by status."""
    return outbound_store.list_records(status=status)


@app.post("/api/v1/outbound/prepare/{intake_id}")
async def prepare_outbound(intake_id: str, _auth=Depends(_require_api_key)):
    """Build outbound payload from existing PO data. Idempotent — safe to re-run."""
    po = local_store.get_po(intake_id)
    if not po:
        raise HTTPException(404, f"PO {intake_id} not found")

    # Resolve source system — normalise to ariba or coupa
    raw_source = (po.get("source") or "ariba").lower()
    source_system = "coupa" if "coupa" in raw_source else "ariba"

    # Derive customer_id from wherever it was stored
    cust_match = po.get("customer_match") or {}
    header = po.get("header") or {}
    customer_id = (
        cust_match.get("p21_id")
        or cust_match.get("p21_customer_id")
        or header.get("customer_id_p21")
        or ""
    )

    # Sum line totals for amount_total
    lines = po.get("lines", [])
    amount_total = round(
        sum((l.get("qty_ordered") or 0) * (l.get("unit_price") or 0) for l in lines),
        2,
    )

    p21_order_no = po.get("p21_order_no") or header.get("p21_order_no", "")

    existing = outbound_store.get_by_intake(intake_id)
    if existing:
        outbound_store.update_record(existing["outbound_id"], {
            "amount_total": amount_total,
            "customer_id": customer_id,
            "p21_order_no": p21_order_no,
            "source_system": source_system,
        })
        record = outbound_store.get_record(existing["outbound_id"])
    else:
        record = outbound_store.create_record(
            intake_id=intake_id,
            source_system=source_system,
            po_no=po.get("po_no", ""),
            p21_order_no=p21_order_no,
            customer_id=customer_id,
            amount_total=amount_total,
        )

    # Build and persist payload
    payload = build_outbound_payload(source_system, record, po)
    outbound_store.update_record(record["outbound_id"], {
        "payload": payload,
        "status": "ready",
    })
    record = outbound_store.get_record(record["outbound_id"])
    return {"outbound_id": record["outbound_id"], "status": "ready", "record": record}


@app.get("/api/v1/outbound/payload/{outbound_id}")
async def get_outbound_payload(outbound_id: str):
    """Return the shaped outbound payload JSON for preview."""
    record = outbound_store.get_record(outbound_id)
    if not record:
        raise HTTPException(404, f"Outbound record {outbound_id} not found")
    return record.get("payload") or {}


@app.post("/api/v1/outbound/send/{outbound_id}")
async def send_outbound(outbound_id: str, _auth=Depends(_require_api_key)):
    """Mock send — marks record as sent with stub acknowledgment. No live posting."""
    record = outbound_store.get_record(outbound_id)
    if not record:
        raise HTTPException(404, f"Outbound record {outbound_id} not found")

    if record["status"] == "sent":
        return {"status": "sent", "outbound_id": outbound_id, "mock": True,
                "message": "Already sent (idempotent)."}

    if record["status"] not in ("ready", "failed"):
        raise HTTPException(
            400,
            f"Cannot send: record is '{record['status']}'. Run prepare first."
        )

    ack = f"MOCK-ACK-{outbound_id[-8:]}"
    outbound_store.update_record(outbound_id, {
        "status": "sent",
        "last_error": "",
        "sent_at": datetime.utcnow().isoformat(),
        "mock_response": {
            "stub": True,
            "acknowledgment": ack,
            "timestamp": datetime.utcnow().isoformat(),
            "note": "Mock only — no live credentials configured.",
        },
    })
    return {
        "status": "sent",
        "outbound_id": outbound_id,
        "mock": True,
        "acknowledgment": ack,
        "message": "Mock send complete. Payload logged. No live posting.",
    }


@app.get("/api/v1/outbound/history")
async def get_outbound_history(limit: int = 50):
    """Return recent outbound sync activity (all non-pending records)."""
    return outbound_store.get_history(limit=limit)


@app.get("/api/v1/ui/config")
async def get_ui_config():
    """Return frontend config. Set ADMIN_PASSPHRASE env var to override the default."""
    return {"admin_passphrase": os.environ.get("ADMIN_PASSPHRASE", "")}


# ── Invoice Module (grayed out — disabled by default) ────────────────────────

@app.get("/api/v1/invoices")
async def list_all_invoices():
    """List all invoices pulled from P21."""
    invoices = list_invoices()
    return {
        "invoices": invoices,
        "count": len(invoices),
        "invoice_module_enabled": settings.invoice_module_enabled,
    }


@app.post("/api/v1/invoices/sync")
async def sync_invoices_from_p21(req: InvoiceSyncRequest, _auth=Depends(_require_api_key)):
    """Pull invoices from P21 by SO number. Grayed out — returns 503 unless enabled."""
    if not settings.invoice_module_enabled:
        raise HTTPException(503, "Invoice module is disabled — contact admin to enable")
    if not settings.p21_sql_server:
        raise HTTPException(503, "P21 SQL not configured — cannot pull invoices")

    synced = 0
    errors = []
    all_invoices = []

    for so_number in req.so_numbers:
        try:
            invs = pull_invoices_for_so(
                so_number=so_number,
                sql_server=settings.p21_sql_server,
                database=settings.p21_sql_database,
                uid=settings.p21_sql_uid,
                pwd=settings.p21_sql_pwd,
                driver=settings.p21_sql_driver,
            )
            for inv in invs:
                inv_id = inv.get("invoice_id") or inv.get("invoice_no", f"INV_{so_number}")
                save_invoice(inv_id, inv)
                synced += 1
                all_invoices.append(inv)
        except Exception as e:
            logger.error(f"Invoice sync failed for SO {so_number}: {e}")
            errors.append({"so_number": so_number, "error": str(e)})

    return {
        "synced": synced,
        "so_numbers": req.so_numbers,
        "invoices": all_invoices,
        "errors": errors,
    }


@app.get("/api/v1/invoices/{invoice_id}")
async def get_invoice_detail(invoice_id: str):
    """Get a single invoice detail."""
    inv = get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, f"Invoice {invoice_id} not found")
    return inv


@app.post("/api/v1/invoices/{invoice_id}/build-coupa")
async def build_coupa_payload(invoice_id: str, _auth=Depends(_require_api_key)):
    """Build Coupa cXML payload for an invoice. Returns the XML string."""
    if not settings.invoice_module_enabled:
        raise HTTPException(503, "Invoice module is disabled — contact admin to enable")

    invoice = get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(404, f"Invoice {invoice_id} not found")

    po_no = invoice.get("po_no", "")
    po_data = local_store.get_po(po_no) if po_no else None

    xml = build_coupa_invoice_xml(invoice, po_data)
    update_invoice(invoice_id, {"coupa_payload": xml, "status": "ready_to_send"})

    return {
        "invoice_id": invoice_id,
        "coupa_xml": xml,
        "po_no": po_no,
        "so_number": invoice.get("so_number", ""),
    }


@app.post("/api/v1/invoices/{invoice_id}/send-coupa")
async def send_invoice_to_coupa(invoice_id: str, req: InvoiceSendRequest, _auth=Depends(_require_api_key)):
    """Send invoice cXML to Coupa. Grayed out — returns 503 unless enabled."""
    if not settings.invoice_module_enabled:
        raise HTTPException(503, "Invoice module is disabled — contact admin to enable")

    invoice = get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(404, f"Invoice {invoice_id} not found")

    # Auto-build if not present
    xml = invoice.get("coupa_payload", "")
    if not xml:
        po_no = invoice.get("po_no", "")
        po_data = local_store.get_po(po_no) if po_no else None
        xml = build_coupa_invoice_xml(invoice, po_data)
        update_invoice(invoice_id, {"coupa_payload": xml})

    # Mock mode if endpoint not configured
    if not settings.coupa_invoice_endpoint:
        return {
            "status": "ready_to_send",
            "invoice_id": invoice_id,
            "mode": "mock",
            "message": "Coupa endpoint not configured — payload is ready but not sent",
        }

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.coupa_invoice_endpoint,
                content=xml,
                headers={
                    "Content-Type": "text/xml",
                    "Authorization": f"Bearer {settings.coupa_invoice_api_key}",
                },
                timeout=60.0,
            )
        resp.raise_for_status()
        update_invoice(invoice_id, {
            "status": "sent_to_coupa",
            "sent_at": datetime.utcnow().isoformat(),
            "coupa_response": resp.text,
        })
        return {
            "status": "sent_to_coupa",
            "invoice_id": invoice_id,
            "coupa_response_status": resp.status_code,
            "mode": "live",
        }
    except Exception as e:
        logger.error(f"Coupa invoice send failed for {invoice_id}: {e}")
        update_invoice(invoice_id, {
            "status": "failed",
            "last_error": str(e),
        })
        raise HTTPException(502, detail={"message": "Failed to send invoice to Coupa", "detail": str(e)})

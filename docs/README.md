# EnPro PO Agent

**Ariba/Coupa Purchase Order Automation Agent** — Ingests POs from email, matches them to P21 via crosswalk + confidence scoring, and exposes a review portal for human approval before CISM/SO export.

**Current Mode:** CISM Export + P21 Payload Generation (live P21 API submit disabled pending credentials).

---

## What It Does

1. **Email Intake** — Polls `orders@enproinc.com` via Microsoft Graph API for new Ariba/Coupa PO emails
2. **PDF Parsing** — Uses Azure Document Intelligence to extract PO data from PDF attachments
3. **Crosswalk Matching** — Matches customers and items against P21 master data via 6-stage pipeline
4. **Confidence Scoring** — 4-dimension weighted scoring (customer 30%, ship-to 15%, items 45%, dedup 10%)
5. **Review Queue** — Human-in-the-loop approval portal with edit, approve, reject, and rescore
6. **CISM SO Generation** — Approved POs generate P21 CISM Order/Quote Import CSV files
7. **P21 Payload Export** — Also builds Transaction API JSON payloads for future live submit
8. **Learn from Approval** — Approved mappings write back to crosswalk CSVs for auto-learning

---

## Quick Start (Local Windows)

### 1. Prerequisites

- Python 3.11+
- pip
- PowerShell

### 2. Create data directories

```powershell
.\start_local.ps1
```

Or manually:
```powershell
mkdir data\crosswalks, data\cism_output, data\cism_so_output, data\cism_batch, data\po_store, data\p21_data, data\quote_data
```

### 3. Configure environment

Copy `.env.example` to `.env` and fill in secrets as needed. For a **CISM-only local demo**, leave all secrets blank — the app boots and runs with local file storage only.

```powershell
copy .env.example .env
```

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Start the server

```powershell
.\start_local.ps1
```

Or directly:
```powershell
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 6. Open the portal

- **Review Queue:** http://localhost:8000/
- **API Docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

---

## One-PO Demo

Run the standalone demo script to see end-to-end flow without email polling:

```powershell
python demo_approve_one_po.py
```

This will:
1. Find a pending PO in local store
2. Fix customer + item mappings
3. Generate CISM SO CSV files
4. Add to CISM batch
5. Build P21 Transaction API payload
6. Show batch status + file listing

---

## CISM Export Process

### For a Single PO

1. Open **Review Queue** → select a green PO
2. Click **Approve**
3. CISM files generate in `data/cism_so_output/`
4. Files also accumulate in `data/cism_batch/`

### For Batch Export

1. Go to **CISM Batch** tab
2. See accumulated POs + line counts
3. Click **Download Header CSV** + **Download Lines CSV**
4. Upload both files to Azure Blob container `ariba-coupa`
5. P21's scheduled CISM import job picks them up
6. Click **Clear Batch** after upload

### CISM File Locations

| File | Path | Purpose |
|---|---|---|
| Per-PO Header | `data/cism_so_output/ENP_SO_HDR_*.csv` | Single PO header |
| Per-PO Lines | `data/cism_so_output/ENP_SO_LIN_*.csv` | Single PO lines |
| Batch Header | `data/cism_batch/batch_orderquoteheader.csv` | Accumulated headers |
| Batch Lines | `data/cism_batch/batch_orderquoteline.csv` | Accumulated lines |

---

## P21 Transaction API Payload

Every approved PO also generates a P21 Transaction API v2 payload:

- **Single PO download:** `GET /api/v1/p21/payload/{intake_id}/download`
- **Batch download:** `POST /api/v1/p21/payload/batch/download` (merged `Transactions[]`)
- **Template:** `template_verification/p21_payload_template.json`

When P21 API credentials are configured (`P21_BASE_URL`, `P21_API_USERNAME`, `P21_API_PASSWORD`), set `P21_AUTO_SUBMIT_ON_APPROVE=true` to post directly to P21 on approval.

---

## Project Structure

```
EnPro-PO-Agent/
├── server.py                          # FastAPI app — all routes
├── config.py                          # Pydantic settings (.env → env vars)
├── models.py                          # Pydantic data models
├── po_parser.py                       # Ariba/Coupa PO XML parsing
├── cism_generator.py                  # Standalone CISM test generator
├── demo_approve_one_po.py             # One-PO end-to-end demo
├── start_local.ps1                    # Windows startup script
├── requirements.txt                   # Python dependencies
├── .env.example                       # Env var template
│
├── services/
│   ├── intake/
│   │   ├── email_classifier.py        # Classify PO source (Ariba/Coupa)
│   │   └── email_poller.py            # Graph API email polling
│   └── processing/
│       ├── cism_so_generator.py       # CISM CSV generation
│       ├── cism_batch.py              # Batch accumulation + download
│       ├── p21_api_client.py          # P21 Transaction API client
│       ├── customer_crosswalk_engine.py  # 6-stage customer matching
│       ├── confidence_scorer.py       # 4-dimension scoring
│       ├── local_store.py             # File-based PO store
│       ├── crosswalk_learner.py       # Auto-learn from approvals
│       ├── crosswalk_csv_builder.py   # Crosswalk CSV management
│       ├── blob_uploader.py           # Azure Blob upload
│       └── processing_agent.py        # Main processing orchestrator
│
├── static/
│   └── index.html                     # Review portal UI (single file)
│
├── portal/
│   └── review.html                    # Alternative review UI
│
├── sql/
│   ├── crosswalk_seed_items.sql       # Seed item crosswalk data
│   ├── crosswalk_seed_vendors.sql     # Seed vendor crosswalk data
│   ├── staging_schema.sql             # SQL staging schema
│   └── so_pull.sql                    # P21 SO pull query
│
├── test_data/
│   └── sample_po_*.xml                # Sample Ariba/Coupa PO XMLs
│
├── docs/
│   ├── GO_LIVE_CHECKLIST.md           # Production readiness checklist
│   ├── OPERATIONS_RUNBOOK.md          # Daily ops workflow
│   ├── BACKLOG_NEXT.md                # P0/P1/P2 backlog
│   ├── TOOL_CONTRACTS_MAPPING.md      # Mapping suggestion agent contract
│   └── GRAPH_API_SETUP.md             # Graph API setup guide
│
├── azure/
│   ├── container-app.bicep            # Azure Container App Bicep
│   └── containerapp.yaml              # Container App manifest
│
└── scripts/
    ├── deploy_azure.sh                # Azure deploy script
    ├── pull_cism_from_blob.ps1        # Pull CISM from Azure Blob
    └── build_batch_payloads.py        # Batch payload builder
```

---

## Key Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System health + version |
| `/api/v1/intake/poll-now` | POST | Manually poll email for new POs |
| `/api/v1/review/queue` | GET | List POs needing review |
| `/api/v1/review/po/{id}` | GET | Single PO detail |
| `/api/v1/review/po/{id}/approve` | POST | Approve PO → CISM + payload |
| `/api/v1/review/po/{id}/edit` | POST | Edit PO + re-score |
| `/api/v1/review/bulk-approve` | POST | Approve all green POs at once |
| `/api/v1/cism/batch` | GET | Batch status + contents |
| `/api/v1/cism/batch/download/{type}` | GET | Download batch CSV |
| `/api/v1/cism/batch/clear` | POST | Clear batch (archive) |
| `/api/v1/p21/payload/{id}/download` | GET | Download single PO payload JSON |
| `/api/v1/p21/payload/batch/download` | POST | Download merged batch payload |
| `/api/v1/p21/payload/validate/{id}` | POST | Validate PO payload readiness |

---

## Environment Variables

See `.env.example` for full list. Key vars for local demo:

| Variable | Default | Purpose |
|---|---|---|
| `CROSSWALK_DIR` | `./data/crosswalks` | Customer/item crosswalk CSVs |
| `CISM_SO_OUTPUT_DIR` | `./data/cism_so_output` | Per-PO CISM files |
| `CISM_BATCH_DIR` | `./data/cism_batch` | Accumulated batch files |
| `P21_AUTO_SUBMIT_ON_APPROVE` | `false` | Set `true` when P21 API creds live |
| `P21_BASE_URL` | *(empty)* | P21 Transaction API base URL |
| `P21_API_USERNAME` | *(empty)* | P21 API user |
| `P21_API_PASSWORD` | *(empty)* | P21 API password |

---

## Current Status

| Metric | Value |
|---|---|
| Total POs processed | 22+ |
| Auto-green rate | 95% (21/22) |
| CISM generation | ✅ Working |
| P21 payload export | ✅ Working |
| P21 live API submit | ⏳ Pending credentials |
| Email polling | ✅ Graph API connected |
| Azure Blob upload | ✅ Working |
| SQL staging DB | ⏳ Optional |

---

## Next Steps (Backlog)

1. **P0:** Set `APP_API_KEY` and `ADMIN_PASSPHRASE` on production
2. **P1:** Bulk "Approve All Green" button in UI
3. **P1:** Mapping suggestion agent (contract written)
4. **P1:** Disk usage monitoring in `/health`
5. **P2:** Live P21 API submit (requires EnPro IT creds)
6. **P2:** Azure SQL staging DB for audit trail

---

## Deploy Anywhere

See `DEPLOY.md` in the repo root for Docker Compose, Railway, Fly.io, Azure, and VPS instructions.

## Handoff Prompt

See `HANDOFF_PROMPT.md` in the repo root for a quick-start guide to give the next developer.

## Contact

Built by Peter Wilson | pwnetsuite@outlook.com

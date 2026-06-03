# EnPro PO Automation Agent

Automated purchase order processing pipeline for EnPro Industries. Receives POs from **Ariba**, **Coupa**, email attachments (PDF/XML), and direct CSV uploads — parses, matches, scores, and routes them through a human review portal for approval before generating CISM import files for Epicor Prophet 21 (P21).

---

## What It Does

```
Email / Ariba / Coupa PO arrives
        │
        ▼
  Parse (cXML, PDF, CSV)
        │
        ▼
  Customer Crosswalk Match   ← ship-to name + zip → P21 customer ID
        │
        ▼
  Item Crosswalk Match       ← supplier part # → P21 inv_mast_uid
        │
        ▼
  Confidence Score (green / yellow / red)
        │
        ▼
  Review Portal (Brittany approves / rejects)
        │
        ▼
  CISM SO files generated    ← batch_orderquoteheader.csv + _line.csv
        │
        ▼
  P21 Transaction API        ← Sales Order created directly via REST
  (or Azure Blob → SQL Agent job)
```

No LLM involved in the core matching pipeline. Rules-based crosswalk engine against your P21 item master and customer data.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API server | FastAPI (Python) |
| Deployment | Azure Container Apps (Bicep) or Render |
| PDF parsing | Azure Document Intelligence |
| Email polling | Microsoft Graph API (`orders@enproinc.com`) |
| PO store | JSON files on disk (`data/po_store/`) |
| Audit log | SQLite (`data/audit.db`) |
| Crosswalk data | CSV files on persistent disk (`data/crosswalks/`) |
| CISM output | CSV files on persistent disk (`data/cism_so_output/`) |
| Blob sync | Azure Blob Storage (crosswalk CSVs, approved CISM files) |
| Persistent disk | Azure Files mount at `/app/data` |
| P21 integration | P21 Transaction API v2 (REST) + direct ODBC for reads |

---

## Storage Architecture

### How data is stored

```
/app/data/                         ← Azure Files mount (persists across deploys)
  po_store/
    {intake_id}.json               ← one file per processed PO (primary store)
  crosswalks/
    customer_crosswalk.csv         ← ship-to → P21 customer ID mappings
    item_crosswalk.csv             ← supplier part # → P21 item ID mappings
    p21_customers.csv              ← synced from Azure Blob on startup
    p21_items.csv                  ← synced from Azure Blob on startup
  cism_so_output/
    ENP_SO_HDR_*.csv               ← CISM header files ready for P21 import
    ENP_SO_LIN_*.csv               ← CISM line files ready for P21 import
  audit.db                         ← SQLite audit trail of all approvals/rejections
```

### Azure Blob Storage (container: `ariba-coupa`)

```
cism/
  approved/{timestamp}_{po_no}_{intake_id}_{file}   ← approved CISM files
  rejected/{timestamp}_{po_no}_{intake_id}_{file}   ← rejected CISM files
crosswalk/
  p21/customers_latest.csv         ← P21 customer master export
  p21/items_latest.csv             ← P21 item master export
  p21/so_headers_latest.csv        ← P21 SO data for duplicate detection
  p21/so_lines_latest.csv
```

### No Supabase

Zero Supabase references exist in this codebase. The project uses Azure Blob + local disk (Azure Files) as its storage layer.

---

## Confidence Scoring

Every processed PO receives a 4-dimension confidence score:

| Dimension | Green | Yellow | Red |
|---|---|---|---|
| Customer match | ≥ 0.85 | 0.60–0.84 | < 0.60 |
| Ship-to match | ≥ 0.80 | 0.50–0.79 | < 0.50 |
| Item match avg | ≥ 0.75 | 0.40–0.74 | < 0.40 |
| Duplicate check | No dup | — | Duplicate found |

- **Green**: Auto-approved, CISM SO generated, crosswalk updated via learning
- **Yellow / Red**: Queued for human review in the portal

---

## Review Portal

Web UI at `/review` — Brittany (EnPro) uses this to:
- See the pending queue (green/yellow/red)
- Inspect parsed PO details and customer/item matches
- Approve → triggers CISM SO generation + optional P21 API submit
- Reject → logs reason, uploads to rejected blob prefix

---

## Key Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/health` | Health check (P21 status, disk usage) |
| `GET` | `/review` | Review portal UI |
| `GET` | `/test-drive` | Upload a PO, see P21 payload live |
| `GET` | `/micdrop` | Demo page — proves P21 payload is valid |
| `POST` | `/api/v1/intake/cxml` | Receive cXML from Ariba/Coupa |
| `POST` | `/api/v1/intake/upload` | Upload PDF, XML, or CSV PO |
| `POST` | `/api/v1/intake/poll-now` | Trigger immediate email poll |
| `GET` | `/api/v1/review/queue` | Get pending PO queue |
| `POST` | `/api/v1/review/po/{id}/approve` | Approve a PO |
| `POST` | `/api/v1/review/po/{id}/reject` | Reject a PO |
| `GET` | `/api/v1/p21/payload/{id}` | Get P21 Transaction API payload |
| `POST` | `/api/v1/p21/submit/{id}` | Submit PO directly to P21 API |
| `POST` | `/api/v1/p21/payload/batch/download` | Download batch payload JSON |
| `GET` | `/api/v1/crosswalk/sync-from-blob` | Pull latest crosswalk CSVs from blob |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# App
ENVIRONMENT=production
APP_API_KEY=your-secret-key

# Azure Blob Storage
AZURE_BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_BLOB_CONTAINER_NAME=ariba-coupa

# Azure Document Intelligence (PDF parsing)
DOC_INTEL_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
DOC_INTEL_KEY=your-key

# Azure OpenAI (optional — AI-assisted field mapping)
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_KEY=your-key
AZURE_OPENAI_MODEL=gpt-4.1

# Microsoft Graph (email polling from orders@enproinc.com)
GRAPH_CLIENT_ID=your-app-id
GRAPH_CLIENT_SECRET=your-secret
GRAPH_TENANT_ID=your-tenant-id
GRAPH_MAILBOX=orders@enproinc.com

# P21 Transaction API (REST — for SO creation)
P21_BASE_URL=https://192.168.x.x:3333
P21_API_USERNAME=poagent
P21_API_PASSWORD=your-password
P21_AUTO_SUBMIT_ON_APPROVE=false

# P21 SQL (ODBC — for reads, SO pulls, duplicate detection)
P21_SQL_SERVER=your-p21-server
P21_SQL_DATABASE=P21
P21_SQL_UID=readonly_user
P21_SQL_PWD=your-password

# Azure SQL Staging DB (optional)
STAGING_SQL_SERVER=your-azure-sql.database.windows.net

# Persistent disk paths (Azure Files mount or Render disk)
CROSSWALK_DIR=/app/data/crosswalks
CISM_OUTPUT_DIR=/app/data/cism_output
CISM_SO_OUTPUT_DIR=/app/data/cism_so_output
PO_STORE_DIR=/app/data/po_store
```

---

## Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill .env
cp .env.example .env

# 3. Run the server
cd src
uvicorn server:app --reload --port 8000

# Or use the PowerShell helper
.\start_server.ps1
```

The server runs on `http://localhost:8000`. Dashboard at `/`, docs at `/docs`.

---

## Deployment

### Azure Container Apps (production)

```bash
# One-time infra setup
az deployment group create \
  --resource-group your-rg \
  --template-file azure/container-app.bicep

# Deploy (uses render.yaml or azd)
azd up
```

The Bicep template provisions:
- Container App with Azure Files volume mount at `/app/data`
- Managed identity for blob access
- Secrets injected as env vars

See `docs/AZURE_DEPLOY.md` for full walkthrough.

### Render (staging / demo)

```bash
# render.yaml is already configured
# Push to GitHub → Render auto-deploys
# Set env vars in Render dashboard
```

See `docs/RENDER_DEPLOY.md`.

---

## Replacing Azure Files with Supabase

Currently, Azure Files (mounted at `/app/data`) provides the persistent disk that holds the JSON PO store, crosswalk CSVs, CISM output files, and the SQLite audit DB. To migrate to Supabase:

### What needs to change

| Current | Replacement | File to Change |
|---|---|---|
| `data/po_store/*.json` | Supabase PostgreSQL table `po_records` | `services/processing/local_store.py` |
| `data/audit.db` (SQLite) | Supabase PostgreSQL table `audit_log` | `src/server.py` → `_log_audit()` |
| Azure Blob (CISM uploads) | Supabase Storage bucket `cism-files` | `services/processing/blob_uploader.py` |
| Azure Blob (crosswalk sync) | Supabase Storage bucket `crosswalk-data` | `services/processing/blob_uploader.py` → `sync_crosswalks_from_blob()` |
| Azure Files disk mount | Not needed — Supabase handles persistence | `azure/container-app.bicep`, `config.py` |
| `AZURE_BLOB_CONNECTION_STRING` | `SUPABASE_URL` + `SUPABASE_KEY` | `.env`, `config.py` |

### Migration steps

1. **Add Supabase client**: `pip install supabase`

2. **New env vars** in `config.py`:
   ```python
   supabase_url: str = ""
   supabase_key: str = ""   # service role key for server-side writes
   ```

3. **Rewrite `local_store.py`** — replace JSON file reads/writes with Supabase PostgreSQL:
   ```python
   from supabase import create_client
   # save_po() → supabase.table("po_records").upsert(data)
   # get_po()  → supabase.table("po_records").select("*").eq("intake_id", id).single()
   # list_pos() → supabase.table("po_records").select("*").execute()
   ```

4. **Rewrite `blob_uploader.py`** — replace `BlobServiceClient` with Supabase Storage:
   ```python
   # upload_approved_cism() → supabase.storage.from_("cism-files").upload(path, data)
   # sync_crosswalks_from_blob() → supabase.storage.from_("crosswalk-data").download(path)
   ```

5. **Rewrite `_log_audit()`** in `server.py` — replace SQLite with:
   ```python
   supabase.table("audit_log").insert({...}).execute()
   ```

6. **Remove Azure Files** volume from `azure/container-app.bicep` — disk mount is no longer needed.

7. **Keep crosswalk CSVs** in Supabase Storage (same filenames, different bucket) — the crosswalk engine reads them from local disk after sync, so keep the sync pattern but swap the download source.

---

## Project Structure

```
├── src/
│   ├── server.py              ← FastAPI app — all routes (3,500 lines)
│   ├── config.py              ← Pydantic settings (env → typed config)
│   ├── models.py              ← Pydantic models (POPayload, POHeader, etc.)
│   ├── po_parser.py           ← cXML, PDF, CSV parsing
│   └── cism_generator.py      ← CISM batch file generation
├── services/
│   ├── intake/
│   │   ├── email_poller.py    ← Microsoft Graph API email polling
│   │   └── email_classifier.py
│   └── processing/
│       ├── local_store.py     ← JSON file store (primary PO database)
│       ├── blob_uploader.py   ← Azure Blob upload + crosswalk sync
│       ├── customer_crosswalk_engine.py  ← Ship-to → P21 customer matching
│       ├── crosswalk_engine.py           ← Vendor/item crosswalk
│       ├── crosswalk_learner.py          ← Auto-learn from approved POs
│       ├── confidence_scorer.py          ← 4-dimension scoring
│       ├── duplicate_detector.py         ← PO dedup logic
│       ├── p21_api_client.py             ← P21 Transaction API v2 client
│       ├── cism_batch.py                 ← CISM batch management
│       ├── cism_so_generator.py          ← CISM SO file generation
│       └── mapping_suggester.py          ← AI-assisted item mapping
├── data/
│   ├── po_store/              ← Live PO JSON files
│   ├── cism_batch/            ← Staged CISM batch CSVs
│   └── cism_so_output/        ← Generated CISM SO files
├── mcp_server/
│   └── mcp_server.py          ← MCP tool server for Claude integration
├── portal/
│   └── review.html            ← PO review portal frontend
├── static/
│   └── index.html             ← Dashboard frontend
├── docs/                      ← Deployment, setup, operations guides
├── docs_project/              ← SOW, backlog, user guide, handoff docs
├── sql/                       ← P21 SQL reference queries
├── scripts/                   ← Azure deploy, blob pull, batch scripts
├── Dockerfile
├── render.yaml
├── azure/container-app.bicep
└── requirements.txt
```

---

## Data Flow: Email PO Example

1. Email arrives at `orders@enproinc.com` with PDF attachment
2. `email_poller.py` polls via Graph API every 60s (`GRAPH_POLL_INTERVAL`)
3. PDF sent to Azure Document Intelligence → structured header + line items
4. `CustomerCrosswalkEngine` matches ship-to name + zip → P21 customer ID
5. Item engine matches each supplier part # → P21 `inv_mast_uid`
6. `confidence_scorer.py` assigns green / yellow / red
7. PO saved to `data/po_store/{intake_id}.json`
8. Email moved to `Processed-PO` folder in mailbox
9. Brittany reviews in portal at `/review`
10. On approval: CISM SO CSVs generated, uploaded to Azure Blob, optionally submitted to P21 Transaction API

---

## Key Files to Know

| File | Purpose |
|---|---|
| `HANDOFF.md` | Full session context and current state |
| `MASTER_BUILDER_SPEC.md` | Complete feature spec |
| `DATA_ARCHITECTURE_PROPOSAL.md` | Proposed future data architecture |
| `DATA_CATALOG.md` | All fields, tables, CSV schemas |
| `docs_project/05_BRITTANY_USER_GUIDE.md` | End-user guide for EnPro |
| `docs_project/07_REMAINING_WORK.md` | Outstanding backlog |
| `docs/CISM_SETUP_GUIDE.md` | CISM import setup in P21 |
| `sql/P21_SQL_REFERENCE.md` | P21 SQL queries reference |

---

*EnPro PO Agent — built by Peter Wilson / Conveyance365 for EnPro Industries*
*Stack: FastAPI · Azure · P21 Transaction API v2 · Microsoft Graph*

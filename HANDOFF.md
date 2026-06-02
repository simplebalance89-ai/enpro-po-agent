# EnPro PO Agent — Comprehensive Handoff Document

**Date:** 2026-06-01
**Repo:** `Desktop\EnPro-PO-Agent-Ariba-Coupa`
**Built By:** Peter Wilson + AI
**Current Mode:** Payload-Export Only (CISM + downloadable P21 JSON)
**Status:** Production-ready in sandbox mode. Live P21 API submit built but disabled.

---

## 1. Executive Summary

This is an end-to-end Ariba/Coupa Purchase Order automation agent. It polls emails, parses PDF/cXML/CSV POs, matches customers and items to P21 master data via crosswalks, scores confidence, presents a human-in-the-loop review queue, and generates CISM SO import CSVs + P21 Transaction API JSON payloads.

**The big picture:** 22 POs have been ingested. 21 auto-resolved to green (95%). 1 red PO remains (Stepan Chemical, PO 4098053). The system works. The gap between "works in sandbox" and "live production" is env vars and a few ops polish items.

---

## 2. What's Built & Verified Working

### Core Pipeline
- [x] Email intake via Microsoft Graph API (coded, credentials set on Render)
- [x] PDF parsing via Azure Document Intelligence
- [x] cXML parsing (Ariba/Coupa OrderRequest native)
- [x] CSV parsing (direct column mapping)
- [x] Customer crosswalk matching (6-stage pipeline: exact → zip → fuzzy → PO history → quote linkage → guess)
- [x] Item crosswalk matching (22K+ part number → inv_mast_uid mappings)
- [x] 4-dimension confidence scoring (customer 30%, ship-to 15%, items 45%, dedup 10%)
- [x] Review queue with green/yellow/red badges + reason display
- [x] Approve → CISM SO CSV generation + batch accumulation
- [x] Reject with reason
- [x] Edit PO + re-score
- [x] **Bulk Approve Greens** — single button approves all green POs
- [x] **Mapping Suggestion Agent** — assistive, human-in-loop, writes to suggestion log
- [x] Auto-learn from approval → writes back to 3 crosswalk CSVs
- [x] P21 Payload export (single + batch download, checkbox UI)
- [x] Test Drive (`/test-drive`) — drag PDF, instant payload preview
- [x] Mic Drop (`/micdrop`) — animated proof payload is structurally correct
- [x] Outbound sync stubs (mock + live HTTP POST when endpoint provided)
- [x] Invoice module (built, disabled behind `ENABLE_INVOICE_SYNC` env var)
- [x] Local file-based PO store (`/app/data/po_store/`)
- [x] CISM batch accumulation (`/app/data/cism_batch/`)

### Auth & Security (Code Ready, Env Vars May Be Missing)
- [x] API key auth scaffold — `_require_api_key` protects 15+ mutating routes
- [x] Admin passphrase gate for admin-only UI tabs
- [x] CORS middleware configured

### Ops Polish (Just Completed)
- [x] **Disk usage in `/health`** — shows used/free/total MB (2026-06-01)
- [x] **Persist `shipto_score` to PO JSON** — saved in `result_data.customer_match.shipto_score` (2026-06-01)
- [x] **Atomic CISM batch CSV writes** — `_atomic_append_csv()` writes to `.tmp` then `os.replace()` (already implemented)

### Crosswalk Data (Static CSVs)
- [x] Customer crosswalk: 4,880 customer + ship-to combos
- [x] Customer-item crosswalk: 22,675 part number mappings
- [x] PO history: 23,452 PO-to-SO linkages
- [x] Item master: 11,911 unique P21 items
- [x] Customer master: 7,833 customers with addresses
- [x] Dynamics quotes: 2,065 active quotes
- [x] Salespeople: 52 reps with customer assignments

---

## 3. What's Partially Built / Needs Attention

These work but have known limitations:

| Feature | Status | Limitation |
|---|---|---|
| Email polling | Coded, credentials set | Works on Render but `orders@enproinc.com` mailbox access should be verified |
| CISM batch CSV format | Generated correctly | **NOT tested against actual P21 CISM import job** — column order/naming may need adjustment |
| Contact ID in CISM | Blank | Needs default or lookup from P21 |
| Ship To ID in CISM | Blank | Needs P21 `address_id` |
| Terms field in CISM | Blank | Needs P21 `terms_id` lookup |
| Carrier ID in CISM | Blank | Needs P21 carrier lookup |
| Invoice module | Built, disabled | Needs `ENABLE_INVOICE_SYNC=true` + Coupa API key |
| Azure SQL staging | Stub exists | `DATABASE_URL` not set; falls back to local_store (works fine at current volume) |
| Outbound sync | Mock works | Real-send scaffolding accepts `endpoint_url` + `api_key` params but needs testing with real Ariba/Coupa endpoints |
| Dynamics CRM | Static CSV only | Quote data is not live API pull |

---

## 4. What's Missing That Should Have Been Built

These are genuine gaps. Not bugs — missing capabilities that a production system should have.

### 4.1 Authentication & Audit (HIGH)
- **No user management.** Brittany is the only operator now, but there's no concept of users, roles, or sessions.
- **No audit log of who approved/rejected what.** The system records *that* a PO was approved, but not *by whom*.
- **No Azure AD / SSO integration.** For production, this should replace the simple API key + passphrase gates.
- **No session management.** Anyone with the URL and API key has full access.

### 4.2 Real Ariba/Coupa Direct Integration (HIGH)
Current flow: Ariba/Coupa → email → PDF attachment → parse.
This is fragile. Better options exist but are not built:
- Ariba cXML direct POST to webhook endpoint
- Ariba scheduled CSV/Excel export → SFTP or email batch
- Coupa CSP API pull (hourly/daily)
- Coupa cXML webhook
- **Recommended:** Scheduled batch pull from both portals → CSV → agent processes batch. More reliable, catches everything, audit trail.

### 4.3 Azure Blob Automation (HIGH)
- CISM batch files sit on Render disk.
- **Missing:** Automated push of `batch_orderquoteheader.csv` + `batch_orderquoteline.csv` to Azure Blob (`ariba-coupa` container).
- **Missing:** Blob → local machine sync → P21 CISM import folder (`\\P21Server\CISM\Import\Incoming\`).

### 4.4 P21 CISM Import Verification (HIGH)
- Batch CSV format is structurally correct per schema docs.
- **Missing:** Actual test import into P21. This is the #1 risk for "it looks right but P21 rejects it."
- **Missing:** Feedback loop — after CISM import, get the real P21 `order_no` back into the system.

### 4.5 Internal Order Tracking (MEDIUM)
- **Missing:** Internal SO number assignment before P21 creates the order.
- **Missing:** Full lifecycle tracking: PO received → parsed → approved → CISM generated → P21 imported → SO number assigned → invoice synced.

### 4.6 Edit PO — Incomplete (MEDIUM)
- **Missing:** Customer search dropdown (manual ID entry only).
- **Missing:** Ship-to address ID lookup.
- **Missing:** Add/remove line items (can only edit existing lines).
- **Missing:** Re-run full crosswalk after edit (currently just re-scores with existing data).
- **Missing:** Audit trail of edits (who changed what, when).

### 4.7 Crosswalk Improvements (MEDIUM)
- Item master shows NULL descriptions for many items — needs `inv_mast` table pull with `item_id` + `item_desc`.
- Supplier names show IDs, not names — needs vendor table join.
- Customer-item crosswalk doesn't show the P21 `item_id` (part number), only `inv_mast_uid`.
- UOM crosswalk not connected (Ariba UN/CEFACT codes → P21 UOM mapping).
- Price anomaly detection exists in data but is not used in scoring.

### 4.8 Data Refresh (MEDIUM)
- Crosswalk data is static — uploaded once, not refreshed.
- **Missing:** Scheduled re-pull from P21 SQL (daily/weekly).
- **Missing:** Crosswalk merge logic (P21 baseline + learned entries).
- **Missing:** Score decay for stale crosswalk entries.

### 4.9 Monitoring & Alerting (MEDIUM)
- **Missing:** Email polling failure alerts.
- **Missing:** Alert when POs go red (unmatched) — should notify sales rep or Brittany.
- **Missing:** Metrics dashboard (processing time, match rates, approval rates, time-to-approve).
- **Missing:** Log aggregation (currently just stdout on Render).
- **Missing:** Health check for crosswalk staleness.
- **Missing:** CI/CD — no GitHub Actions, no smoke tests on push.

### 4.10 Edge Cases Not Handled (LOW-MEDIUM)
- Multi-company POs (`company_id != 1`)
- International orders (non-US addresses, currency conversion)
- Blanket POs / release orders
- PO amendments (changes to existing POs)
- PO cancellations
- Split shipments
- Back-to-back POs from same customer (batch dedup)
- Non-standard PDF layouts

---

## 5. Next Steps to Hand Off Properly

### Step 1: Resolve the One Red PO (5 minutes)
PO 4098053 (Stepan Chemical) is the only red in the queue.
1. Open Review Queue → Edit PO 4098053
2. Set `customer_id_p21` = `207620`
3. Look up `CS-P0400/3000` in P21 item master; set `item_id_p21` on line 10
4. Save → should turn green
5. Approve → CISM generated

### Step 2: Set Security Env Vars on Hosting Platform
Whether Render, Azure, or another platform — these must be set before production use:
```
APP_API_KEY=<strong-random-string>
ADMIN_PASSPHRASE=<strong-random-string>
```
Without these, 15+ mutating routes are unprotected and the admin UI gate is trivially bypassed.

### Step 3: Test CISM Import Against Real P21 (1-2 hours with IT)
This is the most important validation step:
1. Approve 1-2 low-risk test POs.
2. Download `batch_orderquoteheader.csv` + `batch_orderquoteline.csv` from CISM Batch tab.
3. Hand to EnPro IT — import via P21 CISM job.
4. Review P21 import log for errors.
5. Adjust column mappings, field names, or data types as needed.
6. Document the exact P21 CISM import procedure.

### Step 4: Decide on Hosting
The project is moving away from Render. Options:
- **Azure App Service** (recommended if already in Azure ecosystem)
- **Azure Container Instances** (simpler, good for single-container)
- **Railway / Fly.io / DigitalOcean** (Render alternatives)
- **Self-hosted VM** (most control, most maintenance)

Deployment package needs:
- Dockerfile (already exists)
- `docker-compose.yml` for local dev
- CI workflow (GitHub Actions) for build + test
- Environment variable template for the chosen platform

### Step 5: Azure Blob Integration (if staying on cloud)
Automate the CISM batch → Blob → P21 pipeline:
1. Add Azure Blob push on batch approval.
2. Configure Blob trigger or scheduled job to move files to P21 server.
3. OR: Skip blob and use SFTP/SCP direct to P21 server if network path exists.

### Step 6: Add Audit Logging (before multiple users)
Before Brittany is not the only operator:
1. Add `approved_by`, `rejected_by`, `edited_by` fields to PO records.
2. Store user identity (even if just a name entered at login).
3. Add an audit log table/file with timestamp, action, user, PO ID, before/after values.

### Step 7: Real Ariba/Coupa Integration (medium-term)
Move from email-based intake to direct API/webhook:
1. **Short term:** Scheduled CSV export from Ariba/Coupa → email or SFTP → agent processes batch.
2. **Long term:** Direct API/webhook integration.

### Step 8: Crosswalk Refresh Schedule
1. Set up nightly/weekly job to re-pull from P21 SQL:
   - `inv_mast` (items)
   - `customers` + `ship_to` (addresses)
   - `so_history` (recent PO-to-SO linkages)
2. Merge with learned entries (don't overwrite manual corrections).

---

## 6. Critical Risks & Blockers

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **CISM import fails in real P21** | Unknown (not tested) | High — blocks go-live | Test with 1-2 POs immediately (Step 3 above) |
| **APP_API_KEY not set on host** | High if forgotten | High — open mutating routes | Add to deployment checklist; fail health check if missing |
| **Disk full on host** | Medium over time | High — silent save failures | `/health` now monitors disk; add alert at 80% |
| **Email polling fails silently** | Medium | Medium — POs missed | Add alert if `poll-now` returns 0 emails for >24h |
| **Crosswalk goes stale** | High over months | Medium — match rates drop | Schedule refresh; monitor green rate trend |
| **P21 credentials never provided** | High (by IT) | Blocks Mode 2 (live API submit) | Mode 1 (CISM export) works indefinitely; accept |
| **Ariba/Coupa schema changes** | Low | Medium | Parser is flexible; monitor for parse failures |

---

## 7. Architecture Overview

```
Email Inbox (Graph API) ─┐
                         ├─► Intake ──► Parse ──► Crosswalk Match ──► Score ──► Review Queue
PDF (Doc Intel) ─────────┤                                              │
cXML (webhook/ upload) ──┘                                              ▼
                                                                    [Human decides]
                                                              Approve / Reject / Edit
                                                                   │
                                                          ┌────────┴────────┐
                                                          ▼                 ▼
                                                    CISM SO CSVs      P21 Payload JSON
                                                    (batch accum)     (single + batch DL)
                                                          │
                                                          ▼
                                                    Azure Blob (future)
                                                          │
                                                          ▼
                                                    P21 CISM Import
                                                          │
                                                          ▼
                                                    P21 Sales Order
```

### Key Source Files

| File | Purpose | Lines |
|---|---|---|
| `src/server.py` | FastAPI app — all routes, UI, auth, processing orchestration | ~3,200 |
| `src/models.py` | Pydantic data models (PO, lines, health, responses) | ~220 |
| `src/config.py` | Settings (env vars → Pydantic) | ~80 |
| `src/po_parser.py` | cXML + PDF parsing | ~200 |
| `services/processing/processing_agent.py` | Main processing orchestrator | ~150 |
| `services/processing/customer_crosswalk_engine.py` | 6-stage customer matching | ~300 |
| `services/processing/confidence_scorer.py` | 4-dimension scoring | ~150 |
| `services/processing/cism_so_generator.py` | CISM CSV generation | ~200 |
| `services/processing/cism_batch.py` | Batch accumulation + atomic writes | ~150 |
| `services/processing/p21_api_client.py` | P21 Transaction API client + payload builder | ~250 |
| `services/processing/local_store.py` | File-based PO JSON store | ~200 |
| `services/processing/crosswalk_learner.py` | Auto-learn from approvals | ~100 |
| `services/processing/mapping_suggester.py` | Mapping suggestion agent | ~150 |
| `services/intake/email_poller.py` | Graph API email polling | ~200 |
| `services/intake/email_classifier.py` | Ariba/Coupa/direct detection | ~80 |
| `static/index.html` | Review portal UI (single-page, vanilla JS) | ~3,500 |

### Data Directories

| Path | Contents | Persistence |
|---|---|---|
| `./data/po_store/` | One JSON file per PO | Required |
| `./data/cism_so_output/` | Per-PO CISM header + line CSVs | Required |
| `./data/cism_batch/` | Accumulated batch CSVs | Required |
| `./data/crosswalks/` | Customer + item crosswalk CSVs | Required |
| `./data/outbound/` | Outbound sync payloads | Optional |
| `./data/invoice/` | Invoice records (if enabled) | Optional |

---

## 8. Environment Variables — Complete Reference

### Required for Basic Operation
| Variable | Default | Set? | Notes |
|---|---|---|---|
| `AZURE_TENANT_ID` | — | ✅ | Azure AD tenant |
| `AZURE_CLIENT_ID` | — | ✅ | App registration client ID |
| `AZURE_CLIENT_SECRET` | — | ✅ | App registration secret |
| `GRAPH_TENANT_ID` | — | ✅ | Graph API tenant |
| `GRAPH_CLIENT_ID` | — | ✅ | Graph API client ID |
| `GRAPH_CLIENT_SECRET` | — | ✅ | Graph API secret |
| `GRAPH_MAILBOX` | — | ✅ | Mailbox to poll |
| `DOC_INTEL_ENDPOINT` | — | ✅ | Azure Document Intelligence |
| `DOC_INTEL_KEY` | — | ✅ | Document Intelligence key |
| `AZURE_BLOB_CONNECTION_STRING` | — | ⚠️ | Only if crosswalk sync needed |
| `AZURE_BLOB_CONTAINER_NAME` | `ariba-coupa` | ✅ | Via render.yaml |

### Security (MUST SET)
| Variable | Default | Set? | Notes |
|---|---|---|---|
| `APP_API_KEY` | *(empty)* | ❌ | **CRITICAL** — protects all mutating routes |
| `ADMIN_PASSPHRASE` | *(empty)* | ❌ | **CRITICAL** — replaces hardcoded `enpro-admin` |

### P21 Live Submit (Optional — Mode 2)
| Variable | Default | Set? | Notes |
|---|---|---|---|
| `P21_BASE_URL` | — | ❌ | Blocks live API submit |
| `P21_API_USERNAME` | — | ❌ | Blocks live API submit |
| `P21_API_PASSWORD` | — | ❌ | Blocks live API submit |
| `P21_VERIFY_SSL` | `false` | — | TLS cert verification |
| `P21_DEFAULT_TAKER` | `POAGENT` | — | SO taker code |
| `P21_LOCATION_ID` | `10` | — | Source location |
| `P21_COMPANY_ID` | `1` | — | Company ID |
| `P21_AUTO_SUBMIT_ON_APPROVE` | `false` | — | Skip manual button |

### Optional Features
| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_INVOICE_SYNC` | `false` | Enable invoice module |
| `COUPA_INVOICE_API_KEY` | — | Coupa API key |
| `DATABASE_URL` | — | Azure SQL staging (falls back to local) |
| `CROSSWALK_DIR` | `./data/crosswalks` | Crosswalk CSV path |
| `CISM_SO_OUTPUT_DIR` | `./data/cism_so_output` | Per-PO CISM path |
| `CISM_BATCH_DIR` | `./data/cism_batch` | Batch accumulation path |

---

## 9. Deployment Checklist (For New Host)

- [ ] Copy repo to new location / clone from GitHub
- [ ] Create `data/` subdirectories (`po_store`, `cism_so_output`, `cism_batch`, `crosswalks`)
- [ ] Copy crosswalk CSVs into `data/crosswalks/`
- [ ] Set all Required env vars
- [ ] Set `APP_API_KEY` and `ADMIN_PASSPHRASE`
- [ ] `pip install -r requirements.txt`
- [ ] `uvicorn src.server:app --host 0.0.0.0 --port 8000`
- [ ] `GET /health` returns healthy + disk info
- [ ] `POST /api/v1/intake/poll-now` with `X-API-Key` returns emails processed
- [ ] Review queue loads in UI
- [ ] Approve one test PO → CISM Batch tab shows correct counts
- [ ] Download batch CSVs → validate format
- [ ] (Optional) Set P21 vars → test live submit

---

## 10. Contact

**Peter Wilson** — pwnetsuite@outlook.com  
**Original Repo:** github.com/simplebalance89-ai/enpro-po-agent

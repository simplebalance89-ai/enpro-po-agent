# EnPro PO Agent — Builder Handoff & Scope

**Date:** 2026-06-01  
**Local Server:** http://localhost:8000  
**Status:** Foundation complete. Ready for deployment + dataset optimization pass.

---

## What We Built (Foundation Layer)

This is a working Ariba/Coupa PO automation agent. It's running locally right now. Here's what's live:

### Ingestion
- **Email polling** via Microsoft Graph API → downloads PDF attachments from `orders@enproinc.com`
- **PDF parsing** via Azure Document Intelligence
- **cXML parsing** native Ariba/Coupa `OrderRequest`
- **CSV parser** for direct column-mapped PO files

### Matching & Scoring
- **Customer crosswalk** — 6-stage pipeline (exact name → zip match → fuzzy → PO history → quote linkage → guess)
- **Item crosswalk** — 22,675 part number → `inv_mast_uid` mappings
- **4-dimension confidence scoring** — customer 30%, ship-to 15%, items 45%, dedup 10%
- **Auto-learn** — approved matches write back to crosswalk CSVs

### Review Queue (UI)
- Green/Yellow/Red badges with reasons
- Edit PO + re-score
- Approve → CISM batch
- Reject with reason
- **Bulk Approve Greens** (single button)
- **Mapping Suggestion Agent** (assistive, human-in-loop)

### Export
- CISM SO CSV generation (header + line files)
- CISM batch accumulation (multi-PO into single CSV)
- P21 Transaction API JSON payloads (single + batch download)
- Test Drive (`/test-drive`) — drag PDF, instant preview
- Mic Drop (`/micdrop`) — animated payload proof

### Ops (Just Added)
- Disk usage in `/health` endpoint
- `shipto_score` persists to PO JSON
- Atomic CISM batch CSV writes (tmp + os.replace)

---

## What the Next Builder Needs to Do

### Phase 1: Deploy to Railway / Fly.io / Similar

**Goal:** Get the app running on a hosted platform with persistent storage.

| Step | Action | Notes |
|---|---|---|
| 1.1 | Pick platform (Railway, Fly.io, DigitalOcean, Azure Container Apps) | Railway and Fly.io are closest to Render's simplicity |
| 1.2 | Create Dockerfile or use existing one | `Dockerfile` exists in repo root |
| 1.3 | Set up persistent disk/volume | Need at least 1GB for `data/` directory |
| 1.4 | Create `data/` subdirs on boot | `po_store`, `cism_so_output`, `cism_batch`, `crosswalks` |
| 1.5 | Copy crosswalk CSVs into volume | These are in `data/crosswalks/` locally |
| 1.6 | Set all Required env vars (see table below) | Azure Graph + Doc Intel creds are already working |
| 1.7 | **Set `APP_API_KEY` and `ADMIN_PASSPHRASE`** | Critical — protects 15+ mutating routes |
| 1.8 | Verify `/health` returns OK with disk info | Should show used/free/total MB |
| 1.9 | Verify `/` loads the review queue UI | Single-page app in `static/index.html` |
| 1.10 | Test one email poll + one PO approval end-to-end | Confirm CISM batch accumulates |

### Phase 2: Dataset Optimization (HIGH PRIORITY)

**This is the biggest gap.** The crosswalk data is static and has quality issues. The next builder should focus here.

#### 2.1 Crosswalk Data Quality Issues to Fix

| Issue | Impact | Fix |
|---|---|---|
| Item descriptions are NULL for many items | Operators can't verify item matches | Pull `inv_mast` table from P21: `item_id`, `item_desc`, `item_cost` |
| Supplier names show IDs, not names | Hard to verify vendor mappings | Join `vendor` table: `vendor_id`, `vendor_name` |
| Customer-item crosswalk only has `inv_mast_uid`, not P21 part number | Operators see internal IDs, not familiar part numbers | Add `item_id` (P21 part number) to crosswalk display |
| UOM not mapped | Ariba sends UN/CEFACT codes, P21 uses internal UOM IDs | Build UOM crosswalk: `UN-CEFACT-code` → `P21_uom_id` |
| Price anomaly detection exists but unused | Could catch POs with wrong pricing | Wire historical price bounds into confidence scorer |
| Crosswalks are static, never refreshed | Match rates decay over time | Schedule nightly/weekly re-pull from P21 |

#### 2.2 Recommended Data Refresh Architecture

```
P21 SQL Server ──► Scheduled Job (nightly) ──► Export CSVs ──►
    inv_mast                                    items.csv
    customers                                   customers.csv
    ship_to                                     ship_tos.csv
    so_hdr + so_line                            po_history.csv
    vendor                                      vendors.csv
                                              ▼
                                    Agent crosswalk loader
                                    - Load baseline from P21
                                    - Merge learned entries (higher priority)
                                    - Don't overwrite manual corrections
                                    - Update timestamp on each file
```

**Key rule for merge:** Learned entries (from operator approvals) win over P21 baseline. Manual operator edits win over everything. Log every override.

#### 2.3 Data Volume Metrics (Current)

| Dataset | Count | Growth Rate |
|---|---|---|
| Customer crosswalk | 4,880 | Low — new customers occasionally |
| Customer-item crosswalk | 22,675 | Medium — new parts per customer |
| PO history | 23,452 | High — every new PO adds linkage |
| Item master | 11,911 | Low — new items occasionally |
| Customer master | 7,833 | Low — new customers occasionally |
| Dynamics quotes | 2,065 | Medium — quotes expire, new ones created |

**Recommendation:** Refresh item master and customer master weekly. Refresh PO history daily (this is the most valuable for matching). Quotes weekly.

### Phase 3: CISM Import Validation

**Goal:** Prove the generated CSVs actually work in P21.

| Step | Action |
|---|---|
| 3.1 | Approve 1-2 low-risk test POs locally |
| 3.2 | Download `batch_orderquoteheader.csv` + `batch_orderquoteline.csv` |
| 3.3 | Hand to EnPro IT — run through P21 CISM import job |
| 3.4 | Review P21 import log for errors |
| 3.5 | Fix any column mapping, field name, or data type issues |
| 3.6 | Document exact P21 CISM import procedure for Brittany |

**Known blank fields that may need P21 lookups:**
- `contact_id` — needs default or customer contact lookup
- `ship_to_id` — needs P21 `address_id` for the ship-to address
- `terms_id` — needs P21 terms code lookup
- `carrier_id` — needs P21 carrier lookup

### Phase 4: Security & Auth (Before Multi-User)

| Step | Action |
|---|---|
| 4.1 | Confirm `APP_API_KEY` is set and all mutating routes return 403 without it |
| 4.2 | Confirm `ADMIN_PASSPHRASE` is set and replaces hardcoded `enpro-admin` |
| 4.3 | Add `approved_by`, `rejected_by`, `edited_by` fields to PO records |
| 4.4 | Add audit log: timestamp, action, user identity, PO ID, before/after values |
| 4.5 | (Future) Replace API key auth with Azure AD SSO |

### Phase 5: Monitoring & Alerting

| Step | Action |
|---|---|
| 5.1 | Alert if disk usage > 80% |
| 5.2 | Alert if email poll returns 0 emails for > 24 hours |
| 5.3 | Alert if green match rate drops below 90% (crosswalk staleness signal) |
| 5.4 | Track metrics: processing time, match rates, approval rates, time-to-approve |
| 5.5 | Add CI smoke test (GitHub Actions: `pip install` → `import server` → basic pytest) |

---

## Environment Variables — Set These on the New Host

### Must Have (Already Working on Current Setup)
```
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
GRAPH_TENANT_ID=
GRAPH_CLIENT_ID=
GRAPH_CLIENT_SECRET=
GRAPH_MAILBOX=orders@enproinc.com
DOC_INTEL_ENDPOINT=
DOC_INTEL_KEY=
AZURE_BLOB_CONTAINER_NAME=ariba-coupa
```

### Must Have (Security — CRITICAL)
```
APP_API_KEY=<generate strong random string>
ADMIN_PASSPHRASE=<generate strong random string>
```

### Optional (P21 Live Submit — Future)
```
P21_BASE_URL=https://<your-p21-server>:3333
P21_API_USERNAME=
P21_API_PASSWORD=
P21_AUTO_SUBMIT_ON_APPROVE=false
```

### Optional (Invoice Module — Future)
```
ENABLE_INVOICE_SYNC=false
COUPA_INVOICE_API_KEY=
```

---

## Dataset Optimization Checklist

- [ ] Pull `inv_mast` from P21 → add `item_desc` to item master crosswalk
- [ ] Pull `vendor` from P21 → add `vendor_name` to customer crosswalk
- [ ] Add `item_id` (P21 part number) to customer-item crosswalk display
- [ ] Build UOM mapping table (Ariba UN/CEFACT → P21 internal UOM)
- [ ] Wire price anomaly detection into confidence scorer
- [ ] Set up nightly refresh job for PO history (`so_hdr` + `so_line`)
- [ ] Set up weekly refresh job for item master + customer master
- [ ] Implement merge logic: learned > manual > P21 baseline
- [ ] Add crosswalk freshness timestamp to `/health`
- [ ] Alert when crosswalk files are > 7 days old

---

## Files to Know

| File | What It Does |
|---|---|
| `src/server.py` | Main FastAPI app — all routes, ~3,200 lines |
| `src/models.py` | Pydantic data models |
| `services/processing/customer_crosswalk_engine.py` | 6-stage customer matching — optimize here |
| `services/processing/confidence_scorer.py` | Scoring logic — add price anomaly here |
| `services/processing/crosswalk_learner.py` | Auto-learn from approvals — merge logic here |
| `services/processing/local_store.py` | File-based PO storage |
| `services/processing/cism_batch.py` | Batch accumulation |
| `static/index.html` | Review queue UI |
| `data/crosswalks/` | All crosswalk CSVs — the dataset |

---

## The One Red PO to Resolve

**PO 4098053** — Stepan Chemical
1. Open Review Queue → Edit PO
2. Set `customer_id_p21` = `207620`
3. Set line 10 `item_id_p21` = `CS-P0400/3000` (look up in P21 item master)
4. Save → should turn green
5. Approve → generates CISM

---

## Contact

**Peter Wilson** — pwnetsuite@outlook.com  
**Original Repo:** github.com/simplebalance89-ai/enpro-po-agent

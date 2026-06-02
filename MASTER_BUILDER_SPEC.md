# EnPro PO Agent — Master Builder Specification

**Date:** 2026-06-01  
**Status:** Foundation complete. Deep audit done. Ready for builder handoff.  
**Local Server:** http://localhost:8000  

---

## 0. The Mission (What We're Building)

**End-to-end flow:**
```
Email Inbox (orders@enproinc.com)
    │  Microsoft Graph API polls every 60s
    ▼
PDF Attachment Download
    │  Azure Document Intelligence parses PDF
    │  OR cXML parsed natively
    ▼
Structured PO Object (POPayload)
    │
    ├─► Customer Matching (6-stage crosswalk)
    ├─► Item Matching (4-stage crosswalk per line)
    ├─► Confidence Scoring (4-dimension weighted)
    ├─► Deduplication Check
    ▼
Review Queue (Green / Yellow / Red)
    │  Human approves, rejects, or edits
    ▼
Approved PO
    │
    ├─► CISM SO CSV Generation (per-PO + batch accumulation)
    ├─► P21 Transaction API JSON Payload (single + batch)
    ├─► Auto-Learn → writes back to crosswalk CSVs
    ▼
Batch Export → P21 CISM Import OR Live API Submit
```

**The data is the brain.** 4,880 customers, 22,675 item mappings, 23,452 PO histories. This is what gives the 95% auto-green rate. **The builder's #1 priority is protecting and optimizing this data layer.**

---

## 1. WHAT WE BUILT (Foundation Verified Working)

### 1.1 Email Intake — `services/intake/email_poller.py`
- **Microsoft Graph API** polls `orders@enproinc.com` every 60s
- OAuth2 client-credentials flow with token caching (5-min buffer)
- Classifies emails as Ariba/Coupa/direct via regex
- Downloads PDF/XML attachments (base64 inline or `$value` endpoint)
- Moves processed emails to `Processed-PO` folder

### 1.2 Parsing — `src/po_parser.py`
- **PDF:** Azure Document Intelligence `prebuilt-invoice` model
- **cXML:** Native Ariba/Coupa `OrderRequest` parsing (comprehensive field extraction)
- **CSV:** Flexible column-name aliases
- Outputs: `POHeader` + `list[POLineItem]` + raw text

### 1.3 Matching Engine — `services/processing/customer_crosswalk_engine.py`
- **Customer:** 6-stage cascade (learned exact → exact name+zip → fuzzy → PO pattern → best fuzzy → none)
- **Item:** 4-stage cascade (customer-specific part → global part → direct item master → fuzzy description)
- **Fuzzy:** Pure Python (`difflib.SequenceMatcher` + Jaccard token overlap)
- **Price validation:** Historical min/max bounds with margin

### 1.4 Confidence Scoring — `services/processing/confidence_scorer.py`
- Customer 30%, Ship-to 15%, Items 45%, Dedup 10%
- Green ≥ 0.88 + customer green + zero red lines
- Yellow ≥ 0.60 + customer not red + ≤1 red line
- Red otherwise

### 1.5 Review Queue — `static/index.html`
- Single-page vanilla JS app
- Green/Yellow/Red filters with reason badges
- Edit PO with customer/item dropdowns
- Approve → CISM + batch + learn
- Reject with reason
- Bulk Approve Greens
- Mapping Suggestion Agent (assistive)

### 1.6 P21 Output Generation
- **CISM per-PO:** `cism_so_generator.py` — 75-column header + 40-column line CSVs
- **CISM batch:** `cism_batch.py` — accumulated batch CSVs
- **P21 API payload:** `p21_api_client.py` — Transaction API v2 JSON (built, disabled by default)
- **Test Drive:** `/test-drive` — drag PDF, instant preview
- **Mic Drop:** `/micdrop` — structural validation proof

### 1.7 Auto-Learn Loop — `services/processing/crosswalk_learner.py`
- Green POs auto-write to 3 crosswalk CSVs
- Customer crosswalk: UPSERT by (normalized name, zip5)
- Item crosswalk: UPSERT by (customer_id, part_number)
- PO history: append-only
- Engine invalidation on write (forces reload)

---

## 2. CRITICAL BUGS FOUND (Fix Before Anything Else)

These are not nice-to-haves. These are production killers.

### 🔴 BUG-1: CISM Batch Schema Mismatch
**File:** `services/processing/cism_batch.py`  
**What:** Batch accumulator writes 27 header + 15 line columns. Per-PO generator writes 75 + 40 columns.  
**Why it kills:** If P21 CISM import expects the full schema, the batch file will fail or map wrong columns.  
**Fix:** Align batch columns with generator, or better: share a single schema definition.

### 🔴 BUG-2: CISM Batch Race Condition
**File:** `services/processing/cism_batch.py`  
**What:** `_atomic_append_csv` reads entire file → appends → writes temp → os.replace. Two concurrent approvals both read same original, append their rows, second `os.replace` overwrites first. **Data loss.**  
**Why it kills:** Under Uvicorn with multiple workers, simultaneous approvals silently lose POs from the batch.  
**Fix:** Add file locking (lockfile) OR replace CSV batch with SQLite table.

### 🔴 BUG-3: PO Store Non-Atomic Writes
**File:** `services/processing/local_store.py`  
**What:** `save_po` and `update_po` write JSON directly. Crash mid-write = corrupt file.  
**Why it kills:** Power loss or container restart during approval = lost PO data.  
**Fix:** Temp-file + `os.replace` pattern (same as CISM batch attempted).

### 🔴 BUG-4: Crosswalk CSV Race Condition
**File:** `services/processing/crosswalk_learner.py`  
**What:** `learn_from_approval()` reads entire CSV, modifies, rewrites. No file locking. Two concurrent green approvals = one clobbers the other.  
**Why it kills:** Learned mappings get lost. Crosswalk degrades over time.  
**Fix:** Serialize learning via queue OR move to SQLite with `INSERT ... ON CONFLICT`.

### 🔴 BUG-5: `processed_ids` in Email Poller is Memory-Only
**File:** `services/intake/email_poller.py`  
**What:** `EmailPoller.processed_ids` is an in-memory `set()`. Restart = re-process all emails in last 24h.  
**Why it kills:** Container restart on Render/Railway = duplicate POs, wasted Doc Intelligence quota, confused operators.  
**Fix:** Persist `last_processed_datetime` to disk/DB. Use Graph API delta queries.

### 🔴 BUG-6: No Retry Logic Anywhere in Email Pipeline
**File:** `services/intake/email_poller.py`  
**What:** Zero retries on OAuth, message fetch, attachment download, move. One transient network blip = lost PO.  
**Why it kills:** Real-world email pipelines fail constantly. No retries = silent data loss.  
**Fix:** Exponential backoff with jitter for all Graph API calls. Respect `Retry-After` on 429.

### 🔴 BUG-7: `taker` Set to Filesystem Path
**File:** `src/server.py` line ~963  
**What:** `taker=settings.cism_output_dir` passes `/app/data/cism_so_output` into the CISM `Taker` column.  
**Why it kills:** P21 will try to use a filesystem path as a taker code. Import will fail or create garbage data.  
**Fix:** Use `settings.p21_default_taker` ("SYSTEM" or "POAGENT").

### 🔴 BUG-8: `Required Date` Blank in Batch
**File:** `services/processing/cism_batch.py` line ~138  
**What:** `"Required Date": ""` hardcoded instead of mapping `line.get("required_date")`.  
**Why it kills:** All batch line items have blank required dates. P21 may default to today or error.  
**Fix:** Map the actual required date from the PO line.

### 🟡 BUG-9: Fabricated `shipto_score` on Manual Edit
**File:** `src/server.py` line ~2082  
**What:** Manual PO edit computes `ship_score = cust_score * 0.95` instead of actual address matching.  
**Why it hurts:** Ship-to confidence becomes meaningless for edited POs. Can't trust the score.  
**Fix:** Re-run `composite_address_score()` against crosswalk on edit.

### 🟡 BUG-10: Price Stats Never Recalculated on Update
**File:** `services/processing/crosswalk_learner.py`  
**What:** On item crosswalk update, only `unit_price_last` is updated. `min`, `max`, `avg` keep their initial values forever.  
**Why it hurts:** Price anomaly detection uses stale bounds. False positives or missed anomalies.  
**Fix:** Recompute running min/max/avg when `seen_count` increments.

---

## 3. ARCHITECTURE GAPS (Missing Pieces)

### 3.1 Data Layer — Flat Files Don't Scale
**Current:** JSON per PO, CSV crosswalks loaded into memory, full scans on every request.  
**Gap:** At ~1,000 POs, `list_pos()` reads 1,000 JSON files per queue load. At 10K POs, the UI becomes unusable.  
**Fix:** SQLite for PO store + audit log. DuckDB for crosswalk queries. See `DATA_ARCHITECTURE_PROPOSAL.md`.

### 3.2 No Idempotency on P21 API Calls
**Current:** If network times out after P21 creates SO but before response reaches agent, re-approval creates duplicate order.  
**Gap:** No idempotency key sent to P21. No "submitting" lock in local store.  
**Fix:** Send deterministic key (`po_no + "_" + intake_id`) or maintain submit state locally.

### 3.3 No Audit Trail of Human Actions
**Current:** System records THAT a PO was approved, but not BY WHOM or WHAT CHANGED.  
**Gap:** No `approved_by`, `rejected_by`, `edited_by` fields. No before/after values.  
**Fix:** Add audit log table (SQLite): timestamp, user, action, PO ID, field, old_value, new_value.

### 3.4 No Monitoring or Alerting
**Current:** `/health` returns disk usage. No alerts.  
**Gap:** No email on poll failure. No alert when green rate drops. No metrics on processing time.  
**Fix:** Add thresholds to `/health` (degraded status). Log structured metrics. Alert on anomalies.

### 3.5 Email Pipeline Missing Production Hardening
**Current:** Works for demo. Missing: retry, rate-limit handling, large-file protection, dead-letter folder.  
**Gap:** See Email Intake Audit — 7 critical production gaps.  
**Fix:** See Email Intake Audit recommendations P0-P2.

### 3.6 PDF Parser Uses Invoice Model for POs
**Current:** `prebuilt-invoice` model extracts PO fields by treating them as invoice fields.  
**Gap:** Non-standard PO layouts fail silently. Fields come back empty.  
**Fix:** Consider custom Document Intelligence model trained on actual EnPro POs. Add OCR fallback.

### 3.7 Crosswalk Data Quality Issues
**Current:** Item descriptions NULL, supplier names show IDs, no UOM mapping, no price anomaly usage.  
**Gap:** Operators can't verify matches. System can't catch pricing errors.  
**Fix:** Pull `inv_mast`, `vendor` tables from P21. Build UOM crosswalk. Wire price bounds into scorer.

### 3.8 Stale Crosswalks
**Current:** Crosswalk data uploaded once, never refreshed. `last_seen` written but never read.  
**Gap:** Match rates degrade over time. New customers/parts not auto-added.  
**Fix:** Nightly refresh job from P21 SQL. Recency weighting in scoring. Prune inactive entries.

---

## 4. WHY PO 4098053 WENT RED (Case Study)

**PO:** 4098053 — Stepan Chemical  
**Ship-to:** "Matt Stolar" (person's name, not company)  
**Part:** `CS-P0400/3000` (in description, not supplier_part_id field)

**What failed:**
1. **Customer Stage 1 (learned):** No `source_customer_id` match
2. **Customer Stage 2 (exact name+zip):** "Matt Stolar" ≠ "Stepan Chemical" — no match
3. **Customer Stage 3 (fuzzy):** Top candidate was Stepan Chemical at **0.553** — **below 0.65 return threshold**
4. **Customer Stage 4 (PO pattern):** PO 4098053 not in history
5. **Result:** `match_method="none"`, `match_score=0`, customer = RED

6. **Item Stage 1 (customer-specific part):** `supplier_part_id` was blank
7. **Item Stage 4 (fuzzy desc):** "CS-P0400/3000" might have matched, but customer was already red
8. **Result:** PO = RED

**Root cause:** Ship-to was a person's name. No buyer-email/domain heuristic to bridge personal names to company accounts. Fuzzy threshold 0.65 was too rigid for this near-miss.

**How to fix this class of problem:**
- Add buyer-email/domain heuristic: if `@stepan.com` is known domain → boost Stepan Chemical candidates
- Lower fuzzy return threshold from 0.65 to 0.55 (with confirmation)
- Add yellow customer state for 0.55-0.65 range (currently discarded entirely)

---

## 5. PRIORITIZED BUILDER CHECKLIST

### P0 — Fix Before Any New Features (Production Killers)

| # | Task | File(s) | Why |
|---|------|---------|-----|
| 0.1 | Fix CISM batch schema mismatch | `cism_batch.py`, `cism_so_generator.py` | Batch file may fail P21 import |
| 0.2 | Fix CISM batch race condition | `cism_batch.py` | Concurrent approvals lose data |
| 0.3 | Make PO store writes atomic | `local_store.py` | Crash = corrupt PO data |
| 0.4 | Add file locking to crosswalk learner | `crosswalk_learner.py` | Concurrent greens clobber each other |
| 0.5 | Persist email poll watermark | `email_poller.py` | Restart = duplicate POs |
| 0.6 | Add retry logic to Graph API | `email_poller.py` | Transient failures = lost POs |
| 0.7 | Fix `taker` = filesystem path bug | `server.py` ~L963 | P21 import will fail |
| 0.8 | Fix batch `Required Date` blank | `cism_batch.py` ~L138 | All batch lines missing dates |

### P1 — Harden the Data Layer (High ROI)

| # | Task | File(s) | Why |
|---|------|---------|-----|
| 1.1 | Add SQLite PO store (dual-write with JSON) | New `sqlite_store.py` | Queryable, indexed, atomic |
| 1.2 | Add audit log table in SQLite | New `sqlite_store.py` | Track who did what |
| 1.3 | Add SQLite CISM batch table | New `sqlite_store.py` | Concurrent-safe, no CSV races |
| 1.4 | Add DuckDB for crosswalk queries | New `duckdb_engine.py` | Fast fuzzy matching, no full reloads |
| 1.5 | Add crosswalk versioning (backup before overwrite) | `crosswalk_learner.py` | Bad refresh = rollback |
| 1.6 | Add disk-space threshold alert in `/health` | `server.py` | Prevent silent failures |
| 1.7 | Fix `shipto_score` on manual edit | `server.py` ~L2082 | Accurate confidence scores |
| 1.8 | Fix price stats recalculation | `crosswalk_learner.py` | Accurate price anomaly detection |

### P2 — Match Quality Improvements (Push Green Rate to 98%+)

| # | Task | File(s) | Why |
|---|------|---------|-----|
| 2.1 | Add buyer-email/domain heuristic | `customer_crosswalk_engine.py` | Fix person-name ship-tos |
| 2.2 | Lower fuzzy threshold + add yellow state | `customer_crosswalk_engine.py`, `confidence_scorer.py` | Catch near-misses |
| 2.3 | Add recency weighting to crosswalk scoring | `customer_crosswalk_engine.py` | Prevent stale data matches |
| 2.4 | Replace `difflib` with `rapidfuzz` | `customer_crosswalk_engine.py` | 10-100x faster, better accuracy |
| 2.5 | Fix item fuzzy desc cap (0.80 → 0.90) | `customer_crosswalk_engine.py` | Description-only POs unfairly yellow |
| 2.6 | Add `is_active` filter to matching | `customer_crosswalk_engine.py` | Skip inactive customers |
| 2.7 | Index customer_items by part number | `customer_crosswalk_engine.py` | O(1) vs O(n) lookups |

### P3 — Production Deployment (Railway / Fly.io / Azure)

| # | Task | File(s) | Why |
|---|------|---------|-----|
| 3.1 | Create `docker-compose.yml` for local dev | New file | Easy local testing |
| 3.2 | Add CI smoke test (GitHub Actions) | `.github/workflows/` | Catch bad deploys |
| 3.3 | Set `APP_API_KEY` and `ADMIN_PASSPHRASE` on host | Env vars | Secure mutating routes |
| 3.4 | Add P21 connectivity health check on startup | `p21_api_client.py` | Fail fast if P21 unreachable |
| 3.5 | Add idempotency keys for P21 API | `p21_api_client.py`, `server.py` | Prevent duplicate SOs |
| 3.6 | Add retry + circuit breaker for P21 API | `p21_api_client.py` | Resilience against P21 outages |
| 3.7 | Test CISM import against real P21 | Manual with IT | Validate column mappings |
| 3.8 | Document exact P21 CISM import procedure | `docs/` | For Brittany/ops team |

### P4 — Data Refresh & Quality (Ongoing)

| # | Task | File(s) | Why |
|---|------|---------|-----|
| 4.1 | Pull `inv_mast` from P21 → add item descriptions | Data refresh job | Operators can verify items |
| 4.2 | Pull `vendor` table → add vendor names | Data refresh job | Human-readable crosswalk |
| 4.3 | Build UOM mapping (Ariba UN/CEFACT → P21) | New mapping file | Correct units in CISM |
| 4.4 | Wire price anomaly detection into scorer | `confidence_scorer.py` | Catch wrong pricing |
| 4.5 | Scheduled nightly crosswalk refresh from P21 | New refresh job | Keep data current |
| 4.6 | Add crosswalk freshness to `/health` | `server.py` | Alert when data is stale |

---

## 6. FILE INVENTORY FOR BUILDER

| File | What It Does | Lines | Status |
|------|-------------|-------|--------|
| `src/server.py` | FastAPI app — all routes, UI, auth, orchestration | ~3,200 | ⚠️ Contains bugs |
| `src/models.py` | Pydantic data models | ~220 | ✅ Clean |
| `src/config.py` | Settings (env vars → Pydantic) | ~80 | ✅ Clean |
| `src/po_parser.py` | PDF (Doc Intel) + cXML + CSV parsing | ~200 | ⚠️ Invoice model for POs |
| `services/intake/email_poller.py` | Graph API polling + download | ~390 | ⚠️ Missing retries |
| `services/intake/email_classifier.py` | Regex email classification | ~170 | ✅ Simple, works |
| `services/processing/processing_agent.py` | Orchestrator | ~150 | ✅ Clean |
| `services/processing/customer_crosswalk_engine.py` | 6-stage customer + 4-stage item matching | ~300 | ⚠️ Needs rapidfuzz |
| `services/processing/confidence_scorer.py` | 4-dimension scoring | ~150 | ✅ Clean |
| `services/processing/cism_so_generator.py` | Per-PO CISM CSV (75+40 cols) | ~200 | ✅ Clean |
| `services/processing/cism_batch.py` | Batch accumulator (27+15 cols) | ~150 | 🔴 Schema mismatch + race |
| `services/processing/p21_api_client.py` | P21 Transaction API client | ~250 | ✅ Built, disabled |
| `services/processing/local_store.py` | File-based PO JSON store | ~200 | 🔴 Non-atomic writes |
| `services/processing/crosswalk_learner.py` | Auto-learn from approvals | ~100 | 🔴 Race condition |
| `services/processing/mapping_suggester.py` | Mapping suggestion agent | ~150 | ✅ Works |
| `services/processing/duplicate_detector.py` | Deduplication | ~120 | ✅ Clean |
| `services/processing/blob_uploader.py` | Azure Blob sync | ~150 | ✅ Works |
| `static/index.html` | Review portal UI | ~3,500 | ✅ Works |
| `Dockerfile` | Container build | ~30 | ✅ Works |
| `requirements.txt` | Python deps | ~40 | ✅ Works |

---

## 7. ENVIRONMENT VARIABLES — COMPLETE REFERENCE

### Required (Already Working)
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

### Security (MUST SET on new host)
```
APP_API_KEY=<strong-random-string>
ADMIN_PASSPHRASE=<strong-random-string>
```

### P21 Live Submit (Optional)
```
P21_BASE_URL=https://<your-p21-server>:3333
P21_API_USERNAME=
P21_API_PASSWORD=
P21_AUTO_SUBMIT_ON_APPROVE=false
P21_VERIFY_SSL=false
P21_DEFAULT_TAKER=SYSTEM
P21_LOCATION_ID=10
P21_COMPANY_ID=1
```

### Paths (All configurable)
```
PO_STORE_DIR=./data/po_store
CROSSWALK_DIR=./data/crosswalks
CISM_SO_OUTPUT_DIR=./data/cism_so_output
CISM_BATCH_DIR=./data/cism_batch
OUTBOUND_STORE_DIR=./data/outbound_store
```

### Optional Features
```
ENABLE_INVOICE_SYNC=false
COUPA_INVOICE_API_KEY=
DATABASE_URL=                    # Azure SQL staging (falls back to local)
POLL_INTERVAL=60                 # Email poll seconds
```

---

## 8. THE ONE RED PO — RESOLVE THIS FIRST

**PO 4098053** — Stepan Chemical  
**Why red:** Ship-to was "Matt Stolar" (person's name). Fuzzy score 0.553 — below 0.65 threshold. Part ID blank.

**How to resolve:**
1. Open Review Queue → Edit PO 4098053
2. Set `customer_id_p21` = `207620`
3. Set line 10 `item_id_p21` = `CS-P0400/3000` (look up in P21 item master)
4. Save → should turn green
5. Approve → CISM generated

**How to prevent this class of problem:**
- Add buyer-email/domain heuristic (P2.1 above)
- Lower fuzzy threshold to 0.55 (P2.2 above)

---

## 9. DATA ARCHITECTURE DECISIONS (We Need to Decide Together)

### Decision 1: Master Data Store — CSV vs SQLite vs PostgreSQL

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Keep CSVs** | Human-readable, Brittany edits directly, simple | Slow, no transactions, no indexing, race conditions | ❌ Not for PO store |
| **SQLite** | Zero setup, ACID, indexed, Python built-in | Single-writer limits, no replication | ✅ For PO store + audit + batch |
| **PostgreSQL** | Full production DB, replication, monitoring | Requires server/managed service, more complex | ✅ For production scale |
| **DuckDB** | Fast analytical queries, reads CSVs directly | Read-optimized, not for high-frequency writes | ✅ For crosswalk queries |

**Our recommendation:**
- **PO Store → SQLite now** (single file, atomic, queryable)
- **Crosswalk Queries → DuckDB now** (keep CSVs as source, query via DuckDB)
- **PostgreSQL later** when multi-instance or BI needs arise

### Decision 2: Crosswalk Refresh — Who Owns the Master?

| Option | Pros | Cons |
|--------|------|------|
| **CSV is master, DB is cache** | Brittany can edit CSVs directly | Two sources of truth, sync complexity |
| **DB is master, CSV is export** | Single source of truth | Non-technical users can't edit directly |

**Our recommendation:** CSV remains master for now (Brittany's workflow). DuckDB reads CSVs directly with zero import step. When we move to PostgreSQL, we'll build an admin UI for edits.

### Decision 3: Batch Accumulation — CSV vs SQLite

| Option | Pros | Cons |
|--------|------|------|
| **Keep CSV batch** | Simple, Brittany can open in Excel | Race conditions, schema drift |
| **SQLite batch table** | Atomic, concurrent-safe, queryable | Need to export to CSV for download |

**Our recommendation:** SQLite batch table. Export to CSV only on download request. Eliminates all race conditions.

---

## 10. CONTACT

**Peter Wilson** — pwnetsuite@outlook.com  
**Original Repo:** github.com/simplebalance89-ai/enpro-po-agent  
**This Audit:** Generated 2026-06-01 by multi-agent deep-dive of all subsystems.

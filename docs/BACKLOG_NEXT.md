# Backlog — EnPro PO Agent Next Steps

**Updated:** 2026-04-21
**Current mode:** Payload-Export Only (live P21 submit disabled)
**Repo:** simplebalance89-ai/enpro-po-agent — branch `master`

---

## P0 — Now (blocking production trust)

### 1. Set `APP_API_KEY` on Render
**Why it matters:** 9 mutating routes (approve, reject, edit, prepare, send, etc.) are currently open to unauthenticated callers. Code is deployed and correct — only the env var is missing.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- `APP_API_KEY` env var set in Render dashboard → auto-redeploy completes
- `POST /api/v1/outbound/prepare/{id}` without header returns `403`
- Same request with `X-API-Key: <value>` returns `200`

---

### 2. Set `ADMIN_PASSPHRASE` on Render
**Why it matters:** UI admin gate falls back to hardcoded `enpro-admin` — anyone who reads the JS source can enter admin mode.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- `ADMIN_PASSPHRASE` env var set on Render
- `GET /api/v1/ui/config` returns the real passphrase (not empty string)
- Entering `enpro-admin` in the admin prompt is rejected; entering the real passphrase is accepted

---

### 3. Resolve PO 4098053 (Stepan Chemical)
**Why it matters:** Only red PO in the queue; blocks 100% green rate. No code change required — operator action only.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- Open Review Queue → Edit PO 4098053
- Set `customer_id` = `207620` (Stepan Chemical)
- Look up `CS-P0400/3000` in P21 item master; set `item_id_p21` on line 10
- Save → confidence score goes green (≥ 0.85)
- Approve → CISM SO CSVs written to `/app/data/cism_so_output/`

---

## P1 — Next (ops polish, high return)

### 4. Disk usage in `/health`
**Why it matters:** Render persistent disk is 1 GB. Approvals that fail silently with `OSError` are the most common silent failure mode. No monitoring currently.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- `GET /health` response includes `"disk": {"used_mb": N, "free_mb": N, "total_mb": N}`
- Uses `shutil.disk_usage("/app/data")`
- No change to existing `status`, `version`, `environment` fields

---

### 5. Persist `shipto_score` to PO result JSON
**Why it matters:** Ship-to confidence is a distinct scoring dimension (15% weight) but is not saved — cannot audit matching quality historically or filter on it in the queue.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- `result_data` dict in `_process_po_to_so()` includes `"shipto_score": <float>`
- Saved PO JSON file contains the field
- Review queue detail view shows ship-to score alongside customer and item scores

---

### 6. Atomic CISM batch CSV writes
**Why it matters:** `cism_batch.add_to_batch()` appends directly to open CSV files. A Render instance restart mid-write can produce truncated/corrupt rows.
**Scope:** Small
**Owner:** Unassigned
**Acceptance criteria:**
- `add_to_batch()` writes to a `.tmp` file then calls `os.replace()` to atomically swap
- Simulated process kill mid-write leaves either the complete prior file or the complete new file — never a partial row
- Existing download endpoints unaffected

---

### 7. Review Queue "Bulk Approve Greens" button
**Why it matters:** With 18 pending green POs, operators click Approve 18 times. A single bulk action reduces friction and errors.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- Button appears in Review Queue header: "Approve All Green (N)"
- Clicking shows a confirmation modal listing PO numbers
- Confirmed → approves all POs with `status=green` and `approved=false` in a single backend call
- Queue refreshes; approved POs move to Processed tab
- Button disabled (grayed) if no green POs pending

---

### 8. Mapping Suggestion Agent with Identity + Contract
**Why it matters:** Operators manually set `customer_id_p21` and `item_id_p21` on every red/yellow PO. A suggestion agent would surface ranked candidates with confidence and evidence, reducing mapping time and improving consistency without removing human control.
**Scope:** Medium
**Owner:** Unassigned
**Tool identity:** `mapping_suggester` v1 — assistive (human-in-loop); read-only on crosswalks; writes only to suggestion log.
**Contract doc:** `docs/TOOL_CONTRACTS_MAPPING.md`
**Acceptance criteria:**
- `POST /api/v1/suggest/mappings/{intake_id}` returns `customer_suggestions[]` and per-line `item_suggestions[]` with `candidate_id`, `confidence`, `reason`, `evidence`
- Response always includes `"decision_required": true` — no auto-apply path exists
- Operator UI shows suggestion chips in Edit PO panel; each chip has Accept / Reject buttons
- Accepted suggestions are persisted to crosswalk learner path (same as `learn_from_approval`)
- Rejected suggestions are stored as negative signals with `provenance=manual_reject`
- No existing high-confidence mapping is overwritten without an explicit secondary confirmation

---

### 9. Outbound Sync: real send scaffolding
**Why it matters:** Mock send is functional but operators need to know what "real send" will look like before credentials arrive — interface should be ready to swap in.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- `POST /api/v1/outbound/send/{outbound_id}` accepts optional `endpoint_url` and `api_key` body params
- If both provided, attempts real HTTP POST to the given URL with the stored payload; falls back to mock if either is missing
- Response distinguishes `"mode": "mock"` vs `"mode": "live"`
- No hardcoded Ariba/Coupa endpoint URLs in code — all via params or env vars

---

## P2 — Later (audit, observability)

### 9. Export/download outbound history as CSV
**Why it matters:** Ops team needs a paper trail of what was sent when; history tab in UI is useful live but not exportable.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- `GET /api/v1/outbound/history/download` returns a CSV with columns: `outbound_id`, `po_no`, `source_system`, `status`, `sent_at`, `customer_id`, `amount_total`
- Download button added to Outbound Sync → History section
- File named `outbound_history_YYYYMMDD.csv`

---

### 10. Azure SQL staging DB (`dbo.po_staging_log`)
**Why it matters:** `local_store` is durable only as long as Render's persistent disk is healthy. SQL gives cross-instance durability and enables reporting queries.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- `DATABASE_URL` env var set on Render → `local_store` writes also mirror to `dbo.po_staging_log`
- `DATABASE_URL` absent → existing local_store-only behavior unchanged (no regression)
- `/health` reports `"db": "connected"` vs `"db": "unavailable (local fallback)"`

---

### 11. CI smoke test (GitHub Actions)
**Why it matters:** All validation is currently manual. A single wrong import or syntax error on deploy causes a silent 502 that takes 2+ minutes to diagnose.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- GitHub Actions workflow runs on push to `master`
- Steps: `pip install -r requirements.txt` → `python -c "import server"` (import check) → `pytest tests/ -x -q` if tests exist
- Workflow badge visible on repo README
- Failure blocks merge (branch protection optional for now)

---

### 12. Live P21 API submit (optional, currently disabled)
**Why it matters:** End-state automation closes the loop — approved POs become real P21 sales orders without manual CSV upload.
**Scope:** Medium
**Owner:** Unassigned
**Acceptance criteria:**
- `P21_BASE_URL`, `P21_API_USERNAME`, `P21_API_PASSWORD` env vars set on Render
- `POST /api/v1/p21/submit/{intake_id}` sends Transaction API JSON to P21 and records the returned order number
- `/health` reports P21 connectivity status
- Payload-export mode remains default; live submit is opt-in per-PO or per-batch

---

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Render disk full (1 GB) | Medium | High — silent save failures | Add disk usage to `/health` (P1 item #4) immediately |
| `APP_API_KEY` not set | High (currently) | High — open mutating routes | Set on Render today (P0 item #1) |
| CISM CSV corruption on restart | Low | Medium — bad batch download | Atomic write pattern (P1 item #6) |
| P21 item `CS-P0400/3000` not in crosswalk | Low | Low — one PO stays red | Manual lookup + approve (P0 item #3) |
| Azure SQL never configured | High (by choice) | Low — local_store covers current volume | Accept risk until volume requires it |
| `ADMIN_PASSPHRASE` default exposed | High (currently) | Low — UI gate only, no data exposure | Set on Render today (P0 item #2) |
| Ariba/Coupa endpoint contracts change | Unknown | Medium — stub schemas may need rework | Stub schemas are clearly labeled v1; easy to swap |

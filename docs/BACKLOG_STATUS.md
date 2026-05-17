# Backlog Status — EnPro PO Agent Sandbox

**Mode:** Payload-Export Only (no live P21 API submit)
**Last updated:** 2026-04-21

---

## Done

| Item | Owner | Evidence | Notes |
|---|---|---|---|
| Email poll → ingest pipeline | — | `POST /api/v1/intake/poll-now`; commit `5367014` | Graph API + Doc Intel confirmed live |
| Customer crosswalk matching (6-stage) | — | `customer_crosswalk_engine.py`; 21/22 POs green | `exact_name_zip` is dominant match path |
| 4-dimension confidence scoring | — | `confidence_scorer.py:167`; `score_customer_po()` | Weights: cust 30%, shipto 15%, items 45%, dedup 10% |
| CISM SO CSV generation on approve | — | `/app/data/cism_so_output/`; `cism_so_generator.py` | Header + lines CSVs per PO |
| CISM batch accumulation + download | — | `GET /api/v1/cism/batch/download/{type}`; `cism_batch.py` | Batch CSV ready for blob upload |
| Single-PO P21 payload download | — | `GET /api/v1/p21/payload/{id}/download`; commit `e933f71` | Returns valid Transaction API JSON |
| P21 Payloads tab in UI | — | `static/index.html`; commit `4fe308a` | Table, View JSON modal, single Download |
| Multi-PO batch payload export | — | `POST /api/v1/p21/payload/batch/download`; commit `fd03ba2` | Merged `Transactions[]`; checkbox UI; inline notice |
| Edit PO + manual rescore | — | `POST /api/v1/review/po/{id}/edit`; `edit_po()` | Re-runs `score_customer_po()` after override |
| Learn from approval (auto-crosswalk) | — | `crosswalk_learner.py`; `learn_from_approval()`; `server.py:875` | Writes back to 3 crosswalk CSVs on approve |
| API key auth on mutating routes | — | `_require_api_key`; commit `12d930b` | 9 routes gated; sandbox-safe when `APP_API_KEY` unset |
| Zero-line PO guard | — | `server.py:413`; commit `12d930b` | Returns red + saves to store; no 500 |
| Observable intake SQL failures | — | `server.py:543`; commit `12d930b` | `logger.warning` with intake_id + po_no context |
| Safer `_to_p21_date` fallback | — | `p21_api_client.py:494`; commit `12d930b` | Returns `""` + warning on unrecognized format |
| Independent ship-to scoring | — | `CustomerMatch.shipto_score`; commit `29cc330` | Replaces `customer_score × 0.95` proxy |
| Global item customer preference | — | `customer_crosswalk_engine.py:283`; commit `29cc330` | Step 2 prefers customer-specific row before global best |
| Dedup SQL → local_store fallback | — | `duplicate_detector.py:37`; commit `29cc330` | Catches duplicates on Render where SQL is unavailable |
| Operations runbook | — | `docs/OPERATIONS_RUNBOOK.md` | Daily workflow, troubleshooting table |
| Go-live checklist | — | `docs/GO_LIVE_CHECKLIST.md` | Mode 1 (current) + Mode 2 (future live submit) |

---

## In Progress

| Item | Owner | Status | Evidence | Next Action |
|---|---|---|---|---|
| **Resolve PO 4098053** | Brittany (operator) | Red — awaiting manual edit | `intake_id=3ED86EB008B616D3`; `reason="customer not matched; 1 unmatched items"` | Edit PO: set `customer_id_p21=207620` (Stepan Chemical), look up `CS-P0400/3000` in P21 item master and set `item_id_p21` on line 10 |

---

## Next Up

| Item | Priority | Rationale | Next Action |
|---|---|---|---|
| **Persist `shipto_score` to PO JSON** | Medium | Currently computed at ingest but not saved to `result_data["customer_match"]`; can't audit or display independently | Add `"shipto_score": cust_match.shipto_score` to the `customer_match` block in `_process_po_to_so()` result_data; 1-line change in `server.py` |
| **Set `APP_API_KEY` on Render** | Medium | Auth protection is live in code but env var not set → all mutating routes still open | Set `APP_API_KEY` in Render dashboard → Environment; triggers auto-redeploy (~2 min) |
| **Atomic CISM batch CSV writes** | Medium | `cism_batch.add_to_batch()` appends directly; crash mid-write silently truncates batch | Replace append pattern with write-to-temp + `os.replace()` atomic swap in `cism_batch.py` |
| **Disk usage check in `/health`** | Low | `/app/data` is 1 GB Render persistent disk; no capacity alert | Add `shutil.disk_usage("/app/data")` to health response with `disk_free_gb` field |
| **HTTP-tier test suite for approve flow** | Low | No automated regression test for approve → CISM → batch flow; currently manual only | Add `tests/test_approve_flow.py` covering queue → approve → batch status → batch download |

---

## Blocked

| Item | Blocked By | Evidence | Unblock Path |
|---|---|---|---|
| **Live P21 API submit (Mode 2)** | `P21_BASE_URL` / `P21_API_USERNAME` / `P21_API_PASSWORD` not set on Render; P21 env vars must be provided by EnPro IT | `docs/GO_LIVE_CHECKLIST.md` — Mode 2 section; Render dashboard shows 11 vars (no P21 vars) | EnPro IT provides P21 Transaction API credentials; set in Render dashboard; verify approve response contains `"method":"api"` |
| **SQL audit trail (`dbo.po_staging_log`)** | No Azure SQL staging DB configured on Render | `/health` returns `"staging_db":"not configured"`; `log_intake()` warns on every ingest | Provision Azure SQL or accept local-store-only audit trail as permanent for sandbox mode |

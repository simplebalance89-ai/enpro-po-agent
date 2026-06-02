# EnPro PO Agent — Handoff Summary
**Date:** June 1, 2026
**Branch/State:** Working directly in `static/index.html` and `src/server.py`
**Server:** `uvicorn src.server:app --reload --host 0.0.0.0 --port 8000`

---

## ✅ What's Done (P0 + P3 Progress)

| # | Task | File | How | Status |
|---|------|------|-----|--------|
| P0 #1 | CISM batch schema (27→75 cols) | `services/processing/cism_batch.py` | Already had 75 header + 39 line columns defined. **Action needed:** Clear old batch CSVs so new writes use full schema. | Code ✅, Data needs clear |
| P0 #2 | Required Date blank in batch | `services/processing/cism_batch.py:214` | Maps `line.get("required_date")` with `date_due` and `order_date` fallbacks. | ✅ |
| P0 #3 | Taker = filesystem path | `src/server.py:963` | Uses `settings.p21_default_taker` ("SYSTEM" or "POAGENT"). | ✅ |
| P1 #4 | Customer search dropdown in Edit PO | `static/index.html` | New `searchCustomers()` + `selectCustomer()` functions. Queries `/api/v1/lookup/customers?q=`. Auto-fills ID, name, ship-to, reloads item history. | ✅ |
| P1 #5 | Item search dropdown in Edit PO | `static/index.html` | New `searchItems()` + `selectItem()` functions. Filters `_editCustItems` client-side by part number, description, or UID. Hidden `<select>` preserves `saveEditPO()`. | ✅ |
| P3 #15 | Toast notifications | `static/index.html` | `showToast(msg, type, duration)` function. Replaced all `alert()` calls for approve/reject/bulk/upload/batch/submit flows. Green=success, red=error, yellow=warn, blue=info. | ✅ |
| — | UTF-8 encoding crash | `src/server.py:189` | Added `encoding="utf-8"` to `open("static/index.html")`. Fixes Windows `charmap` crash on special characters. | ✅ |
| P1 #8 | Disk usage warning banner | `static/index.html` | `checkDisk()` polls `/health` every 60s. Shows sticky yellow banner at >80%, red at >90%. | ✅ |

---

## 🚧 What's In Progress / Next Up

### Pure Frontend (No Python needed)
| # | Task | Effort | Notes |
|---|------|--------|-------|
| P3 #16 | Keyboard shortcuts | ~15 min | `Enter` = trigger Approve on selected PO. `Esc` = close detail panel or cancel Edit PO mode. Add `document.addEventListener('keydown', ...)` in `static/index.html`. |
| P3 #17 | Dark/light mode toggle | ~30 min | CSS is all hardcoded dark hex. Switch to CSS variables (`var(--bg)`, `var(--text)`) + a toggle button that sets `data-theme` on `<html>`. |
| P3 #18 | Mobile responsive | ~2-4 hrs | `.queue-layout` grid (320px + 1fr) needs to stack to single column below 768px. Tab bar needs horizontal scroll. |

### Needs Backend/API Work
| # | Task | What to Build |
|------|------|---------------|
| P1 #6 | Inline crosswalk editing | New `POST /api/v1/crosswalk/customers/{id}/edit` and `POST /api/v1/crosswalk/items/{id}/edit`. Validate input, write back to CSV, invalidate `_customer_engine` cache, return success/error. |
| P1 #7 | Audit trail view | New SQLite table `audit_log` (id, intake_id, action, actor, timestamp, details). Hook `approvePO`, `rejectPO`, `saveEditPO` to write to it. New `GET /api/v1/audit` endpoint. New UI tab. |
| P2 #9 | Real auth | Replace hardcoded `enpro-admin` passphrase. Options: API key + name entry, or session-based login. Protect admin routes with middleware. |
| P2 #10 | User identity on actions | Add `actor` field to all POST bodies. Display "Approved by Brittany at 2:34 PM" in UI. Depends on audit trail table. |
| P2 #11 | Real outbound send | Wire `POST /api/v1/outbound/send` to actual Ariba/Coupa HTTP POST. Needs endpoint URLs, credentials, retry logic. |
| P2 #12 | Invoice module | New `services/processing/invoice_sync.py`. New routes. New tab gated by `ENABLE_INVOICE_SYNC=true`. Needs Coupa API key. |
| P2 #13 | P21 connectivity status | In `/health`, actually ping P21 API (lightweight endpoint). Return green/yellow/red status. Handle "not configured" gracefully. |
| P2 #14 | Crosswalk freshness | Track `last_modified` of crosswalk CSV files. Return in stats. UI shows "Data refreshed 3 days ago". |

---

## 🎯 Recommended Next Steps (In Order)

1. **Keyboard shortcuts** — 15 min frontend win. Brittany hits Enter to approve, Esc to cancel.
2. **Audit trail** — Foundation for everything else (auth, identity, compliance). Start with the SQLite table and hook the three main actions.
3. **Inline crosswalk editing** — Brittany's #1 daily pain point after search is fixed. Needs the two POST endpoints above.
4. **Real auth** — Once audit trail exists, adding a name/API key login is trivial.

---

## 🧪 Testing Checklist

When you make changes:
- [ ] Server starts: `cd repo; $env:PYTHONPATH="$PWD\src"; uvicorn src.server:app --reload --port 8000`
- [ ] Health OK: `http://localhost:8000/health` returns 200
- [ ] Dashboard loads: `http://localhost:8000/` — no `UnicodeDecodeError`
- [ ] Edit PO customer search: type "Step" → results dropdown → click → fills ID, name, ship-to
- [ ] Edit PO item search: type part of description → filtered results → click → fills desc, UOM, price
- [ ] Approve PO → toast appears (not `alert()` popup)
- [ ] Disk banner: manually edit `checkDisk` to threshold 30% to verify yellow/red styling
- [ ] Save Edit PO → no errors, confidence updates, queue refreshes

---

## 🔐 Environment / Secrets

Never commit `.env`. Required vars for local dev:
```
PYTHONPATH=./src
CISM_BATCH_DIR=./data/cism_batch
CISM_SO_OUTPUT_DIR=./data/cism_so_output
P21_DEFAULT_TAKER=SYSTEM
```

Production secrets (Render dashboard only):
- `AZURE_BLOB_CONNECTION_STRING`
- `P21_API_USERNAME` / `P21_API_PASSWORD`
- `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` / `GRAPH_TENANT_ID`

---

## 📁 Key Files Map

| File | Purpose | Lines |
|------|---------|-------|
| `static/index.html` | Entire UI — vanilla JS, no framework | ~1,750 |
| `src/server.py` | FastAPI backend — all routes | ~2,850 |
| `services/processing/cism_batch.py` | CISM batch CSV builder | 299 |
| `services/processing/cism_so_generator.py` | Per-PO CISM SO files | ~220 |
| `services/processing/customer_crosswalk_engine.py` | Loads crosswalk CSVs into memory | ~180 |
| `data/cism_batch/batch_orderquoteheader.csv` | Running batch headers | Clear to rebuild |
| `data/cism_batch/batch_orderquoteline.csv` | Running batch lines | Clear to rebuild |

---

## 🐛 Known Quirks

- **Crosswalks empty on first start:** If `data/crosswalks/` has no CSVs, the engine loads 0 entries. Upload crosswalk CSVs via the UI (Tab 6 → Upload Crosswalks) or place them manually.
- **Blob sync fails without Azure:** Expected. Warnings in logs are normal for local dev.
- **Email polling disabled without Graph API:** Expected.
- **Old batch CSVs have 27 columns:** Click **Clear Batch** in the CISM Batch tab to archive them. New approvals will write the full 75-column schema.

---

*End of Handoff*

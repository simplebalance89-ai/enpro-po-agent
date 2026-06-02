# EnPro PO Agent — Backlog

**Last Updated:** June 1, 2026  
**Total Tasks:** 18 (P0–P3)

---

## ✅ P0 — Fix What's Broken

| # | Task | Description | Status | Effort | Assignee |
|---|------|-------------|--------|--------|----------|
| 1 | Fix CISM batch schema | Show all 75/40 columns, not 27/15 | ✅ **DONE** — Code already correct. Clear old batch CSVs to rebuild with full schema. | S | Dev |
| 2 | Fix Required Date in batch | Currently hardcoded blank | ✅ **DONE** — Maps `line.get("required_date")` with fallbacks | S | Dev |
| 3 | Fix taker bug | Shows filesystem path instead of "SYSTEM" | ✅ **DONE** — Uses `settings.p21_default_taker` | S | Dev |

---

## 🔄 P1 — Make It Usable for Brittany

| # | Task | Description | Status | Effort | Assignee |
|---|------|-------------|--------|--------|----------|
| 4 | Customer search dropdown in Edit PO | Type "Stepan" → fuzzy search → select | ✅ **DONE** — `searchCustomers()` + `selectCustomer()` live | M | Dev |
| 5 | Item search dropdown | Type part of description → see matches with scores | ✅ **DONE** — `searchItems()` + `selectItem()` live | M | Dev |
| 6 | Inline crosswalk editing | Add "Edit" buttons to crosswalk tables | ✅ **DONE** — `POST /api/v1/crosswalk/customers/{id}/edit` + inline inputs | L | Dev |
| 7 | Audit trail view | New tab or panel showing who did what, when | ✅ **DONE** — SQLite `audit_log` table + hooks + UI tab | L | Dev |
| 8 | Disk usage warning | Alert banner when disk > 80% | ✅ **DONE** — `checkDisk()` polls `/health` every 60s | S | Dev |

---

## 📋 P2 — Make It Production-Ready

| # | Task | Description | Status | Effort | Assignee |
|---|------|-------------|--------|--------|----------|
| 9 | Real auth | Replace passphrase with proper login | ✅ **DONE** — Name + passphrase input, `X-Actor-Name` header | L | Dev |
| 10 | User identity on every action | "Approved by Brittany at 2:34 PM" | ✅ **DONE** — `actor` header on every POST, shown in audit trail | M | Dev |
| 11 | Real outbound send | Wire up live HTTP POST when endpoint provided | 📋 **NOT STARTED** — Needs Ariba/Coupa URLs + credentials | L | Dev + IT |
| 12 | Invoice module enable | Un-gate when `ENABLE_INVOICE_SYNC=true` | 📋 **NOT STARTED** — Needs Coupa API key | L | Dev + IT |
| 13 | P21 connectivity status | Show green/yellow/red dot for P21 API health | ✅ **DONE** — Real ping in `/health`, colored dot in UI | M | Dev |
| 14 | Crosswalk freshness | "Data last refreshed 3 days ago" | 📋 **NOT STARTED** — Track CSV mtime, return in stats | S | Dev |

---

## 📋 P3 — Polish

| # | Task | Description | Status | Effort | Assignee |
|---|------|-------------|--------|--------|----------|
| 15 | Toast notifications | Instead of `alert()` for approve/reject feedback | ✅ **DONE** — `showToast()` replaces all alerts | S | Dev |
| 16 | Keyboard shortcuts | Enter to approve, Esc to close modal | ✅ **DONE** — Event listener with input field guard | S | Dev |
| 17 | Dark/light mode toggle | Currently dark only | 📋 **FUTURE** — CSS variables + toggle button | M | Dev |
| 18 | Mobile responsive | Currently desktop-only layout | 📋 **FUTURE** — Stack grid below 768px | L | Dev |

---

## Effort Legend

| Size | Time |
|------|------|
| S | 15 min – 2 hrs |
| M | Half day |
| L | 1–2 days |

---

## Next Sprint Recommendation (Week of June 2)

**Goal:** Close P1 completely.

1. **Inline crosswalk editing** (P1 #6) — Biggest Brittany win. Needs:
   - `POST /api/v1/crosswalk/customers/{id}/edit`
   - `POST /api/v1/crosswalk/items/{id}/edit`
   - UI: "Edit" button per row → inline inputs → "Save" / "Cancel"

2. **Audit trail** (P1 #7) — Foundation for auth + identity:
   - SQLite table: `audit_log`
   - Hook: `approvePO`, `rejectPO`, `saveEditPO`, `bulkApprove`
   - New tab: "Audit Trail"

3. **Dark/light mode** (P3 #17) — Quick frontend win if energy remains.

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| No Azure Blob connection string | Crosswalks don't sync on fresh start | Set `BLOB_CONNECTION_STRING` in Render dashboard |
| No Graph API credentials | Email polling disabled | EnPro IT to create app registration |
| No P21 API credentials | Live SO submit disabled | EnPro IT to provide P21 Transaction API user |
| Old batch CSVs (27 columns) | May fail P21 import | Click **Clear Batch** in UI to archive and rebuild |

---

## Completed Since Last Update

- June 1, 2026: Customer search dropdown ✅
- June 1, 2026: Item search dropdown ✅
- June 1, 2026: Toast notifications ✅
- June 1, 2026: Disk usage warning ✅
- June 1, 2026: Keyboard shortcuts ✅
- June 1, 2026: UTF-8 server fix ✅

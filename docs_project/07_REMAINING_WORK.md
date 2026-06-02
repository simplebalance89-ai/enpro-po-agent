# EnPro PO Agent — Remaining Work for Next Developer

**Status as of June 1, 2026**
**Files to edit:** `static/index.html`, `src/server.py`, `services/processing/*`

---

## What We Built Today (Done)

- Customer search dropdown in Edit PO ✅
- Item search dropdown in Edit PO ✅
- Toast notifications (replaced `alert()`) ✅
- Disk usage warning banner ✅
- Keyboard shortcuts (Enter/Esc) ✅
- UTF-8 server fix ✅
- Full documentation folder ✅

**The P21 API integration is already built and working** — auth, token refresh, SO creation, batch submit, auto-submit on approve. It just needs credentials to be configured.

---

## What Is Left (In Priority Order)

### 1. Audit Trail — FOUNDATION FOR EVERYTHING ELSE
**Priority: CRITICAL**
**Effort: 1 day**
**Why:** Without this, there is no accountability. Brittany can't see who approved what. Auth and user identity depend on this.

**Backend:**
- New SQLite table `audit_log` in `data_layer/schema.sql`:
  ```sql
  CREATE TABLE audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      intake_id TEXT,
      action TEXT,           -- 'approve', 'reject', 'edit', 'bulk_approve', 'submit_p21'
      actor TEXT,            -- 'Brittany', 'system', API key name
      timestamp TEXT,
      details TEXT,          -- JSON: {po_no, customer_id, old_value, new_value}
      ip_address TEXT
  );
  ```
- Hook into `approvePO`, `rejectPO`, `saveEditPO`, `bulkApprove`, `submit_p21_single`, `submit_p21_batch`
- New endpoint: `GET /api/v1/audit?limit=100&action=approve`
- New endpoint: `GET /api/v1/audit/summary` (counts by action, actor, day)

**Frontend:**
- New tab "Audit Trail" (between Pipeline and Invoices)
- Table: timestamp, actor, action, PO number, details
- Filter by action, date range, actor
- Export to CSV button

---

### 2. Real Auth — Replace Hardcoded Passphrase
**Priority: HIGH**
**Effort: Half day**
**Why:** `enpro-admin` is not real security.

**Backend:**
- Keep it simple: API key + name entry (not full session auth)
- New env var: `OPERATOR_NAME` (display name for audit trail)
- On login: prompt for name + `ADMIN_PASSPHRASE`
- Store `actor_name` in localStorage
- Send `X-Actor-Name` header with every mutating request
- Server reads header, uses it in audit_log.actor

**Frontend:**
- Replace passphrase-only prompt with: name input + passphrase input
- Show "Logged in as Brittany" in top bar
- Logout button clears localStorage

**Why not full OAuth/JWT:** Overkill for one user. API key + name is enough for Brittany and gives audit trail identity.

---

### 3. User Identity on Every Action
**Priority: HIGH**
**Effort: 2 hours**
**Depends on:** #1 (audit trail) and #2 (auth)

**What to do:**
- Every POST request body includes `actor` field (from localStorage)
- Server writes `actor` to audit_log
- UI shows "Approved by Brittany at 2:34 PM" in PO detail view
- UI shows actor name in Processed tab and Audit Trail tab

---

### 4. P21 Connectivity Status
**Priority: MEDIUM**
**Effort: 2 hours**
**Why:** The `/health` endpoint says "ready" or "not configured" but doesn't actually test the connection.

**Backend:**
- In `/health`, if P21 credentials are set, actually try to authenticate (lightweight — just the token endpoint, no SO creation)
- Return: `p21_api: "connected" | "auth_failed" | "unreachable" | "not_configured"`
- Cache the result for 60 seconds (don't hammer P21 on every health check)

**Frontend:**
- In top bar, next to the green status dot, add a P21 status dot
- Green = connected, Yellow = auth_failed (wrong password), Red = unreachable, Gray = not configured
- Tooltip on hover: "P21 API: Connected" or "P21 API: Auth failed — check credentials"

---

### 5. Inline Crosswalk Editing
**Priority: MEDIUM**
**Effort: 1–2 days**
**Why:** Brittany's #1 daily pain point. She has to edit CSV files by hand.

**Backend:**
- `POST /api/v1/crosswalk/customers/{p21_customer_id}/edit`
  - Body: `{ship2_name, ship2_zip, p21_customer_name, ...}`
  - Validate: p21_customer_id exists
  - Write back to `data/crosswalks/customer_crosswalk.csv`
  - Invalidate `_customer_engine = None`
  - Log to audit trail

- `POST /api/v1/crosswalk/items/{customer_id}/{customer_part_number}/edit`
  - Body: `{p21_inv_mast_uid, p21_item_desc, unit_of_measure, ...}`
  - Same pattern: validate, write CSV, invalidate cache, audit log

**Frontend:**
- In Crosswalk tab (Tab 6), add an "Edit" button to each row of each table
- Clicking Edit turns the row into input fields
- "Save" button POSTs to backend
- "Cancel" reverts to read-only
- On save success: show toast, refresh table

---

### 6. Crosswalk Freshness Indicator
**Priority: LOW**
**Effort: 1 hour**

**Backend:**
- In `/api/v1/stats`, add:
  ```json
  "crosswalk_freshness": {
      "customer_crosswalk": "2026-05-28",
      "customer_item_crosswalk": "2026-05-28",
      "item_master_index": "2026-05-15"
  }
  ```
- Read `os.path.getmtime()` of each CSV file

**Frontend:**
- In Crosswalk tab header, show: "Customer data: refreshed 3 days ago"
- Yellow if >7 days, red if >30 days

---

### 7. Real Outbound Send
**Priority: LOW**
**Effort: 1 day**
**Why:** Needs real Ariba/Coupa endpoint URLs and credentials from EnPro IT.

**Backend:**
- In `services/processing/outbound_sync.py`, wire `send_to_ariba()` and `send_to_coupa()` to real HTTP POST
- Add env vars: `ARIBA_API_URL`, `ARIBA_API_KEY`, `COUPA_API_URL`, `COUPA_API_KEY`
- Add retry logic (3 attempts with exponential backoff)
- Add timeout (30s)

**Frontend:**
- In Outbound Sync tab, replace "Mock send only" with real send button
- Show status: Pending → Prepared → Ready → Sent

---

### 8. Invoice Module Enablement
**Priority: LOW**
**Effort: 2 days**
**Why:** Built but disabled. Needs `ENABLE_INVOICE_SYNC=true` + Coupa API key.

**What to do:**
- Set `ENABLE_INVOICE_SYNC=true` in env
- Add Coupa API key
- Enable Invoices tab in UI (remove `disabled` class)
- Test invoice sync endpoints

---

### 9. Dark/Light Mode Toggle
**Priority: LOW**
**Effort: Half day**
**Why:** Nice to have. Not critical for Brittany's workflow.

**What to do:**
- Convert all hardcoded hex colors in CSS to CSS custom properties (`var(--bg)`, `var(--text)`)
- Add `[data-theme="light"]` override section
- Add toggle button in top bar
- Save preference to localStorage

---

### 10. Mobile Responsive
**Priority: LOW**
**Effort: 1–2 days**
**Why:** Brittany uses desktop. Mobile is for emergency access only.

**What to do:**
- `.queue-layout` grid stacks vertically below 768px
- Tab bar becomes horizontally scrollable
- Tables overflow with horizontal scroll
- Reduce padding/font sizes on small screens

---

## What NOT to Do (Out of Scope)

| Item | Why |
|------|-----|
| Dynamics 365 live API | Static CSV works fine for now |
| Multi-tenant / multi-company | Only EnPro uses this |
| Real-time P21 SQL sync | On-prem only, not reachable from cloud |
| AI-assisted field mapping | Azure OpenAI is optional and already stubbed |

---

## Recommended Sprint Plan

**Week 1: Foundation**
- Day 1: Audit trail (backend table + hooks)
- Day 2: Audit trail (frontend tab) + Real auth (name + passphrase)
- Day 3: User identity on actions + P21 connectivity status

**Week 2: UX + Data**
- Day 1–2: Inline crosswalk editing
- Day 3: Crosswalk freshness + Dark/light mode

**Week 3: Integrations (when IT provides credentials)**
- Day 1: Real outbound send
- Day 2: Invoice module enablement
- Day 3: Mobile responsive + final testing

---

## Files Most Likely to Change

| File | What Will Change |
|------|-----------------|
| `src/server.py` | New audit endpoints, auth middleware, P21 health check, crosswalk edit endpoints |
| `static/index.html` | Audit tab, auth UI, crosswalk edit buttons, P21 status dot, dark mode |
| `data_layer/schema.sql` | New `audit_log` table |
| `services/processing/p21_api_client.py` | Maybe add a lightweight ping method |
| `services/processing/outbound_sync.py` | Wire real HTTP POST |
| `src/config.py` | New env vars: `OPERATOR_NAME`, `ARIBA_API_URL`, etc. |

---

## Testing Before Handoff

**Must pass:**
- [ ] Upload a PDF PO → appears in queue with confidence
- [ ] Search for customer in Edit PO → select → saves correctly
- [ ] Search for item in Edit PO → select → saves correctly
- [ ] Approve PO → toast confirms → appears in Processed tab
- [ ] Audit trail shows the approval with actor name and timestamp
- [ ] P21 status dot shows correct color (gray if not configured, green if connected)
- [ ] Bulk approve greens → all approved, audit log has N entries
- [ ] Reject PO → audit log shows rejection with reason
- [ ] Disk banner shows at >80%
- [ ] Keyboard shortcuts work (Enter = approve, Esc = cancel)

**Nice to have:**
- [ ] Crosswalk edit → change a customer name → save → refresh → change persists
- [ ] Dark mode toggle works
- [ ] Mobile layout doesn't break

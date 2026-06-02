# EnPro PO Agent — Statement of Work

**Project:** Purchase Order Automation Agent for EnPro Filtration  
**Sponsor:** EnPro Operations Team (Brittany)  
**Builder:** Peter Wilson + AI Assistants  
**Date:** June 1, 2026

---

## 1. Scope

### In Scope
- Email-based PO intake (Ariba, Coupa, direct PDF/XML/CSV)
- Automated parsing and structured extraction
- Customer and item matching against P21 master data
- Confidence scoring with human-in-the-loop review queue
- CISM Sales Order CSV generation (per-PO + batch)
- P21 Transaction API payload export (JSON)
- Auto-learning from approvals (crosswalk enrichment)
- Browser-based review portal with admin tools

### Out of Scope (Future Phases)
- Live Dynamics 365 CRM integration (static CSV only)
- Invoice synchronization (built but disabled)
- Real-time P21 SQL connectivity (on-prem only)
- Multi-tenant / multi-company support

---

## 2. Phases

### Phase 1 — MVP (Complete)
**Goal:** Ingest POs, match customers/items, generate CISM files, human review.

| Deliverable | Status |
|------------|--------|
| Email polling via Graph API | ✅ |
| PDF/cXML/CSV parsing | ✅ |
| Customer matching (6-stage) | ✅ |
| Item matching (4-stage) | ✅ |
| Confidence scoring | ✅ |
| Review queue UI | ✅ |
| Approve → CISM generation | ✅ |
| Reject with reason | ✅ |
| Crosswalk data load (CSV) | ✅ |

**Success Criteria:** A PO arrives via email, is parsed, matched, and Brittany can approve it to generate a CISM file. **ACHIEVED.**

---

### Phase 2 — UX Hardening (In Progress)
**Goal:** Make the tool something Brittany uses confidently every day without calling IT.

| Deliverable | Status |
|------------|--------|
| Customer search dropdown in Edit PO | ✅ Done |
| Item search dropdown in Edit PO | ✅ Done |
| Toast notifications (no more `alert()`) | ✅ Done |
| Disk usage warning banner | ✅ Done |
| Keyboard shortcuts (Enter/Esc) | 🔄 In Progress |
| Inline crosswalk editing | 📋 Planned |
| Audit trail view | 📋 Planned |
| Dark/light mode toggle | 📋 Planned |
| Mobile responsive layout | 📋 Planned |

**Success Criteria:** Brittany can handle 20+ POs/day without friction. Zero manual ID entry.

---

### Phase 3 — Production Readiness (Planned)
**Goal:** Deploy to live environment with real credentials and audit logging.

| Deliverable | Status |
|------------|--------|
| Real authentication (replace passphrase) | 📋 Planned |
| User identity on every action | 📋 Planned |
| Live P21 API connectivity check | 📋 Planned |
| Crosswalk freshness indicator | 📋 Planned |
| Real outbound sync (Ariba/Coupa HTTP POST) | 📋 Planned |
| Invoice module enablement | 📋 Planned |
| Dynamics CRM live API pull | 📋 Future |

**Success Criteria:** System runs 24/7 on Render/Azure. All actions are auditable. Brittany has a login, not a passphrase.

---

## 3. Acceptance Criteria

### Functional
1. A PDF PO emailed to `orders@enproinc.com` appears in the review queue within 2 minutes.
2. Green POs are auto-approved and CISM files are generated without human intervention.
3. Yellow/red POs appear in the queue with clear reason badges.
4. Brittany can search for a customer by name, select it, search for items, and approve — all in under 30 seconds per PO.
5. Batch CSV export contains all 75 header columns and 39 line columns matching P21 CISM spec.
6. Approved POs accumulate into a batch that can be downloaded, cleared, and archived.

### Non-Functional
1. UI loads in under 2 seconds.
2. Review queue updates automatically every 30 seconds.
3. Disk usage warning appears before the server runs out of space.
4. No secrets are committed to version control.
5. All mutating API routes require authentication.

---

## 4. Roles & Responsibilities

| Role | Who | Responsibility |
|------|-----|---------------|
| Product Owner | Brittany | Define workflow, test features, approve releases |
| Builder | Peter + AI | Write code, fix bugs, deploy |
| IT/Security | EnPro IT | Provide credentials, review security, manage Azure |
| P21 Admin | EnPro IT | Verify CISM format, troubleshoot import failures |

---

## 5. Timeline (Estimated)

| Phase | Effort | Target |
|-------|--------|--------|
| Phase 1 MVP | 3 weeks | ✅ Complete |
| Phase 2 UX | 1 week | 🔄 In Progress (est. June 7) |
| Phase 3 Prod | 2 weeks | 📋 Planned (est. June 21) |

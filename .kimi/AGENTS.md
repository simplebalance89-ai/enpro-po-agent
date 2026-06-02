# EnPro PO Agent — Kimi Context

**Project:** EnPro PO Agent  
**Repo:** `Desktop\EnPro-PO-Agent-Ariba-Coupa`  
**Live Service:** https://enpro-po-agent.onrender.com  
**Current Mode:** Payload-Export Only (CISM + downloadable P21 JSON)  
**Last Handoff:** May 17, 2026 → Andrew  
**Built By:** Peter Wilson + AI  

---

## What This Does

Ariba/Coupa Purchase Order Automation Agent. End-to-end pipeline:

1. **Email Intake** — Polls `orders@enproinc.com` via Microsoft Graph API
2. **PDF Parsing** — Azure Document Intelligence extracts PO data from PDF attachments
3. **cXML Parsing** — Native Ariba/Coupa `OrderRequest` XML parsing
4. **Crosswalk Matching** — 6-stage pipeline matches customers & items to P21 master data
5. **Confidence Scoring** — 4-dimension weighted scoring:
   - Customer match: 30%
   - Ship-to match: 15%
   - Items match: 45%
   - Dedup check: 10%
6. **Review Queue** — Human-in-the-loop approval portal (green/yellow/red)
7. **CISM SO Generation** — Approved POs generate P21 CISM Order/Quote Import CSVs
8. **P21 Payload Export** — Transaction API v2 JSON payloads (single + batch download)
9. **Learn from Approval** — New mappings auto-write back to crosswalk CSVs

**No LLM. No manual data entry. Rules-based matching against item master and customer crosswalk.**

---

## Where We Left Off (May 17, 2026)

System declared **"production-ready in payload-export mode."** Live P21 API submit is built but disabled pending credentials.

### Production Queue Snapshot (as of May 17)
| Metric | Value |
|---|---|
| Total POs ingested | 22 |
| Green (auto-resolved) | 21 (95%) |
| Red | 1 — PO 4098053 (Stepan Chemical) |
| Yellow | 0 |
| Approved | 4 |
| Pending review | 18 |
| Crosswalk customers | 4,880 |
| Crosswalk items | 22,722 |

### Already Built & Working
- Email poll → ingest → local_store (Graph API + Doc Intel)
- Customer crosswalk matching (6-stage, 95% auto-green)
- Item crosswalk matching (22K+ mappings)
- 4-dimension confidence scoring
- Review queue + approve/reject/edit/rescore
- **Bulk Approve Greens** ✅
- **Mapping Suggestion Agent** ✅ (assistive, human-in-loop)
- P21 Payloads tab (single + batch download, checkbox UI)
- CISM SO CSV generation + batch accumulation
- API key auth scaffold (code deployed, env var not set on Render)
- **Test Drive** (`/test-drive`) — drag PDF, instant payload preview
- **Mic Drop** (`/micdrop`) — animated proof payload is structurally correct
- Outbound sync stubs (mock + live HTTP POST when endpoint provided)
- Invoice module (built, disabled behind env var)
- Auto-learn from approval writes back to 3 crosswalk CSVs

---

## Ultimate Goal

1. **Immediate:** Close the loop. Approve → real P21 Sales Order via Transaction API v2 (no manual CSV upload).
2. **Ops hardening:** Secure mutating routes, monitor disk, atomic writes.
3. **Future:** Enable invoice module for Coupa invoice sync.

**The only blocker for live SO creation is 3 env vars on Render:**
```
P21_BASE_URL=https://<your-p21-server>:3333
P21_API_USERNAME=<transaction-api-user>
P21_API_PASSWORD=<transaction-api-password>
```

Optional: `P21_AUTO_SUBMIT_ON_APPROVE=true` to skip the button entirely.

---

## Action Items & Backlog

### P0 — Now (Blocking Production Trust)
1. **Set `APP_API_KEY` on Render** — 9 mutating routes currently open
2. **Set `ADMIN_PASSPHRASE` on Render** — admin gate uses hardcoded `enpro-admin`
3. **Resolve PO 4098053** — Edit PO, set `customer_id_p21=207620` (Stepan Chemical), look up `CS-P0400/3000` in P21 item master for line 10, save → green → approve

### P1 — Next (Ops Polish)
4. **Disk usage in `/health`** — Render disk is 1 GB, no monitoring
5. **Persist `shipto_score` to PO JSON** — computed but not saved; can't audit historically
6. **Atomic CISM batch CSV writes** — `add_to_batch()` appends directly; crash can corrupt
7. **Outbound Sync real-send scaffolding** — accept endpoint_url + api_key, attempt live HTTP POST

### P2 — Later (Audit, Observability)
8. **Export outbound history as CSV**
9. **Azure SQL staging DB** (`dbo.po_staging_log`)
10. **CI smoke test** (GitHub Actions)
11. **Live P21 API submit** (requires EnPro IT credentials)

---

## Key Docs

| Doc | Path |
|---|---|
| Main README | `docs\README.md` |
| Backlog (P0/P1/P2) | `docs\BACKLOG_NEXT.md` |
| Backlog Status / Done / Blocked | `docs\BACKLOG_STATUS.md` |
| Go-Live Checklist | `docs\GO_LIVE_CHECKLIST.md` |
| Ops Runbook (for Brittany) | `docs\OPERATIONS_RUNBOOK.md` |
| Mapping Suggester Contract | `docs\TOOL_CONTRACTS_MAPPING.md` |
| Handoff to Andrew (latest) | `docs\ANDREW_HANDOFF.md` |
| Session Handoff (prior) | `docs\SESSION_HANDOFF.md` |
| Setup Log | `docs\SETUP_LOG.md` |

---

## Key Source Files

| File | Purpose |
|---|---|
| `src\server.py` | FastAPI app — all routes, UI endpoints, test drive, mic drop |
| `src\config.py` | Pydantic settings (.env → env vars) |
| `src\models.py` | Pydantic data models |
| `src\po_parser.py` | Ariba/Coupa PO XML parsing |
| `src\demo_approve_one_po.py` | One-PO end-to-end demo |
| `services\intake\email_poller.py` | Graph API email polling |
| `services\intake\email_classifier.py` | Classify PO source (Ariba/Coupa/direct) |
| `services\processing\processing_agent.py` | Main processing orchestrator |
| `services\processing\customer_crosswalk_engine.py` | 6-stage customer matching |
| `services\processing\confidence_scorer.py` | 4-dimension scoring |
| `services\processing\cism_so_generator.py` | CISM CSV generation |
| `services\processing\cism_batch.py` | Batch accumulation + download |
| `services\processing\p21_api_client.py` | P21 Transaction API client + payload builder |
| `services\processing\local_store.py` | File-based PO store |
| `services\processing\crosswalk_learner.py` | Auto-learn from approvals |
| `services\processing\mapping_suggester.py` | Mapping suggestion agent |
| `services\processing\outbound_mapper.py` | Outbound sync mapping |
| `services\processing\outbound_store.py` | Outbound sync storage |
| `services\processing\duplicate_detector.py` | Dedup SQL → local_store fallback |
| `static\index.html` | Main review portal UI |

---

## Environment Variables

See `.env.example` for full list. Key vars:

| Variable | Default | Purpose |
|---|---|---|
| `APP_API_KEY` | *(empty)* | Protects all mutating routes |
| `ADMIN_PASSPHRASE` | *(empty)* | Enables admin-only UI tabs |
| `P21_BASE_URL` | *(empty)* | P21 Transaction API base URL |
| `P21_API_USERNAME` | *(empty)* | P21 API user |
| `P21_API_PASSWORD` | *(empty)* | P21 API password |
| `P21_AUTO_SUBMIT_ON_APPROVE` | `false` | Set `true` for live submit on approve |
| `CROSSWALK_DIR` | `./data/crosswalks` | Customer/item crosswalk CSVs |
| `CISM_SO_OUTPUT_DIR` | `./data/cism_so_output` | Per-PO CISM files |
| `CISM_BATCH_DIR` | `./data/cism_batch` | Accumulated batch files |

---

## Known Risks

| Risk | Likelihood | Impact |
|---|---|---|
| Render disk full (1 GB) | Medium | High — silent save failures |
| `APP_API_KEY` not set | High (currently) | High — open mutating routes |
| `ADMIN_PASSPHRASE` default exposed | High (currently) | Low — UI gate only |
| CISM CSV corruption on restart | Low | Medium — bad batch download |
| P21 credentials not provided | High (by IT) | Blocks Mode 2 (live submit) |
| Azure SQL never configured | High (by choice) | Low — local_store covers volume |

---

## How to Run Locally

```powershell
# 1. Create data dirs
.\start_local.ps1

# 2. Install deps
pip install -r requirements.txt

# 3. Start server
uvicorn server:app --reload --host 0.0.0.0 --port 8000

# Or use the startup script
.\start_local.ps1
```

- Review Queue: http://localhost:8000/
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Test Drive: http://localhost:8000/test-drive
- Mic Drop: http://localhost:8000/micdrop

---

## Contact

**Peter Wilson** — pwnetsuite@outlook.com  
**Repo:** github.com/simplebalance89-ai/enpro-po-agent

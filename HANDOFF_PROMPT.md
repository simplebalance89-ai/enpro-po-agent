# Handoff Prompt — EnPro PO Agent

**Give this to the next developer/ops person.**

---

## What This Is
Ariba/Coupa Purchase Order automation agent. Ingests POs from email, matches them to P21 ERP customers/items, and outputs CISM SO import files + P21 Transaction API JSON payloads.

## Current State
- **Version:** 1.1.0
- **Status:** Sandbox/Payload-Export mode (CISM + downloadable JSON)
- **Live P21 API submit:** Built but disabled pending credentials
- **Auto-match rate:** ~95% green
- **Last handoff:** May 17, 2026

## What's Working
- Email intake (Graph API) ✅
- PDF/cXML parsing (Azure Doc Intel) ✅
- Customer/item crosswalk matching ✅
- Confidence scoring (4-dimension) ✅
- Review queue (green/yellow/red) ✅
- Bulk approve greens ✅
- CISM SO CSV generation + batch download ✅
- P21 payload export (single + batch) ✅
- Mapping suggestion agent ✅
- Test Drive + Mic Drop demos ✅

## What's Actually Missing / Next Steps
1. **P21 credentials** — need `P21_BASE_URL`, `P21_API_USERNAME`, `P21_API_PASSWORD` to enable live SO creation
2. **Security env vars** — `APP_API_KEY` and `ADMIN_PASSPHRASE` must be set on any host
3. **SQL staging DB** — schema exists (`sql/staging_schema.sql`) but file-based JSON is still the primary store
4. **PO 4098053** — one red PO (Stepan Chemical) needs manual edit + approve in the queue
5. **CI/CD** — no automated tests or deploy pipeline
6. **Audit trail** — no immutable log of who approved what

## How to Run Locally (Windows)
```powershell
cd EnPro-PO-Agent-Ariba-Coupa
.\start.ps1
```
That's it. It creates data dirs, checks deps, and starts the server at http://localhost:8000

## How to Run Locally (Docker)
```bash
cd EnPro-PO-Agent-Ariba-Coupa
docker-compose up --build -d
```

## How to Deploy Anywhere
See `DEPLOY.md`. The app is containerized and runs on any Docker host.

## Key Files
| File | Purpose |
|---|---|
| `src/server.py` | FastAPI app — all routes, UI, processing |
| `services/processing/customer_crosswalk_engine.py` | 6-stage customer matching |
| `services/processing/confidence_scorer.py` | 4-dimension scoring |
| `services/processing/cism_so_generator.py` | CISM CSV generation |
| `services/processing/p21_api_client.py` | P21 Transaction API client |
| `static/index.html` | Review portal UI |

## Risks to Know About
- **File-based storage:** No transactions, no WAL. Crash during write = corrupted PO or crosswalk.
- **No concurrency control:** Concurrent approvals can race on crosswalk CSV writes.
- **CORS wide open:** `allow_origins=["*"]` in production until tightened.
- **Disk limit:** Render was 1 GB. Monitor `/health` `disk` field.

## Contact
Built by Peter Wilson | pwnetsuite@outlook.com

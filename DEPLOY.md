# Deployment Guide — EnPro PO Agent

**Goal:** Run this anywhere Docker runs (local, cloud VPS, Railway, Fly.io, Azure, AWS, etc.)

---

## Quick Start (Docker Compose)

```bash
# 1. Clone / copy the repo
cd EnPro-PO-Agent-Ariba-Coupa

# 2. Copy env template and fill in secrets
cp .env.example .env
# Edit .env — add APP_API_KEY, ADMIN_PASSPHRASE, Azure secrets, P21 creds

# 3. Build & run
docker-compose up --build -d

# 4. Check health
curl http://localhost:8000/health
```

**Access:**
- Review Queue: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Test Drive: http://localhost:8000/test-drive
- Mic Drop: http://localhost:8000/micdrop

---

## Environment Variables (Minimum for Demo)

| Variable | Required? | Notes |
|---|---|---|
| `APP_API_KEY` | **Strongly recommended** | Protects all mutating routes |
| `ADMIN_PASSPHRASE` | **Strongly recommended** | Locks admin UI tabs |
| `AZURE_BLOB_CONNECTION_STRING` | Optional | Crosswalk blob sync |
| `DOC_INTEL_ENDPOINT` | Optional | PDF parsing |
| `DOC_INTEL_KEY` | Optional | PDF parsing |
| `GRAPH_CLIENT_ID` | Optional | Email polling |
| `GRAPH_CLIENT_SECRET` | Optional | Email polling |
| `GRAPH_TENANT_ID` | Optional | Email polling |
| `P21_BASE_URL` | Optional | Live P21 API submit |
| `P21_API_USERNAME` | Optional | Live P21 API submit |
| `P21_API_PASSWORD` | Optional | Live P21 API submit |

**For a local demo with no cloud services:** leave everything blank. The app boots with local file storage only.

---

## Going Live (Checklist)

1. **Set `APP_API_KEY`** — any strong random string
2. **Set `ADMIN_PASSPHRASE`** — any strong random string
3. **Configure Azure Blob** — for crosswalk sync (optional if crosswalks are baked into image)
4. **Configure Document Intelligence** — for PDF PO parsing
5. **Configure Graph API** — for email intake from `orders@enproinc.com`
6. **Configure P21 Transaction API** — for live SO creation (optional; CISM batch mode works without it)
7. **Volume backup** — `/app/data` is a Docker volume. Back it up:
   ```bash
   docker run --rm -v enpro-po-agent_enpro-data:/data -v $(pwd):/backup alpine tar czf /backup/enpro-data-backup.tar.gz -C /data .
   ```

---

## Cloud Hosts (Render Alternatives)

### Railway
```bash
railway login
railway init
railway up
```
Railway reads `Dockerfile` automatically. Add env vars in dashboard.

### Fly.io
```bash
fly launch --dockerfile Dockerfile
fly secrets set APP_API_KEY=xxx ADMIN_PASSPHRASE=xxx ...
```

### Azure Container Apps
Use `azure/container-app.bicep` or deploy the Dockerfile directly:
```bash
az containerapp up --name enpro-po-agent --source .
```

### Raw VPS (DigitalOcean, Linode, etc.)
```bash
git clone <repo>
cd EnPro-PO-Agent-Ariba-Coupa
cp .env.example .env
# edit .env
docker-compose up -d
```

---

## Data Persistence

All state lives in `/app/data`:
- `po_store/` — JSON records for every PO
- `crosswalks/` — customer/item crosswalk CSVs
- `cism_so_output/` — generated CISM CSVs
- `cism_batch/` — accumulated batch CSVs

**This is a Docker volume.** It survives container restarts but not volume deletion.

---

## Migration from Render

If you're moving from Render:
1. Download `/app/data` from Render dashboard (Shell → `tar czf data.tar.gz /app/data`)
2. Extract locally: `tar xzf data.tar.gz`
3. Copy into volume: `docker cp data/. enpro-po-agent:/app/data/`
4. Restart: `docker-compose restart`

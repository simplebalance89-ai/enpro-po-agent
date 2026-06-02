# EnPro PO Agent — Deployment Guide

---

## Local Development (Windows)

### Prerequisites
- Python 3.12+ installed
- PowerShell (comes with Windows)

### Step 1: Start the Server
```powershell
cd C:\Users\Dekan AI Brother\Desktop\EnPro-PO-Agent-Ariba-Coupa
.\start.ps1
```

This script will:
1. Check Python is available
2. Create all data directories (`data/crosswalks`, `data/cism_batch`, etc.)
3. Install dependencies if needed
4. Start Uvicorn on `http://localhost:8000`

### Step 2: Verify It's Running
Open your browser to:
- **Dashboard:** `http://localhost:8000/`
- **Health Check:** `http://localhost:8000/health`
- **API Docs:** `http://localhost:8000/docs`
- **Test Drive:** `http://localhost:8000/test-drive`

### Step 3: Load Crosswalk Data
If `data/crosswalks/` is empty, the engine starts with 0 entries. You have two options:

**Option A — Upload via UI:**
1. Go to **Crosswalk** tab (Tab 6)
2. Click **Upload Crosswalks**
3. Select your 3 CSV files:
   - `p21_headers.csv` (SO history)
   - `p21_lines.csv` (SO line items)
   - `p21_customers.csv` (customer master)

**Option B — Place files manually:**
```powershell
# Copy your crosswalk CSVs into the data directory
copy "path\to\customer_crosswalk.csv" "data\crosswalks\"
copy "path\to\customer_item_crosswalk.csv" "data\crosswalks\"
# etc.
```
Then restart the server so it picks them up.

### Step 4: Test the Flow
1. Go to **Review Queue** tab
2. Upload a test PO: drag a PDF/XML/CSV into the file drop zone
3. Select source (Ariba/Coupa/Direct)
4. Watch it appear in the queue with a confidence badge
5. Click it → review details → Approve or Edit

---

## Production Deployment

### Option A: Render (Recommended for Web Service)

1. **Push code to GitHub**
2. **Create new Web Service** on Render
3. **Connect your repo**
4. **Set environment variables** in Render dashboard (see `03_CREDENTIALS_AND_ENV_GUIDE.md`)
5. **Create a disk** (persistent storage) mounted at `/app/data`
6. **Deploy**

Render will:
- Build from `Dockerfile`
- Start `uvicorn src.server:app --host 0.0.0.0 --port $PORT`
- Serve static files from `static/`

**Post-deploy:**
- Upload crosswalk CSVs via the UI
- Or sync from Azure Blob if `BLOB_CONNECTION_STRING` is set

---

### Option B: Azure Container Apps

1. **Build Docker image**
```bash
docker build -t enpro-po-agent:latest .
docker tag enpro-po-agent:latest enproregistry.azurecr.io/enpro-po-agent:latest
docker push enproregistry.azurecr.io/enpro-po-agent:latest
```

2. **Deploy using Bicep**
```bash
az deployment group create \
  --resource-group enpro-rg \
  --template-file azure/container-app.bicep \
  --parameters containerImage=enproregistry.azurecr.io/enpro-po-agent:latest
```

3. **Mount Azure Files** for persistent storage at `/app/data`

4. **Set secrets** in Container App Environment Variables

---

## When Crosswalks Are Missing

On first start, if `data/crosswalks/` has no CSVs:

```
WARNING: Crosswalk file not found: .\data\crosswalks\customer_crosswalk.csv
INFO: customer_crosswalk: 0 entries
```

**This is normal.** The system still works — it just has nothing to match against. All incoming POs will score red until crosswalks are loaded.

**Fix:** Upload via UI Tab 6, or place CSVs manually and restart.

---

## Health Checks

| Endpoint | Expected Response | What It Means |
|----------|-------------------|---------------|
| `GET /health` | `{"status":"healthy"}` | Server is alive |
| `GET /health` | `disk: {...}` | Shows disk usage (used/free/total MB) |
| `GET /api/v1/stats` | Queue counts, crosswalk counts | Dashboard data source |
| `GET /docs` | Swagger UI | Interactive API documentation |

---

## Restarting the Server

**After code changes:** Uvicorn `--reload` handles this automatically.

**After crosswalk changes:** The engine caches crosswalks in memory. Two ways to invalidate:
1. Restart the server
2. Trigger a crosswalk rebuild via UI Tab 6 → **Build Crosswalks**

---

## Backup Strategy

| Data | Location | Backup Method |
|------|----------|---------------|
| Crosswalk CSVs | `data/crosswalks/` | Azure Blob sync (automatic if configured) |
| PO store | `data/po_store/` | Azure Blob sync |
| CISM output | `data/cism_so_output/` | Manual download as needed |
| CISM batch | `data/cism_batch/` | Cleared after upload to Azure Blob |
| Audit log | SQLite (future) | Azure SQL or blob backup |

---

## Rollback

If a deploy breaks something:
1. Revert the commit on GitHub
2. Render auto-redeploys from latest commit
3. If data is corrupted, restore from Azure Blob or local backup

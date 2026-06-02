# EnPro PO Agent — Credentials & Environment Guide

**Security Rule #1:** Never commit `.env` files. Never paste secrets in chat. Use Render dashboard or Azure Key Vault.

---

## Quick Reference Table

| Variable | Required For | Local Dev | Production | Where to Get It |
|----------|-------------|-----------|------------|-----------------|
| `APP_API_KEY` | Protecting mutating API routes | Leave empty | ✅ Required | Generate random string (e.g., `openssl rand -hex 32`) |
| `ADMIN_PASSPHRASE` | Admin-mode UI tabs | Set to `enpro-admin` or custom | ✅ Required | Choose a passphrase, share with Brittany |
| `BLOB_CONNECTION_STRING` | Azure Blob crosswalk sync | Leave empty | ✅ Required | Azure Portal → Storage Account → Access Keys |
| `DOC_INTEL_KEY` | PDF parsing | Leave empty (parsing falls back) | ✅ Required | Azure Portal → Cognitive Services → Keys |
| `GRAPH_CLIENT_ID` | Email polling | Leave empty | ✅ Required | Azure AD → App Registrations → New |
| `GRAPH_CLIENT_SECRET` | Email polling | Leave empty | ✅ Required | Same app → Certificates & Secrets → New |
| `GRAPH_TENANT_ID` | Email polling | Leave empty | ✅ Required | Azure AD → Properties → Tenant ID |
| `P21_BASE_URL` | Live P21 API submit | Leave empty | ⚠️ Optional | P21 admin (e.g., `https://p21.enproinc.com/api`) |
| `P21_API_USERNAME` | Live P21 API submit | Leave empty | ⚠️ Optional | P21 admin |
| `P21_API_PASSWORD` | Live P21 API submit | Leave empty | ⚠️ Optional | P21 admin |
| `P21_DEFAULT_TAKER` | CISM taker code | `SYSTEM` | `POAGENT` | Choose (POAGENT = trackable in P21) |
| `ENABLE_INVOICE_SYNC` | Invoice module | `false` | `false` until ready | Toggle when Coupa API ready |

---

## Local Dev `.env` (Brittany's Sandbox)

Create `C:\Users\Dekan AI Brother\Desktop\EnPro-PO-Agent-Ariba-Coupa\.env.local`:

```bash
# ── App ──
PORT=8000
ENVIRONMENT=development
DEBUG=false

# ── Security ──
# Leave APP_API_KEY empty in local dev
APP_API_KEY=
ADMIN_PASSPHRASE=enpro-admin

# ── Azure (all empty in local dev) ──
BLOB_CONNECTION_STRING=
DOC_INTEL_KEY=
GRAPH_CLIENT_ID=
GRAPH_CLIENT_SECRET=
GRAPH_TENANT_ID=

# ── P21 (empty = disabled) ──
P21_BASE_URL=
P21_API_USERNAME=
P21_API_PASSWORD=
P21_VERIFY_SSL=false
P21_DEFAULT_TAKER=SYSTEM
P21_AUTO_SUBMIT_ON_APPROVE=false

# ── Paths (Windows) ──
CROSSWALK_DIR=.\data\crosswalks
CISM_OUTPUT_DIR=.\data\cism_output
CISM_SO_OUTPUT_DIR=.\data\cism_so_output
CISM_BATCH_DIR=.\data\cism_batch
PO_STORE_DIR=.\data\po_store
```

---

## Production Checklist (Render)

Before going live, set these in the Render dashboard:

```
APP_API_KEY=<random-hex-32>
ADMIN_PASSPHRASE=<strong-passphrase>
BLOB_CONNECTION_STRING=<from-azure-portal>
DOC_INTEL_KEY=<from-azure-portal>
GRAPH_CLIENT_ID=<from-azure-ad>
GRAPH_CLIENT_SECRET=<from-azure-ad>
GRAPH_TENANT_ID=<from-azure-ad>
P21_BASE_URL=<p21-server-url>
P21_API_USERNAME=<p21-user>
P21_API_PASSWORD=<p21-password>
P21_VERIFY_SSL=true
P21_DEFAULT_TAKER=POAGENT
P21_AUTO_SUBMIT_ON_APPROVE=false
ENVIRONMENT=production
```

---

## Where Each Secret Lives

### Azure Blob Storage
1. Azure Portal → Storage Accounts → `enproaidatav1`
2. Access Keys → Copy connection string
3. Container name: `ariba-coupa`

### Azure Document Intelligence
1. Azure Portal → Cognitive Services → `enpro-filtration-ai`
2. Keys and Endpoint → Copy KEY 1

### Microsoft Graph API (Email)
1. Azure AD → App Registrations → New registration
2. Name: `EnPro-PO-Agent-Email`
3. Supported account types: Single tenant
4. Redirect URI: `http://localhost:8000/auth/callback` (for OAuth flow if needed)
5. Certificates & Secrets → New client secret
6. API Permissions → Add `Mail.Read` (Microsoft Graph)
7. Grant admin consent

### P21 Transaction API
- Contact EnPro IT / P21 administrator
- Needs: base URL, username, password
- Verify P21 Middleware (Transaction API v2) is installed
- Test connectivity: `curl -u user:pass https://p21-server/api/health`

---

## Secret Rotation

| Secret | Rotate When | How |
|--------|------------|-----|
| `APP_API_KEY` | Quarterly, or if leaked | Generate new, update Render dashboard, restart |
| `GRAPH_CLIENT_SECRET` | When it expires (max 24 months) | Azure AD → New secret → Update Render → Restart |
| `P21_API_PASSWORD` | Quarterly, or on staff change | P21 admin resets → Update Render → Restart |
| `BLOB_CONNECTION_STRING` | If compromised | Azure Portal → Regenerate keys → Update Render |

---

## Troubleshooting

**"Blob client not configured" in logs**
→ Normal for local dev. Set `BLOB_CONNECTION_STRING` for sync.

**"Graph API credentials not configured"**
→ Normal for local dev. Email polling disabled without credentials.

**"P21 API not configured"**
→ Normal for sandbox mode. CISM CSV export still works.

**"Crosswalks missing"**
→ Place CSV files in `data/crosswalks/` or upload via UI Tab 6.

# Go-Live Checklist — EnPro PO Agent

**Two modes:** Payload-Export Mode (current sandbox) and Live P21 API Submit Mode (future).

---

## Mode 1: Payload-Export Mode (Current — Active in Sandbox)

Inbox → Parse → Review → Approve → CISM batch + downloadable P21 payload JSON.  
No direct P21 API calls. Safe to operate now.

### Required Env Vars (must be set in Render dashboard)

| Var | Purpose | Status |
|---|---|---|
| `AZURE_TENANT_ID` | Azure AD tenant for Graph auth | ✅ Set |
| `AZURE_CLIENT_ID` | App registration client ID | ✅ Set |
| `AZURE_CLIENT_SECRET` | App registration secret | ✅ Set |
| `GRAPH_TENANT_ID` | Graph API tenant (same as AZURE_TENANT_ID) | ✅ Set |
| `GRAPH_CLIENT_ID` | Graph API client ID | ✅ Set |
| `GRAPH_CLIENT_SECRET` | Graph API client secret | ✅ Set |
| `GRAPH_MAILBOX` | Mailbox to poll for PO emails | ✅ Set |
| `DOC_INTEL_ENDPOINT` | Azure Document Intelligence endpoint | ✅ Set |
| `DOC_INTEL_KEY` | Azure Document Intelligence key | ✅ Set |
| `AZURE_BLOB_CONNECTION_STRING` | Blob storage (crosswalk sync) | Set if crosswalk sync needed |
| `AZURE_BLOB_CONTAINER_NAME` | Container name (`ariba-coupa`) | ✅ Set via render.yaml |

### Preflight Checks

- [ ] `GET /health` returns `{"status":"healthy"}`
- [ ] `POST /api/v1/intake/poll-now` returns `{"emails_found":N,"processed":N,"errors":[]}`
- [ ] Review queue loads in UI without error
- [ ] One green PO → Download P21 Payload → file opens as valid JSON with `"Name":"Order"`
- [ ] Approve one PO → CISM Batch tab shows 1 header, correct line count

### Rollback

- Render: revert to previous deploy via Render dashboard → Deploys → previous deploy → **Redeploy**
- No database to rollback; POs are stored on `/app/data` persistent disk (1 GB, survives redeploys)

---

## Mode 2: Live P21 API Submit Mode (Future — Not Active)

Inbox → Parse → Review → Approve → **direct SO creation in P21 via Transaction API**.

### Additional Env Vars Required

| Var | Purpose | Notes |
|---|---|---|
| `P21_BASE_URL` | P21 server base URL (e.g. `https://p21.company.com`) | No trailing slash |
| `P21_API_USERNAME` | P21 API username | Service account preferred |
| `P21_API_PASSWORD` | P21 API password | Store in Render dashboard only |
| `P21_VERIFY_SSL` | Whether to verify P21 TLS cert (`true`/`false`) | Default: `false` |
| `P21_DEFAULT_TAKER` | Default SO taker code in P21 | Default: `POAGENT` |
| `P21_LOCATION_ID` | Default source location ID | Default: `10` |
| `P21_COMPANY_ID` | Default company ID | Default: `1` |

### Activation Steps

1. Set all three required P21 vars in Render dashboard → Environment → Save Changes.
2. Confirm a new deploy starts (visible in Render Events tab).
3. Wait for deploy to go live (~2–4 min).
4. Run preflight checks (above).
5. Approve one low-risk test PO and confirm approve response includes:
   ```json
   { "p21": { "method": "api", "status": "success", "order_no": "XXXXXX" } }
   ```
6. If `method` is still `"cism"`, the P21 vars did not take effect — check Render env var count (should be 14+).

### P21 API Auth Flow (for reference)

1. `POST {P21_BASE_URL}/api/security/token/v2` → Bearer token
2. `GET {P21_BASE_URL}/api/ui/router/v1?urlType=external` → UI server URL
3. `POST {ui_server}/api/v2/transaction` → create Sales Order

### Rollback for Live Submit

- Remove `P21_BASE_URL` from Render env vars → service falls back to CISM mode automatically.
- No data loss; SO creation in P21 is irreversible if it succeeded.

---

## Key File Locations (on Render persistent disk)

| Path | Contents |
|---|---|
| `/app/data/po_store/` | JSON records for every ingested PO |
| `/app/data/cism_so_output/` | Generated CISM SO header and line CSVs |
| `/app/data/crosswalks/` | Customer and item crosswalk CSVs (synced from blob) |

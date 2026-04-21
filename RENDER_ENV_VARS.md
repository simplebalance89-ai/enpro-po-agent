# Render Environment Variables

This file is the source of truth for environment variables used by the app in Render.

Rule:
- Safe, non-secret defaults may live in `render.yaml`.
- Credentials, secrets, and endpoints must be set manually in the Render dashboard and never committed.

## Runtime note

The production service (`enpro-po-agent`) uses **Docker** runtime (not Python native).
The Dockerfile in the repo root handles all build steps including ODBC driver installation.
`render.yaml` documents intent; the live service is configured via the Render dashboard.

## Must be set manually in Render dashboard (never in any committed file)

### Azure Blob Storage
- `AZURE_BLOB_CONNECTION_STRING`

### Azure Document Intelligence (required for PDF PO parsing)
- `DOC_INTEL_ENDPOINT`
- `DOC_INTEL_KEY`

### Azure OpenAI (optional — AI-assisted field mapping)
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_KEY`
- `AZURE_OPENAI_MODEL`

### Microsoft Graph API (email poller)
The app supports both `AZURE_*` and `GRAPH_*` naming conventions.
- `GRAPH_TENANT_ID`
- `GRAPH_CLIENT_ID`
- `GRAPH_CLIENT_SECRET`
- `GRAPH_MAILBOX`
- `AZURE_TENANT_ID` (alias — set to same tenant as GRAPH_TENANT_ID)
- `AZURE_CLIENT_ID` (alias — set to same app as GRAPH_CLIENT_ID)
- `AZURE_CLIENT_SECRET` (alias — set to same secret as GRAPH_CLIENT_SECRET)

### P21 Transaction API
- `P21_BASE_URL`
- `P21_API_USERNAME`
- `P21_API_PASSWORD`

### SQL / DB (optional)
- `STAGING_SQL_SERVER`
- `STAGING_SQL_USERNAME`
- `STAGING_SQL_PASSWORD`
- `P21_SQL_SERVER`
- `P21_SQL_DATABASE`
- `P21_SQL_UID`
- `P21_SQL_PWD`

### Dynamics 365 CRM (optional)
- `DYNAMICS_ORG_URL`
- `DYNAMICS_CLIENT_ID`
- `DYNAMICS_CLIENT_SECRET`
- `DYNAMICS_TENANT_ID`

## Safe to set in render.yaml (non-secret defaults)

- `ENVIRONMENT`
- `AZURE_BLOB_CONTAINER_NAME`
- `STAGING_SQL_DATABASE`
- `CROSSWALK_DIR`
- `CISM_OUTPUT_DIR`
- `CISM_SO_OUTPUT_DIR`
- `PO_STORE_DIR`
- `P21_VERIFY_SSL`
- `P21_DEFAULT_TAKER`
- `P21_COMPANY_ID`
- `P21_LOCATION_ID`
- `POLL_INTERVAL`
- `GRAPH_POLL_INTERVAL`

## Notes

- Render provides `PORT` automatically; do not hardcode it.
- `TEST_BASE_URL` is test-only and not required for Render runtime.
- Without `DOC_INTEL_ENDPOINT` and `DOC_INTEL_KEY`, PDF PO parsing will fail with HTTP 401.
  Set both in the dashboard to enable the full PDF intake flow.

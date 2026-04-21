# Render Environment Variables

This file is the source of truth for environment variables used by the app in Render.

Rule:
- Safe, non-secret defaults may live in `render.yaml`.
- Credentials, secrets, and connection-string-style values must be set manually in the Render dashboard and never committed.

## Safe in `render.yaml` (non-secret defaults)

- `PYTHON_VERSION`
- `ENVIRONMENT`
- `AZURE_BLOB_CONTAINER_NAME`
- `STAGING_SQL_DATABASE`
- `CROSSWALK_DIR`
- `CISM_OUTPUT_DIR`
- `CISM_SO_OUTPUT_DIR`
- `PO_STORE_DIR`
- `P21_DATA_DIR`
- `QUOTE_DATA_DIR`
- `AZURE_BLOB_APPROVED_PREFIX`
- `AZURE_BLOB_REJECTED_PREFIX`
- `CISM_BATCH_DIR`
- `CROSSWALK_VENDOR_CSV`
- `CROSSWALK_ITEM_CSV`
- `P21_VERIFY_SSL`
- `P21_DEFAULT_TAKER`
- `P21_COMPANY_ID`
- `P21_LOCATION_ID`
- `POLL_INTERVAL`
- `GRAPH_POLL_INTERVAL`

## Must be set manually in Render dashboard (never in file)

- `AZURE_BLOB_CONNECTION_STRING` (connection string secret)
- `STAGING_SQL_SERVER` (internal endpoint; treat as sensitive infra config)
- `STAGING_SQL_USERNAME` (credential)
- `STAGING_SQL_PASSWORD` (credential)
- `DOC_INTEL_ENDPOINT` (service endpoint; keep with related secret config)
- `DOC_INTEL_KEY` (secret)
- `AZURE_OPENAI_ENDPOINT` (service endpoint; keep with related secret config)
- `AZURE_OPENAI_KEY` (secret)
- `AZURE_OPENAI_MODEL` (deployment-specific setting; keep with AOAI config)
- `P21_BASE_URL` (internal service endpoint)
- `P21_API_USERNAME` (credential)
- `P21_API_PASSWORD` (credential)
- `DYNAMICS_ORG_URL` (tenant/org endpoint)
- `DYNAMICS_CLIENT_ID` (app identity)
- `DYNAMICS_CLIENT_SECRET` (secret)
- `DYNAMICS_TENANT_ID` (tenant identifier)
- `P21_SQL_SERVER` (internal DB endpoint)
- `P21_SQL_DATABASE` (DB target)
- `P21_SQL_UID` (credential)
- `P21_SQL_PWD` (credential)
- `AZURE_TENANT_ID` (Graph auth alias)
- `AZURE_CLIENT_ID` (Graph auth alias)
- `AZURE_CLIENT_SECRET` (Graph auth alias secret)
- `GRAPH_TENANT_ID` (Graph auth)
- `GRAPH_CLIENT_ID` (Graph auth)
- `GRAPH_CLIENT_SECRET` (Graph auth secret)
- `GRAPH_MAILBOX` (target mailbox identity)

## Current Graph/email poller values (for dashboard entry)

- `GRAPH_TENANT_ID`: `cef9f0a2-ca34-41d0-a6e6-45631b486411`
- `GRAPH_CLIENT_ID`: `bda7e772-b6b7-4b54-a0d9-6bd566b89e66`
- `GRAPH_CLIENT_SECRET`: set from local `.env` value (do not commit)
- `GRAPH_MAILBOX`: `PeterWilson@GCEstack.onmicrosoft.com`

## Notes

- Email poller supports both naming conventions:
  - `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`
  - `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET`
- Render provides `PORT` automatically; do not hardcode it in `render.yaml`.
- `TEST_BASE_URL` is test-only and not required for Render runtime.

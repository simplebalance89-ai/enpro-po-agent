# Microsoft 365 Inbox Setup for PO Intake

## Overview
The PO intake email poller connects to a Microsoft 365 mailbox, reads incoming messages, and routes qualifying purchase-order attachments into the PO processing pipeline.

Graph API access is required because the poller uses Microsoft Graph application permissions to:
- Read mailbox folders and messages
- Download attachments for processing
- Move processed messages to target folders

This guide is for setting up the production mailbox `orders@enproinc.com`.

## Azure AD App Registration

1. Go to `https://portal.azure.com`.
2. Open **Microsoft Entra ID**.
3. Go to **App registrations** > **New registration**.
4. Set:
- **Name**: `enpro-po-agent`
- **Supported account types / Audience**: `AzureADandPersonalMicrosoftAccount`
5. Create the app.
6. Record these values from the app overview:
- **Tenant ID**
- **Client ID**
7. Go to **Certificates & secrets**.
8. Select **New client secret**.
9. Create the secret and immediately record the **secret value**.

## API Permissions Required

1. In the app, open **API permissions**.
2. Select **Add a permission** > **Microsoft Graph** > **Application permissions**.
3. Add:
- `Mail.Read`
- `Mail.ReadWrite`
- `Mail.Send`
4. Select **Grant admin consent** for the tenant.
5. Confirm status shows granted for all three permissions.

## Environment Variables
Set these in Render dashboard (or Azure Key Vault-backed deployment config):

- `GRAPH_TENANT_ID`
- `GRAPH_CLIENT_ID`
- `GRAPH_CLIENT_SECRET`
- `GRAPH_MAILBOX` = `orders@enproinc.com`

## How the Poller Works
- Poll interval is controlled by environment variable (`POLL_INTERVAL`, default 60 seconds).
- The poller checks the configured mailbox inbox via Microsoft Graph.
- It identifies candidate PO emails.
- It downloads supported attachments.
- It routes parsed payloads into the intake pipeline and review queue.
- It moves or updates processed messages to prevent duplicate handling.

## Email Requirements for PO Intake
- Subject line must contain `PO`.
- Attachment must be PDF.
- Sender filtering is planned for a future update.

## Testing the Connection
Trigger immediate polling:

```bash
POST /api/v1/intake/poll-now
```

Expected result:
- API response confirms poll run status.
- Matching mailbox email is discovered.
- Attachment processing is attempted.
- Intake/review queue entries appear when parsing succeeds.

## Switching from Test to Production
No code change is required.

Only update:
- `GRAPH_MAILBOX`

Set it to the target production mailbox (`orders@enproinc.com`).

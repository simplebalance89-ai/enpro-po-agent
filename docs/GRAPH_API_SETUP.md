# Microsoft Graph API Setup — EnPro PO Agent

## What This Is For

The PO Automation Agent needs to read emails from `orders@enproinc.com` to automatically process incoming purchase orders. It reads email attachments (PDF and XML files), processes them through our crosswalk system, and queues them for review.

The agent needs **read-only access** to one mailbox. It does not send emails or modify mailbox content (except moving processed emails to a subfolder).

## What We Need From IT

Three values after setup:
1. **Tenant ID** (your Azure AD tenant)
2. **Client ID** (the app registration ID)
3. **Client Secret** (the app's password)

## Step-by-Step Setup

### 1. Register an App in Azure AD

1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations
2. Click **+ New registration**
3. Settings:
   - **Name:** `EnPro PO Agent - Mail Reader`
   - **Supported account types:** "Accounts in this organizational directory only (EnPro Inc only - Single tenant)"
   - **Redirect URI:** Leave blank (not needed for daemon/service apps)
4. Click **Register**
5. Copy the **Application (client) ID** — this is the Client ID we need
6. Copy the **Directory (tenant) ID** — this is the Tenant ID we need

### 2. Create a Client Secret

1. In the app registration, go to **Certificates & secrets**
2. Click **+ New client secret**
3. Description: `PO Agent Mail Access`
4. Expiration: 24 months (recommended)
5. Click **Add**
6. **IMMEDIATELY copy the Value** (it won't be shown again) — this is the Client Secret we need

### 3. Set API Permissions

1. In the app registration, go to **API permissions**
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Select **Application permissions** (NOT delegated)
5. Add these permissions:
   - `Mail.Read` — Read mail in all mailboxes (we will scope it down in step 4)
   - `Mail.ReadWrite` — Required to move processed emails to a subfolder
6. Click **Add permissions**
7. Click **Grant admin consent for EnPro Inc** (requires Global Admin)

### 4. Scope Access to One Mailbox (Recommended)

By default, `Mail.Read` grants access to ALL mailboxes. To restrict to only `orders@enproinc.com`:

1. Open **Exchange Admin Center** (https://admin.exchange.microsoft.com)
2. Or use PowerShell:

```powershell
# Connect to Exchange Online
Connect-ExchangeOnline -UserPrincipalName admin@enproinc.com

# Create an application access policy scoping to orders@ only
New-ApplicationAccessPolicy `
  -AppId "<Client ID from step 1>" `
  -PolicyScopeGroupId "orders@enproinc.com" `
  -AccessRight RestrictAccess `
  -Description "PO Agent - orders mailbox only"

# Verify the policy
Test-ApplicationAccessPolicy `
  -AppId "<Client ID>" `
  -Identity "orders@enproinc.com"
# Should return: "Granted"

Test-ApplicationAccessPolicy `
  -AppId "<Client ID>" `
  -Identity "someother@enproinc.com"  
# Should return: "Denied"
```

### 5. Create Subfolders in the Mailbox

Create these folders in the orders@enproinc.com mailbox (Outlook or OWA):
- **Processed-PO** — successfully processed emails move here
- **Failed-PO** — emails that failed parsing move here

### 6. Send Us the Three Values

Send these securely (not in plain email — use a password manager share, Teams DM, or encrypted channel):

| Value | Example |
|-------|---------|
| Tenant ID | `3c91d890-f683-4d42-a4e8-1688784e1892` |
| Client ID | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| Client Secret | `abc123~xYz456-SecretValue` |

## How the Agent Uses It

- Polls every 60 seconds for new unread emails
- Checks for PDF/XML attachments
- Downloads and parses attachments
- Moves processed emails to Processed-PO folder
- All processing is read + move only — no emails are sent or deleted
- The agent runs on Azure (not on any EnPro server)

## Security Notes

- The app uses **application permissions** (daemon flow), not user-delegated
- No user login required — it authenticates with the client secret
- Scoped to the orders@ mailbox only (if step 4 is completed)
- Client secret should be rotated before expiration
- All access is logged in Azure AD sign-in logs under the app name

## Questions?

Contact Peter Wilson (peterw_conveyance@enproinc.com)

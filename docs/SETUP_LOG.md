## 2026-04-20 — Email Inbox Proof of Concept
- Registered Azure AD app: enpro-po-agent-test (GCE tenant)
- Granted Mail.Read, Mail.ReadWrite, Mail.Send with admin consent
- Test mailbox: PeterWilson@GCEstack.onmicrosoft.com
- Completed email_poller.py TODO at line 307 — PDF and cXML routing
- Added POST /api/v1/intake/poll-now endpoint to server.py
- Confirmed end-to-end: email found → Document Intelligence reached → PO in review queue
- Real PDF test pending

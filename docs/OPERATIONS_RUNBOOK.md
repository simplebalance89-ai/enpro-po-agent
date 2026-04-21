# Operations Runbook — EnPro PO Agent

**Audience:** Brittany / daily operator  
**Service URL:** https://enpro-po-agent.onrender.com  
**Last updated:** 2026-04-21

---

## Daily Workflow

1. Open the UI at https://enpro-po-agent.onrender.com
2. Click **Review Queue** tab — new POs appear here after automatic email polling (runs every few minutes) or after a manual poll (see below).
3. Click any PO card in the left sidebar to open it in the detail panel.
4. Review confidence badge:
   - **GREEN** — all fields matched. Safe to approve immediately.
   - **YELLOW** — partial match. Verify item IDs and customer before approving.
   - **RED** — customer or items unmatched. Must edit before approving (see below).
5. Click **Approve & Create SO** to approve and generate the CISM batch file.
6. Click **Download P21 Payload** to save the P21 Transaction API payload JSON to your machine.

---

## Manually Triggering an Email Poll

```
POST https://enpro-po-agent.onrender.com/api/v1/intake/poll-now
```

Or open the URL in a tool like Postman / curl. Returns:
```json
{ "emails_found": N, "processed": N, "errors": [] }
```

---

## Handling Red POs (Unmatched Customer or Items)

1. Select the red PO in the queue.
2. Click **Edit PO**.
3. Fill in the correct P21 Customer ID and/or Item IDs.
4. Click **Save** — the system re-scores. If all fields resolve, confidence upgrades to green.
5. Review the updated result, then approve or reject.

If you cannot find the correct IDs, click **Reject** and note the reason. The PO stays in history but won't enter the batch.

---

## Exporting a P21 Payload JSON

- Select any PO in the queue → click **Download P21 Payload**.
- File saved as: `p21_payload_<po_no>_<intake_id>.json`
- For already-approved POs: go to **Processed** tab → click **P21 JSON** in the Download column.
- This file is for review or manual submission only — it does **not** auto-submit to P21.

---

## Approving a Batch and Downloading CISM Files

1. Go to **CISM Batch** tab.
2. Review the header and line counts.
3. Click **Download Header CSV** and **Download Lines CSV**.
4. Upload both files to Azure Blob (`ariba-coupa` container) for P21's scheduled import job.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Queue is empty after poll | No new emails in mailbox | Check `PeterWilson@GCEstack.onmicrosoft.com` inbox directly |
| poll-now returns 401 | Graph API credentials expired | Rotate `GRAPH_CLIENT_SECRET` in Azure AD, update Render env var |
| PDF PO not parsed | Document Intelligence key invalid | Rotate `DOC_INTEL_KEY` in Azure, update Render env var |
| Payload download returns 500 | Rare — check if `httpx` is installed | Redeploy service; package is in requirements.txt |
| Approve returns "already approved" | PO was previously approved | Normal — check Processed tab for the CISM file |
| Customer not matched (score 0) | Ship-to name/zip not in crosswalk | Use Edit PO to manually set `customer_id_p21` |
| Item not matched (UNMAPPED) | Part number not in crosswalk | Use Edit PO to set `item_id_p21` from P21 item catalog |
| Service returns 502 | Render is deploying a new version | Wait ~2 minutes and refresh |

---

## Service Health Check

```
GET https://enpro-po-agent.onrender.com/health
```

Expected: `{"status":"healthy","environment":"production"}`

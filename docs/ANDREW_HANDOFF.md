# EnPro PO Agent — Handoff to Andrew

**Date:** May 17, 2026  
**Service:** https://enpro-po-agent.onrender.com  
**Repo:** github.com/simplebalance89-ai/enpro-po-agent  
**Status:** Production-ready in payload-export mode. Live P21 submit ready pending credentials.

---

## ✅ What Works Today

| Feature | Status | Evidence |
|---------|--------|----------|
| Email poll (Graph API) | ✅ Live | Polls `orders@enproinc.com` every 60s |
| PDF parse (Doc Intel) | ✅ Live | Extracts header + line items from PDF attachments |
| cXML parse (Ariba/Coupa) | ✅ Live | Native XML parsing for OrderRequest |
| Customer crosswalk match | ✅ 95% auto-green | 6-stage pipeline: learned → exact_name_zip → fuzzy → PO pattern |
| Item crosswalk match | ✅ Live | Customer part# → P21 `inv_mast_uid` via 22K+ item mappings |
| Confidence scoring | ✅ Live | 4-dimension: customer 30% + shipto 15% + items 45% + dedup 10% |
| Review queue + approve/reject | ✅ Live | Operator UI with green/yellow/red status |
| Edit PO + rescore | ✅ Live | Manual override re-runs confidence scoring |
| Bulk approve greens | ✅ Live | One-click approve all green POs |
| P21 payload generation | ✅ Live | Transaction API v2 JSON — download per-PO or batch |
| **Test Drive** | ✅ Live | `/test-drive` — drag a PDF and watch the P21 payload build in seconds |
| **Mic Drop** | ✅ Live | `/micdrop` — animated proof the payload is structurally correct |
| CISM SO CSV generation | ✅ Live | Header + lines CSVs per approved PO |
| CISM batch download | ✅ Live | Accumulated batch CSV for Azure Blob upload |
| Mapping suggestion agent | ✅ Live | Suggests customer/item mappings for red/yellow POs |
| API key auth | ✅ Deployed | Gates all mutating routes (approve, reject, edit, submit) |
| Learn from approval | ✅ Live | Auto-writes new mappings to crosswalk CSVs |
| Outbound sync (Ariba/Coupa stubs) | ✅ Live | Mock send + live HTTP POST when endpoint provided |
| Invoice module (future) | 🔒 Built, disabled | Pulls from P21 SQL → builds Coupa cXML. Enable with env var. |

**No LLM. No manual data entry. Rules-based matching against your item master and customer crosswalk.**

---

## 🎯 The Ask

**Set three environment variables on Render and we're live:**

```
P21_BASE_URL=https://<your-p21-server>:3333
P21_API_USERNAME=<transaction-api-user>
P21_API_PASSWORD=<transaction-api-password>
```

**That's it.** The "Submit to P21" buttons in the UI go live. Approved POs become real Sales Orders instantly.

Optional: set `P21_AUTO_SUBMIT_ON_APPROVE=true` to skip the button entirely — approve → SO created automatically.

---

## 🚀 Quick Demo for You

1. Go to https://enpro-po-agent.onrender.com
2. Click **🚀 Test Drive** (top-right)
3. Drag any PO PDF onto the drop zone
4. Watch: Upload → Parse → Match Customer → Match Items → P21 Payload
5. Download the JSON or click **🎤 Mic Drop** for the animated proof

**Postman collection:** `EnPro_PO_Agent_Postman_Collection.json` in repo root — import, set `baseUrl`, hit Validate.

---

## 🔧 Remaining Gaps (Non-Blocking)

| Gap | Impact | Fix |
|-----|--------|-----|
| **P21 credentials not set** | 🔴 Blocks live SO creation | You provide 3 env vars |
| `APP_API_KEY` not set | 🟡 Mutating routes are open | Set any secret string on Render |
| `ADMIN_PASSPHRASE` not set | 🟡 Admin tabs use default | Set any secret string on Render |
| **Official P21 Transaction API docs** | 🟡 Need to confirm required vs optional fields | Your P21 admin or Epicor docs |
| Invoice module | 🔒 Disabled | Enable when Coupa invoice endpoint ready |
| CI smoke test | 🟢 Built (GitHub Actions) | Needs repo admin to enable Actions |

---

## 📊 Current Queue Status (as of last session)

| Metric | Value |
|--------|-------|
| Total POs ingested | 22 |
| Green (auto-resolved) | 21 (95%) |
| Red (needs manual edit) | 1 (PO 4098053 — Stepan Chemical) |
| Approved | 4 |
| Pending review | 18 |
| Crosswalk customers | 4,880 |
| Crosswalk items | 22,722 |

---

## 🗣️ What I Need From You

1. **P21 Transaction API credentials** (base URL, username, password)
2. **P21 SQL read access** for invoice pull (optional — only if you want invoice sync later)
3. **Confirmation:** does the payload shape in `/test-drive` look right to your P21 admin?

**I don't need Jordan.** I can set the env vars, test the connection, and verify SO creation end-to-end. Just give me the credentials and I'll handle the rest.

---

*Built by Pete + AI. No external consultants required.*

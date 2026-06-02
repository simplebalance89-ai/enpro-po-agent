# EnPro PO Agent — Solution Overview

**What this tool does:** Automatically reads purchase orders from email (Ariba, Coupa, direct PDF), matches them to P21 customer and item master data, scores confidence, and generates CISM import files for P21 Sales Order creation.

**Who uses it:** Brittany (operations) reviews yellow/red POs in the browser. The system auto-approves green ones.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EMAIL INTAKE                                       │
│  orders@enproinc.com  →  Microsoft Graph API  →  PDF/XML/CSV attachments    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PARSING                                            │
│  PDF → Azure Document Intelligence    cXML → native parser    CSV → direct  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MATCHING ENGINE                                      │
│  Customer: 6-stage cascade (exact → zip → fuzzy → PO pattern → best → none) │
│  Item:     4-stage cascade (customer-specific → global part → item master)  │
│  Data:     4,880 customers · 22,675 item mappings · 23,452 PO histories     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONFIDENCE SCORER                                     │
│  Customer 30% · Ship-to 15% · Items 45% · Dedup 10%                         │
│  Green ≥ 0.88  ·  Yellow ≥ 0.60  ·  Red otherwise                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        REVIEW QUEUE (Brittany)                               │
│  Green = auto-approve    Yellow = review    Red = manual entry              │
│  Edit PO → search customer, search items, adjust quantities/prices          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OUTPUT GENERATION                                    │
│  ├─ CISM SO CSV (per-PO + batch accumulation)                               │
│  ├─ P21 Transaction API JSON payload (single + batch ZIP)                   │
│  └─ Auto-learn → writes back to crosswalk CSVs                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            P21 IMPORT                                        │
│  CISM Batch CSV  →  Azure Blob  →  Local Machine  →  P21 CISM Import Job   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | Vanilla JS, single `index.html`, no framework |
| Parsing | Azure Document Intelligence (PDF), native cXML/CSV |
| Data | CSV crosswalks (in-memory engine), SQLite fallback |
| Storage | Azure Blob Storage, local filesystem |
| Integration | Microsoft Graph API (email), P21 Transaction API (REST) |
| Deployment | Render (web service) or Azure Container Apps |

---

## Key Integrations

| System | Purpose | Status |
|--------|---------|--------|
| **Ariba** | cXML PO ingestion | ✅ Built |
| **Coupa** | cXML PO ingestion | ✅ Built |
| **Email/Graph API** | Polls `orders@enproinc.com` | ✅ Coded, needs credentials |
| **P21 CISM Import** | CSV-based SO creation | ✅ Generates correct format |
| **P21 Transaction API** | Direct REST SO creation | ✅ Built, disabled pending credentials |
| **Azure Blob** | Crosswalk sync + backup | ✅ Built, needs connection string |
| **Dynamics 365** | Quote lookup | ⚠️ Static CSV only |
| **Invoice Sync** | Coupa invoice matching | ⚠️ Built, disabled behind env var |

---

## Data Assets

| Dataset | Records | Source |
|---------|---------|--------|
| Customer crosswalk | 4,880 | P21 export + learned from approvals |
| Customer-item crosswalk | 22,675 | P21 export + learned from approvals |
| PO history | 23,452 | P21 SO headers |
| Item master | 11,911 | P21 inventory |
| Dynamics quotes | 2,065 | CRM export |
| Quote-to-PO linkage | 910 | CRM + P21 |

---

## Performance

- **Auto-green rate:** ~95% (21 of 22 POs ingested so far)
- **Ingestion latency:** PDF parse ~3-5s, total pipeline ~10s
- **Review queue load:** Near-instant (all data in memory)
- **Batch export:** 1-2s for 10 POs

---

## Security Model

| Level | Protection |
|-------|-----------|
| API mutations | `APP_API_KEY` header required |
| Admin UI tabs | Passphrase gate (`ADMIN_PASSPHRASE`) |
| Env secrets | Never committed; injected via Render dashboard / Azure Key Vault |
| CORS | Restricted to known origins |

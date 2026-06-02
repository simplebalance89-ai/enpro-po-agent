# P21 Crosswalk Data Specification
## For EnPro IT / P21 Team

**Date:** June 1, 2026  
**Purpose:** Document exactly what CSV files the PO Agent portal needs, where the data comes from in P21, and how to get it there.

---

## The Big Picture

```
┌──────────────────────────────────────────────────────────────────────┐
│  P21 SQL Database (on-prem)                                          │
│  Your job: run scheduled queries, export to CSV                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼  Scheduled job (Power Automate / SQL Agent / Task Scheduler)
┌──────────────────────────────────────────────────────────────────────┐
│  Export to CSV → drop in local folder OR upload to Azure Blob        │
│  Frequency: nightly (recommended) or weekly                          │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼  Portal picks up on startup or manual sync
┌──────────────────────────────────────────────────────────────────────┐
│  PO Agent Portal (Render / Azure / Local)                            │
│  Reads crosswalk CSVs into memory for matching                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Required CSV Files (6 total)

All files go in the same folder. The portal reads them on startup.

**File naming is exact.** Do not rename.

| # | Filename | Purpose | Rows (typical) | Refresh Frequency |
|---|----------|---------|---------------|-------------------|
| 1 | `customer_crosswalk.csv` | Maps ship-to names + zip codes to P21 customer IDs | 4,880 | Weekly |
| 2 | `customer_item_crosswalk.csv` | Maps each customer's part numbers to P21 items | 22,675 | Weekly |
| 3 | `customer_po_history.csv` | Links customer PO numbers to P21 SO numbers (dedup) | 23,452 | Daily |
| 4 | `item_master_index.csv` | P21 inventory items (fallback matching) | 11,911 | Weekly |
| 5 | `customers_p21.csv` | P21 customer master (names, addresses) | 7,833 | Weekly |
| 6 | `customer_defaults.csv` | Contact ID, ship-to ID, terms, carrier per customer | 7,833 | Weekly |

---

## File 1: `customer_crosswalk.csv`

**What it does:** When a PO comes in with ship-to name "Waupaca Foundry" and zip "47586", this file tells us "that's P21 customer 207620."

**P21 Source:** Sales Order history (who shipped where) + customer master

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `p21_customer_id` | VARCHAR | customer | customer_id | 207620 |
| `p21_customer_name` | VARCHAR | customer | customer_name | Stepan Chemical |
| `ship2_name` | VARCHAR | ship_to / oe_order | ship_to_name | Waupaca Foundry, Inc. |
| `ship2_zip` | VARCHAR | ship_to / oe_order | zip_code | 47586 |
| `source_system` | VARCHAR | — | — | Ariba, Coupa, Direct |
| `match_method` | VARCHAR | — | — | learned, exact, fuzzy |
| `seen_count` | INT | — | count | 15 |

**Suggested SQL (starting point — adjust to your schema):**

```sql
-- Extract unique customer + ship-to combinations from recent SOs
SELECT DISTINCT
    c.customer_id AS p21_customer_id,
    c.customer_name AS p21_customer_name,
    s.ship_to_name AS ship2_name,
    s.zip_code AS ship2_zip,
    'P21' AS source_system,
    'exact' AS match_method,
    COUNT(*) AS seen_count
FROM oe_order o
JOIN customer c ON o.customer_id = c.customer_id
JOIN ship_to s ON o.ship_to_id = s.ship_to_id
WHERE o.order_date >= DATEADD(year, -3, GETDATE())
  AND o.delete_flag = 'N'
GROUP BY c.customer_id, c.customer_name, s.ship_to_name, s.zip_code
ORDER BY seen_count DESC;
```

---

## File 2: `customer_item_crosswalk.csv`

**What it does:** When customer 207620 orders part "PH0260", this file tells us "that's P21 inv_mast_uid 7931, description is 'Pall Filter Element', UOM is EA."

**P21 Source:** Sales Order line items (what each customer has ordered before)

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `p21_customer_id` | VARCHAR | customer | customer_id | 207620 |
| `customer_part_number` | VARCHAR | oe_order_item | supplier_part_id | PH0260 |
| `p21_inv_mast_uid` | VARCHAR | inv_mast | inv_mast_uid | 7931 |
| `p21_item_desc` | VARCHAR | inv_mast | item_desc | Pall Filter Element |
| `unit_of_measure` | VARCHAR | inv_mast | unit_of_measure | EA |
| `unit_price_avg` | DECIMAL | oe_order_item | unit_price | 185.50 |
| `seen_count` | INT | — | count | 12 |

**Suggested SQL:**

```sql
-- Extract customer-specific part number mappings from SO history
SELECT
    o.customer_id AS p21_customer_id,
    oi.supplier_part_id AS customer_part_number,
    i.inv_mast_uid AS p21_inv_mast_uid,
    i.item_desc AS p21_item_desc,
    i.unit_of_measure,
    AVG(oi.unit_price) AS unit_price_avg,
    COUNT(*) AS seen_count
FROM oe_order_item oi
JOIN oe_order o ON oi.order_no = o.order_no
JOIN inv_mast i ON oi.item_id = i.item_id
WHERE o.order_date >= DATEADD(year, -2, GETDATE())
  AND o.delete_flag = 'N'
  AND oi.supplier_part_id IS NOT NULL
  AND oi.supplier_part_id <> ''
GROUP BY o.customer_id, oi.supplier_part_id, i.inv_mast_uid, i.item_desc, i.unit_of_measure
HAVING COUNT(*) >= 2  -- Only include if ordered at least twice
ORDER BY seen_count DESC;
```

---

## File 3: `customer_po_history.csv`

**What it does:** Prevents duplicate POs. If customer PO "4500819454" was already processed as SO "123456", the system flags it as a duplicate.

**P21 Source:** Sales Order headers (customer PO number field)

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `customer_id` | VARCHAR | customer | customer_id | 207620 |
| `customer_po_no` | VARCHAR | oe_order | po_no | 4500819454 |
| `p21_so_no` | VARCHAR | oe_order | order_no | 123456 |
| `order_date` | DATE | oe_order | order_date | 2026-05-15 |
| `ship_to_name` | VARCHAR | ship_to | ship_to_name | Waupaca Foundry |
| `status` | VARCHAR | oe_order | status | Approved |

**Suggested SQL:**

```sql
-- Extract customer PO to P21 SO linkages
SELECT
    o.customer_id,
    o.po_no AS customer_po_no,
    o.order_no AS p21_so_no,
    o.order_date,
    s.ship_to_name,
    o.approved AS status
FROM oe_order o
LEFT JOIN ship_to s ON o.ship_to_id = s.ship_to_id
WHERE o.po_no IS NOT NULL
  AND o.po_no <> ''
  AND o.order_date >= DATEADD(year, -2, GETDATE())
  AND o.delete_flag = 'N'
ORDER BY o.order_date DESC;
```

---

## File 4: `item_master_index.csv`

**What it does:** Fallback matching. If a part number isn't in the customer-specific crosswalk, search the global item master.

**P21 Source:** `inv_mast` table

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `p21_inv_mast_uid` | VARCHAR | inv_mast | inv_mast_uid | 7931 |
| `item_id` | VARCHAR | inv_mast | item_id | PH0260 |
| `item_desc` | VARCHAR | inv_mast | item_desc | Pall Filter Element |
| `unit_of_measure` | VARCHAR | inv_mast | unit_of_measure | EA |
| `product_group_id` | VARCHAR | inv_mast | product_group_id | FILT |
| `supplier_id` | VARCHAR | inv_mast | supplier_id | 10045 |

**Suggested SQL:**

```sql
-- Extract active inventory items
SELECT
    inv_mast_uid AS p21_inv_mast_uid,
    item_id,
    item_desc,
    unit_of_measure,
    product_group_id,
    supplier_id
FROM inv_mast
WHERE delete_flag = 'N'
ORDER BY item_id;
```

---

## File 5: `customers_p21.csv`

**What it does:** Provides customer names and addresses for display and matching.

**P21 Source:** `customer` and `ship_to` tables

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `customer_id` | VARCHAR | customer | customer_id | 207620 |
| `customer_name` | VARCHAR | customer | customer_name | Stepan Chemical |
| `address_1` | VARCHAR | customer | address_1 | 123 Main St |
| `city` | VARCHAR | customer | city | Chicago |
| `state` | VARCHAR | customer | state | IL |
| `zip_code` | VARCHAR | customer | zip_code | 60601 |
| `country` | VARCHAR | customer | country | US |

**Suggested SQL:**

```sql
-- Extract active customers
SELECT
    customer_id,
    customer_name,
    address_1,
    city,
    state,
    zip_code,
    country
FROM customer
WHERE delete_flag = 'N'
ORDER BY customer_id;
```

---

## File 6: `customer_defaults.csv`

**What it does:** Provides default values for CISM generation and P21 API submission: contact ID, ship-to ID, terms, carrier.

**P21 Source:** `customer_defaults` or `customer` + `ship_to` + `contact` tables

**Required Columns:**

| Column | Type | P21 Source Table | P21 Column | Example |
|--------|------|-----------------|------------|---------|
| `customer_id` | VARCHAR | customer | customer_id | 207620 |
| `default_contact_id` | VARCHAR | contact | contact_id | C001 |
| `default_address_id` | VARCHAR | ship_to | ship_to_id | S001 |
| `default_terms` | VARCHAR | customer | terms_id | NET30 |
| `default_carrier_id` | VARCHAR | customer | carrier_id | UPS |
| `class_1id` | VARCHAR | customer | class_1id | — |

**Suggested SQL:**

```sql
-- Extract customer defaults for CISM
SELECT
    c.customer_id,
    c.contact_id AS default_contact_id,
    c.ship_to_id AS default_address_id,
    c.terms_id AS default_terms,
    c.carrier_id AS default_carrier_id,
    c.class_1id
FROM customer c
WHERE c.delete_flag = 'N'
ORDER BY c.customer_id;
```

**Note:** If your P21 schema stores defaults differently (e.g., in a separate `customer_defaults` table), adjust the query accordingly. The portal just needs these 6 columns.

---

## CSV Format Requirements

All files must follow these rules:

| Requirement | Value |
|-------------|-------|
| Encoding | UTF-8 |
| Delimiter | Comma (`,`) |
| Header row | Yes — first row must be column names exactly as shown above |
| Quote character | Double quote (`"`) |
| Line endings | CRLF or LF (both work) |
| Date format | `YYYY-MM-DD` or `MM/DD/YYYY` |
| Empty values | Leave blank (`,,`) or `""` |
| Decimal separator | Period (`.`) — `185.50` not `185,50` |

---

## Delivery Options

### Option A: Azure Blob (Recommended for Cloud Deploy)

1. P21 team exports CSVs to a local folder
2. Power Automate / AzCopy / custom script uploads to Azure Blob:
   - Container: `ariba-coupa`
   - Path: `crosswalks/`
   - Files: `customer_crosswalk.csv`, `customer_item_crosswalk.csv`, etc.
3. Portal syncs from blob on startup (if `BLOB_CONNECTION_STRING` is set)

**Portal sync endpoint:** `POST /api/v1/admin/sync-crosswalks`

### Option B: Local File Drop (For On-Prem or Local Dev)

1. P21 team exports CSVs to a shared folder
2. Place files in: `C:\Users\...\Desktop\EnPro-PO-Agent-Ariba-Coupa\data\crosswalks\`
3. Restart portal or trigger rebuild via UI

**Portal rebuild endpoint:** `POST /api/v1/crosswalk/build`

### Option C: Manual Upload (One-Off or Emergency)

1. Go to portal → Crosswalk tab (Tab 6)
2. Click **Upload Crosswalks**
3. Select 3 files: `p21_headers.csv`, `p21_lines.csv`, `p21_customers.csv`
4. Click Build

---

## Validation Checklist (For P21 Team)

Before sending CSVs to the portal:

- [ ] All 6 files present with exact filenames
- [ ] First row is headers, exactly matching column names above
- [ ] No duplicate column names within a file
- [ ] `customer_id` / `p21_customer_id` values match between files
- [ ] `inv_mast_uid` / `item_id` values exist in P21
- [ ] `zip_code` has no extra spaces (e.g., "47586" not "47586 ")
- [ ] `unit_price_avg` uses `.` decimal separator
- [ ] Dates are in recognizable format
- [ ] File size is reasonable (customer_item_crosswalk.csv should be largest, ~2-5 MB)

---

## Sample Row (Each File)

### customer_crosswalk.csv
```csv
p21_customer_id,p21_customer_name,ship2_name,ship2_zip,source_system,match_method,seen_count
207620,Stepan Chemical,Waupaca Foundry Inc.,47586,Ariba,learned,15
```

### customer_item_crosswalk.csv
```csv
p21_customer_id,customer_part_number,p21_inv_mast_uid,p21_item_desc,unit_of_measure,unit_price_avg,seen_count
207620,PH0260,7931,Pall Filter Element - High Pressure,EA,185.50,12
```

### customer_po_history.csv
```csv
customer_id,customer_po_no,p21_so_no,order_date,ship_to_name,status
207620,4500819454,123456,2026-05-15,Waupaca Foundry,Approved
```

### item_master_index.csv
```csv
p21_inv_mast_uid,item_id,item_desc,unit_of_measure,product_group_id,supplier_id
7931,PH0260,Pall Filter Element - High Pressure,EA,FILT,10045
```

### customers_p21.csv
```csv
customer_id,customer_name,address_1,city,state,zip_code,country
207620,Stepan Chemical,123 Main St,Chicago,IL,60601,US
```

### customer_defaults.csv
```csv
customer_id,default_contact_id,default_address_id,default_terms,default_carrier_id,class_1id
207620,C001,S001,NET30,UPS,
```

---

## Questions?

Contact: Peter Wilson (Builder)  
P21 Schema Questions: EnPro IT / P21 Administrator

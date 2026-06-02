# P21 SQL Reference — EnPro PO Agent

Use these queries on the P21 sandbox to verify CISM imports, look up master data, and pull invoices for outbound sync.

---

## SECTION 1: CISM IMPORT VERIFICATION

### 1.1 Check latest Sales Orders created by CISM

```sql
SELECT TOP 10
    o.order_no,
    o.customer_id,
    c.customer_name,
    o.po_no,
    o.order_date,
    o.requested_date,
    o.taker,
    o.ship_to_id,
    o.approved,
    o.company_id,
    o.source_location_id,
    o.carrier_id,
    o.terms_id,
    o.entered_date,
    o.delete_flag
FROM oe_order o
LEFT JOIN customers c ON o.customer_id = c.customer_id
WHERE o.taker = 'POAGENT'
   OR o.po_no LIKE '45008%'
   OR o.entered_date >= CAST(GETDATE() AS DATE)
ORDER BY o.order_no DESC;
```

### 1.2 Check line items for a specific SO

```sql
DECLARE @order_no INT = 0;  -- Replace with actual order number

SELECT
    oi.order_no,
    oi.line_no,
    oi.item_id,
    i.item_desc,
    oi.unit_quantity,
    oi.unit_of_measure,
    oi.unit_price,
    oi.required_date,
    oi.disposition,
    oi.source_loc_id,
    oi.ship_loc_id
FROM oe_order_item oi
LEFT JOIN inv_mast i ON oi.inv_mast_uid = i.inv_mast_uid
WHERE oi.order_no = @order_no
ORDER BY oi.line_no;
```

### 1.3 Find all SOs created today with POAGENT taker

```sql
SELECT
    o.order_no,
    o.customer_id,
    o.po_no,
    o.order_date,
    COUNT(oi.line_no) AS line_count,
    SUM(oi.unit_quantity * oi.unit_price) AS total_amount
FROM oe_order o
LEFT JOIN oe_order_item oi ON o.order_no = oi.order_no
WHERE o.entered_date >= CAST(GETDATE() AS DATE)
  AND o.taker = 'POAGENT'
GROUP BY o.order_no, o.customer_id, o.po_no, o.order_date
ORDER BY o.order_no DESC;
```

### 1.4 Check if a specific PO number was already imported

```sql
DECLARE @po_number VARCHAR(50) = '4500819454';

SELECT
    o.order_no,
    o.customer_id,
    o.po_no,
    o.order_date,
    o.taker,
    o.entered_date
FROM oe_order o
WHERE o.po_no = @po_number;
```

### 1.5 Check CISM import log for errors

```sql
SELECT TOP 50
    log_id,
    import_set_no,
    import_date,
    import_status,
    error_message,
    record_count
FROM cism_import_log
WHERE import_date >= CAST(GETDATE() AS DATE)
ORDER BY import_date DESC;
```

---

## SECTION 2: INVOICE PULL (for Outbound Sync to Ariba/Coupa)

### 2.1 Pull invoices by PO number

```sql
DECLARE @po_number VARCHAR(50) = '4500819454';

SELECT
    i.invoice_no,
    i.order_no,
    o.po_no,
    i.customer_id,
    c.customer_name,
    i.invoice_date,
    i.invoice_amount,
    i.freight_amount,
    i.tax_amount,
    i.total_amount,
    i.ship_date,
    i.tracking_no,
    i.invoice_status,
    i.payment_status
FROM ar_invoice i
LEFT JOIN oe_order o ON i.order_no = o.order_no
LEFT JOIN customers c ON i.customer_id = c.customer_id
WHERE o.po_no = @po_number
ORDER BY i.invoice_date DESC;
```

### 2.2 Pull invoice lines with item detail

```sql
DECLARE @invoice_no INT = 0;  -- Replace with actual invoice number

SELECT
    il.invoice_no,
    il.line_no,
    il.item_id,
    im.item_desc,
    il.unit_quantity,
    il.unit_of_measure,
    il.unit_price,
    il.extended_price,
    il.ship_qty,
    il.tax_amount
FROM ar_invoice_line il
LEFT JOIN inv_mast im ON il.inv_mast_uid = im.inv_mast_uid
WHERE il.invoice_no = @invoice_no
ORDER BY il.line_no;
```

### 2.3 Pull all un-synced invoices (for outbound queue)

```sql
-- Invoices that exist in P21 but haven't been synced back to Ariba/Coupa yet
-- Requires a sync tracking table (see staging schema)

SELECT
    i.invoice_no,
    i.order_no,
    o.po_no,
    i.customer_id,
    c.customer_name,
    i.invoice_date,
    i.total_amount,
    i.ship_date,
    i.tracking_no,
    CASE 
        WHEN s.sync_status IS NULL THEN 'UNSYNCED'
        ELSE s.sync_status 
    END AS sync_status
FROM ar_invoice i
LEFT JOIN oe_order o ON i.order_no = o.order_no
LEFT JOIN customers c ON i.customer_id = c.customer_id
LEFT JOIN po_invoice_sync s ON i.invoice_no = s.invoice_no
WHERE i.invoice_date >= DATEADD(day, -30, GETDATE())
  AND (s.sync_status IS NULL OR s.sync_status = 'pending')
ORDER BY i.invoice_date DESC;
```

### 2.4 Pull invoice with full SO linkage

```sql
SELECT
    i.invoice_no,
    i.order_no,
    o.po_no AS customer_po,
    o.customer_id,
    c.customer_name,
    o.ship_to_id,
    st.ship_to_name,
    i.invoice_date,
    i.ship_date,
    i.invoice_amount,
    i.freight_amount,
    i.tax_amount,
    i.total_amount,
    i.tracking_no,
    car.carrier_id,
    car.carrier_name,
    i.terms_id
FROM ar_invoice i
LEFT JOIN oe_order o ON i.order_no = o.order_no
LEFT JOIN customers c ON i.customer_id = c.customer_id
LEFT JOIN ship_to st ON o.customer_id = st.customer_id AND o.ship_to_id = st.ship_to_id
LEFT JOIN carrier car ON o.carrier_id = car.carrier_id
WHERE i.invoice_date >= DATEADD(day, -7, GETDATE())
ORDER BY i.invoice_date DESC;
```

---

## SECTION 3: MASTER DATA LOOKUP

### 3.1 Look up a customer by ID

```sql
DECLARE @customer_id VARCHAR(20) = '207620';

SELECT
    c.customer_id,
    c.customer_name,
    c.address1,
    c.city,
    c.state,
    c.zip_code,
    c.country,
    c.phone,
    c.email,
    c.terms_id,
    t.terms_desc,
    c.default_carrier_id,
    car.carrier_name
FROM customers c
LEFT JOIN terms t ON c.terms_id = t.terms_id
LEFT JOIN carrier car ON c.default_carrier_id = car.carrier_id
WHERE c.customer_id = @customer_id;
```

### 3.2 Look up a customer by name (fuzzy)

```sql
DECLARE @customer_name VARCHAR(100) = 'Stepan Chemical';

SELECT TOP 10
    c.customer_id,
    c.customer_name,
    c.city,
    c.state,
    c.zip_code,
    c.phone
FROM customers c
WHERE c.customer_name LIKE '%' + @customer_name + '%'
ORDER BY c.customer_name;
```

### 3.3 Look up an item by ID

```sql
DECLARE @item_id VARCHAR(40) = 'CS-P0400/3000';

SELECT
    im.inv_mast_uid,
    im.item_id,
    im.item_desc,
    im.product_group_id,
    pg.product_group_desc,
    im.default_unit_of_measure,
    im.purchase_unit_of_measure,
    im.standard_cost,
    im.last_cost,
    im.average_cost
FROM inv_mast im
LEFT JOIN product_group pg ON im.product_group_id = pg.product_group_id
WHERE im.item_id = @item_id;
```

### 3.4 Look up ship-to addresses for a customer

```sql
DECLARE @customer_id VARCHAR(20) = '207620';

SELECT
    st.ship_to_id,
    st.ship_to_name,
    st.address1,
    st.address2,
    st.city,
    st.state,
    st.zip_code,
    st.country,
    st.phone,
    st.email
FROM ship_to st
WHERE st.customer_id = @customer_id
ORDER BY st.ship_to_id;
```

### 3.5 Look up customer defaults (contact, carrier, terms)

```sql
DECLARE @customer_id VARCHAR(20) = '207620';

SELECT
    c.customer_id,
    c.customer_name,
    c.default_contact_id,
    con.contact_name,
    con.phone AS contact_phone,
    con.email AS contact_email,
    c.default_carrier_id,
    car.carrier_name,
    c.terms_id,
    t.terms_desc,
    c.default_address_id,
    st.ship_to_name AS default_ship_to_name
FROM customers c
LEFT JOIN contact con ON c.customer_id = con.customer_id AND c.default_contact_id = con.contact_id
LEFT JOIN carrier car ON c.default_carrier_id = car.carrier_id
LEFT JOIN terms t ON c.terms_id = t.terms_id
LEFT JOIN ship_to st ON c.customer_id = st.customer_id AND c.default_address_id = st.ship_to_id
WHERE c.customer_id = @customer_id;
```

---

## SECTION 4: CROSSWALK SEEDING QUERIES

### 4.1 Export all active customers for crosswalk CSV

```sql
SELECT
    c.customer_id AS p21_id,
    c.customer_name AS name,
    c.address1,
    c.city,
    c.state,
    c.zip_code,
    c.country,
    c.phone,
    c.email,
    c.terms_id,
    c.default_carrier_id,
    c.default_contact_id,
    c.default_address_id
FROM customers c
WHERE c.delete_flag = 'N'
  AND c.customer_id IS NOT NULL
ORDER BY c.customer_name;
```

### 4.2 Export all active items for crosswalk CSV

```sql
SELECT
    im.inv_mast_uid,
    im.item_id,
    im.item_desc,
    im.product_group_id,
    im.default_unit_of_measure,
    im.standard_cost
FROM inv_mast im
WHERE im.delete_flag = 'N'
  AND im.item_id IS NOT NULL
ORDER BY im.item_id;
```

### 4.3 Export customer-item price history (for mapping suggestions)

```sql
SELECT DISTINCT
    o.customer_id,
    oi.item_id,
    AVG(oi.unit_price) AS avg_price,
    MAX(o.order_date) AS last_ordered,
    COUNT(*) AS order_count
FROM oe_order o
JOIN oe_order_item oi ON o.order_no = oi.order_no
WHERE o.order_date >= DATEADD(year, -1, GETDATE())
GROUP BY o.customer_id, oi.item_id
ORDER BY o.customer_id, last_ordered DESC;
```

---

## SECTION 5: DIAGNOSTIC QUERIES

### 5.1 Check if P21 company exists

```sql
SELECT
    company_id,
    company_name,
    address1,
    city,
    state,
    zip_code
FROM company
WHERE company_id = '1';
```

### 5.2 Check if P21 location exists

```sql
SELECT
    location_id,
    location_name,
    address1,
    city,
    state,
    zip_code
FROM location
WHERE location_id = '10';
```

### 5.3 Count total orders by taker

```sql
SELECT
    taker,
    COUNT(*) AS order_count,
    MIN(order_date) AS earliest,
    MAX(order_date) AS latest
FROM oe_order
WHERE order_date >= DATEADD(day, -30, GETDATE())
GROUP BY taker
ORDER BY order_count DESC;
```

### 5.4 Find duplicate PO imports (same PO number, different order)

```sql
SELECT
    po_no,
    COUNT(*) AS import_count,
    STRING_AGG(CAST(order_no AS VARCHAR), ', ') AS order_numbers
FROM oe_order
WHERE po_no IS NOT NULL
  AND po_no != ''
GROUP BY po_no
HAVING COUNT(*) > 1
ORDER BY import_count DESC;
```

### 5.5 Check CISM table exists and structure

```sql
-- Check if CISM-related tables exist
SELECT 
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME LIKE '%cism%'
   OR TABLE_NAME LIKE '%import%'
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

---

## SECTION 6: OUTBOUND INVOICE SYNC (Future)

### 6.1 Mark an invoice as synced

```sql
-- After successfully sending invoice data to Ariba/Coupa
INSERT INTO po_invoice_sync (
    invoice_no,
    order_no,
    po_no,
    customer_id,
    sync_status,
    synced_at,
    synced_by,
    response_code
)
VALUES (
    @invoice_no,
    @order_no,
    @po_no,
    @customer_id,
    'synced',
    GETDATE(),
    'POAGENT',
    @response_code
);
```

### 6.2 Get all invoices for a date range

```sql
DECLARE @start_date DATE = DATEADD(day, -7, GETDATE());
DECLARE @end_date DATE = GETDATE();

SELECT
    i.invoice_no,
    i.order_no,
    o.po_no,
    i.customer_id,
    c.customer_name,
    i.invoice_date,
    i.total_amount,
    i.ship_date,
    i.tracking_no
FROM ar_invoice i
LEFT JOIN oe_order o ON i.order_no = o.order_no
LEFT JOIN customers c ON i.customer_id = c.customer_id
WHERE i.invoice_date BETWEEN @start_date AND @end_date
ORDER BY i.invoice_date DESC;
```

---

## Quick Reference

| Table | Purpose |
|---|---|
| `oe_order` | Sales Order headers |
| `oe_order_item` | Sales Order line items |
| `ar_invoice` | Invoice headers |
| `ar_invoice_line` | Invoice line items |
| `customers` | Customer master |
| `inv_mast` | Item master |
| `ship_to` | Ship-to addresses |
| `contact` | Customer contacts |
| `carrier` | Carriers |
| `terms` | Payment terms |
| `company` | Companies |
| `location` | Locations/warehouses |
| `product_group` | Product groups |
| `cism_import_log` | CISM import history |

---

*Last updated: 2026-05-17*
*For P21 Prophet 21 — version-agnostic where possible*

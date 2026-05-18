/*
DIRECT_SQL_SO_INSERT.sql — Create P21 Sales Orders directly via SQL

Use this when CISM is not available. Inserts directly into:
  - oe_order (header)
  - oe_order_item (lines)

Run this in SQL Server Management Studio (SSMS) on the P21 sandbox.
*/

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 0: Discover your P21 schema (run this first)
-- ═══════════════════════════════════════════════════════════════════════════════

-- What columns does oe_order actually have?
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'oe_order'
ORDER BY ORDINAL_POSITION;

-- What columns does oe_order_item actually have?
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'oe_order_item'
ORDER BY ORDINAL_POSITION;

-- Does P21 have an order number sequence/function?
SELECT * FROM sys.objects WHERE name LIKE '%order_no%' OR name LIKE '%sequence%';

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 1: Set variables for the PO you want to import
-- ═══════════════════════════════════════════════════════════════════════════════

DECLARE @customer_id VARCHAR(20) = '207620';
DECLARE @po_no VARCHAR(50) = '4500819454';
DECLARE @order_date DATE = '05/17/2026';
DECLARE @requested_date DATE = '05/17/2026';
DECLARE @taker VARCHAR(30) = 'POAGENT';
DECLARE @company_id VARCHAR(5) = '1';
DECLARE @source_location_id VARCHAR(5) = '10';
DECLARE @terms_id VARCHAR(10) = '';
DECLARE @carrier_id VARCHAR(10) = '';

-- Ship-to info (optional — P21 will default from customer if blank)
DECLARE @ship_to_id VARCHAR(20) = '';

-- Line items
-- Format: (line_no, item_id, qty, uom, unit_price, description)
DECLARE @lines TABLE (
    line_no INT,
    item_id VARCHAR(40),
    qty_ordered DECIMAL(18,4),
    uom VARCHAR(8),
    unit_price DECIMAL(18,4),
    item_description VARCHAR(255)
);

INSERT INTO @lines VALUES
(1, 'CS-P0400/3000', 10, 'EA', 185.5000, 'Buffer Solution / CaliMat pH Buffer'),
(2, 'CS-P0400/3001', 5,  'EA', 96.5200,  'Calibration Standard');

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 2: Validate — does the customer exist?
-- ═══════════════════════════════════════════════════════════════════════════════

IF NOT EXISTS (SELECT 1 FROM customers WHERE customer_id = @customer_id)
BEGIN
    RAISERROR('Customer %s does not exist in P21. Add them first.', 16, 1, @customer_id);
    RETURN;
END

-- Validate items exist
DECLARE @missing_items VARCHAR(MAX) = '';
SELECT @missing_items = STRING_AGG(item_id, ', ')
FROM @lines l
WHERE NOT EXISTS (SELECT 1 FROM inv_mast im WHERE im.item_id = l.item_id);

IF @missing_items IS NOT NULL AND @missing_items <> ''
BEGIN
    RAISERROR('Items not found in P21 item master: %s. Add them first.', 16, 1, @missing_items);
    RETURN;
END

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 3: Get defaults from customer master (optional but safer)
-- ═══════════════════════════════════════════════════════════════════════════════

SELECT TOP 1
    @terms_id = ISNULL(@terms_id, default_terms),
    @carrier_id = ISNULL(@carrier_id, default_carrier_id),
    @ship_to_id = ISNULL(@ship_to_id, default_address_id)
FROM customers
WHERE customer_id = @customer_id;

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 4: Get next order number
-- ═══════════════════════════════════════════════════════════════════════════════

-- Method A: If P21 has an identity column or sequence
-- DECLARE @order_no INT = NEXT VALUE FOR dbo.oe_order_seq;  -- if sequence exists

-- Method B: Get max + 1 (safest for sandbox)
DECLARE @order_no INT;
SELECT @order_no = ISNULL(MAX(order_no), 0) + 1 FROM oe_order;

-- Method C: If P21 has a control table
-- SELECT @order_no = next_order_no FROM order_control WHERE company_id = @company_id;
-- UPDATE order_control SET next_order_no = next_order_no + 1 WHERE company_id = @company_id;

PRINT 'Creating Sales Order #' + CAST(@order_no AS VARCHAR);

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 5: Insert header (oe_order)
-- ═══════════════════════════════════════════════════════════════════════════════

BEGIN TRANSACTION;

BEGIN TRY
    INSERT INTO oe_order (
        order_no,
        customer_id,
        po_no,
        order_date,
        requested_date,
        taker,
        company_id,
        source_location_id,
        ship_to_id,
        terms_id,
        carrier_id,
        approved,
        entered_date,
        delete_flag
        -- Add other fields here if your P21 schema has them
    )
    VALUES (
        @order_no,
        @customer_id,
        @po_no,
        @order_date,
        @requested_date,
        @taker,
        @company_id,
        @source_location_id,
        @ship_to_id,
        @terms_id,
        @carrier_id,
        'Y',
        GETDATE(),
        'N'
    );

    -- ═══════════════════════════════════════════════════════════════════════════
    -- STEP 6: Insert lines (oe_order_item)
    -- ═══════════════════════════════════════════════════════════════════════════

    INSERT INTO oe_order_item (
        order_no,
        line_no,
        item_id,
        unit_quantity,
        unit_of_measure,
        unit_price,
        required_date,
        source_loc_id,
        disposition
        -- Add: inv_mast_uid if required instead of item_id
        -- Add: ship_loc_id, extended_price, etc.
    )
    SELECT
        @order_no,
        l.line_no,
        l.item_id,
        l.qty_ordered,
        l.uom,
        l.unit_price,
        @requested_date,
        @source_location_id,
        'B'  -- B = Backorder
    FROM @lines l;

    COMMIT TRANSACTION;

    PRINT 'SUCCESS: Sales Order ' + CAST(@order_no AS VARCHAR) + ' created with ' + CAST(@@ROWCOUNT AS VARCHAR) + ' lines.';

END TRY
BEGIN CATCH
    ROLLBACK TRANSACTION;
    PRINT 'ERROR: ' + ERROR_MESSAGE();
    PRINT 'Line: ' + CAST(ERROR_LINE() AS VARCHAR);
    RAISERROR('SO creation failed. See message above.', 16, 1);
END CATCH;

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 7: Verify
-- ═══════════════════════════════════════════════════════════════════════════════

SELECT 'HEADER' AS type, order_no, customer_id, po_no, order_date, taker
FROM oe_order
WHERE order_no = @order_no;

SELECT 'LINES' AS type, order_no, line_no, item_id, unit_quantity, unit_price
FROM oe_order_item
WHERE order_no = @order_no
ORDER BY line_no;

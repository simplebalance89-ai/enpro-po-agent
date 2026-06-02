-- INSERT_SO_NOW.sql -- Run this directly in SSMS. No CISM needed.
-- Change the variables below to match your PO, then hit F5.

-- ═══════════════════════════════════════════════════════════
-- 1. SET YOUR PO DATA HERE
-- ═══════════════════════════════════════════════════════════

DECLARE @customer_id VARCHAR(20) = '207620';
DECLARE @po_no VARCHAR(50) = '4500819454';
DECLARE @order_date DATE = CAST(GETDATE() AS DATE);
DECLARE @requested_date DATE = CAST(GETDATE() AS DATE);
DECLARE @taker VARCHAR(30) = 'POAGENT';
DECLARE @company_id VARCHAR(5) = '1';
DECLARE @source_location_id VARCHAR(5) = '10';

-- ═══════════════════════════════════════════════════════════
-- 2. GET NEXT ORDER NUMBER
-- ═══════════════════════════════════════════════════════════

DECLARE @order_no INT;
SELECT @order_no = ISNULL(MAX(order_no), 0) + 1 FROM oe_order;

-- ═══════════════════════════════════════════════════════════
-- 3. VALIDATE CUSTOMER EXISTS
-- ═══════════════════════════════════════════════════════════

IF NOT EXISTS (SELECT 1 FROM customers WHERE customer_id = @customer_id)
BEGIN
    RAISERROR('Customer not found: %s', 16, 1, @customer_id);
    RETURN;
END

-- ═══════════════════════════════════════════════════════════
-- 4. INSERT HEADER
-- ═══════════════════════════════════════════════════════════

INSERT INTO oe_order (order_no, customer_id, po_no, order_date, requested_date, taker, company_id, source_location_id, approved, entered_date, delete_flag)
VALUES (@order_no, @customer_id, @po_no, @order_date, @requested_date, @taker, @company_id, @source_location_id, 'Y', GETDATE(), 'N');

-- ═══════════════════════════════════════════════════════════
-- 5. INSERT LINES (add more INSERT statements for more lines)
-- ═══════════════════════════════════════════════════════════

INSERT INTO oe_order_item (order_no, line_no, item_id, unit_quantity, unit_of_measure, unit_price, required_date, source_loc_id, disposition)
VALUES (@order_no, 1, 'CS-P0400/3000', 10, 'EA', 185.50, @requested_date, @source_location_id, 'B');

INSERT INTO oe_order_item (order_no, line_no, item_id, unit_quantity, unit_of_measure, unit_price, required_date, source_loc_id, disposition)
VALUES (@order_no, 2, 'CS-P0400/3001', 5, 'EA', 96.52, @requested_date, @source_location_id, 'B');

-- ═══════════════════════════════════════════════════════════
-- 6. VERIFY
-- ═══════════════════════════════════════════════════════════

PRINT 'Sales Order ' + CAST(@order_no AS VARCHAR) + ' created.';

SELECT 'HEADER' AS type, order_no, customer_id, po_no, order_date, taker FROM oe_order WHERE order_no = @order_no;
SELECT 'LINES'  AS type, order_no, line_no, item_id, unit_quantity, unit_price FROM oe_order_item WHERE order_no = @order_no ORDER BY line_no;

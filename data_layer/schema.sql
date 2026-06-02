-- ============================================================
-- EnPro PO Agent — SQLite Data Layer Schema
-- Replaces flat JSON + CSV files with proper relational storage
-- Date: 2026-06-01
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ── 1. PO STORE ─────────────────────────────────────────────
-- Replaces: data/po_store/*.json (one JSON file per PO)

CREATE TABLE IF NOT EXISTS po_store (
    intake_id           TEXT PRIMARY KEY,
    po_number           TEXT NOT NULL,
    source_system       TEXT NOT NULL,    -- EMAIL, ARIBA, COUPA, PDF, DIRECT
    format              TEXT NOT NULL,    -- cxml, pdf, text
    received_at         TEXT NOT NULL,    -- ISO datetime
    status              TEXT NOT NULL DEFAULT 'RECEIVED',
    overall_confidence  TEXT,             -- green, yellow, red
    review_required     INTEGER NOT NULL DEFAULT 0,
    classification_confidence REAL DEFAULT 0.0,
    cism_blob_path      TEXT,

    -- Header fields (flattened for querying)
    supplier_name       TEXT,
    supplier_email      TEXT,
    ship2_name          TEXT,
    ship2_add1          TEXT,
    ship2_city          TEXT,
    ship2_state         TEXT,
    ship2_zip           TEXT,
    buyer               TEXT,
    buyer_email         TEXT,
    po_desc             TEXT,
    terms               TEXT,
    order_date          TEXT,
    currency_id         TEXT DEFAULT 'USD',

    -- Crosswalk results (flattened for querying)
    customer_id_p21     TEXT,
    customer_name_p21   TEXT,
    customer_match_score REAL,
    customer_match_method TEXT,
    shipto_score        REAL,

    -- Review tracking
    reviewer            TEXT,
    reviewed_at         TEXT,
    reviewer_notes      TEXT,

    -- P21 submit tracking
    p21_so_number       TEXT,
    p21_submitted_at    TEXT,
    p21_submit_result   TEXT,
    p21_import_status   TEXT DEFAULT 'pending',

    -- Raw payload (full JSON)
    raw_payload         TEXT NOT NULL,

    -- Timestamps
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_po_status ON po_store(status);
CREATE INDEX IF NOT EXISTS idx_po_confidence ON po_store(overall_confidence);
CREATE INDEX IF NOT EXISTS idx_po_customer ON po_store(customer_id_p21);
CREATE INDEX IF NOT EXISTS idx_po_received ON po_store(received_at);
CREATE INDEX IF NOT EXISTS idx_po_source ON po_store(source_system, po_number);
CREATE INDEX IF NOT EXISTS idx_po_review ON po_store(review_required, status);

-- ── 2. PO LINES ─────────────────────────────────────────────
-- Normalized line items (one row per line, linked to po_store)

CREATE TABLE IF NOT EXISTS po_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_id           TEXT NOT NULL REFERENCES po_store(intake_id) ON DELETE CASCADE,
    line_no             INTEGER NOT NULL,
    supplier_part_id    TEXT,
    item_description    TEXT,
    qty_ordered         REAL DEFAULT 0,
    unit_price          REAL DEFAULT 0,
    unit_of_measure     TEXT DEFAULT 'EA',
    item_id_p21         TEXT,
    crosswalk_match_score REAL,
    confidence          TEXT,             -- green, yellow, red
    date_due            TEXT,
    required_date       TEXT,
    ship_to_name        TEXT,
    ship_to_address     TEXT,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_lines_intake ON po_lines(intake_id);
CREATE INDEX IF NOT EXISTS idx_lines_item ON po_lines(item_id_p21);

-- ── 3. AUDIT LOG ────────────────────────────────────────────
-- NEW: Tracks every human action with before/after values

CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    user_id             TEXT,             -- who performed the action
    user_email          TEXT,             -- for traceability
    action              TEXT NOT NULL,    -- approve, reject, edit, create
    intake_id           TEXT NOT NULL,
    po_number           TEXT,
    field_name          TEXT,             -- which field changed (if edit)
    old_value           TEXT,             -- previous value
    new_value           TEXT,             -- new value
    reason              TEXT,             -- reviewer notes
    ip_address          TEXT,
    session_id          TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_intake ON audit_log(intake_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- ── 4. CISM BATCH ───────────────────────────────────────────
-- Replaces: data/cism_batch/*.csv (race-condition-prone CSV accumulation)

CREATE TABLE IF NOT EXISTS cism_batch_headers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_id           TEXT NOT NULL REFERENCES po_store(intake_id),
    import_set_no       TEXT NOT NULL,
    customer_id         TEXT NOT NULL,
    customer_name       TEXT,
    company_id          TEXT DEFAULT '1',
    sales_location_id   TEXT DEFAULT '10',
    customer_po_number  TEXT,
    contact_id          TEXT,
    contact_name        TEXT,
    taker               TEXT DEFAULT 'SYSTEM',
    job_name            TEXT,
    order_date          TEXT,
    requested_date      TEXT,
    quote               TEXT,
    approved            TEXT DEFAULT 'Y',
    ship_to_id          TEXT,
    ship_to_name        TEXT,
    ship_to_address_1   TEXT,
    ship_to_address_2   TEXT,
    ship_to_city        TEXT,
    ship_to_state       TEXT,
    ship_to_zip         TEXT,
    ship_to_country     TEXT DEFAULT 'US',
    packing_basis       TEXT DEFAULT 'Partial/Order',
    delivery_instructions TEXT,
    terms               TEXT,
    carrier_id          TEXT,
    will_call           TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cismh_intake ON cism_batch_headers(intake_id);
CREATE INDEX IF NOT EXISTS idx_cismh_customer ON cism_batch_headers(customer_id);
CREATE INDEX IF NOT EXISTS idx_cismh_batch ON cism_batch_headers(import_set_no);

CREATE TABLE IF NOT EXISTS cism_batch_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_header_id     INTEGER NOT NULL REFERENCES cism_batch_headers(id) ON DELETE CASCADE,
    intake_id           TEXT NOT NULL,
    import_set_number   TEXT NOT NULL,
    line_no             INTEGER NOT NULL,
    item_id             TEXT,
    unit_quantity       REAL DEFAULT 0,
    unit_of_measure     TEXT DEFAULT 'EA',
    unit_price          REAL DEFAULT 0,
    extended_description TEXT,
    source_location_id  TEXT DEFAULT '10',
    ship_location_id    TEXT DEFAULT '10',
    product_group_id    TEXT,
    required_date       TEXT,
    disposition         TEXT DEFAULT 'B',
    manual_price_override TEXT,
    capture_usage       TEXT,
    item_description    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cisml_header ON cism_batch_lines(batch_header_id);
CREATE INDEX IF NOT EXISTS idx_cisml_intake ON cism_batch_lines(intake_id);

-- ── 5. CUSTOMER CROSSWALK ───────────────────────────────────
-- Mirrors: data/crosswalks/customer_crosswalk.csv

CREATE TABLE IF NOT EXISTS crosswalk_customers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system       TEXT NOT NULL,
    source_customer_id  TEXT,
    source_customer_name TEXT,
    ship2_name          TEXT NOT NULL,
    ship2_name_normalized TEXT,
    ship2_add1          TEXT,
    ship2_add1_normalized TEXT,
    ship2_city          TEXT,
    ship2_state         TEXT,
    ship2_zip           TEXT,
    p21_customer_id     TEXT NOT NULL,
    p21_customer_name   TEXT,
    match_score         REAL DEFAULT 1.0,
    match_method        TEXT DEFAULT 'seed',
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    last_seen           TEXT,
    seen_count          INTEGER DEFAULT 1,

    UNIQUE(source_system, ship2_name_normalized, ship2_zip)
);

CREATE INDEX IF NOT EXISTS idx_cw_cust_lookup ON crosswalk_customers(p21_customer_id);
CREATE INDEX IF NOT EXISTS idx_cw_cust_name ON crosswalk_customers(ship2_name_normalized);
CREATE INDEX IF NOT EXISTS idx_cw_cust_zip ON crosswalk_customers(ship2_zip);
CREATE INDEX IF NOT EXISTS idx_cw_cust_active ON crosswalk_customers(is_active);

-- ── 6. CUSTOMER-ITEM CROSSWALK ──────────────────────────────
-- Mirrors: data/crosswalks/customer_item_crosswalk.csv

CREATE TABLE IF NOT EXISTS crosswalk_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    p21_customer_id     TEXT NOT NULL,
    customer_part_number TEXT NOT NULL,
    p21_inv_mast_uid    TEXT NOT NULL,
    p21_item_id         TEXT,             -- NEW: part number from inv_mast
    p21_item_desc       TEXT,
    unit_of_measure     TEXT,
    product_group_id    TEXT,
    unit_price_last     REAL,
    unit_price_avg      REAL,
    unit_price_min      REAL,
    unit_price_max      REAL,
    last_seen           TEXT,
    seen_count          INTEGER DEFAULT 1,

    UNIQUE(p21_customer_id, customer_part_number)
);

CREATE INDEX IF NOT EXISTS idx_cw_item_customer ON crosswalk_items(p21_customer_id);
CREATE INDEX IF NOT EXISTS idx_cw_item_part ON crosswalk_items(customer_part_number);
CREATE INDEX IF NOT EXISTS idx_cw_item_uid ON crosswalk_items(p21_inv_mast_uid);

-- ── 7. PO HISTORY ───────────────────────────────────────────
-- Mirrors: data/crosswalks/customer_po_history.csv

CREATE TABLE IF NOT EXISTS po_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    p21_customer_id     TEXT NOT NULL,
    customer_po_no      TEXT NOT NULL,
    p21_order_no        TEXT NOT NULL,
    order_date          TEXT,
    completed           TEXT,
    approved            TEXT,
    ship2_name          TEXT
);

CREATE INDEX IF NOT EXISTS idx_ph_po ON po_history(customer_po_no);
CREATE INDEX IF NOT EXISTS idx_ph_customer ON po_history(p21_customer_id);

-- ── 8. ITEM MASTER ──────────────────────────────────────────
-- Mirrors: data/crosswalks/item_master_index.csv

CREATE TABLE IF NOT EXISTS item_master (
    p21_inv_mast_uid    TEXT PRIMARY KEY,
    p21_part_number     TEXT,
    p21_item_desc       TEXT,
    p21_item_desc_normalized TEXT,
    default_selling_unit TEXT,
    product_group       TEXT,
    default_supplier_id TEXT,
    supplier_name       TEXT
);

CREATE INDEX IF NOT EXISTS idx_im_desc ON item_master(p21_item_desc_normalized);
CREATE INDEX IF NOT EXISTS idx_im_part ON item_master(p21_part_number);

-- ── 9. P21 CUSTOMERS ────────────────────────────────────────
-- Mirrors: data/crosswalks/customers_p21.csv

CREATE TABLE IF NOT EXISTS p21_customers (
    customer_id         TEXT PRIMARY KEY,
    customer_name       TEXT,
    address             TEXT,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    country             TEXT DEFAULT 'US',
    phone               TEXT,
    email               TEXT,
    default_terms       TEXT,
    default_carrier_id  TEXT
);

-- ── 10. CUSTOMER DEFAULTS ───────────────────────────────────
-- Mirrors: data/crosswalks/customer_defaults.csv

CREATE TABLE IF NOT EXISTS customer_defaults (
    customer_id         TEXT PRIMARY KEY,
    customer_name       TEXT,
    default_contact_id  TEXT,
    default_address_id  TEXT,
    default_terms       TEXT,
    default_carrier_id  TEXT
);

-- ── 11. VENDOR CROSSWALK ────────────────────────────────────
-- NEW: Was in SQL schema but never built as CSV

CREATE TABLE IF NOT EXISTS crosswalk_vendors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system       TEXT NOT NULL,
    source_vendor_id    TEXT NOT NULL,
    source_vendor_name  TEXT,
    p21_vendor_id       TEXT NOT NULL,
    p21_vendor_name     TEXT,
    match_score         REAL DEFAULT 1.0,
    match_method        TEXT DEFAULT 'exact',
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    last_seen           TEXT,
    seen_count          INTEGER DEFAULT 1,

    UNIQUE(source_system, source_vendor_id)
);

CREATE INDEX IF NOT EXISTS idx_cw_vend_lookup ON crosswalk_vendors(p21_vendor_id);

-- ── 12. UOM CROSSWALK ───────────────────────────────────────
-- NEW: Maps Ariba/Coupa UOM codes to P21 internal UOM

CREATE TABLE IF NOT EXISTS uom_crosswalk (
    p21_uom             TEXT PRIMARY KEY,
    ariba_uom           TEXT,
    coupa_uom           TEXT,
    description         TEXT
);

-- Seed common mappings
INSERT OR IGNORE INTO uom_crosswalk (p21_uom, ariba_uom, coupa_uom, description) VALUES
('EA', 'C62', 'EA', 'Each'),
('CS', 'CS', 'CS', 'Case'),
('BX', 'BX', 'BX', 'Box'),
('FT', 'FOT', 'FT', 'Foot'),
('LB', 'LBR', 'LB', 'Pound'),
('KG', 'KGM', 'KG', 'Kilogram'),
('GL', 'GLL', 'GL', 'Gallon'),
('PR', 'PR', 'PR', 'Pair'),
('RL', 'RL', 'RL', 'Roll'),
('PK', 'PK', 'PK', 'Pack'),
('DZ', 'DZN', 'DZ', 'Dozen'),
('ST', 'SET', 'ST', 'Set'),
('PC', 'C62', 'PC', 'Piece'),
('SET', 'SET', 'SET', 'Set'),
('RL', 'RL', 'RL', 'Roll'),
('BG', 'BG', 'BG', 'Bag'),
('DR', 'DR', 'DR', 'Drum'),
('PL', 'PF', 'PL', 'Pallet');

-- ── 13. PO-SO CROSSWALK ─────────────────────────────────────
-- NEW: Tracks linkage between source PO and P21 SO

CREATE TABLE IF NOT EXISTS po_so_linkage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_po_number    TEXT NOT NULL,
    source_system       TEXT NOT NULL,
    p21_order_no        TEXT NOT NULL,
    p21_customer_id     TEXT,
    match_method        TEXT DEFAULT 'manual',
    match_confidence    REAL DEFAULT 1.0,
    status              TEXT DEFAULT 'active',
    created_at          TEXT DEFAULT (datetime('now')),
    created_by          TEXT,
    notes               TEXT,

    UNIQUE(source_po_number, source_system, p21_order_no)
);

CREATE INDEX IF NOT EXISTS idx_link_po ON po_so_linkage(source_po_number, source_system);
CREATE INDEX IF NOT EXISTS idx_link_so ON po_so_linkage(p21_order_no);

-- ── 14. CROSSWALK REFRESH LOG ───────────────────────────────
-- NEW: Tracks when crosswalks were last refreshed

CREATE TABLE IF NOT EXISTS crosswalk_refresh_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_type        TEXT NOT NULL,    -- full, incremental, manual
    table_name          TEXT NOT NULL,
    rows_before         INTEGER,
    rows_after          INTEGER,
    duration_seconds    REAL,
    status              TEXT,             -- success, failed, rolled_back
    error_message       TEXT,
    refreshed_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_refresh_table ON crosswalk_refresh_log(table_name);

-- ── 15. METRICS ─────────────────────────────────────────────
-- NEW: Time-series metrics for monitoring

CREATE TABLE IF NOT EXISTS metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name         TEXT NOT NULL,
    metric_value        REAL,
    metric_label        TEXT,
    recorded_at         TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name, recorded_at);

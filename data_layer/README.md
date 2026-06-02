# EnPro PO Agent — Data Layer

This folder contains the proper relational data layer for the PO Agent. It replaces the fragile flat-file storage (JSON per PO, CSV crosswalks) with SQLite-backed structured storage.

---

## Files

| File | Purpose |
|------|---------|
| `schema.sql` | Complete SQLite schema — 15 tables, indexes, seed data |
| `migrate.py` | One-time migration: JSON → SQLite, CSV → SQLite |
| `refresh.py` | Scheduled job: pull fresh P21 data, rebuild crosswalks |
| `README.md` | This file |

---

## The Problem We Solved

**Before (flat files):**
- One JSON file per PO → O(n) full scan to load review queue
- CSV crosswalks → race conditions on concurrent writes
- No audit trail → who approved what? Unknown.
- No transactions → crash mid-approval = corrupted state
- CISM batch CSV → concurrent approvals lose data

**After (SQLite):**
- Indexed PO store → sub-second queries by status, customer, date
- ACID transactions → approval = update PO + insert audit + insert CISM batch in one transaction
- Concurrent-safe → WAL mode handles multiple writers
- Queryable → SQL for reporting, metrics, debugging
- Versioned crosswalks → backup before every refresh

---

## Schema Overview

### PO Store (replaces `data/po_store/*.json`)
- `po_store` — one row per PO, all header fields flattened for querying
- `po_lines` — normalized lines, linked to po_store by intake_id

### Audit (NEW)
- `audit_log` — every action with before/after values

### CISM Batch (replaces `data/cism_batch/*.csv`)
- `cism_batch_headers` — one row per approved PO header
- `cism_batch_lines` — one row per line item

### Crosswalks (mirror of `data/crosswalks/*.csv`)
- `crosswalk_customers` — ship-to → customer_id
- `crosswalk_items` — customer_part_number → inv_mast_uid
- `po_history` — PO number → SO linkage
- `item_master` — inv_mast_uid → item details
- `p21_customers` — customer master
- `customer_defaults` — most-common CISM fields per customer

### New Tables (not in CSVs)
- `crosswalk_vendors` — Ariba/Coupa vendor → P21 vendor
- `uom_crosswalk` — UN/CEFACT codes → P21 UOM (seeded)
- `po_so_linkage` — tracks PO → SO creation
- `crosswalk_refresh_log` — when/what was refreshed
- `metrics` — time-series for monitoring

---

## How to Use

### 1. Initial Migration (Run Once)

```powershell
cd Desktop\EnPro-PO-Agent-Ariba-Coupa
python data_layer/migrate.py
```

This will:
- Create `data/po_store.db`
- Read all `data/po_store/*.json` → insert into SQLite
- Read all `data/crosswalks/*.csv` → insert into SQLite
- Validate row counts match
- Archive JSON files to `.json.bak`

### 2. Refresh Crosswalks (Run Nightly/Weekly)

```powershell
# Full refresh (5 years of P21 data)
python data_layer/refresh.py --mode full

# Incremental refresh (last 7 days)
python data_layer/refresh.py --mode incremental --days 7

# Dry run (generate but don't swap)
python data_layer/refresh.py --mode full --dry-run
```

This requires P21 SQL credentials:
```
P21_SQL_SERVER=your-p21-server
P21_SQL_DATABASE=your-p21-db
P21_SQL_USERNAME=your-username
P21_SQL_PASSWORD=your-password
```

### 3. Query the Database

```python
import sqlite3
conn = sqlite3.connect("data/po_store.db")
conn.row_factory = sqlite3.Row

# All pending review POs
rows = conn.execute("""
    SELECT intake_id, po_number, customer_name_p21, overall_confidence
    FROM po_store
    WHERE review_required = 1 AND status = 'PENDING_REVIEW'
    ORDER BY received_at DESC
""").fetchall()

# Customer lookup
rows = conn.execute("""
    SELECT * FROM crosswalk_customers
    WHERE ship2_name_normalized LIKE '%stepan%'
      AND is_active = 1
""").fetchall()

# Audit trail for a PO
rows = conn.execute("""
    SELECT * FROM audit_log
    WHERE intake_id = ?
    ORDER BY timestamp DESC
""", ("INTAKE_ID_HERE",)).fetchall()
```

---

## Backwards Compatibility

The app code in `src/server.py` still reads from JSON/CSV files. To use SQLite:

1. Run `migrate.py` to populate the database
2. Update `local_store.py` to read from SQLite (new `sqlite_store.py` module)
3. Update `crosswalk_learner.py` to write to SQLite
4. Update `cism_batch.py` to use SQLite tables

The migration is designed to be gradual:
- Phase 1: Dual-write (write to both JSON and SQLite)
- Phase 2: Read from SQLite, keep JSON as backup
- Phase 3: Remove JSON entirely

---

## Design Decisions

### Why SQLite (not PostgreSQL yet)?
- Zero setup — single file, no server
- Python built-in — no extra dependencies
- ACID with WAL mode — handles concurrent writes
- Easy migration path to PostgreSQL later (same SQL schema)

### Why keep CSVs as source of truth?
- Brittany can still edit CSVs directly
- Easy to inspect, backup, version control
- CSVs are the "build artifacts" from P21 SQL
- SQLite is the "runtime cache" with indexes

### Why 15 tables?
- Each domain gets its own table (customers, items, POs, audit, metrics)
- Foreign keys enforce relationships
- Indexes on every lookup key
- Normalized lines (no JSON blobs in main table)

---

## Next Steps for Builder

1. ✅ Schema defined (`schema.sql`)
2. ✅ Migration script (`migrate.py`)
3. ✅ Refresh job (`refresh.py`)
4. ⬜ Create `services/data/sqlite_store.py` — SQLite-based PO store (replaces `local_store.py`)
5. ⬜ Create `services/data/duckdb_engine.py` — DuckDB crosswalk queries
6. ⬜ Update `crosswalk_learner.py` to write to SQLite
7. ⬜ Update `cism_batch.py` to use SQLite tables
8. ⬜ Add audit logging to all mutating routes
9. ⬜ Add disk-space alert threshold to `/health`
10. ⬜ Schedule `refresh.py` via cron/systemd/APScheduler

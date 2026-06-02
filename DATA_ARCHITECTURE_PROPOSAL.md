# EnPro PO Agent — Data Architecture Review & Proposal

**Date:** 2026-06-01  
**Goal:** Document current data storage, identify problems, propose better containers, explain WHY each choice wins.

---

## 1. CURRENT State — Flat CSVs + JSON Files

Everything lives in `data/` as flat files. Here's what we have:

```
data/
├── po_store/
│   ├── po_abc123.json          # One JSON per PO
│   ├── po_def456.json
│   └── ...                     # 22 files now, grows daily
├── cism_so_output/
│   ├── po_abc123_header.csv    # Per-PO CISM header
│   ├── po_abc123_line.csv      # Per-PO CISM lines
│   └── ...
├── cism_batch/
│   ├── batch_orderquoteheader.csv    # Accumulated headers
│   └── batch_orderquoteline.csv      # Accumulated lines
├── crosswalks/
│   ├── customer_crosswalk.csv        # 4,880 rows
│   ├── customer_item_crosswalk.csv   # 22,675 rows
│   ├── po_history.csv                # 23,452 rows
│   ├── item_master.csv               # 11,911 rows
│   ├── customer_master.csv           # 7,833 rows
│   ├── dynamics_quotes.csv           # 2,065 rows
│   ├── quote_to_po_linkage.csv       # 910 rows
│   ├── salespeople.csv               # 52 rows
│   └── vendor_crosswalk.csv          # (learned mappings)
├── outbound/
│   └── ...                     # Outbound sync payloads
└── invoice/
    └── ...                     # Invoice records (if enabled)
```

### How It Works Now
1. **Read:** Every request reads the full CSV into a pandas DataFrame
2. **Match:** Fuzzy string matching against the in-memory DataFrame
3. **Write:** Append new rows to CSV (atomic via tmp + os.replace)
4. **Store POs:** One JSON file per PO, loaded by filename pattern

---

## 2. PROBLEMS with Current Approach

| Problem | Why It Hurts | When It Bites |
|---|---|---|
| **Full CSV load on every request** | Customer crosswalk (4,880 rows) loads into memory every time a PO is processed | At scale, this is slow and memory-hungry |
| **No indexing** | Fuzzy matching scans every row | Customer lookup is O(n) instead of O(1) or O(log n) |
| **No foreign keys / relationships** | Customer-item crosswalk has customer info + item info in one file | Data duplication, update anomalies |
| **JSON files for POs** | Hard to query across POs ("show me all POs from Stepan Chemical last month") | Reporting, audit, ops dashboards |
| **No versioning** | Crosswalk gets overwritten on refresh | If refresh is bad, you lose learned mappings |
| **No schema enforcement** | CSV columns can drift | Silent failures when column names change |
| **No transactions** | PO approval writes to 3-4 files | Crash mid-approval = corrupted state |
| **Flat file locking** | Multiple requests can race on the same CSV | Concurrent approvals may corrupt batch CSVs |
| **No incremental sync** | To refresh crosswalks, we reload entire files | Wasteful, slow, error-prone |

---

## 3. PROPOSAL — Better Data Containers

### Option A: SQLite (Embedded, Zero-Config)
**What:** Single `.db` file per dataset or one master `.db` file.

**Best for:**
- PO store (replaces 22+ JSON files)
- Crosswalks with lookups (indexed customer name, zip, item number)
- Audit log

**Pros:**
- Zero setup, zero server, just a file
- SQL queries for reporting
- Indexes for fast lookups
- ACID transactions
- Lightweight, built into Python

**Cons:**
- Not great for concurrent writes (SQLite has WAL mode but still)
- Single-file limit for very large datasets
- No replication

**Verdict:** Excellent for PO store + audit log. Good for crosswalks if single-writer.

---

### Option B: DuckDB (Analytical, Fast)
**What:** In-process analytical database. Like SQLite but optimized for analytical queries.

**Best for:**
- Crosswalks (fast fuzzy matching, full-text search)
- Reporting queries across PO history
- Large CSVs you want to query like a database

**Pros:**
- Reads CSVs directly without import
- Fast analytical queries
- Fuzzy matching, regex, full-text search built-in
- Zero server, just a Python package
- Can query Parquet files too

**Cons:**
- Read-optimized, not write-optimized
- Not ideal for high-frequency transactional writes
- Still single-writer limitations

**Verdict:** Best for crosswalk lookups + reporting. Keep CSVs as source of truth, query via DuckDB.

---

### Option C: PostgreSQL (Production-Grade)
**What:** Full relational database. Requires a server or managed service.

**Best for:**
- Everything, if we want production-grade
- Multi-user concurrent access
- Real replication/backup

**Pros:**
- ACID, indexes, constraints, foreign keys
- Concurrent writes handled perfectly
- Managed services exist (Railway, Supabase, Neon, AWS RDS)
- Can run in Docker locally

**Cons:**
- Requires setup (even Docker)
- Managed service costs money
- Overkill if volume stays small

**Verdict:** Best long-term. If we deploy to Railway, they offer managed PostgreSQL with one click.

---

### Option D: Redis (Fast Cache + Queue)
**What:** In-memory key-value store with persistence.

**Best for:**
- Caching crosswalk lookups (avoid re-loading CSVs)
- Queue for PO processing jobs
- Session store if we add auth

**Pros:**
- Blazing fast lookups
- Can cache compiled crosswalk indexes
- Job queue for background processing

**Cons:**
- Not a primary datastore (data fits in memory)
- Another service to manage

**Verdict:** Nice-to-have optimization layer. Not a replacement for persistent storage.

---

### Option E: Parquet (Columnar Storage)
**What:** Columnar file format (like CSV but compressed + typed + column-oriented).

**Best for:**
- Large crosswalk files that are read-heavy
- PO history (23K+ rows, growing)
- Data that gets loaded into pandas/DuckDB

**Pros:**
- 10-50x smaller than CSV
- Typed columns (no string parsing)
- Fast columnar reads
- Industry standard for data lakes

**Cons:**
- Not human-readable
- Harder to append (typically rewrite whole file)

**Verdict:** Great for large read-only datasets like PO history. Crosswalks too if refreshed in batches.

---

## 4. RECOMMENDED Architecture

Here's what we propose, phase by phase:

### Phase 1: Immediate (This Week)

| Dataset | Current | Proposed | Why |
|---|---|---|---|
| **PO Store** | 22 JSON files | **SQLite** `.db` file | Queryable, indexed by date/customer/status, ACID transactions |
| **Audit Log** | None | **SQLite** table | Who approved what, when, before/after values |
| **Crosswalk lookups** | Load full CSV into pandas | **DuckDB** in-memory + CSV source | Fast fuzzy matching without full reload, can still edit CSVs |
| **CISM Batch** | Append to CSV | **SQLite** batch table → export to CSV on demand | Atomic transactions, no corruption on concurrent writes |

**Why SQLite for POs:**
- One file replaces 22+ JSON files
- Query: `SELECT * FROM po WHERE customer_id='207620' AND status='APPROVED'`
- No more globbing directories, parsing JSON, building lists
- Transaction safety: PO approval updates PO + creates audit log + adds to batch — all in one transaction

**Why DuckDB for crosswalks:**
- Don't change the CSV files Brittany knows
- DuckDB reads them directly: `SELECT * FROM 'customer_crosswalk.csv' WHERE name ILIKE '%stepan%'`
- Fuzzy matching via DuckDB: `SELECT * FROM customer_crosswalk ORDER BY jaro_winkler(name, 'Stepan Chemical') DESC LIMIT 5`
- No import step, no sync lag

---

### Phase 2: Short-Term (Next 2-4 Weeks)

| Dataset | Current | Proposed | Why |
|---|---|---|---|
| **Crosswalk refresh** | Manual CSV overwrite | **Versioned Parquet + Delta** | Keep last N versions, rollback if bad refresh |
| **PO History** | 23K row CSV | **Parquet** file + DuckDB | Fast analytical queries, 10x smaller |
| **Learned mappings** | Append to CSV | **SQLite** learned_mappings table | Track provenance, confidence, date learned, who approved |

**Why versioned Parquet:**
- Every crosswalk refresh creates a new Parquet file with timestamp
- DuckDB can query across versions: "show me customers added in last refresh"
- If a refresh corrupts data, roll back to previous version instantly
- Compression means 23K rows → ~200KB file

---

### Phase 3: Production (When Volume Demands)

| Dataset | Proposed | Why |
|---|---|---|
| **Everything** | **PostgreSQL** (managed) | Concurrent users, real backup, replication, monitoring |
| **Cache layer** | **Redis** | Sub-millisecond crosswalk lookups, job queue |
| **Data lake** | **Parquet on S3/Blob** | Long-term archive, analytics, BI tools |

---

## 5. Migration Path — How We Get There Without Breaking Anything

### Step 1: Add SQLite alongside JSON (no removal yet)
- Create `data/po_store.db`
- Write every new PO to BOTH JSON file AND SQLite
- Read from SQLite for queries, JSON as backup
- After 1 week of no issues, stop writing JSON

### Step 2: Add DuckDB for crosswalk queries
- Install `duckdb` package
- On startup, create in-memory views: `CREATE VIEW customers AS SELECT * FROM 'data/crosswalks/customer_crosswalk.csv'`
- Replace pandas DataFrame lookups with DuckDB queries
- CSVs stay the source of truth — no change to Brittany's workflow

### Step 3: Add audit logging to SQLite
- New table: `audit_log(id, timestamp, user, action, po_id, field, old_value, new_value)`
- Every PO edit/approve/reject writes one or more rows

### Step 4: Convert CISM batch to SQLite
- Table: `cism_batch_headers` and `cism_batch_lines`
- PO approval inserts rows into tables (transaction-safe)
- Download endpoint queries tables → generates CSV on the fly
- No more append-to-CSV corruption risk

### Step 5: Version crosswalks as Parquet
- Refresh job: `p21_export → CSV → validate → Parquet with timestamp`
- Keep last 10 versions
- DuckDB reads latest Parquet automatically

---

## 6. Why This Beats the Current Approach

| Dimension | Current (Flat Files) | Proposed (SQLite + DuckDB + Parquet) |
|---|---|---|
| **Query speed** | O(n) scans, load full file | O(log n) indexed lookups, sub-second |
| **Concurrent writes** | Race conditions, corruption | SQLite WAL mode handles it |
| **Reporting** | Custom Python code to glob/parse JSON | SQL queries, standard tools |
| **Data safety** | Overwrite = data loss | Transactions, versioning, rollback |
| **Ops overhead** | None (simple) | Minimal (single files, no server for Phase 1) |
| **Scale path** | Hits wall at ~1000 POs | SQLite → PostgreSQL when needed |
| **Brittany's workflow** | Edit CSVs directly | Same CSVs, just queried better |

---

## 7. Open Questions for Us to Decide

1. **Do we want to keep CSVs as the "source of truth" forever, or move to SQLite/PostgreSQL as the master?**
   - CSVs: Human-readable, Brittany can edit directly, easy to backup
   - DB: Faster, safer, better queries, harder for non-technical users to edit

2. **Should the refresh job write to CSV first, then import to DB, or write to DB and export to CSV?**
   - CSV-first: Maintains current workflow, DB is read-only cache
   - DB-first: DB is master, CSV is export format

3. **Do we need a proper job queue (Redis/Celery) or is in-process enough?**
   - In-process: Simpler, fine for current volume
   - Job queue: Better for email polling, batch processing, retries

4. **How many crosswalk versions do we keep?**
   - Last 10? 30? All of them? (Storage is cheap, but cleanup matters)

5. **When do we move to PostgreSQL?**
   - When SQLite can't handle concurrent writes?
   - When we need multi-user auth?
   - When we add a second instance/load balancing?

---

## 8. Files to Create for This Architecture

| File | Purpose |
|---|---|
| `services/data/sqlite_store.py` | SQLite PO store, audit log, batch tables |
| `services/data/duckdb_engine.py` | DuckDB crosswalk queries, fuzzy matching |
| `services/data/parquet_manager.py` | Versioned Parquet read/write |
| `services/data/migration.py` | JSON → SQLite migration script |
| `services/data/refresh_job.py` | Scheduled P21 → Parquet refresh |

---

**Next Step:** Review this proposal together. Decide which pieces to build first. Then scope each file with the builder.

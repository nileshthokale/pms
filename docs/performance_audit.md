# Pharmacy Management System — Stage 1 Performance Audit

Audit date: 2026-11-01
Scope: safe baseline, isolated benchmark, and read-only code inspection. Stage 2 work was not started.

## Scope and safety

- The active database was `data/pharmacy.db`. It was read for hashing and verification only. Its SHA-256 matched before backup, after backup, and after all benchmark runs.
- A SQLite online backup was created, verified, and retained. The benchmark clone was made from that backup and was the only database used for benchmark login, sales, and CRUD activity.
- Benchmark processes set `PHARMACY_DB` to the clone and checked the resolved database path. The clone's integrity and foreign-key checks remain clean.
- No application source, schema, or active-database records were changed. WAL settings were not changed. No EXE was built and no files were removed.
- The retained clone contains benchmark-side auth, audit, ledger, and accounting changes. It is an audit artifact, not a clean production copy.

## Database baseline and backup

| Database | Size | SHA-256 | Integrity check | FK violations | Application tables | Journal mode |
|---|---:|---|---|---:|---:|---|
| Active source before and after | 57,925,632 bytes | `a9eeffa5c71f09922af0913b914c245411c708ad3f6fbe7dcba6447fa34edebf` | `ok` | 0 | 51 | `wal` |
| Online backup | 57,925,632 bytes | `95f881bac5680c23b27a98a3d0723bc12c58913d3c9a100d0fba1544e5463760` | `ok` | 0 | 51 | `wal` |
| Benchmark clone after runs | 57,925,632 bytes | `9b7ac07276a2a7dd1e00ba089b22005d719c7ea14ea2c4d202d732ca021be1bc` | `ok` | 0 | 51 | `wal` |

Backup: `backups/pharmacy_pre_performance_20261101_183617.db`
Benchmark clone: `backups/pharmacy_performance_benchmark_20261101_183617.db`

The source hash was the same before and after online backup capture and after benchmarking. The backup and clone were each checked with SHA-256, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and table counts. Backup counts matched the source. The clone schema had zero differences from the backup.

| Key table | Source and backup baseline | Clone after benchmarks |
|---|---:|---:|
| items | 940 | 940 |
| stock_batches | 7,817 | 7,817 |
| sales_invoices | 72,255 | 72,255 |
| sales_invoice_items | 234,337 | 234,337 |
| purchase_invoices | 5,732 | 5,732 |
| purchase_invoice_items | 11,927 | 11,927 |
| ledger_transactions | 157,788 | 157,948 |
| app_users | 2 | 3 |
| customers | 29 | 29 |
| account_ledgers | 124 | 144 |
| auth_audit_log | 279 | 289 |

The increased clone counts are the retained effects of the throwaway benchmark login and CRUD/accounting paths. The sales, invoice-item, and stock-batch row counts returned to baseline after the test sale lifecycle. No corresponding operations ran on the source.

## Benchmark method

- The runner launched 5 cold-process runs and 5 warm-cache-process runs on Windows. Every process resolved and asserted the clone path before exercising the application.
- A cold-process run had fresh Python, Qt, and SQLite process state. The OS file cache was not flushed. A warm-cache-process run was also a fresh process, launched after the cold group had primed filesystem cache; OS cache state was not controlled. Within each process, repeat searches, page constructions, CRUD actions, and report generation were also recorded where available.
- Therefore, “warm” here means a fresh process after cache priming, not a pre-existing interactive application session. Startup and login are measured in each process; repeated in-process operations provide the warm-operation observations.
- The application and real PySide6 pages were exercised with Qt's offscreen platform because no interactive desktop was available. Each process used Python 3.13.14, PySide6 6.11.2, and Qt 6.11.2.
- A throwaway admin account was used only in the clone. The runner measured startup to LoginDialog show/event processing, authentication submission, and dashboard first frame. It then exercised Item Master load/search, Counter Sale loading/navigation, customer and sales add/edit/delete with persistence and immediate UI refresh checks, and a full active-financial-year sales report.
- Sales persistence timings include the DAO operation/commit, database readback, and sales-history refresh. Customer timings include commit and Customer Master refresh. The report covered 2026-04-01 through 2027-03-31 and produced 271 pages in each run.
- Working-set RSS was sampled during each process; Python heap peak was recorded with tracemalloc. A 10 ms Qt timer measured event-loop stalls after the dashboard's first frame. Thus the timer does not capture stalls during startup or dashboard construction.
- Each phase has five observations. Median and p95 are calculated across those five runs; p95 uses nearest rank, so with n=5 the reported p95 is the slowest observation. Durations are milliseconds; memory is MiB.
- All 10 processes returned successfully with no harness errors. Login was accepted, the dashboard appeared, CRUD persistence/refresh checks completed, and each report generated 271 pages. The recorded `login_dialog_visible` flag was sampled after login submission had closed the dialog, so it is not a visibility result; a separate offscreen show/processEvents check confirmed the dialog was visible and exposed before submission.

Raw per-run measurements and environment details: `backups/pharmacy_performance_benchmark_20261101_183617.results.json`
Repeatable audit runner: `backups/performance_audit_stage1_runner_20261101.py`

## Measurements

Values are median / p95. “Warm-cache” uses the process definition above.

### Startup and page flows

| Flow | Cold median / p95 | Warm-cache median / p95 | Measurement |
|---|---:|---:|---|
| Application startup to login screen | 5,183.6 / 6,325.8 | 3,120.3 / 5,011.9 | Process start to LoginDialog shown and event processing |
| Authentication submit | 257.4 / 294.4 | 188.2 / 229.5 | Login submission/authentication only |
| Login submit to dashboard first frame | 56,382.1 / 66,436.6 | 60,639.9 / 74,001.4 | Per-run authentication duration plus accepted-login-to-dashboard duration |
| Accepted login to dashboard first frame | 56,087.7 / 66,171.7 | 60,493.4 / 73,771.9 | Dashboard transition after authentication |
| Dashboard construction | 54,586.6 / 64,690.0 | 59,044.9 / 69,797.7 | Main window setup and eager page construction |
| Item Master constructor on initial route build | 312.4 / 362.2 | 323.6 / 404.7 | First measured ItemMasterPage constructor |
| Item Master initial full refresh | 645.2 / 720.9 | 493.0 / 1,257.8 | Populate table from item records |
| Item Master first search | 134.6 / 180.9 | 184.0 / 211.3 | First measured query and results update |
| Item Master repeat search | 116.6 / 132.6 | 136.2 / 173.9 | Repeated search in the same process |
| Counter Sale page constructor on initial route build | 1,900.9 / 3,558.1 | 2,113.9 / 2,347.4 | First measured CounterSalePage constructor |
| Counter Sale additional constructor in-process | 2,237.8 / 2,599.6 | 2,615.8 / 3,294.4 | Additional page instance after initial app setup |
| Navigate to already-built Sales page | 11.4 / 12.9 | 16.2 / 26.6 | First measured stack navigation |
| Repeat navigation to Sales page | 0.3 / 0.6 | 0.4 / 0.5 | Repeated stack navigation |

The dashboard constructor is the dominant measured wait. Warm-cache runs did not make dashboard construction faster; the measured median was higher than the cold-process median. The groups were not run under controlled OS cache or system-load conditions, so the difference should not be interpreted as a causal effect of caching.

### Persisted CRUD and refresh

Each timing covers a successful operation, persistence/readback as applicable, and immediate visible refresh/absence check. Customer and sale operations are reported separately because they exercise different accounting paths.

| Flow | Cold median / p95 | Warm-cache median / p95 |
|---|---:|---:|
| Customer add + refresh | 28.9 / 45.2 | 34.9 / 42.6 |
| Customer edit + refresh | 22.2 / 28.1 | 27.9 / 35.6 |
| Customer delete + refresh | 136.1 / 796.3 | 170.8 / 176.4 |
| Sale add + commit, readback, history refresh | 260.4 / 320.3 | 259.0 / 327.8 |
| Sale edit + commit, readback, history refresh | 334.2 / 433.5 | 365.3 / 394.7 |
| Sale delete + commit, readback, history refresh | 349.0 / 386.3 | 366.9 / 419.1 |

The cold customer-delete p95 includes one 796 ms outlier; its other four samples were about 131–137 ms.

### Report generation

| Flow | Cold median / p95 | Warm-cache median / p95 | Result |
|---|---:|---:|---|
| Full active-year Sales Report, first generation | 4,067.9 / 4,537.2 | 4,234.7 / 5,397.9 | 271 pages each run |
| Full active-year Sales Report, repeat generation in-process | 3,833.2 / 8,295.3 | 5,322.9 / 5,886.4 | 271 pages each run |

### Memory and GUI event-loop stalls

| Metric | Cold median / p95 | Warm-cache median / p95 |
|---|---:|---:|
| Peak process working set | 445.5 / 492.4 MiB | 428.7 / 462.0 MiB |
| Peak Python heap (tracemalloc) | 113.09 / 113.10 MiB | 113.12 / 113.12 MiB |
| Maximum 10 ms timer stall per run | 4,538.5 / 8,287.3 ms | 5,313.7 / 5,878.1 ms |
| Per-run p95 timer stall, summarized across runs | 3,824.1 / 8,287.3 ms | 4,111.5 / 5,395.5 ms |

The timer started after the first dashboard frame. The multi-second stalls observed during the measured page/report work are direct evidence of a blocked offscreen Qt event loop during those intervals. These values characterize the offscreen run and are not a substitute for an interactive desktop measurement.

## Findings: confirmed versus unverified

### Confirmed structure and measured behavior

1. Initialization is invoked before login in `main.py::main` and repeated after login in `ui/main_window.py::PharmacyMainWindow.__init__`: database initialization, auth schema assurance, and default financial-year assurance are called at both points. The duplicate calls are confirmed; their individual time cost was not isolated.
2. `screens/__init__.py` imports screen modules eagerly. `PharmacyMainWindow._build_pages` in `ui/main_window.py` constructs the routed page set before the dashboard first frame; the measured stack contained 73 pages.
3. `SalesReportPage.__init__` in `screens/sales_report.py` calls `_on_generate()` during construction. `_on_generate` performs report generation and rendering synchronously. Report generation measured about 4.1–5.4 seconds for the first full-year run.
4. The measured dashboard constructor took 52.0–69.8 seconds across individual runs (median 54.6 seconds cold-process, 59.0 seconds warm-cache). Counter Sale and Item Master constructors/refreshes and synchronous report generation are measurable contributors, but these timings do not explain the full dashboard duration.
5. `database/connection.py::get_connection` executes `PRAGMA journal_mode=WAL` and enables foreign keys on every opened connection. This behavior is confirmed in source. The audit did not change WAL and did not isolate the cost of these statements.
6. `ItemMasterPage._refresh` in `screens/item_master.py` populates the table from the item list. The measured initial refresh was roughly 0.5–0.7 seconds in the median, with a 1.26 second warm-cache p95 outlier; measured search medians were 0.13–0.18 seconds.
7. `SalesDAO.insert_invoice`, `update_invoice`, and `delete_invoice` in `database/sales_dao.py` execute transactional sale paths. The benchmark verified persistence and immediate history refresh for these operations; sale add/edit/delete medians were about 0.26–0.37 seconds.
8. `CustomerDAO` operations in `database/customer_dao.py` and the Customer Master refresh path in `screens/customer_master.py` were exercised with successful visible refresh/absence checks. The measured medians were about 0.02–0.17 seconds.
9. The source search found no `QThread`, `QThreadPool`, or `QRunnable` usage. This is a structural observation, not proof that no other asynchronous mechanism exists.

### Unverified hypotheses

- Eager construction and repeated initialization are likely contributors to the long dashboard wait, but their individual contribution has not been isolated. Dashboard construction remains much slower than the specific measured Item Master, Counter Sale, and report operations; additional page constructors and database work need per-page timing.
- Synchronous report generation is a confirmed UI-thread operation and a plausible cause of individual multi-second event-loop stalls. The audit did not attribute each timer stall to a particular page or SQL statement.
- Reapplying the WAL pragma and repeating schema assurance may add connection/startup overhead. Their cost is unmeasured.
- The high process RSS compared with the Python heap peak may come from Qt widgets, native libraries, cached page data, or other allocations. This audit did not profile native allocations or per-page memory.
- No query-plan, index-coverage, or SQL-level profiling was performed. Database indexes or query shapes may contribute to slow constructors and reports, but that remains unverified.

## Affected code areas

| File | Functions/classes inspected | Relevance |
|---|---|---|
| `main.py` | `main` | Startup database/auth/financial-year setup before login |
| `ui/main_window.py` | `PharmacyMainWindow.__init__`, `_build_pages` | Repeated setup and eager route/page construction |
| `screens/__init__.py` | module imports | Eager screen-module imports |
| `screens/sales_report.py` | `SalesReportPage.__init__`, `_on_generate` | Synchronous first report generation/render during construction |
| `screens/item_master.py` | `ItemMasterPage`, `_refresh` | Initial table population and search |
| `screens/counter_sale.py` | `CounterSalePage` | Sales page construction |
| `database/connection.py` | `get_connection`, `init_database` | Per-connection pragmas and schema initialization |
| `database/sales_dao.py` | `SalesDAO.insert_invoice`, `update_invoice`, `delete_invoice` | Persisted sale operations |
| `database/customer_dao.py`, `screens/customer_master.py` | `CustomerDAO`, customer refresh path | Customer CRUD and immediate refresh |

## Prioritized recommendations for a separately approved Stage 2

1. **Highest priority — reduce dashboard work before first frame.** Instrument every page constructor and its database calls, then lazily construct routes on first navigation. This is the most direct response to the measured 55–59 second dashboard-construction median and the 73-page eager stack.
2. **High — defer report work.** Avoid generating a full report as a constructor side effect. Show the report page first, then generate on request; if asynchronous execution is considered, keep database access and Qt widget updates on their appropriate threads.
3. **High — remove redundant startup setup after measuring it.** Time schema initialization and financial-year/auth assurance separately, then keep the necessary initialization at a single lifecycle boundary.
4. **Medium — profile expensive page and database work.** Add temporary per-page, DAO, and SQL timing to find what accounts for the dashboard time not explained by the measured Item Master, Counter Sale, and Sales Report operations. Inspect query plans and indexes only for measured slow queries.
5. **Medium — investigate process memory.** Capture per-page RSS and native allocation growth while pages are constructed; the measured process peak was about 429–446 MiB while Python heap peak was about 113 MiB.
6. **Lower — optimize Item Master refresh/search if the target warrants it.** The initial full table refresh is measurably slower than search; evaluate table/model population and repeated list fetching after the startup bottleneck is addressed.
7. **Lower — measure connection setup before changing it.** Benchmark connection creation and pragma/schema-assurance costs independently. Preserve the current WAL configuration unless a separately approved test demonstrates a safe benefit.

No recommendations above were implemented during the Stage 1 audit. Stage 2 implementation and verification results follow.

## Stage 2 implementation and verification

Audit date: 2026-11-01. All application and CRUD verification used a fresh clone created from the retained verified Stage 1 online backup. The active database remained read-only throughout Stage 2.

### Safety and database verification

- Preserved the Stage 1 backup at `backups/pharmacy_pre_performance_20261101_183617.db` (SHA-256 `95f881bac5680c23b27a98a3d0723bc12c58913d3c9a100d0fba1544e5463760`). Its integrity check is `ok`, it has 0 foreign-key violations and 51 application tables.
- Created and used `backups/pharmacy_stage2_working_20261101_191221.db` as the isolated Stage 2 working database. Its initial SHA-256 matched the backup; the clone was integrity- and FK-checked before tests. After tests its SHA-256 is `c23b9d99d214f493b00d6ebbab2a0b438ac5b6095577ba83eebc207adf3c5666`; `PRAGMA integrity_check` is `ok`, `PRAGMA foreign_key_check` returns 0 rows, and it still has 51 application tables.
- The clone schema matches the preserved backup exactly (zero `sqlite_master` differences); journal mode remains `wal`.
- Rechecked the active `data/pharmacy.db` after implementation and testing: SHA-256 is `a9eeffa5c71f09922af0913b914c245411c708ad3f6fbe7dcba6447fa34edebf`, unchanged from the Stage 1 baseline. Integrity is `ok`; FK violations are 0. No test CRUD operations targeted it.

| Key table | Active source / preserved backup | Stage 2 clone after testing |
|---|---:|---:|
| items | 940 | 940 |
| stock_batches | 7,817 | 7,818 |
| sales_invoices | 72,255 | 72,255 |
| sales_invoice_items | 234,337 | 234,337 |
| purchase_invoices | 5,732 | 5,732 |
| purchase_invoice_items | 11,927 | 11,927 |
| ledger_transactions | 157,788 | 157,812 |
| app_users | 2 | 14 |
| customers | 29 | 29 |
| account_ledgers | 124 | 126 |
| auth_audit_log | 279 | 317 |

The added clone rows are test-only authentication/audit/accounting data and a zero-quantity stock batch retained by the application's purchase-delete behavior. Sale and purchase invoice counts returned to their starting values. The clone is retained with test effects; it is not a replacement for production data.

### Changes implemented

| File | Change |
|---|---|
| `screens/__init__.py` | Replaced eager screen imports with lazy attribute imports. Existing public names and `__all__` exports remain available; importing the package no longer imports all page modules. |
| `ui/main_window.py` | Registers all 73 existing routes using lightweight placeholders and a page factory. The initially selected Counter Sale route is created for the first dashboard frame; other pages are constructed on first navigation, cached by route/index, and reused. Permission checks still happen before construction. Existing route aliases, navigation signals, and page state are retained. Later-created pages receive the selected financial year. Added `initialize_database=True` default for direct callers; normal startup passes `False` after `main()` performs its database setup. |
| `main.py` | Kept database initialization and financial-year assurance before login. Removed the redundant auth-schema assurance because `run_login()` already assures that schema. Main-window construction skips its former duplicate database/auth/year setup while direct window construction keeps the default initialization behavior. |
| `screens/sales_report.py` | Removed automatic report generation from the constructor. The filter/report interface opens empty and immediately; generation occurs after a user request. Print/export actions are unavailable until a report exists. Report calculation, filters, print/export dispatch, and output rendering remain on the existing paths. |
| `screens/item_master.py` | Suspends table repaint, sorting, and `ResizeToContents` sizing while populating rows, then restores header resize modes, sorting, sort column/order, and updates. This prevents per-row resize work from dominating a visible full refresh. |

No SQL, index, schema, WAL, or foreign-key behavior was changed. Query plans were inspected for the measured full-year Sales Report query. The plan scans `sales_invoice_items` and uses a temporary B-tree for ordering, but DAO execution itself was about 103 ms median for 8,936 rows; no index change was justified by that measurement.

### Benchmark method

Five fresh-process cold runs and five fresh-process warm-cache runs were collected using the Stage 2 runner. Cold/warm definitions and limitations match Stage 1: OS cache was not flushed or controlled, and the warm group starts after the cold group. Each run explicitly resolved `PHARMACY_DB` to the Stage 2 clone and asserted the path before exercising the app. Runs used Windows, Python 3.13.14, PySide6 6.11.2, Qt 6.11.2, and Qt's offscreen platform.

Timing begins at the indicated UI action and includes event processing to the measured frame/result. Lazy page-construction timings include first factory creation and polish. Item Master visible initial refresh was also timed separately. Report runs cover 2026-04-01 to 2027-03-31. The event-loop timer has a 10 ms interval and was active after the dashboard first frame; it does not capture startup/dashboard stalls. Median and p95 use five observations; p95 is nearest rank and therefore the slowest sample. These are offscreen measurements, not interactive desktop measurements.

The JSON results are retained at `backups/pharmacy_performance_stage2_20261101.results.json`; the runner is `backups/performance_audit_stage2_runner_20261101.py`. The final source hash was checked independently after all testing. The runner's own source-before/after guard also recorded the source as unchanged for the 10 benchmark runs.

### Before/after performance comparison

Values are median / p95 milliseconds unless otherwise shown. Stage 1 baseline values are repeated here for comparison. “Not directly comparable” means the new metric includes first lazy construction/polish while the old one measured a prebuilt page or constructor-only path.

| Flow | Stage 1 cold | Stage 2 cold | Stage 1 warm-cache | Stage 2 warm-cache |
|---|---:|---:|---:|---:|
| Startup to login screen | 5,183.6 / 6,325.8 | 807.6 / 870.6 | 3,120.3 / 5,011.9 | 811.2 / 863.6 |
| Accepted login to dashboard first frame | 56,087.7 / 66,171.7 | 2,461.5 / 2,536.2 | 60,493.4 / 73,771.9 | 2,485.2 / 2,533.3 |
| Dashboard construction | 54,586.6 / 64,690.0 | 2,334.8 / 2,386.5 | 59,044.9 / 69,797.7 | 2,365.3 / 2,407.7 |
| Item Master constructor / first lazy creation | 312.4 / 362.2 | 364.2 / 370.9 | 323.6 / 404.7 | 344.6 / 358.3 |
| Item Master full visible refresh | 645.2 / 720.9 | 311.0 / 330.9 | 493.0 / 1,257.8 | 304.0 / 324.5 |
| Item Master first search | 134.6 / 180.9 | 99.6 / 113.9 | 184.0 / 211.3 | 101.5 / 108.4 |
| Counter Sale constructor / first creation | 1,900.9 / 3,558.1 | 1,254.0 / 1,308.5 | 2,113.9 / 2,347.4 | 1,312.5 / 1,329.8 |
| Sales Report constructor / first lazy creation | 1,399.3 / 1,762.9 | 383.0 / 401.4 | 2,180.5 / 4,199.9 | 347.8 / 429.2 |
| First full-year report generation | 4,067.9 / 4,537.2 | 2,964.3 / 3,272.3 | 4,234.7 / 5,397.9 | 2,927.7 / 3,089.8 |
| Maximum 10 ms event-loop stall | 4,538.5 / 8,287.3 | 3,239.4 / 3,885.2 | 5,313.7 / 5,878.1 | 2,993.5 / 3,104.3 |
| Peak working set | 445.5 / 492.4 MiB | 231.6 / 233.2 MiB | 428.7 / 462.0 MiB | 231.5 / 234.0 MiB |
| Peak Python heap | 113.09 / 113.10 MiB | 58.91 / 58.92 MiB | 113.12 / 113.12 MiB | 58.92 / 58.92 MiB |

The dashboard first-frame median fell by about 95.6% in the cold-process group and 95.9% in the warm-cache group. Startup-to-login median fell by about 84.4% and 74.0%, respectively. Report-page creation dropped because the constructor no longer computes and renders the report. Full report generation still takes about three seconds when requested and remains synchronous. Item Master refresh/search medians improved; page-construction timings include lazy import and polish and are not the same timing boundary as Stage 1.

Memory is also not a like-for-like workload: Stage 1 built every route before the dashboard, whereas Stage 2 initially builds one route and materialized only Counter Sale, Item Master, and Sales Report during this benchmark. This is consistent with the intended lazy behavior, but it does not isolate a per-page memory saving. RSS is native plus Python memory; the separate Python heap measurement is lower.

Initialization work was timed independently. Stage 1's separate pre-edit clone timings were database initialization 9.55 ms median, auth schema assurance 6.47 ms, and financial-year assurance 15.36 ms. During Stage 2 app startup, cold-process medians/p95s were 13.54/25.02 ms, 4.65/5.46 ms, and 15.87/16.73 ms; warm-cache values were 11.42/12.86 ms, 4.13/4.55 ms, and 14.36/16.66 ms. The main-window duplicate database call count was zero in all 10 runs. Auth schema assurance is reached through login once; database initialization and financial-year assurance remain before login.

### Functional regression verification

All checks below used the isolated clone, not `data/pharmacy.db`.

| Area | Result | Verification and limitation |
|---|---|---|
| Login and dashboard | PASS | Throwaway admin login accepted; dashboard visible with all 73 routes registered and one page instantiated on initial show. |
| Lazy construction and navigation | PASS | First visit constructed route, repeat navigation reused the same instance/state. Sales History, Purchase, All Stock, Ledger, Item Master, Customer Master, and Sales Report routes were visited. Counter Sale's history signal navigated to Sales History. |
| Permissions | PASS | Staff account could access an allowed Master route; Account Roles was denied before page construction. |
| Item Master | PASS, partial scope | Add/edit, persistence readback, search, refresh, and sort-state restoration passed. No Item Master delete UI or `ItemDAO.delete` operation exists, so app-level Item Master deletion could not be exercised; the test-created item was removed directly from the clone and the table reloaded. |
| Counter Sale / sale lifecycle | PASS | Counter Sale page and navigation signal worked. Sale insert/edit/delete completed through the real DAO path with persistence readback, stock returning to its prior quantity, Sales History immediate refresh/absence, and balanced per-sale ledger reference. |
| Customer CRUD | PASS | Add/edit/delete persisted; Customer Master refreshed immediately and deleted customer was absent. |
| Purchase and stock | PASS | Purchase insert/update/delete persisted; stock moved 2 to 3 to 0 and invoice state matched. Purchase ledger reference remained balanced. The application's delete path leaves a zero-quantity stock batch row. |
| Ledger/accounting | PASS | Sale and purchase reference balances and customer/accounting paths were checked on the clone. |
| Sales Reports | PASS, printing mocked | Constructor made no report query and opened with empty results. Explicit full-year report returned 8,936 rows / 271 pages; summary line count matched. Item filter matched DAO results. Print dispatch was intercepted and verified; no physical printer or real print output was exercised. |
| Persistence and database safety | PASS | Relevant writes were read back after operations. Final clone integrity check was `ok`, foreign-key violations were zero, and source SHA-256 remained unchanged. |

The Item Master visible refresh over 943 displayed rows completed in 116.13 ms in the dedicated state-restoration check. Sorting remained enabled and the prior descending sort on column 1 was restored. The 943 displayed rows can exceed the 940 item records because the page's joined query can produce multiple rows for an item; the underlying `items` count remained 940.

### Measured query/render profile and remaining bottlenecks

Five clone-only `SalesReportDAO.get_sales_report` calls for the full-year 8,936-row result took 97.21, 98.60, 103.10, 114.18, and 103.38 ms (median 103.10 ms). Hidden-page report rendering of 271 pages took 585.13 ms in a separate profile. The end-to-end UI measurement is roughly 2.9-3.3 seconds, and a report request produces a roughly 3-second event-loop stall. This supports page/table construction and rendering as substantial remaining work; it does not prove a single exclusive cause for the remaining time.

The traced report query plan scans `sales_invoice_items`, performs primary-key lookups for related rows, and uses a temporary B-tree for ordering. Since the DAO query was about 103 ms median and no index/query bottleneck was demonstrated, no SQL or index changes were made. Other identified remaining costs include Counter Sale's roughly 1.25-1.31 second first construction, Item Master's roughly 0.7 second first navigation (including load/event processing), and the dashboard's roughly 2.3 second constructor even with one initial page. Per-page work outside the measured routes remains unprofiled.

### Stage 2 outcome

The requested lazy page creation, report deferral, duplicate initialization reduction, and measured Item Master refresh optimization are implemented. Ten benchmark processes and the clone-based functional checks above completed with no remaining application-level failure. Limitations are the unavailable Item Master delete feature, mocked rather than physical printing, offscreen-only GUI measurements, and the synchronous report-generation stall. No EXE was built, production data/schema/WAL settings were not modified, and no files or historical production records were deleted.

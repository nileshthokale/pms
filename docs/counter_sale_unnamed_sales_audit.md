# Counter Sale — Unnamed Sales and Blank Bill Numbers

## Purpose

A Counter Sale saved with an empty or whitespace-only **Patient Name** must:

1. store `patient_name = 'WALKIN'` for a **new** sale;
2. keep a genuinely blank **business Bill No** (`bill_no = ''`), with no
   generated number, placeholder, internal row id, `CNo`, or voucher id;
3. keep a real Patient Name and the existing bill-number generation/display
   behaviour when a name is supplied.

Historical records are **not** rewritten. A historical row whose stored
`patient_name` is empty or whitespace is displayed with a blank Bill No; its
stored bill number (if any) and all internal ids/foreign keys remain intact.

## Reliable identification rule

The only reliable historical marker is the stored patient name itself:

```sql
patient_name IS NULL OR TRIM(patient_name) = ''
```

Rows whose stored patient name is literally `WALKIN` are **not** classified as
unnamed. `WALKIN` is also a legitimate patient name, and the application must
not assume every historical `WALKIN` row was auto-generated. The audit reports
those rows separately.

## Read-only historical audit

Run:

```text
python tools/audit_counter_sale_unnamed_sales.py
python tools/audit_counter_sale_unnamed_sales.py --db data/pharmacy.db --json audit.json
```

The tool opens SQLite with `mode=ro` and `PRAGMA query_only=ON`. It reports:

- total sales and named/unnamed counts;
- unnamed rows with blank versus stored bill numbers;
- the shape of stored numbers on unnamed rows (legacy `...-S<id>`, financial
  year compound, plain numeric, `CS-` prefix, blank);
- unnamed rows attached to the `WALKIN` customer;
- stored `WALKIN` patient rows (reported, never treated as unnamed);
- duplicate non-empty bill numbers;
- whether the partial unique nonblank index is present and whether the old
  inline `UNIQUE` remains.

### Audit observed on the existing application database (2026-10-22)

| Measure | Count |
|---|---:|
| Total sales invoices | 72,175 |
| Unnamed patient (empty/whitespace) | 17,876 |
| Named patient | 54,299 |
| Stored patient exactly `WALKIN` | 0 |
| Unnamed with legacy `...-S<legacy_id>` bill | 17,874 |
| Unnamed with financial-year compound bill | 2 |
| Unnamed with WALKIN customer | 17,876 |
| Blank stored Bill No | 0 |

No data was changed by the audit. All 17,876 unnamed rows retain their stored
historical bill numbers; the display layer hides those numbers because the
stored patient name is empty. Geneuine-name records are never blanked.

## Storage and schema

- New unnamed sales store `bill_no = ''` (empty string, not `NULL`) because the
  application treats bill numbers as strings everywhere.
- The old `bill_no TEXT NOT NULL UNIQUE` constraint allowed only one empty
  value. `_migrate_sales_invoices_blank_bill_no()` rebuilds the table once,
  preserving every internal `id`, foreign key, and the `sqlite_sequence`
  high-water mark, then creates:

```sql
CREATE UNIQUE INDEX ux_sales_invoices_bill_no_nonblank
ON sales_invoices(bill_no) WHERE bill_no <> '';
```

- Multiple blank Bill Nos are therefore allowed, while every non-empty number
  remains unique.
- A consistent database snapshot is written beside the database before the
  one-time rebuild, when the old constraint is detected.
- Bill-number generation ignores blank values, so `''` can never become the
  sequence prefix or width source.

## Behaviour by flow

| Flow | Patient Name | Bill No |
|---|---|---|
| New sale, empty/whitespace input | `WALKIN` | blank (`''`) |
| New sale, real name | real name | generated/assigned as before |
| Edit existing unnamed sale | `WALKIN` or preserved empty historical marker | stored value preserved; blank stays blank |
| Edit existing named sale | real name | stored number preserved |
| Historical unnamed row with legacy number | displayed `WALKIN` | displayed blank; stored number unchanged |
| Historical named row | real name | displayed numeric as before |

Display helpers (`SalesDAO.display_bill_no`,
`format_sales_bill_number`, history/report tables, details dialog, tooltips)
return an empty string for an unnamed sale. They never substitute `--`,
an internal id, or a different voucher number.

## Regression tests

Isolated tests run only against temporary SQLite databases:

```text
python test_counter_sale_unnamed_sales_blank_bill.py
```

They cover:

1. empty Patient Name → `WALKIN` + blank Bill No;
2. whitespace-only Patient Name → `WALKIN` + blank Bill No;
3. real Patient Name → preserved name + non-empty bill number;
4. multiple unnamed sales can all store blank Bill No (no unique collision);
5. blank Bill No persists through save, history refresh, reopen, edit, and a
   new database connection (restart simulation);
6. historical unnamed rows display blank while their stored number, ids, and
   stock remain unchanged; named rows keep their number;
7. stock deduction, accounting posting, and bill printing still work for an
   unnamed sale.

The tests never open or modify `data/pharmacy.db`; `PHARMACY_DB` is pointed at a
fresh temporary file before `init_database()` is called.

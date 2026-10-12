# Phase 3 — Collision-Safe Resolution (STAGING ONLY, NO APPLY)

- Source: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY)
- Target (read-only): `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\staging\stock_final_verify.db`
- Mode: `resolution-report` — this report plans distinct identities only.
  No stock quantity was written and no historical FK was changed.

## Safety

- Never merges distinct source batches by normalized key.
- Exact originals retained per variant below + in JSON provenance.
- Synthetic aliases only where stripping collides; otherwise existing
  distinct identities are reused (no renames, no text-linkage breaks).
- Quantities are per-variant `(purchase-sales)/pack`; no double-counted
  adjustments; missing pack stays blocking (never `/1`).

## Base plan (blocking, for reference)

- source rows: 7793
- distinct target keys: 7792
- keys in base plan: 7776
- withheld: 16
- normalized collisions: 7
- missing pack: 0

## Resolution summary

- collision groups: 8 (grouped by target_item + normalized key)
- resolved: 8
- still blocked: 0
- variants mapped: 17/17
- withheld stripped keys covered: 16/16
- partition math: 7792 source keys = 7776 base rows + 16 withheld; resolution covers 16/16 withheld stripped keys as 17/17 variants
- resolved quantities: positive 2, zero 15, negative 0

### item 961 · `N 142033` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `N 142033`
- conflicting: `mrp`; agreeing: `expiry, pack_size, purchase_rate, net_rate`
- sales moves planned: 0; sales already correct: 41; purchase lines documented: 2; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `N  142033` | `N  142033` | `N[2sp]142033` | 2017-05-31 | 1 | 270.0 | 72.0 | 72.0 | 0.0 | 0.0 | 751 | 21 | 1 |
| `N 142033` | `N 142033` | `N 142033` | 2017-05-31 | 1 | 210.0 | 72.0 | 72.0 | 0.0 | 0.0 | 372 | 20 | 1 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `N  142033` → `N  142033`: none — existing batch metadata already matches this variant
  - `N 142033` → `N 142033`: none — existing batch metadata already matches this variant

### item 1094 · `KR 2923` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `KR 2923`
- conflicting: `purchase_rate, net_rate`; agreeing: `expiry, pack_size, mrp`
- sales moves planned: 0; sales already correct: 20; purchase lines documented: 2; mixed vouchers: 1

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `KR  2923` | `KR  2923` | `KR[2sp]2923` | 2016-11-30 | 10 | 46.5 | 35.8 | 37.59 | 0.0 | 0.0 | 120 | 2 | 1 |
| `KR 2923` | `KR 2923` | `KR 2923` | 2016-11-30 | 10 | 46.5 | 36.49 | 38.31 | 0.0 | 0.0 | 338 | 18 | 1 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `KR  2923` → `KR  2923`: none — existing batch metadata already matches this variant
  - `KR 2923` → `KR 2923`: none — existing batch metadata already matches this variant

### item 1134 · `CARE UNI` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `CARE UNI`
- conflicting: `mrp, purchase_rate, net_rate`; agreeing: `expiry, pack_size`
- sales moves planned: 0; sales already correct: 10; purchase lines documented: 2; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CARE  UNI` | `CARE  UNI` | `CARE[2sp]UNI` | 2017-05-31 | 1 | 230.0 | 110.0 | 110.0 | 9.0 | 9.0 | 1492 | 3 | 1 |
| `CARE UNI` | `CARE UNI` | `CARE UNI` | 2017-05-31 | 1 | 260.0 | 95.0 | 107.44 | 0.0 | 0.0 | 1054 | 7 | 1 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `CARE  UNI` → `CARE  UNI`: none — existing batch metadata already matches this variant
  - `CARE UNI` → `CARE UNI`: UPDATE batch id 1054 fields on apply: mrp 220.0->260.0; purchase 110.0->95.0; net 110.0->107.44; historical invoice-line copies untouched

### item 1182 · `CARE` — RESOLVED

- variant: surrounding whitespace; stripped collision: True; canonical: `CARE`
- conflicting: `expiry, net_rate`; agreeing: `pack_size, mrp, purchase_rate`
- sales moves planned: 21; sales already correct: 0; purchase lines documented: 4; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ` CARE` | `CARE[exact=' CARE']` | `CARE[exact=' CARE']` | 2018-05-31 | 1 | 125.0 | 52.0 | 50.0 | 0.0 | 0.0 | NEW | 21 | 1 |
| `CARE` | `CARE` | `CARE` | 2017-05-31 | 1 | 125.0 | 52.0 | 52.0 | 0.0 | 0.0 | 176 | 112 | 3 |
- variant-specific metadata plans (existing rows never reused blindly):

  - ` CARE` → `CARE[exact=' CARE']`: INSERT new batch "CARE[exact=' CARE']" with source metadata (expiry 2018-05-31, pack 1, mrp 125.0, purchase 52.0, net 50.0); history rows untouched
  - `CARE` → `CARE`: none — existing batch metadata already matches this variant

### item 1199 · `CARE UNI` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `CARE UNI`
- conflicting: `mrp, purchase_rate, net_rate`; agreeing: `expiry, pack_size`
- sales moves planned: 0; sales already correct: 13; purchase lines documented: 3; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CARE  UNI` | `CARE  UNI` | `CARE[2sp]UNI` | 2017-05-31 | 1 | 360.0 | 175.0 | 175.0 | 0.0 | 0.0 | 177 | 5 | 1 |
| `CARE UNI` | `CARE UNI` | `CARE UNI` | 2017-05-31 | 1 | 415.0 | 160.0 | 163.25 | 18.0 | 18.0 | 1995 | 8 | 2 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `CARE  UNI` → `CARE  UNI`: none — existing batch metadata already matches this variant
  - `CARE UNI` → `CARE UNI`: UPDATE batch id 1995 fields on apply: expiry '2020-02-29'->'2017-05-31'; mrp 390.0->415.0; purchase 175.0->160.0; net 175.0->163.25; historical invoice-line copies untouched

### item 1294 · `CARE 1` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `CARE 1`
- conflicting: `mrp`; agreeing: `expiry, pack_size, purchase_rate, net_rate`
- sales moves planned: 0; sales already correct: 8; purchase lines documented: 0; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CARE   1` | `CARE   1` | `CARE[3sp]1` | 2017-05-31 | 1 | 75.0 | 15.0 | 15.0 | 0.0 | 0.0 | 7393 | 4 | 0 |
| `CARE  1` | `CARE  1` | `CARE[2sp]1` | 2017-05-31 | 1 | 55.0 | 15.0 | 15.0 | 0.0 | 0.0 | 7418 | 2 | 0 |
| `CARE 1` | `CARE 1` | `CARE 1` | 2017-05-31 | 1 | 65.0 | 15.0 | 15.0 | 0.0 | 0.0 | 7392 | 2 | 0 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `CARE   1` → `CARE   1`: UPDATE batch id 7393 fields on apply: purchase 75.0->15.0; net 0.0->15.0; historical invoice-line copies untouched
  - `CARE  1` → `CARE  1`: UPDATE batch id 7418 fields on apply: purchase 55.0->15.0; net 0.0->15.0; historical invoice-line copies untouched
  - `CARE 1` → `CARE 1`: UPDATE batch id 7392 fields on apply: purchase 65.0->15.0; net 0.0->15.0; historical invoice-line copies untouched

### item 1524 · `LA 60709` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `LA 60709`
- conflicting: `net_rate`; agreeing: `expiry, pack_size, mrp, purchase_rate`
- sales moves planned: 0; sales already correct: 86; purchase lines documented: 2; mixed vouchers: 0

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `LA  60709` | `LA  60709` | `LA[2sp]60709` | 2019-06-30 | 5 | 23.0 | 17.36 | 19.09 | 0.0 | 0.0 | 1477 | 25 | 1 |
| `LA 60709` | `LA 60709` | `LA 60709` | 2019-06-30 | 5 | 23.0 | 17.36 | 10.95 | 0.0 | 0.0 | 1444 | 61 | 1 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `LA  60709` → `LA  60709`: UPDATE batch id 1477 fields on apply: net 17.48->19.09; historical invoice-line copies untouched
  - `LA 60709` → `LA 60709`: UPDATE batch id 1444 fields on apply: net 17.76->10.95; historical invoice-line copies untouched

### item 1543 · `ST16 2195` — RESOLVED

- variant: internal whitespace; stripped collision: False; canonical: `ST16 2195`
- conflicting: `net_rate`; agreeing: `expiry, pack_size, mrp, purchase_rate`
- sales moves planned: 0; sales already correct: 157; purchase lines documented: 6; mixed vouchers: 2

| exact raw | alias (target identity) | display | expiry | pack | mrp | purch.rate | net rate | net loose | stock | existing id | sales | purch |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ST16  2195` | `ST16  2195` | `ST16[2sp]2195` | 2018-09-30 | 10 | 71.0 | 50.71 | 53.25 | 0.0 | 0.0 | 2089 | 67 | 3 |
| `ST16 2195` | `ST16 2195` | `ST16 2195` | 2018-09-30 | 10 | 71.0 | 50.71 | 52.07 | 0.0 | 0.0 | 2083 | 90 | 3 |
- variant-specific metadata plans (existing rows never reused blindly):

  - `ST16  2195` → `ST16  2195`: UPDATE batch id 2089 fields on apply: net 56.8->53.25; historical invoice-line copies untouched
  - `ST16 2195` → `ST16 2195`: UPDATE batch id 2083 fields on apply: net 56.8->52.07; historical invoice-line copies untouched

## UC-ROSE (unchanged, from base `plan_rows`)

- legacy 832 → target 1775: 14 projected batches, 4 with stock, 2 sellable, 0 offered now.

_End of resolution report — no quantities applied, no FKs changed._

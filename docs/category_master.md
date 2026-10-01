# Category Master

## Purpose

Category Master is ordinary item-classification master data. It is not an accounting feature and does not change stock, pricing, GST, ingredients, posting, ledgers, or reports.

## Item-model audit conclusion

Before this feature, `items` had nullable `unit_id` and `company_id` relationships, but no category or category ID column, no category table, and no indirect category representation. Item imports, Item Master, stock/report DAO queries, and accounting posting also had no category behavior. A nullable `items.category_id` is therefore a safe, additive relationship consistent with the existing Item architecture.

Existing items remain valid with `category_id = NULL`; no records are assigned an invented category.

## Model and migration

`categories` contains:

- `id`
- `category_name`
- nullable `description`
- `is_active`
- `created_at` and `updated_at`

Names are whitespace-normalized and protected by a case-insensitive normalized unique index. Database initialization creates the table if needed and adds nullable `items.category_id` only if it is missing. It does not rebuild `items` or modify stock batches, invoices, ledgers, or accounting history. The item relationship has `ON DELETE SET NULL`, so a low-level database deletion cannot leave a broken reference. The application exposes activation/deactivation rather than a destructive category delete.

## CRUD and activation

ADMIN users can create, edit, search, activate, and deactivate categories from Master → Category Master. Deactivation keeps existing Item links intact. New items and imports can select only active categories. An existing item associated with a category that later becomes inactive remains readable and can be edited without losing its existing category.

## Item integration and imports

Item Master has an optional Category selector and a Category table column/filter. Blank remains valid. The selector lists active categories for new items; when editing a historical item, its inactive category is retained and visibly marked inactive.

Item CSV/XLSX imports accept an optional `Category`/`Category Name` column and resolve it to `category_id`. Files without that column remain compatible. A supplied unknown or inactive category is rejected during preview. Updating an existing item from an older import without a Category column preserves its current category.

## Permissions

The existing two-role policy is used unchanged. `ADMIN` receives the centralized `category_management` permission, which gates Category Master administration. `PHARMACIST/STAFF` retains `view_masters` and can view/use active categories in Item Master, but cannot administer Category Master. No role was added.

## Safety and limitations

Category is deliberately not yet a report dimension and does not alter posting calculations. There is no destructive Category DAO delete operation. Future work may add category reporting or controlled reassignment tools only after separate accounting/reporting review.

## Tests

`test_category_master.py` contains 53 dedicated tests using `PHARMACY_DB` throwaway SQLite files, covering schema/idempotence, CRUD, duplicate normalization, activation, Item behavior, import compatibility, permissions, menu wiring, persistence, and transaction-preservation checks. They never target `data/pharmacy.db` and never access MySQL or the old Pharma-WINNER system.

# Licensing PostgreSQL schema and changes

`license_server.models.Base` remains the sole schema definition. Super Admin
uses the existing `LICENSE_DATABASE_URL` and the same eight licensing tables.
The migration wrapper imports that Base; it does not create a second database or
read any local pharmacy records. This change adds endpoints/audit event types and
uses the existing `licenses.status = DISABLED` value for license-wide revocation.
It adds no tables, columns, constraints or incompatible persisted status values.

For an existing licensing database, run the read-only check:

```text
python -m super_admin.database.migrate --check
```

For a new, empty managed licensing database, run:

```text
python -m super_admin.database.migrate
python -m super_admin.database.migrate --check
```

Set the target's environment variables in the trusted operator shell before
running either command. Use a DDL-capable operator role for initialization, then
give the Vercel runtime role DML permissions only on licensing tables. Use a
direct PostgreSQL endpoint for schema setup and a provider pooler endpoint for
Vercel requests. Configure TLS (`sslmode=require` at minimum; `verify-full` with
the provider's CA is preferable). `create_all` is idempotent and never migrates
existing columns or business rows. Schema setup is never run during a Vercel
build, cold start, or request.

Production must use the existing central licensing records. If transferring an
existing central database to a managed service, transfer **only** its eight
licensing tables through the provider's migration tooling. Keep license/device
IDs, credential hashes, response revisions, signing key ID/private key, and the
HMAC pepper stable. Verify devices in an isolated provider test branch before
changing the desktop service URL. This is central licensing infrastructure
administration; no pharmacy database is transferred or recovered.

Create preview databases empty, or seed synthetic licenses/devices. Do not
clone production licensing credentials/sessions into preview. Use a separate
preview signing key, pepper, administrator and managed branch ID.

Code rollback does not require a schema rollback because the schema is unchanged.
Promote the previous compatible Vercel deployment while retaining current records
and keys. A rollback to code predating license-wide signed revocation would lose
that behavior; explicitly review that capability before promotion. Do not drop
tables, restore stale licensing response revisions, or rotate keys as part of
ordinary code rollback. Managed provider point-in-time recovery is an operator
procedure for the central license service only; Super Admin exposes no database
download/restore endpoints and no customer pharmacy recovery functionality.

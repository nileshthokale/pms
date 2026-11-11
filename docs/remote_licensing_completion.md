# Remote device licensing implementation — 9 November 2026

The subsequent [Super Admin implementation](../super_admin/README.md) moves the
dashboard/admin routes into `super_admin/`, adds compatible license-wide actions,
and prepares Vercel hosting. See its [verification report](../super_admin/tests/verification.json)
for the current 51-test results and deployment limits. The original implementation
report below records the earlier licensing work.

The subsystem is implemented in source and verified locally with PostgreSQL and
actual HTTPS. It is **not publicly deployed**. Public remote monitoring is not
claimed. The desktop service URL and public key remain unconfigured until a real
deployment provides them, so a source launch currently presents the safe licensing
configuration/activation screen before database initialization. No unsigned or
unlicensed access is granted as a fallback.

## Production data protection

The active source-run database is
`C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\data\pharmacy.db`.
The packaged application resolves to
`%LOCALAPPDATA%\PharmacyManagementSystem\pharmacy.db`; both existing files were
hashed. The root-level `pharmacy.db` is an existing empty file, not the active
source database. No customer database or backup was deleted, renamed, moved,
encrypted, overwritten, or tested against. Production was accessed only by file
reads for hashing and creating the isolated clone.

The existing `database/backup_restore.py` mechanism uses SQLite's online backup
API, read-only integrity/schema validation, SHA-256 checks, and safety backups
for user-requested restore. That module was not modified. Migration backups in
`database/connection.py` remain intact. Licensing neither calls restore nor owns
any tables in the pharmacy database.

| Database | SHA-256 before | SHA-256 after |
| --- | --- | --- |
| Active `data/pharmacy.db` | `e87e89a2772052169efe551bdf49a0b205b376d873a5769737a6bafdb11685a4` | `e87e89a2772052169efe551bdf49a0b205b376d873a5769737a6bafdb11685a4` |
| Existing packaged database | `c5672f3817900f57f8e3bea9cc9e7af526b4ab6f3572c4f11b67fa4dd9974fcb` | `c5672f3817900f57f8e3bea9cc9e7af526b4ab6f3572c4f11b67fa4dd9974fcb` |
| Empty root-level database | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Evidence: `temp/license_validation/production_before.json` and
`temp/license_validation/production_after.json`. Before implementation there
were no WAL/SHM sidecars for these databases. The test fixture was copied to
`temp/license_validation/pharmacy_clone.db` without opening production through
SQLite. The clone's integrity check returned `ok`; foreign-key check returned
zero violations. Its preserved counts include 72,255 sales invoices, 5,732
purchase invoices, 940 items, 7,817 stock batches, 29 customers, 86 suppliers,
and 157,788 ledger transaction rows.

## Files

Modified existing files:

- `main.py`: license validation before normal initialization/login; controller
  attachment and safe network-worker shutdown.
- `database/connection.py`: independent connection-admission hook and leases
  covering existing connection lifetimes; normal SQLite settings preserved.
- `ui/main_window.py`: prevent pharmacy routing/hotkeys while restricted.
- `requirements.txt`: desktop `cryptography` and `httpx` dependencies.
- `.gitignore`: exclude secrets, environment files, private key files, device state.

Created desktop package:

- `licensing/__init__.py`, `config.json`, `protocol.py`, `storage.py`, `client.py`,
  `gate.py`, `qt.py`.

Created server package:

- `license_server/__init__.py`, `app.py`, `models.py`, `settings.py`, `manage.py`,
  `requirements.txt`, `.env.example`, `Dockerfile`, `compose.yaml`, `Caddyfile`,
  `README.md`.
- `license_server/dashboard/index.html`, `login.html`, `dashboard.js`, `login.js`,
  `style.css`.

Created tests/documentation:

- `tests/licensing/conftest.py`, `test_remote_licensing.py`, `test_ui_startup.py`,
  `run_pharmacy_regression.py`, `https_postgres_smoke.py`.
- This completion report and `docs/remote_licensing_verification.json`.

Disposable clones, portable PostgreSQL binaries/test cluster, TLS certificates,
and test evidence are under ignored `temp/license_validation/`. The test
PostgreSQL process was shut down after verification. Nothing was packaged into
an EXE, and existing `build/` and `dist/` artifacts were not changed.

## Architecture, schema, and desktop integration

See [the deployment guide](../license_server/README.md) for concrete deployment
commands, API paths, secrets, recovery, and operational requirements.

FastAPI and the developer web dashboard run separately from the pharmacy desktop.
PostgreSQL stores eight tables: `license_customers`, `licenses`, `devices`,
`new_device_alerts`, `administrators`, `admin_sessions`, `license_rate_limits`,
and `license_audit`. Their schema was actually created and exercised in an
isolated PostgreSQL 17.6 cluster. No licensing schema migration touches pharmacy
SQLite. Row locks enforce seat capacity; PostgreSQL advisory locks serialize
registration/rate windows across server workers.

ALERT mode creates the first-seen record and one new-device alert immediately.
Valid customer activation keys authorize within expiry/status/seat limits without
manual approval for newness. Unassociated devices remain pending, and exhausted
licenses yield LIMIT_REACHED. NEW detection is shown separately from authorization
status. The dashboard includes customer/license/version, device ID, first seen,
first activation, last seen, status, alerts, counts, audit history, pagination,
explicit revoke/reactivate confirmation and reasons. “Recently online” uses a
900-second observation threshold and displays actual last-seen timestamps; it
does not imply a live connection. Recently seen covers 24 hours.

The desktop creates a random UUID and 48-byte random secret before its first
request. Windows DPAPI encrypts credentials, activation material, signed leases,
last successful validation, and clock state in the per-user licensing directory.
The device identity is independent from MAC addresses/hardware serial numbers.
Only public verification keys and the HTTPS URL are configured in the desktop.

Signed server time, locally verified expiry, a 48-hour lease, monotonic elapsed
time, persisted trusted time, and a wall-clock high-water mark enforce the offline
policy. Restart does not extend the deadline. A detected rollback requires
successful signed internet validation. A server failure, network outage, timeout,
invalid response, license expiry, and confirmed revocation produce distinct states.
Unsigned error messages cannot revoke a device or renew the offline timer.

Networking runs in a Qt worker with verified TLS, request deadlines, response-size
limits, and no redirects. Heartbeats run every five minutes; local expiry is
checked at 15-second intervals. After restriction, new connections/navigation
are denied. Existing database connections retain their leases and can commit or
roll back normally. The modal lock appears only after those leases finish.
Reactivation requires an administrator action and a newer signed authorization;
there is no local unlock control. Sale/purchase calculations, stock, patient,
supplier, ledger, reports, printing, backup, and normal pharmacy authentication
were not rewritten.

## Security protections

- Ed25519 server-only private key; strict signed envelopes with issuer/audience,
  installation ID, nonce, revision, issue time, offline deadline, and expiry.
- HTTPS required by desktop/server; TLS certificate validation; restricted trusted
  proxy addresses; no public PostgreSQL/Uvicorn ports in the deployment definition.
- Server activation/device/session credentials stored as HMAC digests with a secret
  pepper. Developer passwords use Argon2id.
- Secure HttpOnly SameSite administrator cookies, session expiry, developer-role
  checks on all administrative data/action routes, CSRF validation and origin
  checks, per-user/IP login throttling and device request limits.
- Administrator/device audit events with timestamps, administrator, device,
  reasons, failed checks, heartbeats, registrations, revoke/reactivate. Desktop
  logs offline/status transitions with rotation. No passwords, device secrets,
  activation keys, access tokens, or signing keys are logged. Validation errors
  do not echo submitted secrets. Dashboard text is rendered with `textContent`.
- No licensing file operation targets a pharmacy database or backup.

## Test results

| Verification | Result |
| --- | --- |
| Dedicated licensing suite against isolated PostgreSQL | **28 passed**, one dependency deprecation warning |
| Controlled first registration, pending/limit states, idempotency, alerts | Passed |
| Existing startup, heartbeat and observed online/offline/recent transitions | Passed |
| 48-hour boundary, restart, timeout/Internet/server outage and recovery | Passed without real-time waiting |
| Clock rollback persistence and monotonic elapsed-time expiry | Passed |
| Unsigned/tampered/wrong-device/replayed responses, bad credentials | Passed |
| Admin authentication/authorization, secure cookies, CSRF, confirmation, reasons, audit, rate limiting | Passed |
| Concurrent PostgreSQL registration with one available seat | One authorization, three LIMIT_REACHED; no oversubscription |
| DPAPI roundtrip, ciphertext and corrupted-state rejection | Passed on Windows |
| Revocation during actual `SalesDAO.insert_invoice` posting transaction | Invoice, stock deduction, ledger entries committed; new connection denied; lock deferred |
| Revocation restart, reactivation, Qt lock/recovery and startup into existing window | Passed |
| Actual socket HTTPS + PostgreSQL + DPAPI smoke test | Activation, heartbeat, dashboard, revocation, restart and reactivation passed with certificate verification |
| Existing pharmacy subset | 509 run; 496 passed, 13 failures, 0 errors, 0 skips |
| Original-code comparison of all failing modules | 184 run; the same 13 failures reproduced with original HEAD versions of modified application files |
| Clone integrity / foreign keys | `ok` / 0 violations |
| Production/packaged/root database hashes | All unchanged |
| Python syntax, dashboard JavaScript syntax, Git whitespace checks | Passed |

The 13 existing regression failures are three WALKIN-description/accounting
expectations, one purchase stock-unit expectation, eight document-number
formatting expectations, and one sales-report stock-unit expectation. They
reproduce before these licensing edits. They were preserved for honest reporting,
not weakened or changed as part of licensing. The full historical suite was not
run; the selected subset covers login, financial years, backup/restore, sale save,
stock/batch integrity, purchase/payment/receipt posting, patient history, printing,
reports, and UI wiring. Regression evidence is in
`temp/license_validation/pharmacy_regression.log` and `pharmacy_baseline.log`.

## Remaining limitations

Public hosting, real DNS/TLS provisioning, server administrator/customer setup,
and actual remote-device acceptance are still required. The provided Docker
deployment definitions were reviewed but Docker was unavailable locally; the
Python service was tested with real local PostgreSQL and TLS instead. Configure
the real public key and URL before deploying the desktop. Installer resource
inclusion must be handled in a later authorized packaging task. No EXE was built.

Offline revocation cannot be learned before a successful server request; the
previous signed allowance can last up to 48 hours. Full system snapshot rollback
and privileged Python/source tampering require stronger platform attestation.
DPAPI credentials belong to a Windows profile; multiple Windows profiles on the
same computer are distinct installations. There is no MFA/SSO, automated central
backup scheduler, schema-upgrade migration system, or automatic pruning of expired
sessions/rate-limit rows. Recovery/retention/infrastructure load tests remain
operator responsibilities. No license key or customer association is inferred
from existing business records.

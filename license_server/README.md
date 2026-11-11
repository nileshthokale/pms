# Remote pharmacy licensing service

This is a separate developer-owned service. Deploy `license_server/` and the
shared `licensing/protocol.py`; never upload the pharmacy database, backups,
desktop credentials, or desktop source data directories to the service.

The developer dashboard and admin routes now live in `super_admin/`. This service
imports that router and preserves `/admin/*` and `/v1/devices/*` compatibility.
See [Super Admin and Vercel deployment](../super_admin/README.md) for the Vercel
runtime, managed PostgreSQL, environment separation, data boundaries and tests.
Docker deployment includes the same `super_admin/backend` and `frontend` files.

FastAPI serves device APIs and the authenticated developer dashboard. SQLAlchemy
stores central licensing records in PostgreSQL. Ed25519 signatures authorize
desktop operation. Caddy terminates public HTTPS and forwards to an internal
Uvicorn process. PostgreSQL and Uvicorn have no published ports in Compose.

## Deployment

1. Provision a Linux host, public DNS name, and inbound TCP 443 (80 is used only
   for ACME certificate issuance and HTTPS redirects). Install Docker/Compose.
2. Generate an Ed25519 key on a trusted developer/server machine:

   ```text
   python -m license_server.manage generate-key --private-file /secure/license-signing.pem --public-file /secure/license-public.json
   ```

   Restrict the private file to the server service account (`chmod 600` on Linux;
   Windows ACLs if developing on Windows). Store an encrypted recovery copy.
   Never include the private key in a desktop package. The CLI uses exclusive
   writes so an existing key cannot accidentally be overwritten.
3. Set these variables in an untracked deployment `.env` beside `compose.yaml`:

   ```text
   LICENSE_DOMAIN=licenses.your-domain.example
   LICENSE_PRIVATE_KEY_FILE=/secure/license-signing.pem
   LICENSE_POSTGRES_PASSWORD=<strong random password>
   LICENSE_DATABASE_URL=postgresql+psycopg://licensing:<URL-encoded-password>@postgres:5432/licensing
   LICENSE_SECRET_PEPPER=<at least 32 cryptographically random characters>
   ```

   URL-encode special characters in the database password. Keep the pepper
   stable: changing it invalidates device credentials and activation hashes.
4. From `license_server/`, initialize and start:

   ```text
   docker compose up -d postgres
   docker compose build api
   docker compose run --rm api python -m license_server.manage init-db
   docker compose run --rm api python -m license_server.manage create-admin developer
   docker compose up -d
   ```

   Administrator passwords are entered through hidden prompts and stored with
   Argon2id. There are no default accounts/passwords. The initial bootstrap CLI
   is available only to the server operator. Developer license issuance and
   updates require an existing developer password.
5. Issue a customer license through an interactive server command:

   ```text
   docker compose exec api python -m license_server.manage issue-license --customer "Customer pharmacy" --expires "2027-11-09T00:00:00+00:00" --max-devices 2 --admin developer
   ```

   The activation key is shown once for secure delivery. It is stored centrally
   only as an HMAC digest. Do not capture the command's output in plaintext
   operational logs. To renew or disable a license:

   ```text
   docker compose exec api python -m license_server.manage update-license LICENSE_UUID --expires "2028-11-09T00:00:00+00:00" --status ACTIVE --admin developer --reason "Customer renewal"
   ```
6. Configure `licensing/config.json` in the desktop installation with the real
   `https://` service URL and the **public** keys from `license-public.json`:

   ```json
   {
     "server_url": "https://licenses.your-domain.example",
     "public_keys": {"primary": "BASE64_RAW_ED25519_PUBLIC_KEY"},
     "heartbeat_seconds": 300,
     "activation_mode": "ALERT",
     "offline_grace_hours": 48
   }
   ```

   An unconfigured installation displays a restricted activation screen; it
   never grants unsigned access. This checkout deliberately contains no live
   server URL or invented production key. A future packaging step must bundle
   this public config and the new desktop dependencies. No EXE is built here.
7. Open `https://<domain>/admin/sign-in`, sign in, launch an actual test
   installation, and enter its activation key. Verify the NEW alert, customer,
   version, first activation, and last seen. Revoke with a reason and explicit
   confirmation, validate from the test device, then reactivate and validate
   again. Only after this succeeds can public remote monitoring be claimed.

The proxy has a fixed internal address `172.30.0.10`. Uvicorn trusts forwarded
headers only from that address. If changing the network, change both settings;
never trust arbitrary client-provided forwarded headers. Requests reaching the
API with an HTTP scheme are rejected. Direct Uvicorn deployment can instead use
`--ssl-certfile` and `--ssl-keyfile`; it still requires a trusted HTTPS certificate.

## Central schema v1

| Table | Purpose |
| --- | --- |
| `license_customers` | Customer ID and display name |
| `licenses` | Customer relation, activation digest, expiry, seat limit, active/disabled status |
| `devices` | Random installation ID, credential digest, license relation, version, authorization status, first seen/activation, last seen, signed response revision |
| `new_device_alerts` | One immediate alert per installation, acknowledgement administrator/time |
| `administrators` | Argon2id password hash, developer role, active flag |
| `admin_sessions` | Hashed authentication cookie, CSRF value/hash, expiry |
| `license_rate_limits` | Shared rate windows serialized across PostgreSQL workers |
| `license_audit` | Event, administrator/actor, device ID, reason, UTC timestamp |

Schema creation is explicit and idempotent. Future schema changes need reviewed
migrations; `create_all` does not migrate existing columns. Use PostgreSQL backup
and restore procedures independently from pharmacy backups. Back up the central
database and secrets together. Keep central audit rows under a documented retention
policy. Periodically remove expired admin sessions and old rate-limit rows using
a server maintenance job; no automatic pruning is configured in this release.

## APIs and policy

- `POST /v1/devices/register`: persist device and alert immediately; authorize a
  valid activation subject to license expiry/status and seat limit. Repeated
  registration is idempotent. Revocation cannot be overridden by an activation key.
- `POST /v1/devices/validate`, `/heartbeat`, `/status`: authenticate the device,
  update last seen/version, audit, and return a signed license or restriction.
- `/admin/me`, `/summary`, `/devices`, `/alerts`, `/audit`: authenticated,
  developer-authorized views. Device listing is paginated.
- `POST /admin/devices/{id}/revoke` and `/reactivate`: authenticated developer,
  CSRF token, matching device confirmation, and reason required. Reactivation
  enforces active license, expiry, and available seat capacity.
- `/admin/licenses` and `POST /admin/licenses/{id}/revoke` or `/reactivate`:
  license-wide management over existing ACTIVE/DISABLED rows. DISABLED licenses
  return signed REVOKED status for associated devices. Reactivation retains
  individually revoked devices. `/admin/devices/{id}/history` shows existing
  licensing activation/audit events.
- `POST /admin/alerts/{id}/acknowledge`, `/logout`: developer session and CSRF
  required. `POST /admin/login` is rate limited by user and client IP.

All device results include a signature, issuer, audience, installation ID,
request nonce, monotonically increasing revision, server issue time, expiry,
and an offline deadline no later than 48 hours or the underlying license expiry.
Plain JSON, invalid signatures, and responses from other devices cannot renew
the lease or revoke a device. A signed revocation remains locked across restarts
and outages until a higher-revision signed authorization is received.

NEW is detection state, separate from AUTHORIZED/PENDING/LIMIT_REACHED/REVOKED.
First detection requires no manual approval when a valid license has capacity.
The dashboard says “Recently online” only if last seen is within the 900-second
heartbeat threshold, and shows the actual timestamp. “Recently seen” covers 24
hours. These are observations of recent requests, not live sockets.

## Recovery and operational limits

Reactivation is performed in the dashboard and requires the next successful
desktop validation. License expiry can be renewed with the CLI. If a Windows
profile is lost or DPAPI state becomes unreadable, support should inspect/revoke
the old device, preserve the pharmacy database/backups, and provision a new
installation through the normal activation process. Do not delete credentials
as a revocation workaround. Copied license state is bound to the Windows user
through DPAPI, but fully privileged local attackers or a restored complete system
snapshot cannot be defeated by Python-only client licensing.

Clock checks use signed server time, a monotonic clock while running, persisted
trusted time, and a wall-clock high-water mark. A rollback exceeding five minutes
requires fresh internet validation. Restart does not renew the offline lease.
Full protection against repeated system snapshot restores or manipulation of the
Windows account requires stronger platform attestation beyond this implementation.

An offline device learns a revocation on its next successful validation. It may
continue under its existing signed lease for at most 48 hours; immediate offline
revocation is not possible. Timeouts, Internet outages, and server errors are
tracked separately, and never become revocations. TLS failures cannot securely
distinguish a broken network from a misconfigured peer; both preserve the existing
lease while requiring eventual successful validation.

Administrator authentication has password hashing, expiring secure HttpOnly
SameSite cookies, developer-role authorization, CSRF checks, request validation
without secret echoing, and shared rate limiting. MFA and SSO are not included.
Public hosting, disaster recovery drills, infrastructure load testing, and final
installer resource inclusion remain deployment tasks. No service is publicly
deployed by this implementation.

## Verification

Install desktop requirements and server requirements, then `pytest`:

```text
python -m pip install -r requirements.txt -r license_server/requirements.txt pytest==8.4.2
python -m pytest tests/licensing -q
python tests/licensing/run_pharmacy_regression.py
```

Prepare the isolated pharmacy file clone first, including any WAL sidecars;
never direct tests at an active pharmacy database. The regression runner copies
source and the clone into a disposable workspace and audits SQLite open paths.
It can compare original application code with `--baseline`.

The licensing tests use controlled time and injectable in-process transport by
default. Set `LICENSE_TEST_POSTGRES_URL` only to the test cluster
`postgresql+psycopg://license_test@127.0.0.1:55439/licensing_isolated_test` to run
against real PostgreSQL; every fixture creates/drops its own test schema. The
port/database guard rejects other central databases. Start/stop this loopback
cluster manually; it is never a production service. `https_postgres_smoke.py`
uses this cluster, a temporary loopback certificate, verified TLS, and actual
network connections, then shuts down its HTTP service and drops its test schema.

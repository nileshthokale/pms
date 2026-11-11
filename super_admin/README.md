# Super Admin: software licenses and device access

Super Admin is implemented in source and ready for Vercel configuration. It
shares the existing FastAPI application and PostgreSQL licensing schema.
`license_server.app:create_app` remains compatible for Docker/Uvicorn deployment;
it imports the Super Admin router rather than maintaining a second dashboard.

The system handles software access only. It has no patient, sales, purchase,
stock, ledger, pharmacy database download/restore, file-modification, or remote
computer-control APIs. Customer association is the name/ID recorded with a
software license, not customer pharmacy business records. No desktop database
path, database file, or business-data backup is transmitted to the server.

## Folder structure

```text
super_admin/
  frontend/              # Authenticated HTML, browser JS/CSS and local Three.js module
  backend/
    app.py               # Vercel ASGI entrypoint wrapping existing create_app()
    routes.py            # Shared administrator routes at /admin/*
    build_frontend.py    # Copies public JS/CSS/Three.js assets into public/admin/assets
    .env.example         # Server configuration names; no secrets
  database/
    migrate.py           # Existing central schema creation/read-only checks
    README.md            # Managed PostgreSQL setup and rollback policy
  tests/                 # Admin, preview isolation, Vercel and browser tests
  README.md
```

Shared modules remain in `license_server/` and `licensing/protocol.py`. The
desktop's signed verification, DPAPI credentials, 48-hour grace, ALERT mode,
and transaction-safe lock are retained. Desktop code was not changed in this
Super Admin task. A confirmed device or license revocation arrives in a signed
response; a timeout/server error never becomes a confirmed revocation.

## Dashboard behavior

`/admin/sign-in` provides secure administrator login. `/admin` requires a
developer-authorized session before returning dashboard HTML. It displays
registered/online/offline/revoked devices, new installation alerts, active/revoked
licenses, license customer associations, application versions, first registration,
first activation, last seen, device activation history and administrator audit
logs. Online means last seen within the configured threshold (default 900 seconds);
the timestamp is shown and the dashboard does not imply a live connection.

The interface follows `DESIGN.md`: a pure-black canvas, white Swiss-style
typography, border-separated information grids, minimal shadows and restrained
color reserved for status. The device network uses a locally hosted, lazy-loaded
Three.js module. It pauses outside the viewport or while the page is hidden,
honors reduced-motion preferences, disposes WebGL resources on exit and provides
an accessible device-map fallback when WebGL is unavailable. All network nodes,
counters, alerts and details come from authenticated licensing APIs.

Device and license revocation require a matching ID, explicit checkbox confirmation,
and a reason. The dashboard displays the operation result. License-wide revocation
sets the existing central `licenses.status` to `DISABLED` and causes associated
devices to receive signed REVOKED results at their next successful validation.
License reactivation requires an unexpired license/capacity and leaves individually
revoked devices revoked. Device reactivation requires an active, unexpired license
and an available seat. Administrator actions, rejected auth/CSRF/origin requests,
dashboard views and activation events are audited without logging credentials.

## Vercel deployment

This implementation follows Vercel's supported FastAPI Python/ASGI runtime,
Python 3.13, custom module entrypoint and static `public/` assets. Sources:
[FastAPI](https://vercel.com/docs/frameworks/backend/fastapi),
[Python runtime](https://vercel.com/docs/functions/runtimes/python),
[project configuration](https://vercel.com/docs/project-configuration),
[upload exclusions](https://vercel.com/docs/deployments/vercel-ignore), and
[request headers](https://vercel.com/docs/headers/request-headers).

1. Provision managed PostgreSQL through a provider such as Neon/Supabase. Use
   the existing central licensing database or migrate its licensing records using
   the provider's tooling. Create an empty/synthetic preview branch. Follow
   [database setup](database/README.md). No local pharmacy data is uploaded.
2. Create a Vercel project with the **repository root** as Root Directory and
   **FastAPI** as the framework. `pyproject.toml` selects
   `super_admin.backend.app:app`, overriding the repository's desktop `main.py`.
   `vercel.json` installs only `license_server/requirements.txt` and runs
   `python -m super_admin.backend.build_frontend`. No PySide6/desktop dependency
   is installed in the Vercel function. Choose a deployment region near the
   PostgreSQL provider using Vercel project settings.
3. Configure the server environment variables below in **Production**. Configure
   separate Preview/Development values, never inherit production credentials
   into those environments. Mark key/pepper/database credentials as sensitive.
4. Initialize schema and create the administrator from a trusted operator machine
   as described below. These commands do not run inside public API requests or
   Vercel build hooks.
5. Deploy a Preview, inspect `/health` and `/health/ready`, sign in using the preview
   account, and activate a synthetic test device using its preview verification
   key. Test revoke/reactivate before promoting the prepared code to Production.
6. In Vercel Project Settings → Domains, add a stable hostname such as
   `licenses.example.com`. Follow Vercel's exact DNS instructions at your DNS
   provider. Vercel provisions HTTPS. Set production `LICENSE_ADMIN_ORIGIN` to
   `https://licenses.example.com`; use that origin for administrator login/actions.
   The same host serves frontend and API, so browser sessions need no CORS or
   cross-domain token storage. Other deployment aliases may show the sign-in
   screen but cannot perform admin mutations unless they match the configured
   origin. Do not enable a deployment-protection gate across production device
   endpoints that the desktop cannot authenticate through; protect `/admin`
   with the application's authentication and optionally Vercel firewall rules.
7. Keep the current signing key ID/private key and pepper when deploying existing
   devices. Set only the stable HTTPS URL and public verification key in desktop
   `licensing/config.json`. Never put a private key, database URL, administrator
   password or Vercel deployment-bypass secret in the desktop or frontend.
8. Verify an actual test installation connects to the public deployment, appears
   in alerts, validates, revokes safely, and reactivates. Public deployment and
   real remote-device acceptance remain outstanding; local tests do not prove
   public monitoring.

For CLI deployment from this repository, use Vercel CLI >=48.1.8:

```text
vercel link
vercel pull --environment=preview
vercel build
vercel deploy --prebuilt
```

After preview acceptance, use your normal reviewed production promotion process
or `vercel deploy --prod`. No deployment was performed during implementation.
CLI linking/pulling requires your Vercel account and configured project. Do not
commit generated `.vercel/` files containing project/environment settings.

The `.vercelignore` is a strict upload allowlist: only 24 required config/licensing/
Super Admin files are uploaded. It excludes pharmacy databases/backups/records,
desktop modules, test fixtures, environment files and private key files before
upload. `vercel.json` also excludes non-service folders from function bundles.
The build copies only public JS/CSS/Three.js assets to `public/admin/assets`; sign-in/dashboard HTML are
served by FastAPI and the dashboard remains authenticated. PostgreSQL persists
sessions, rate limits and device state across function instances; `NullPool`
avoids a persistent process-local database pool. Use a provider pooler that supports
the transaction-scoped locks used for seat enforcement; migrations use the direct
database endpoint. There are no background threads/jobs or SQLite server storage.

## Environment variables

| Variable | Environment / purpose |
| --- | --- |
| `LICENSE_DATABASE_URL` | Server-only `postgresql+psycopg://...?...sslmode=require` URL with URL-encoded password. Use `verify-full` when CA configuration permits. |
| `LICENSE_SIGNING_KEY_PEM_B64` | Server-only base64 of the complete Ed25519 private PEM. Required in Vercel; no temporary key file is written. |
| `LICENSE_SECRET_PEPPER` | Server-only stable cryptographically random string, at least 32 characters. Separate preview/production values. |
| `LICENSE_KEY_ID` | Signing key ID. Preserve `primary` for existing production devices; use a distinct preview ID. |
| `LICENSE_ADMIN_ORIGIN` | Exact HTTPS browser origin without a path. Required stable production custom domain; omit in Preview to derive `https://$VERCEL_URL`. |
| `LICENSE_DEPLOYMENT_ENV` | Must match Vercel's `production`, `preview` or `development` environment. |
| `LICENSE_ONLINE_THRESHOLD_SECONDS` | Optional, default 900; allowed 60–3600. |
| `LICENSE_DATABASE_ID` | Preview/Development: provider's current distinct database/branch identity. |
| `LICENSE_PRODUCTION_DATABASE_ID` | Preview/Development: actual production provider database/branch identity for the guard. |
| `LICENSE_PRODUCTION_DATABASE_HOST` | Preview/Development: production PostgreSQL hostname. |
| `LICENSE_PRODUCTION_DATABASE_NAME` | Preview/Development: production PostgreSQL database name. Matching both host/name is rejected. |
| `LICENSE_PRODUCTION_KEY_ID` | Preview/Development: production key ID; the preview key ID must differ. |
| `LICENSE_PRODUCTION_SIGNING_KEY_SHA256` | Preview/Development: SHA-256 of the production raw Ed25519 public key; the preview key material must differ. Public fingerprint, not a secret. |
| `VERCEL`, `VERCEL_ENV`, `VERCEL_URL` | Set by Vercel. Do not manually override in hosted deployments. |

For Docker/Uvicorn, `LICENSE_SIGNING_KEY_FILE` remains supported. Vercel requires
the environment-secret form. There are no frontend environment variables or secret
build-time interpolations. Production/preview use different cookie names with
Secure, HttpOnly, SameSite=strict attributes, eight-hour expiry, server-side role
checks and CSRF tokens. In Vercel, Origin is required for every admin mutation,
including login. Server-to-server test/automation clients must send that exact
Origin and the session's CSRF header. Vercel's edge-provided client IP is used for
rate limiting only when running in the Vercel environment; arbitrary forwarded
headers are not trusted by the standalone service.

Preview guards catch common configuration mistakes, but their provider identities
must be entered correctly. Verify the provider branch in the console. Never copy
production secrets or sessions into previews or use a production database under
an alternative hostname to evade the guard.

## Administrator and license setup

Install server dependencies in a separate operator environment:

```text
python -m pip install -r license_server/requirements.txt
python -m super_admin.database.migrate
python -m super_admin.database.migrate --check
python -m license_server.manage create-admin developer
python -m license_server.manage issue-license --customer "Customer pharmacy" --expires "2027-11-09T00:00:00+00:00" --max-devices 2 --admin developer
```

Passwords use hidden interactive prompts and Argon2id storage. There is no default
administrator account or public bootstrap endpoint. Activation keys are shown once
for secure customer delivery and stored as HMAC digests. Do not pipe setup output
containing activation keys into plaintext logs. Use the existing `update-license`
CLI to renew expired licenses before legitimate reactivation.

For a new service, generate a key using `license_server.manage generate-key` on a
trusted server/operator machine and configure its private PEM as the server secret.
For an existing service, retain its current key instead. Derive the preview guard
fingerprint locally from the production public key and keep production private
material out of preview. The desktop embeds only public verification material.

## API endpoints

Device APIs retain their existing paths/request schemas and signed envelope:

| Method / path | Purpose / authorization |
| --- | --- |
| `GET /health` | Public liveness and licensing policy; no records/secrets. |
| `GET /health/ready` | Public licensing-schema/database readiness; generic 503 on failure. |
| `POST /v1/devices/register` | Device credential + nonce + optional activation key; ALERT registration. |
| `POST /v1/devices/validate`, `/heartbeat`, `/status` | Device credential + nonce; signed status and last-seen update. |
| `POST /admin/login` | Developer credentials; origin check, user/IP rate limits, secure session. |
| `GET /admin/me` | Authenticated identity, CSRF token, environment. |
| `POST /admin/logout` | Authenticated + CSRF + origin; invalidate session. |
| `GET /admin/summary` | Authenticated device/activity/license/alert counts. |
| `GET /admin/devices?offset=0&limit=100&activity=all&q=&status=all` | Authenticated paginated licensing device records with global search, activity and effective-status filtering. |
| `GET /admin/devices/{id}` | Authenticated licensing-only device detail; no customer business data or credentials. |
| `GET /admin/devices/{id}/history?offset=0&limit=100` | Authenticated registration/activation/revoke/reactivate licensing events. |
| `GET /admin/licenses?offset=0&limit=100&q=&status=all` | Authenticated license status/customer/expiry/capacity with global search/filtering; no activation keys. |
| `GET /admin/alerts` | Authenticated outstanding new-device alerts with licensing association and application version (up to 500). |
| `POST /admin/alerts/{id}/acknowledge` | Authenticated + CSRF + origin; acknowledge alert. |
| `POST /admin/devices/{id}/revoke`, `/reactivate` | Authenticated + CSRF + origin; `confirm: true`, matching `confirmed_device_id`, meaningful `reason`. |
| `POST /admin/licenses/{id}/revoke`, `/reactivate` | Authenticated + CSRF + origin; `confirm: true`, matching `confirmed_license_id`, meaningful `reason`. |
| `GET /admin/audit` | Authenticated recent licensing/admin audit entries (up to 200). |
| `GET /admin` | Authenticated dashboard HTML. |
| `GET /admin/sign-in`, `/admin/assets/{name}` | Public sign-in and static JS/CSS, no records or controls without API authorization. |

License API statuses map existing `DISABLED` rows to dashboard REVOKED. Wire
license responses remain the same signed protocol; no desktop signature bypass
or ordinary JSON unlock is added. API mutations return a clear status/message.

## Migrations and rollback

This release reuses the eight existing tables without schema changes. Run the
read-only schema check on the target before deployment. Schema creation/migration
never occurs at Vercel startup. For future schema changes, add reviewed versioned
migrations and test against an empty/synthetic managed branch first.

Use Vercel's deployment rollback/promote action to return to a **compatible**
previous version while leaving central licensing rows, signing key, key ID, pepper
and device revisions intact. A pre-Super-Admin build does not implement license-wide
signed revocation; account for that before rollback. Never delete licensing rows,
restore older signed revisions, or touch local pharmacy databases for code rollback.
Provider backup/PITR procedures belong to the central licensing infrastructure
operator and are not exposed by this dashboard.

## Verification and remaining steps

The implementation passed 54 isolated PostgreSQL desktop/admin/runtime tests
(one dependency deprecation warning), verified local socket HTTPS with PostgreSQL
and DPAPI, and passed headless Chrome acceptance for login, summary, history,
device and license revoke/reactivate, offline filtering and logout with no page
errors. The redesign browser suite also passed real Three.js selection, accessible
fallback, keyboard details, global searches, filters, pagination, alert review,
desktop/tablet/mobile layout, reduced motion and API outage recovery. Official
`@vercel/python` entrypoint detection and Vercel JSON property validation pass;
the 24-file upload allowlist excludes all pharmacy files.
The production pharmacy SHA-256 is unchanged (see `tests/verification.json`).

Run the tests with a dedicated local test PostgreSQL cluster, never production:

```text
python -m pip install -r requirements.txt -r license_server/requirements.txt pytest==8.4.2 vercel-runtime==0.24.1
python -m pytest tests/licensing super_admin/tests -q
```

Without `LICENSE_TEST_POSTGRES_URL`, fixtures use disposable SQLite and the
PostgreSQL concurrency test is skipped. Set it only to the guarded loopback test
cluster `postgresql+psycopg://license_test@127.0.0.1:55439/licensing_isolated_test`
to exercise PostgreSQL. The preserved pharmacy fixture is an isolated clone.
Node verification/browser scripts use tooling under ignored
`temp/super_admin_validation/tooling`; their setup/results are in `tests/verification.json`.

No Vercel account/project, managed production database, DNS or production secrets
were supplied. A Vercel cloud build/deploy and actual public test-device connection
remain required. Local official builder/runtime checks are not a completed cloud
deployment. The local browser fixture uses a self-signed test certificate; the
separate socket smoke test verifies its trusted test certificate. The Docker
definition was updated for the moved dashboard but was not built locally. No EXE
was built. MFA/SSO, central backup scheduling, audit/session/rate-limit retention,
provider capacity/load tests and privileged-client anti-tampering remain operator
or future implementation work. Offline revocation arrives only on the next
successful validation, with the existing signed allowance capped at 48 hours.

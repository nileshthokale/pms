from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import secrets
import socket
import sys
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from starlette.requests import ClientDisconnect

from licensing.protocol import AUDIENCE, ISSUER, OFFLINE_SECONDS, sign_license
from license_server.models import Alert, Audit, Device, License, RateLimit
from license_server.settings import Settings
from license_server.security import digest, utc


def patch_proactor_connection_lost():
    """Silence WinError 10054 ConnectionResetError during socket.shutdown in Python 3.13 Proactor."""
    if sys.platform != "win32":
        return
    try:
        import asyncio.proactor_events
    except ImportError:
        return
    cls = asyncio.proactor_events._ProactorBasePipeTransport
    orig = getattr(cls, "_call_connection_lost", None)
    if orig is None or getattr(orig, "_patched_winerror_10054", False):
        return

    def _call_connection_lost_patched(self, exc):
        if self._called_connection_lost:
            return
        try:
            self._protocol.connection_lost(exc)
        finally:
            if hasattr(self._sock, "shutdown") and self._sock.fileno() != -1:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            server = self._server
            if server is not None:
                server._detach(self)
                self._server = None
            self._called_connection_lost = True

    _call_connection_lost_patched._patched_winerror_10054 = True
    cls._call_connection_lost = _call_connection_lost_patched


patch_proactor_connection_lost()


class ShutdownRegistry:
    """Tracks devices that gracefully closed their application session."""
    def __init__(self):
        self._devices: dict[str, datetime] = {}

    def mark_offline(self, device_id: str, when: datetime):
        self._devices[str(device_id)] = when

    def mark_online(self, device_id: str):
        self._devices.pop(str(device_id), None)

    def is_shut_down(self, device_id: str, last_seen: datetime) -> bool:
        when = self._devices.get(str(device_id))
        if when is None:
            return False
        if utc(last_seen) > utc(when):
            self._devices.pop(str(device_id), None)
            return False
        return True

    def active_shut_down_ids(self) -> set[str]:
        return set(self._devices.keys())


def utcnow():
    return datetime.now(timezone.utc)


class DeviceRequest(BaseModel):
    device_id: uuid.UUID
    device_secret: str = Field(min_length=40, max_length=100)
    app_version: str = Field(min_length=1, max_length=80)
    nonce: str = Field(min_length=32, max_length=100)


class Registration(DeviceRequest):
    activation_key: str | None = Field(default=None, max_length=200)


def ensure_schema_compatibility(engine):
    """Idempotently ensure database constraints allow ARCHIVED status."""
    if getattr(engine, "dialect", None) and engine.dialect.name == "postgresql":
        try:
            from sqlalchemy import text
            with engine.begin() as conn:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM pg_constraint WHERE conname = 'licenses_status_check'
                        ) THEN
                            ALTER TABLE licenses DROP CONSTRAINT licenses_status_check;
                        END IF;
                        ALTER TABLE licenses ADD CONSTRAINT licenses_status_check CHECK (status IN ('ACTIVE', 'DISABLED', 'ARCHIVED'));
                    EXCEPTION WHEN OTHERS THEN
                        NULL;
                    END $$;
                """))
        except Exception:
            pass


def create_app(settings=None, *, engine=None, clock=utcnow):
    patch_proactor_connection_lost()
    settings = settings or Settings.from_env()
    if engine is None:
        if not settings.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Production requires PostgreSQL")
        engine = create_engine(settings.database_url, pool_pre_ping=True,
                               poolclass=NullPool if settings.vercel else None,
                               connect_args={"connect_timeout": 5})
    ensure_schema_compatibility(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    shutdown_registry = ShutdownRegistry()
    app = FastAPI(title="Pharmacy Device Licensing", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.sessions = engine, sessions
    app.state.shutdown_registry = shutdown_registry

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default error response can echo submitted secrets in `input`.
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.exception_handler(ClientDisconnect)
    async def handle_disconnect(request, exc):
        return Response(status_code=499)

    @app.exception_handler(ConnectionResetError)
    async def handle_conn_reset(request, exc):
        return Response(status_code=499)

    @app.middleware("http")
    async def secure_transport(request, call_next):
        if request.url.scheme != "https":
            return JSONResponse({"detail": "HTTPS is required"}, status_code=400)
        try:
            response = await call_next(request)
        except (ClientDisconnect, ConnectionResetError):
            return Response(status_code=499)
        except OSError as exc:
            if getattr(exc, "winerror", None) in (10054, 10053):
                return Response(status_code=499)
            raise
        response.headers["Cache-Control"] = "no-store"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def db():
        with sessions() as session:
            yield session

    def audit(session, event, actor, device_id=None, reason=""):
        session.add(Audit(id=str(uuid.uuid4()), event=event, actor=actor,
                          device_id=device_id, reason=reason, created_at=clock()))

    def throttle(session, key, limit, seconds=60):
        # Advisory transaction lock serializes absent-row creation across PostgreSQL workers.
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        hashed = digest(key, settings.pepper)
        row = session.scalar(select(RateLimit).where(RateLimit.key == hashed).with_for_update())
        now = clock()
        if row is None:
            row = RateLimit(key=hashed, window_start=now, count=0)
            session.add(row)
        elif now >= utc(row.window_start) + timedelta(seconds=seconds):
            row.window_start, row.count = now, 0
        row.count += 1
        if row.count > limit:
            audit(session, "rate_limit", "anonymous")
            session.commit()
            raise HTTPException(429, "Too many requests; retry later")

    def request_ip(request):
        if settings.vercel:
            # Vercel overwrites this header at its edge. Trust it only in its runtime.
            value = request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                pass
        return request.client.host if request.client else "unknown"

    def authenticate_device(session, body):
        device = session.scalar(select(Device).where(Device.id == str(body.device_id)).with_for_update())
        if not device or not hmac.compare_digest(device.secret_hash, digest(body.device_secret, settings.pepper)):
            audit(session, "license_check_failed", "device", str(body.device_id), "Invalid device credentials")
            session.commit()
            raise HTTPException(401, "Device credentials rejected")
        return device

    def associate(session, device, activation_key):
        key = (activation_key or "").strip()
        if not key:
            return
        # 1. Accept License ID directly (case-insensitive UUID format)
        clean_key = key.lower()
        license = session.scalar(select(License).where(func.lower(License.id) == clean_key).with_for_update())
        # 2. Or accept the cryptographic activation hash
        if not license:
            license = session.scalar(select(License).where(License.activation_hash == digest(key, settings.pepper)).with_for_update())
        if not license:
            audit(session, "activation_failed", "device", device.id, f"Invalid activation key or license ID: {key[:8]}...")
            return
        if device.status == "REVOKED":
            return  # activation keys cannot override a developer revocation
        if license.status != "ACTIVE" or utc(license.expires_at) <= clock():
            device.status = "PENDING"
            return
        used = session.scalar(select(func.count()).select_from(Device).where(
            Device.license_id == license.id, Device.status == "AUTHORIZED", Device.id != device.id))
        device.license_id = license.id
        device.status = "AUTHORIZED" if used < license.max_devices else "LIMIT_REACHED"
        if device.status == "AUTHORIZED":
            if device.first_activation is None:
                device.first_activation = clock()
            audit(session, "device_activated", "device", device.id, license.id)

    def result(session, device, body, event):
        now = clock()
        shutdown_registry.mark_online(device.id)
        device.last_seen, device.app_version = now, body.app_version
        device.revision += 1
        license = session.get(License, device.license_id) if device.license_id else None
        status = device.status
        if status != "REVOKED" and license:
            if license.status != "ACTIVE":
                status = "REVOKED"
            elif utc(license.expires_at) <= now:
                status = "EXPIRED"
        expires = utc(license.expires_at).timestamp() if license else now.timestamp()
        offline_until = min(now.timestamp() + OFFLINE_SECONDS, expires) if status == "AUTHORIZED" else now.timestamp()
        payload = {"schema": 1, "issuer": ISSUER, "audience": AUDIENCE, "device_id": device.id,
                   "license_id": device.license_id, "customer_id": license.customer_id if license else None,
                   "status": status, "issued_at": now.timestamp(), "offline_until": offline_until,
                   "license_expires_at": expires, "revision": device.revision, "nonce": body.nonce}
        audit(session, event, "device", device.id, status)
        if status != "AUTHORIZED":
            audit(session, "license_check_unsuccessful", "device", device.id, status)
        session.commit()
        return sign_license(settings.private_key, settings.key_id, payload)

    @app.get("/health")
    def health():
        return {"status": "ok", "activation_mode": "ALERT", "offline_grace_hours": 48}

    @app.get("/health/ready")
    def readiness(session: Session = Depends(db)):
        try:
            # Verify the actual licensing schema, without returning record counts or secrets.
            from license_server.models import Base
            for table in Base.metadata.sorted_tables:
                session.execute(select(table).limit(0))
            return {"status": "ready"}
        except Exception:
            session.rollback()
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.post("/v1/devices/register")
    def register(body: Registration, request: Request, session: Session = Depends(db)):
        throttle(session, "register:" + request_ip(request), 30)
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": int.from_bytes(hashlib.sha256(str(body.device_id).encode()).digest()[:8], "big", signed=True)})
        device = session.scalar(select(Device).where(Device.id == str(body.device_id)).with_for_update())
        if device:
            device = authenticate_device(session, body)
        else:
            now = clock()
            device = Device(id=str(body.device_id), secret_hash=digest(body.device_secret, settings.pepper),
                            app_version=body.app_version, status="PENDING", first_seen=now, last_seen=now, revision=0)
            session.add(device)
            session.flush()
            session.add(Alert(id=str(uuid.uuid4()), device_id=device.id, created_at=now))
            audit(session, "new_device_registered", "device", device.id, "ALERT mode")
        if body.activation_key:
            associate(session, device, body.activation_key)
        return result(session, device, body, "license_check")

    def check(body, request, session, event):
        throttle(session, "check:" + request_ip(request), 120)
        device = authenticate_device(session, body)
        return result(session, device, body, event)

    @app.post("/v1/devices/validate")
    def validate(body: DeviceRequest, request: Request, session: Session = Depends(db)):
        return check(body, request, session, "license_check")

    @app.post("/v1/devices/heartbeat")
    def heartbeat(body: DeviceRequest, request: Request, session: Session = Depends(db)):
        return check(body, request, session, "heartbeat")

    @app.post("/v1/devices/status")
    def status(body: DeviceRequest, request: Request, session: Session = Depends(db)):
        return check(body, request, session, "status_check")

    @app.post("/v1/devices/offline")
    @app.post("/v1/devices/shutdown")
    def offline(body: DeviceRequest, request: Request, session: Session = Depends(db)):
        throttle(session, "offline:" + request_ip(request), 60)
        device = authenticate_device(session, body)
        now = clock()
        device.last_seen = now
        shutdown_registry.mark_offline(device.id, now)
        audit(session, "device_shutdown", "device", device.id, "Graceful application shutdown")
        session.commit()
        return {"status": "offline", "device_id": device.id, "timestamp": now.isoformat()}

    from super_admin.backend.routes import create_admin_router
    app.include_router(create_admin_router(settings, sessions, clock, audit, throttle, request_ip, shutdown_registry=shutdown_registry))

    return app

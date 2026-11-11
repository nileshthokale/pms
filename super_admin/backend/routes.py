"""Developer-only administration over the existing licensing schema and security."""
from datetime import datetime, timedelta, timezone
import hmac
from pathlib import Path
import secrets
from typing import Literal
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from license_server.models import AdminSession, Administrator, Alert, Audit, Customer, Device, License
from license_server.security import digest, utc

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class DeviceAction(BaseModel):
    confirm: Literal[True]
    confirmed_device_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("A meaningful reason is required")
        return value.strip()


class LicenseAction(BaseModel):
    confirm: Literal[True]
    confirmed_license_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        return DeviceAction.nonblank(value)


class LicenseIssue(BaseModel):
    customer: str = Field(min_length=1, max_length=200)
    expires_at: datetime
    max_devices: int = Field(ge=1, le=1000)
    notes: str = Field(default="", max_length=1000)

    @field_validator("customer")
    @classmethod
    def nonblank_customer(cls, value: str):
        if not value.strip():
            raise ValueError("Customer / Pharmacy Name cannot be blank")
        return value.strip()

    @field_validator("expires_at")
    @classmethod
    def ensure_tz(cls, value: datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def create_admin_router(settings, sessions, clock, audit, throttle, request_ip, shutdown_registry=None):
    if shutdown_registry is None:
        from license_server.app import ShutdownRegistry
        shutdown_registry = ShutdownRegistry()
    router = APIRouter()
    password_hasher = PasswordHasher()
    dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))

    def db():
        with sessions() as session:
            yield session

    def deny(session, event, actor, message, code=403, device_id=None):
        audit(session, event, actor, device_id)
        session.commit()
        raise HTTPException(code, message)

    def check_origin(request, session, actor="anonymous"):
        expected = settings.admin_origin or str(request.base_url).rstrip("/")
        origin = request.headers.get("origin")
        if (origin and origin != expected) or (settings.vercel and origin != expected and request.method not in ("GET", "HEAD")):
            deny(session, "admin_origin_rejected", actor, "Invalid request origin")

    def record_view(session, user, event, device_id=None):
        audit(session, event, user.username, device_id)
        session.commit()

    def admin(request: Request, session: Session = Depends(db)):
        token = request.cookies.get(settings.cookie_name, "")
        auth_session = session.get(AdminSession, digest(token, settings.pepper)) if token else None
        user = session.get(Administrator, auth_session.username) if auth_session else None
        if (not auth_session or utc(auth_session.expires_at) <= clock()
                or not user or not user.active):
            deny(session, "admin_unauthenticated_request", "anonymous", "Developer login required", 401)
        if user.role != "DEVELOPER":
            deny(session, "admin_authorization_rejected", user.username, "Developer authorization required")
        if request.method not in ("GET", "HEAD"):
            csrf = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(digest(csrf, settings.pepper), auth_session.csrf_hash):
                deny(session, "admin_csrf_rejected", user.username, "Invalid CSRF token")
            check_origin(request, session, user.username)
        return user, auth_session

    @router.post("/admin/login")
    def login(body: Login, request: Request, response: Response, session: Session = Depends(db)):
        check_origin(request, session)  # Login CSRF must also be rejected, before setting any cookie.
        throttle(session, "login-ip:" + request_ip(request), 10, 900)
        throttle(session, "login-user:" + body.username, 10, 900)
        user = session.get(Administrator, body.username)
        try:
            password_hasher.verify(user.password_hash if user else dummy_hash, body.password)
            valid = bool(user and user.active and user.role == "DEVELOPER")
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            audit(session, "admin_login_failed", "anonymous")
            session.commit()
            raise HTTPException(401, "Invalid developer credentials")
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        session.add(AdminSession(token_hash=digest(token, settings.pepper), username=user.username,
                                 csrf_hash=digest(csrf, settings.pepper), csrf_value=csrf,
                                 expires_at=clock() + timedelta(seconds=settings.session_seconds)))
        audit(session, "admin_login", user.username)
        session.commit()
        response.set_cookie(settings.cookie_name, token, secure=True, httponly=True, samesite="strict", max_age=settings.session_seconds, path="/admin")
        return {"csrf_token": csrf}

    @router.get("/admin/me")
    def me(auth=Depends(admin)):
        return {"username": auth[0].username, "csrf_token": auth[1].csrf_value, "environment": settings.environment}

    @router.post("/admin/logout")
    def logout(response: Response, auth=Depends(admin), session: Session = Depends(db)):
        session.delete(auth[1])
        audit(session, "admin_logout", auth[0].username)
        session.commit()
        response.delete_cookie(settings.cookie_name, path="/admin", secure=True, httponly=True, samesite="strict")
        return {"ok": True}

    def device_record(d, l, c, a, now):
        is_closed = shutdown_registry.is_shut_down(d.id, d.last_seen)
        is_online = (not is_closed) and (utc(d.last_seen) >= now - timedelta(seconds=settings.heartbeat_threshold))
        if is_online:
            activity_status = "online"
        elif (not is_closed) and (utc(d.last_seen) >= now - timedelta(seconds=settings.recent_threshold)):
            activity_status = "recently_online"
        else:
            activity_status = "offline"

        return {"device_id": d.id, "status": d.status,
                "effective_status": "REVOKED" if d.status == "REVOKED" or l and l.status != "ACTIVE" else ("EXPIRED" if l and utc(l.expires_at) <= now else d.status),
                "detection": "NEW" if a and a.acknowledged_at is None else "SEEN",
                "online": is_online,
                "activity_status": activity_status,
                "activity": activity_status,
                "first_seen": utc(d.first_seen).isoformat(), "first_activation": utc(d.first_activation).isoformat() if d.first_activation else None,
                "last_seen": utc(d.last_seen).isoformat(), "app_version": d.app_version,
                "customer": c.name if c else None, "license_id": d.license_id,
                "license_status": l.status if l else None, "license_expires_at": utc(l.expires_at).isoformat() if l else None,
                "max_devices": l.max_devices if l else None}

    def device_query():
        return (select(Device, License, Customer, Alert)
                .outerjoin(License, Device.license_id == License.id)
                .outerjoin(Customer, License.customer_id == Customer.id)
                .outerjoin(Alert, Alert.device_id == Device.id))

    @router.get("/admin/devices")
    def devices(offset: int = 0, limit: int = 100,
                activity: Literal["all", "online", "recent", "recently_online", "offline"] = "all",
                q: str = Query(default="", max_length=200),
                status: Literal["all", "AUTHORIZED", "PENDING", "REVOKED", "EXPIRED", "LIMIT_REACHED", "NEW"] = "all",
                license_id: uuid.UUID | None = None, auth=Depends(admin), session: Session = Depends(db)):
        if offset < 0 or not 1 <= limit <= 500:
            raise HTTPException(422, "Invalid pagination")
        now = clock()
        query = device_query()
        threshold = now - timedelta(seconds=settings.heartbeat_threshold)
        recent_threshold = now - timedelta(seconds=settings.recent_threshold)
        shut_down_ids = shutdown_registry.active_shut_down_ids()
        if activity == "online":
            query = query.where(Device.last_seen >= threshold)
            if shut_down_ids:
                query = query.where(Device.id.not_in(shut_down_ids))
        elif activity in ("recent", "recently_online"):
            query = query.where(Device.last_seen >= recent_threshold, Device.last_seen < threshold)
            if shut_down_ids:
                query = query.where(Device.id.not_in(shut_down_ids))
        elif activity == "offline":
            if shut_down_ids:
                query = query.where(or_(Device.last_seen < threshold, Device.id.in_(shut_down_ids)))
            else:
                query = query.where(Device.last_seen < threshold)
        if q.strip():
            query = query.where(or_(*(column.icontains(q.strip(), autoescape=True) for column in
                                     (Device.id, Device.app_version, Customer.name, Device.license_id))))
        if license_id:
            query = query.where(Device.license_id == str(license_id))
        if status == "NEW":
            query = query.where(Alert.id.is_not(None), Alert.acknowledged_at.is_(None))
        elif status != "all":
            effective = case((or_(Device.status == "REVOKED", License.status == "DISABLED"), "REVOKED"),
                             (License.expires_at <= now, "EXPIRED"), else_=Device.status)
            query = query.where(effective == status)
        total = session.scalar(select(func.count()).select_from(query.with_only_columns(Device.id).subquery()))
        rows = session.execute(query.order_by(Device.first_seen.desc(), Device.id).offset(offset).limit(limit)).all()
        record_view(session, auth[0], "admin_devices_viewed")
        return {"heartbeat_threshold_seconds": settings.heartbeat_threshold, "recent_threshold_seconds": settings.recent_threshold,
                "server_time": now.isoformat(), "total": total,
                "devices": [device_record(d, l, c, a, now) for d, l, c, a in rows]}

    @router.get("/admin/devices/{device_id}")
    def device_details(device_id: uuid.UUID, auth=Depends(admin), session: Session = Depends(db)):
        row = session.execute(device_query().where(Device.id == str(device_id))).first()
        if not row:
            raise HTTPException(404, "Device not found")
        record_view(session, auth[0], "admin_device_details_viewed", str(device_id))
        return device_record(*row, clock())

    @router.get("/admin/summary")
    def summary(auth=Depends(admin), session: Session = Depends(db)):
        now = clock()
        shut_down_ids = shutdown_registry.active_shut_down_ids()
        def count(model, *conditions):
            return session.scalar(select(func.count()).select_from(model).where(*conditions))
        total = count(Device)
        if shut_down_ids:
            online = count(Device, Device.last_seen >= now - timedelta(seconds=settings.heartbeat_threshold), Device.id.not_in(shut_down_ids))
        else:
            online = count(Device, Device.last_seen >= now - timedelta(seconds=settings.heartbeat_threshold))
        offline = total - online
        recently_seen = count(Device, Device.last_seen >= now - timedelta(seconds=settings.recent_threshold))
        if shut_down_ids:
            recently_online = count(Device, Device.last_seen >= now - timedelta(seconds=settings.recent_threshold),
                                    Device.last_seen < now - timedelta(seconds=settings.heartbeat_threshold),
                                    Device.id.not_in(shut_down_ids))
        else:
            recently_online = count(Device, Device.last_seen >= now - timedelta(seconds=settings.recent_threshold),
                                    Device.last_seen < now - timedelta(seconds=settings.heartbeat_threshold))
        result = {"total": total, "online": online, "offline": offline,
                "recently_seen": recently_seen, "recently_online": recently_online,
                "new_alerts": count(Alert, Alert.acknowledged_at.is_(None)), "revoked": count(Device, Device.status == "REVOKED"),
                "active_licenses": count(License, License.status == "ACTIVE", License.expires_at > now),
                "revoked_licenses": count(License, License.status == "DISABLED"),
                "heartbeat_threshold_seconds": settings.heartbeat_threshold, "recent_threshold_seconds": settings.recent_threshold}
        record_view(session, auth[0], "admin_summary_viewed")
        return result

    @router.get("/admin/alerts")
    def alerts(auth=Depends(admin), session: Session = Depends(db)):
        rows = session.execute(select(Alert, Device, License, Customer).join(Device, Alert.device_id == Device.id)
                .outerjoin(License, Device.license_id == License.id).outerjoin(Customer, License.customer_id == Customer.id)
                .where(Alert.acknowledged_at.is_(None)).order_by(Alert.created_at.desc(), Alert.id).limit(500)).all()
        record_view(session, auth[0], "admin_alerts_viewed")
        return [{"id": a.id, "device_id": a.device_id, "created_at": utc(a.created_at).isoformat(),
                 "first_seen": utc(d.first_seen).isoformat(), "customer": c.name if c else None,
                 "license_id": d.license_id, "app_version": d.app_version, "acknowledged": False} for a, d, l, c in rows]

    @router.post("/admin/alerts/{alert_id}/acknowledge")
    def acknowledge(alert_id: uuid.UUID, auth=Depends(admin), session: Session = Depends(db)):
        alert = session.get(Alert, str(alert_id))
        if not alert:
            raise HTTPException(404, "Alert not found")
        alert.acknowledged_at, alert.acknowledged_by = clock(), auth[0].username
        audit(session, "alert_acknowledged", auth[0].username, alert.device_id)
        session.commit()
        return {"ok": True}

    def action(device_id, body, auth, session, reactivate):
        if str(body.confirmed_device_id) != str(device_id):
            raise HTTPException(400, "Device confirmation does not match")
        device = session.scalar(select(Device).where(Device.id == str(device_id)).with_for_update())
        if not device:
            raise HTTPException(404, "Device not found")
        if reactivate:
            license = session.scalar(select(License).where(License.id == device.license_id).with_for_update())
            if not license or license.status != "ACTIVE" or utc(license.expires_at) <= clock():
                raise HTTPException(409, "A valid active license is required for reactivation")
            used = session.scalar(select(func.count()).select_from(Device).where(
                Device.license_id == license.id, Device.status == "AUTHORIZED", Device.id != device.id))
            if used >= license.max_devices:
                raise HTTPException(409, "License device limit reached")
            device.status = "AUTHORIZED"
            if not device.first_activation:
                device.first_activation = clock()
        else:
            device.status = "REVOKED"
        device.revision += 1
        audit(session, "device_reactivated" if reactivate else "device_revoked", auth[0].username, device.id, body.reason)
        session.commit()
        return {"device_id": device.id, "status": device.status,
                "message": "Device reactivated. Access resumes after signed validation." if reactivate else "Device revoked. Access locks after the next successful validation."}

    @router.post("/admin/devices/{device_id}/revoke")
    def revoke(device_id: uuid.UUID, body: DeviceAction, auth=Depends(admin), session: Session = Depends(db)):
        return action(device_id, body, auth, session, False)

    @router.post("/admin/devices/{device_id}/reactivate")
    def reactivate(device_id: uuid.UUID, body: DeviceAction, auth=Depends(admin), session: Session = Depends(db)):
        return action(device_id, body, auth, session, True)

    @router.get("/admin/devices/{device_id}/history")
    def device_history(device_id: uuid.UUID, offset: int = 0, limit: int = 100, auth=Depends(admin), session: Session = Depends(db)):
        if offset < 0 or not 1 <= limit <= 500:
            raise HTTPException(422, "Invalid pagination")
        device = session.get(Device, str(device_id))
        if not device:
            raise HTTPException(404, "Device not found")
        # History uses existing licensing audit events only; no client business data is collected.
        events = ("new_device_registered", "device_activated", "activation_failed", "device_revoked", "device_reactivated", "device_shutdown")
        condition = (Audit.device_id == device.id, Audit.event.in_(events))
        total = session.scalar(select(func.count()).select_from(Audit).where(*condition))
        rows = list(session.scalars(select(Audit).where(*condition).order_by(Audit.created_at.desc(), Audit.id).offset(offset).limit(limit)))
        record_view(session, auth[0], "admin_device_history_viewed", device.id)
        return {"device_id": device.id, "first_seen": utc(device.first_seen).isoformat(),
                "first_activation": utc(device.first_activation).isoformat() if device.first_activation else None,
                "total": total, "events": [{"event": a.event, "actor": a.actor, "reason": a.reason, "created_at": utc(a.created_at).isoformat()} for a in rows]}

    @router.get("/admin/licenses")
    def licenses(offset: int = 0, limit: int = 100, q: str = Query(default="", max_length=200),
                 status: Literal["all", "ACTIVE", "REVOKED", "EXPIRED"] = "all", auth=Depends(admin), session: Session = Depends(db)):
        if offset < 0 or not 1 <= limit <= 500:
            raise HTTPException(422, "Invalid pagination")
        query = select(License, Customer).join(Customer, License.customer_id == Customer.id)
        if q.strip():
            query = query.where(or_(License.id.icontains(q.strip(), autoescape=True), Customer.name.icontains(q.strip(), autoescape=True)))
        if status == "REVOKED":
            query = query.where(License.status == "DISABLED")
        elif status == "ACTIVE":
            query = query.where(License.status == "ACTIVE", License.expires_at > clock())
        elif status == "EXPIRED":
            query = query.where(License.status == "ACTIVE", License.expires_at <= clock())
        rows = session.execute(query.order_by(License.id).offset(offset).limit(limit)).all()
        usage = dict(session.execute(select(Device.license_id, func.count()).where(Device.status == "AUTHORIZED").group_by(Device.license_id)).all())
        total = session.scalar(select(func.count()).select_from(query.with_only_columns(License.id).subquery()))
        record_view(session, auth[0], "admin_licenses_viewed")
        return {"total": total, "licenses": [{"license_id": l.id, "customer_id": c.id, "customer": c.name,
                 "status": "REVOKED" if l.status == "DISABLED" else ("EXPIRED" if utc(l.expires_at) <= clock() else "ACTIVE"),
                 "expires_at": utc(l.expires_at).isoformat(), "max_devices": l.max_devices,
                 "authorized_devices": usage.get(l.id, 0)} for l, c in rows]}

    def license_action(license_id, body, auth, session, reactivate):
        if str(body.confirmed_license_id) != str(license_id):
            raise HTTPException(400, "License confirmation does not match")
        license = session.scalar(select(License).where(License.id == str(license_id)).with_for_update())
        if not license:
            raise HTTPException(404, "License not found")
        if reactivate:
            if utc(license.expires_at) <= clock():
                raise HTTPException(409, "Renew the expired license before reactivation")
            used = session.scalar(select(func.count()).select_from(Device).where(Device.license_id == license.id, Device.status == "AUTHORIZED"))
            if used > license.max_devices:
                raise HTTPException(409, "License capacity must cover its authorized devices")
        license.status = "ACTIVE" if reactivate else "DISABLED"
        audit(session, "license_reactivated" if reactivate else "license_revoked", auth[0].username,
              reason=license.id + ": " + body.reason)
        session.commit()
        return {"license_id": license.id, "status": "ACTIVE" if reactivate else "REVOKED",
                "message": "License reactivated. Individually revoked devices remain revoked." if reactivate else "License revoked for all associated devices at their next successful validation."}

    @router.post("/admin/licenses/{license_id}/revoke")
    def revoke_license(license_id: uuid.UUID, body: LicenseAction, auth=Depends(admin), session: Session = Depends(db)):
        return license_action(license_id, body, auth, session, False)

    @router.post("/admin/licenses/{license_id}/reactivate")
    def reactivate_license(license_id: uuid.UUID, body: LicenseAction, auth=Depends(admin), session: Session = Depends(db)):
        return license_action(license_id, body, auth, session, True)

    @router.post("/admin/licenses/issue")
    def issue_license(body: LicenseIssue, auth=Depends(admin), session: Session = Depends(db)):
        now = clock()
        expires = body.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            raise HTTPException(400, "License expiration date must be in the future")
        if body.max_devices < 1:
            raise HTTPException(422, "Maximum allowed devices must be at least 1")

        throttle(session, "issue-license:" + auth[0].username, 30, 300)

        customer = session.scalars(select(Customer).where(Customer.name == body.customer)).first()
        if not customer:
            customer = Customer(id=str(uuid.uuid4()), name=body.customer)
            session.add(customer)
            session.flush()

        activation = secrets.token_urlsafe(48)
        license_id = str(uuid.uuid4())
        activation_hash = digest(activation, settings.pepper)

        license = License(
            id=license_id,
            customer_id=customer.id,
            activation_hash=activation_hash,
            expires_at=expires,
            max_devices=body.max_devices,
            status="ACTIVE",
        )
        session.add(license)

        audit_reason = f"{license_id}: {body.notes.strip()}" if body.notes.strip() else license_id
        audit(session, "license_issued", auth[0].username, reason=audit_reason)
        session.commit()

        return {
            "license_id": license.id,
            "customer_id": customer.id,
            "customer": customer.name,
            "activation_key": activation,
            "expires_at": utc(license.expires_at).isoformat(),
            "max_devices": license.max_devices,
            "status": "ACTIVE",
        }

    @router.get("/admin/audit")
    def audit_list(auth=Depends(admin), session: Session = Depends(db)):
        rows = list(session.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(200)))
        record_view(session, auth[0], "admin_audit_viewed")
        return [{"event": a.event, "actor": a.actor, "device_id": a.device_id,
                 "reason": a.reason, "created_at": utc(a.created_at).isoformat()} for a in rows]

    static = Path(__file__).resolve().parents[1] / "frontend"
    @router.get("/")
    def home():
        return RedirectResponse("/admin/sign-in", status_code=303)

    @router.get("/admin")
    def dashboard(auth=Depends(admin), session: Session = Depends(db)):
        record_view(session, auth[0], "admin_dashboard_viewed")
        return FileResponse(static / "index.html")

    @router.get("/admin/sign-in")
    def signin():
        return FileResponse(static / "login.html")

    @router.get("/admin/assets/{name}")
    def asset(name: Literal["dashboard.js", "login.js", "style.css", "network.js", "three.module.min.js", "THREE-LICENSE.txt"]):
        return FileResponse(static / name)

    return router

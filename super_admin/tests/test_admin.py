from dataclasses import replace
from datetime import timedelta
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from license_server.app import create_app, digest
from license_server.models import Administrator, Audit, Customer, Device, License
from license_server.security import utc
from licensing.client import LicenseClient
from tests.licensing.conftest import MemoryStore, admin_login, change_device


def license_action(env, action, *, headers=None, **changes):
    license_id = env["license_id"]
    headers = headers if headers is not None else admin_login(env)
    return env["api"].post(f"/admin/licenses/{license_id}/{action}", headers=headers,
        json={"confirm": True, "confirmed_license_id": license_id, "reason": "Test license access action", **changes})


def test_admin_login_and_protected_super_admin_data(env):
    for path in ["/admin", "/admin/licenses", "/admin/devices", "/admin/summary", "/admin/alerts", "/admin/audit"]:
        assert env["api"].get(path).status_code == 401
    assert env["api"].get("/admin/sign-in").status_code == 200
    headers = admin_login(env)
    assert env["api"].get("/admin").status_code == 200
    assert env["api"].get("/admin/licenses").json()["licenses"][0]["license_id"] == env["license_id"]
    assert env["api"].post("/admin/logout", headers=headers, json={}).status_code == 200
    assert env["api"].get("/admin/summary").status_code == 401


def test_new_device_online_offline_and_activation_history(activated):
    env = activated
    admin_login(env)
    summary = env["api"].get("/admin/summary").json()
    assert summary["total"] == 1 and summary["online"] == 1 and summary["offline"] == 0
    assert summary["active_licenses"] == 1 and summary["revoked_licenses"] == 0 and summary["new_alerts"] == 1
    env["clock"].advance(901)
    devices = env["api"].get("/admin/devices?activity=offline").json()
    assert devices["total"] == 1
    data = devices["devices"][0]
    assert not data["online"] and data["detection"] == "NEW" and data["customer"] == "Test pharmacy"
    assert data["last_seen"] and data["app_version"] == "1.0.0"
    assert env["api"].get("/admin/devices?activity=online").json()["total"] == 0
    history = env["api"].get(f'/admin/devices/{data["device_id"]}/history').json()
    assert history["first_activation"] and history["first_seen"]
    assert {event["event"] for event in history["events"]} == {"new_device_registered", "device_activated"}
    assert env["client"].validate(heartbeat=True).allowed
    assert env["api"].get("/admin/summary").json()["offline"] == 0


def test_license_wide_revocation_signed_desktop_lock_and_reactivation(activated):
    env = activated
    response = license_action(env, "revoke")
    assert response.status_code == 200 and response.json()["status"] == "REVOKED"
    assert response.json()["message"]
    assert env["client"].validate().status == "REVOKED"
    env["transport"].failure = "timeout"
    assert env["client"].validate().status == "REVOKED"
    assert env["api"].get("/admin/summary").json()["revoked_licenses"] == 1
    assert env["api"].get("/admin/devices").json()["devices"][0]["effective_status"] == "REVOKED"
    assert license_action(env, "reactivate").status_code == 200
    env["transport"].failure = None
    assert env["client"].validate().allowed
    events = env["api"].get("/admin/audit").json()
    for name in ("license_revoked", "license_reactivated"):
        row = next(event for event in events if event["event"] == name)
        assert row["actor"] == "developer" and env["license_id"] in row["reason"]


def test_license_reactivation_preserves_specific_device_revocation(activated):
    env = activated
    assert change_device(env, "revoke").status_code == 200
    assert license_action(env, "revoke").status_code == 200
    assert license_action(env, "reactivate").status_code == 200
    assert env["client"].validate().status == "REVOKED"
    assert change_device(env, "reactivate").status_code == 200
    assert env["client"].validate().allowed


def test_license_actions_require_csrf_authorization_and_explicit_confirmation(activated):
    env = activated
    assert license_action(env, "revoke", headers={}).status_code == 401
    headers = admin_login(env)
    assert license_action(env, "revoke", headers={}).status_code == 403
    assert license_action(env, "revoke", headers=headers, confirm=False).status_code == 422
    assert license_action(env, "revoke", headers=headers, confirmed_license_id=str(uuid.uuid4())).status_code == 400
    assert license_action(env, "revoke", headers=headers, reason="  ").status_code == 422
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "VIEWER"
        session.commit()
    assert env["api"].get("/admin/licenses").status_code == 403
    assert license_action(env, "revoke", headers=headers).status_code == 403


def test_expired_license_cannot_reactivate(activated):
    env = activated
    assert license_action(env, "revoke").status_code == 200
    with env["app"].state.sessions() as session:
        session.get(License, env["license_id"]).expires_at = env["clock"].now()
        session.commit()
    assert license_action(env, "reactivate").status_code == 409


def test_login_csrf_and_vercel_cookie_origin_isolation(env):
    origin = "https://admin.example.test"
    settings = replace(env["settings"], admin_origin=origin, cookie_name="license_admin_preview", environment="preview", vercel=True)
    app = create_app(settings, engine=env["app"].state.engine, clock=env["clock"].now)
    with TestClient(app, base_url=origin) as api:
        body = {"username": "developer", "password": "test-password-123"}
        assert api.post("/admin/login", json=body).status_code == 403
        assert api.post("/admin/login", headers={"Origin": "https://evil.test"}, json=body).status_code == 403
        auth = api.post("/admin/login", headers={"Origin": origin}, json=body)
        assert auth.status_code == 200
        assert "license_admin_preview=" in auth.headers["set-cookie"]
        headers = {"Origin": origin, "X-CSRF-Token": auth.json()["csrf_token"]}
        assert api.get("/admin/me").json()["environment"] == "preview"
        assert api.post("/admin/logout", headers=headers, json={}).status_code == 200


def test_ready_health_and_persistence_across_app_instances(activated):
    env = activated
    assert env["api"].get("/health/ready").json() == {"status": "ready"}
    # A fresh application uses the same PostgreSQL records, not serverless process memory.
    app = create_app(env["settings"], engine=env["app"].state.engine, clock=env["clock"].now)
    with TestClient(app, base_url="https://testserver") as api:
        auth = api.post("/admin/login", json={"username": "developer", "password": "test-password-123"})
        assert auth.status_code == 200
        assert api.get("/admin/summary").json()["total"] == 1
        assert api.get("/admin/licenses").json()["licenses"][0]["license_id"] == env["license_id"]


def test_admin_actions_audited_and_dashboard_data_contains_no_credentials(activated):
    env = activated
    admin_login(env)
    responses = [env["api"].get(path) for path in ["/admin/devices", "/admin/summary", "/admin/licenses", "/admin/alerts", "/admin/audit", "/admin"]]
    assert all(response.status_code == 200 for response in responses)
    payload = " ".join(response.text for response in responses)
    for secret in [env["activation"], env["client"].state["device_secret"], env["settings"].pepper, "password_hash", "secret_hash", "activation_hash", "token_hash"]:
        assert secret not in payload
    with env["app"].state.sessions() as session:
        events = set(session.scalars(select(Audit.event)))
    assert {"admin_devices_viewed", "admin_summary_viewed", "admin_licenses_viewed", "admin_alerts_viewed", "admin_audit_viewed", "admin_dashboard_viewed"} <= events


def test_pharmacy_business_routes_and_imports_do_not_exist(env):
    import ast
    from tests.licensing.conftest import ROOT
    admin_login(env)
    for path in ["/admin/patients", "/admin/sales", "/admin/purchases", "/admin/stock", "/admin/ledger", "/admin/database/download", "/admin/database/restore", "/admin/computers/control"]:
        assert env["api"].get(path).status_code == 404
        assert env["api"].post(path, json={}).status_code == 404
    for directory in [ROOT / "super_admin/backend", ROOT / "super_admin/database", ROOT / "license_server"]:
        for file in directory.glob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [name.name for name in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                assert not any(module.split('.')[0] in {"database", "screens", "ui"} for module in modules)


def test_issue_license_success_and_one_time_key(env):
    headers = admin_login(env)
    expires = (env["clock"].now() + timedelta(days=365)).isoformat()
    response = env["api"].post(
        "/admin/licenses/issue",
        headers=headers,
        json={
            "customer": "Apollo Care Pharmacy",
            "expires_at": expires,
            "max_devices": 3,
            "notes": "New branch order #5001",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["activation_key"]) >= 48
    uuid.UUID(data["license_id"])
    assert data["customer"] == "Apollo Care Pharmacy"
    assert data["customer_id"]
    assert data["max_devices"] == 3
    assert data["status"] == "ACTIVE"

    activation_key = data["activation_key"]
    license_id = data["license_id"]

    with env["app"].state.sessions() as session:
        license_row = session.get(License, license_id)
        assert license_row is not None
        assert license_row.activation_hash == digest(activation_key, env["settings"].pepper)

        # Verify activation_key is NOT stored in License or Customer
        for val in [license_row.id, license_row.customer_id, license_row.activation_hash, license_row.status]:
            assert activation_key != val and activation_key not in str(val)
        customer_row = session.get(Customer, license_row.customer_id)
        assert customer_row is not None
        for val in [customer_row.id, customer_row.name]:
            assert activation_key != val and activation_key not in str(val)

        audits = list(session.scalars(select(Audit).where(Audit.event == "license_issued")))
        audit_row = next(a for a in audits if license_id in (a.reason or ""))
        assert audit_row.actor == "developer"
        assert "New branch order #5001" in audit_row.reason


def test_issue_license_security_and_validation(env):
    expires = (env["clock"].now() + timedelta(days=365)).isoformat()
    valid_payload = {
        "customer": "Apollo Care Pharmacy",
        "expires_at": expires,
        "max_devices": 3,
        "notes": "Security test",
    }

    # Without auth -> status 401
    assert env["api"].post("/admin/licenses/issue", json=valid_payload).status_code == 401

    headers = admin_login(env)

    # Without CSRF token -> status 403
    assert env["api"].post("/admin/licenses/issue", headers={}, json=valid_payload).status_code == 403

    # With non-developer role (change role to VIEWER) -> status 403
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "VIEWER"
        session.commit()
    assert env["api"].post("/admin/licenses/issue", headers=headers, json=valid_payload).status_code == 403

    # Restore developer role for validation checks
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "DEVELOPER"
        session.commit()

    # Blank customer name -> status 422
    assert env["api"].post("/admin/licenses/issue", headers=headers,
                           json={**valid_payload, "customer": "   "}).status_code == 422
    assert env["api"].post("/admin/licenses/issue", headers=headers,
                           json={**valid_payload, "customer": ""}).status_code == 422

    # Past expiration date -> status 400
    past = (env["clock"].now() - timedelta(days=1)).isoformat()
    assert env["api"].post("/admin/licenses/issue", headers=headers,
                           json={**valid_payload, "expires_at": past}).status_code == 400

    # max_devices < 1 -> status 422
    assert env["api"].post("/admin/licenses/issue", headers=headers,
                           json={**valid_payload, "max_devices": 0}).status_code == 422
    assert env["api"].post("/admin/licenses/issue", headers=headers,
                           json={**valid_payload, "max_devices": -1}).status_code == 422


def test_issued_license_can_activate_desktop_client(env):
    headers = admin_login(env)
    expires = (env["clock"].now() + timedelta(days=365)).isoformat()
    response = env["api"].post(
        "/admin/licenses/issue",
        headers=headers,
        json={
            "customer": "Apollo Care Pharmacy",
            "expires_at": expires,
            "max_devices": 3,
            "notes": "Desktop client activation test",
        },
    )
    assert response.status_code == 200
    activation_key = response.json()["activation_key"]

    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    validation = client.validate(activation_key=activation_key)

    assert validation.allowed is True
    assert validation.status == "AUTHORIZED"


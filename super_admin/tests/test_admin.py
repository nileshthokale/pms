from dataclasses import replace
from datetime import datetime, timedelta, timezone
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


def test_license_renewal_active_and_expired(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    # Test 1: Active license renewal (License expires in 30 days)
    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        old_expiry = lic.expires_at
        if old_expiry.tzinfo is None:
            old_expiry = old_expiry.replace(tzinfo=timezone.utc)

    response = env["api"].post(
        f"/admin/licenses/{license_id}/renew",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "extension_days": 60,
            "reason": "Customer requested 60-day extension",
        },
    )
    assert response.status_code == 200
    data = response.json()
    expected_expiry = old_expiry + timedelta(days=60)
    assert datetime.fromisoformat(data["expires_at"]) == expected_expiry

    with env["app"].state.sessions() as session:
        audit_row = session.scalar(
            select(Audit).where(Audit.event == "license_renewed").order_by(Audit.created_at.desc())
        )
        assert audit_row is not None
        assert audit_row.actor == "developer"
        assert old_expiry.isoformat() in audit_row.reason
        assert expected_expiry.isoformat() in audit_row.reason
        assert "Customer requested 60-day extension" in audit_row.reason

    # Test 2: Expired license renewal
    past_time = env["clock"].now() - timedelta(days=10)
    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        lic.expires_at = past_time
        lic.status = "ACTIVE"
        session.commit()

    now = env["clock"].now()
    response2 = env["api"].post(
        f"/admin/licenses/{license_id}/renew",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "extension_days": 30,
            "reason": "Renewal after expiration",
        },
    )
    assert response2.status_code == 200
    data2 = response2.json()
    expected_expiry2 = now + timedelta(days=30)
    assert datetime.fromisoformat(data2["expires_at"]) == expected_expiry2
    assert data2["status"] == "ACTIVE"

    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        assert lic.status == "ACTIVE"
        assert utc(lic.expires_at) == expected_expiry2


def test_license_edit_supported_details(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    response = env["api"].post(
        f"/admin/licenses/{license_id}/edit",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "customer_name": "Apollo Pharmacy Updated",
            "max_devices": 5,
            "notes": "Updated contract terms",
            "reason": "Contract adjustment",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["customer"] == "Apollo Pharmacy Updated"
    assert data["max_devices"] == 5

    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        cust = session.get(Customer, lic.customer_id)
        assert cust.name == "Apollo Pharmacy Updated"
        assert lic.max_devices == 5

    # Capacity check: add 3 authorized devices to this license
    with env["app"].state.sessions() as session:
        for _ in range(3):
            session.add(
                Device(
                    id=str(uuid.uuid4()),
                    secret_hash="fakehash",
                    license_id=license_id,
                    app_version="1.0.0",
                    status="AUTHORIZED",
                    first_seen=env["clock"].now(),
                    last_seen=env["clock"].now(),
                )
            )
        session.commit()

    # Reducing max_devices below authorized device count (e.g. to 2 when 3 are authorized) returns 409
    res_conflict = env["api"].post(
        f"/admin/licenses/{license_id}/edit",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "max_devices": 2,
            "reason": "Attempting to reduce capacity below authorized count",
        },
    )
    assert res_conflict.status_code == 409
    assert "Cannot reduce capacity" in res_conflict.json()["detail"]


def test_license_archive_safely_disables_activations(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    response = env["api"].post(
        f"/admin/licenses/{license_id}/archive",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "reason": "Contract terminated",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ARCHIVED"

    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        assert lic.status == "ARCHIVED"

        audit_row = session.scalar(
            select(Audit).where(Audit.event == "license_archived").order_by(Audit.created_at.desc())
        )
        assert audit_row is not None
        assert audit_row.actor == "developer"
        assert license_id in audit_row.reason
        assert "Contract terminated" in audit_row.reason

    # Attempting to activate a new device with this license's activation key is rejected
    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    validation = client.validate(activation_key=env["activation"])
    assert validation.allowed is False
    assert validation.status in ("REVOKED", "PENDING")


def test_device_unlink_frees_capacity(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    # Setup license with max_devices=1
    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        lic.max_devices = 1
        session.commit()

    # Device 1 activates -> AUTHORIZED
    store1 = MemoryStore()
    client1 = LicenseClient(env["config"], store1, clock=env["clock"], transport=env["transport"])
    val1 = client1.validate(activation_key=env["activation"])
    assert val1.allowed is True
    assert val1.status == "AUTHORIZED"
    device1_id = client1.state["device_id"]

    # Device 2 attempts activation -> fails / gets LIMIT_REACHED
    store2 = MemoryStore()
    client2 = LicenseClient(env["config"], store2, clock=env["clock"], transport=env["transport"])
    val2 = client2.validate(activation_key=env["activation"])
    assert val2.allowed is False
    assert val2.status == "LIMIT_REACHED"
    device2_id = client2.state["device_id"]

    # Unlink Device 1
    res_unlink = env["api"].post(
        f"/admin/devices/{device1_id}/unlink",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_device_id": device1_id,
            "reason": "Decommissioning old workstation",
        },
    )
    assert res_unlink.status_code == 200

    # Verify Device 1 has license_id is None and status == "PENDING"
    with env["app"].state.sessions() as session:
        d1 = session.get(Device, device1_id)
        assert d1.license_id is None
        assert d1.status == "PENDING"

        audit_row = session.scalar(
            select(Audit).where(Audit.event == "device_unlinked").order_by(Audit.created_at.desc())
        )
        assert audit_row is not None
        assert audit_row.actor == "developer"
        assert audit_row.device_id == device1_id
        assert "Decommissioning old workstation" in audit_row.reason

    # Device 2 attempts activation again -> SUCCEEDS and becomes AUTHORIZED!
    val2_retry = client2.validate(activation_key=env["activation"])
    assert val2_retry.allowed is True
    assert val2_retry.status == "AUTHORIZED"


def test_license_history_endpoint(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    # Generate an audit event for this license
    env["api"].post(
        f"/admin/licenses/{license_id}/renew",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "extension_days": 30,
            "reason": "Audit history test renewal",
        },
    )

    response = env["api"].get(f"/admin/licenses/{license_id}/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["license_id"] == license_id
    assert data["total"] >= 1
    assert isinstance(data["events"], list)
    assert any(e["event"] == "license_renewed" for e in data["events"])


def test_desktop_activation_after_valid_renewal(env):
    license_id = env["license_id"]

    # Initial activation while license is valid
    val_init = env["client"].validate(activation_key=env["activation"])
    assert val_init.allowed is True
    assert val_init.status == "AUTHORIZED"

    # Expire the license
    past_time = env["clock"].now() - timedelta(days=5)
    with env["app"].state.sessions() as session:
        lic = session.get(License, license_id)
        lic.expires_at = past_time
        session.commit()

    # Desktop client validation returns EXPIRED
    val_expired = env["client"].validate(heartbeat=True)
    assert val_expired.allowed is False
    assert val_expired.status == "EXPIRED"

    # Admin renews license via /admin/licenses/{license_id}/renew
    headers = admin_login(env)
    renew_res = env["api"].post(
        f"/admin/licenses/{license_id}/renew",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "extension_days": 90,
            "reason": "Customer renewed subscription",
        },
    )
    assert renew_res.status_code == 200
    assert renew_res.json()["status"] == "ACTIVE"

    # Desktop client validation now succeeds with AUTHORIZED!
    val_after = env["client"].validate(heartbeat=True)
    assert val_after.allowed is True
    assert val_after.status == "AUTHORIZED"

    # A new desktop client can also activate now
    store_new = MemoryStore()
    client_new = LicenseClient(env["config"], store_new, clock=env["clock"], transport=env["transport"])
    val_new = client_new.validate(activation_key=env["activation"])
    assert val_new.allowed is True
    assert val_new.status == "AUTHORIZED"


def test_security_and_validation_for_new_endpoints(env):
    license_id = env["license_id"]

    # Register a device linked to license for unlinking tests
    device_id = str(uuid.uuid4())
    with env["app"].state.sessions() as session:
        session.add(
            Device(
                id=device_id,
                secret_hash="fakehash",
                license_id=license_id,
                app_version="1.0.0",
                status="AUTHORIZED",
                first_seen=env["clock"].now(),
                last_seen=env["clock"].now(),
            )
        )
        session.commit()

    endpoints = [
        ("post", f"/admin/licenses/{license_id}/renew", {
            "confirm": True, "confirmed_license_id": license_id, "extension_days": 30, "reason": "Valid reason for renewal"
        }),
        ("post", f"/admin/licenses/{license_id}/edit", {
            "confirm": True, "confirmed_license_id": license_id, "notes": "Updated", "reason": "Valid reason for edit"
        }),
        ("post", f"/admin/licenses/{license_id}/archive", {
            "confirm": True, "confirmed_license_id": license_id, "reason": "Valid reason for archive"
        }),
        ("post", f"/admin/devices/{device_id}/unlink", {
            "confirm": True, "confirmed_device_id": device_id, "reason": "Valid reason for unlink"
        }),
        ("get", f"/admin/licenses/{license_id}/history", None),
    ]

    # 1. Unauthenticated requests return 401
    for method, path, payload in endpoints:
        if method == "post":
            assert env["api"].post(path, json=payload).status_code == 401
        else:
            assert env["api"].get(path).status_code == 401

    headers = admin_login(env)

    # 2. Missing CSRF header returns 403 for POST endpoints
    for method, path, payload in endpoints:
        if method == "post":
            assert env["api"].post(path, headers={}, json=payload).status_code == 403

    # 3. Non-developer role returns 403
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "VIEWER"
        session.commit()

    for method, path, payload in endpoints:
        if method == "post":
            assert env["api"].post(path, headers=headers, json=payload).status_code == 403
        else:
            assert env["api"].get(path, headers=headers).status_code == 403

    # Restore developer role
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "DEVELOPER"
        session.commit()

    # 4. Invalid or missing confirmation returns 400 or 422
    # Missing / false confirmation -> 422
    assert env["api"].post(f"/admin/licenses/{license_id}/renew", headers=headers,
                           json={"confirm": False, "confirmed_license_id": license_id, "extension_days": 30, "reason": "Test"}).status_code == 422
    assert env["api"].post(f"/admin/licenses/{license_id}/edit", headers=headers,
                           json={"confirm": False, "confirmed_license_id": license_id, "reason": "Test"}).status_code == 422
    assert env["api"].post(f"/admin/licenses/{license_id}/archive", headers=headers,
                           json={"confirm": False, "confirmed_license_id": license_id, "reason": "Test"}).status_code == 422
    assert env["api"].post(f"/admin/devices/{device_id}/unlink", headers=headers,
                           json={"confirm": False, "confirmed_device_id": device_id, "reason": "Test"}).status_code == 422

    # Mismatched confirmation ID -> 400
    wrong_id = str(uuid.uuid4())
    assert env["api"].post(f"/admin/licenses/{license_id}/renew", headers=headers,
                           json={"confirm": True, "confirmed_license_id": wrong_id, "extension_days": 30, "reason": "Test"}).status_code == 400
    assert env["api"].post(f"/admin/licenses/{license_id}/edit", headers=headers,
                           json={"confirm": True, "confirmed_license_id": wrong_id, "reason": "Test"}).status_code == 400
    assert env["api"].post(f"/admin/licenses/{license_id}/archive", headers=headers,
                           json={"confirm": True, "confirmed_license_id": wrong_id, "reason": "Test"}).status_code == 400
    assert env["api"].post(f"/admin/devices/{device_id}/unlink", headers=headers,
                           json={"confirm": True, "confirmed_device_id": wrong_id, "reason": "Test"}).status_code == 400

    # Blank reason -> 422
    assert env["api"].post(f"/admin/licenses/{license_id}/renew", headers=headers,
                           json={"confirm": True, "confirmed_license_id": license_id, "extension_days": 30, "reason": "   "}).status_code == 422
    assert env["api"].post(f"/admin/devices/{device_id}/unlink", headers=headers,
                           json={"confirm": True, "confirmed_device_id": device_id, "reason": "   "}).status_code == 422


def test_device_delete_and_assign_workflow(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    # Register an unassociated pending device (e.g. user pasted wrong key or no key)
    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    val = client.validate(activation_key="wrong-key-123")
    assert val.allowed is False
    assert val.status == "PENDING"
    dev_id = client.state["device_id"]

    # Verify device is recorded in database as PENDING with no license
    with env["app"].state.sessions() as session:
        d = session.get(Device, dev_id)
        assert d is not None
        assert d.license_id is None
        assert d.status == "PENDING"

    # 1. Direct Assignment from Dashboard: Admin assigns pending device to active license
    res_assign = env["api"].post(
        f"/admin/devices/{dev_id}/assign",
        headers=headers,
        json={
            "confirmed_device_id": dev_id,
            "license_id": license_id,
            "reason": "Authorized workstation for pharmacy counter",
        },
    )
    assert res_assign.status_code == 200
    assert res_assign.json()["status"] == "AUTHORIZED"
    assert res_assign.json()["license_id"] == license_id

    # Desktop client now validates over internet -> SUCCEEDS immediately!
    val_after_assign = client.validate()
    assert val_after_assign.allowed is True
    assert val_after_assign.status == "AUTHORIZED"

    # 2. Deletion: Admin permanently deletes device
    res_del = env["api"].post(
        f"/admin/devices/{dev_id}/delete",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_device_id": dev_id,
            "reason": "Decommissioned old test workstation",
        },
    )
    assert res_del.status_code == 200

    with env["app"].state.sessions() as session:
        assert session.get(Device, dev_id) is None
        # Verify audit log
        audit_entry = session.scalar(
            select(Audit).where(Audit.event == "device_deleted", Audit.device_id == dev_id)
        )
        assert audit_entry is not None
        assert "Decommissioned old test workstation" in audit_entry.reason


def test_license_regenerate_key_workflow(env):
    headers = admin_login(env)
    license_id = env["license_id"]
    old_key = env["activation"]

    # Regenerate key
    res = env["api"].post(
        f"/admin/licenses/{license_id}/regenerate-key",
        headers=headers,
        json={
            "confirm": True,
            "confirmed_license_id": license_id,
            "reason": "Customer misplaced original activation token",
        },
    )
    assert res.status_code == 200
    new_key = res.json()["activation_key"]
    assert new_key != old_key
    assert len(new_key) >= 40

    # Old key fails for new device activation
    store_old = MemoryStore()
    client_old = LicenseClient(env["config"], store_old, clock=env["clock"], transport=env["transport"])
    val_old = client_old.validate(activation_key=old_key)
    assert val_old.allowed is False
    assert val_old.status == "PENDING"

    # New key succeeds for new device activation
    store_new = MemoryStore()
    client_new = LicenseClient(env["config"], store_new, clock=env["clock"], transport=env["transport"])
    val_new = client_new.validate(activation_key=new_key)
    assert val_new.allowed is True
    assert val_new.status == "AUTHORIZED"

    # Verify audit log
    with env["app"].state.sessions() as session:
        audit_row = session.scalar(
            select(Audit).where(Audit.event == "license_key_regenerated").order_by(Audit.created_at.desc())
        )
        assert audit_row is not None
        assert audit_row.actor == "developer"
        assert "misplaced original activation token" in audit_row.reason


def test_direct_license_id_activation_in_desktop_client(env):
    """Verifies that customers can activate by entering their License ID directly (e.g. 3db7dd0f-...) in any case."""
    license_id = env["license_id"]

    # 1. Desktop user copies License ID directly (uppercase, with hyphens) and pastes it
    store1 = MemoryStore()
    client1 = LicenseClient(env["config"], store1, clock=env["clock"], transport=env["transport"])
    val1 = client1.validate(activation_key=license_id.upper())
    assert val1.allowed is True
    assert val1.status == "AUTHORIZED"
    assert client1.state["license"]["payload"]["license_id"] == license_id

    # 2. Another device activates with lowercase License ID
    with env["app"].state.sessions() as session:
        session.get(License, license_id).max_devices = 5
        session.commit()

    store2 = MemoryStore()
    client2 = LicenseClient(env["config"], store2, clock=env["clock"], transport=env["transport"])
    val2 = client2.validate(activation_key=license_id.lower())
    assert val2.allowed is True
    assert val2.status == "AUTHORIZED"
    assert client2.state["license"]["payload"]["license_id"] == license_id


def test_direct_device_authorization_from_super_admin(env):
    """Verifies that an admin can paste a Device ID directly in Super Admin to authorize it, and the client unlocks."""
    license_id = env["license_id"]
    with env["app"].state.sessions() as session:
        session.get(License, license_id).max_devices = 5
        session.commit()

    headers = admin_login(env)

    # 1. Direct authorization of a new device that hasn't connected yet
    new_device_id = str(uuid.uuid4())
    auth_resp = env["api"].post("/admin/devices/authorize", json={
        "device_id": new_device_id,
        "license_id": license_id,
        "reason": "Direct authorization by Super Admin"
    }, headers=headers)
    assert auth_resp.status_code == 200, auth_resp.text
    assert auth_resp.json()["status"] == "AUTHORIZED"

    # Now this new workstation opens and connects (without needing to enter any key!)
    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    client.state["device_id"] = new_device_id
    dec = client.validate()
    assert dec.allowed is True
    assert dec.status == "AUTHORIZED"
    assert client.state["license"]["payload"]["license_id"] == license_id


def test_device_deletion_terminates_offline_grace_and_locks_client(env):
    """Verifies that when a device is deleted from Super Admin, the client immediately terminates offline grace and locks."""
    license_id = env["license_id"]
    headers = admin_login(env)

    # 1. Device activates and has a valid offline envelope
    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    val = client.validate(activation_key=license_id)
    assert val.allowed is True
    assert val.status == "AUTHORIZED"
    device_id = client.state["device_id"]

    # 2. Admin deletes device from Super Admin
    del_resp = env["api"].post(f"/admin/devices/{device_id}/delete", json={
        "confirm": True,
        "confirmed_device_id": device_id,
        "reason": "De-commissioned computer"
    }, headers=headers)
    assert del_resp.status_code == 200

    # 3. Client checks validation: server rejects credentials (401)
    val_after = client.validate()
    assert val_after.allowed is False
    assert val_after.status == "AUTHENTICATION_ERROR"
    assert client.state.get("license") is None
    assert client.decision().allowed is False





"""Dashboard queries remain authorized, global, deterministic and licensing-only."""
from datetime import timedelta
import uuid

from license_server.models import Customer, Device, License
from license_server.security import digest
from tests.licensing.conftest import admin_login


def test_global_device_license_search_and_pagination(activated):
    env = activated
    admin_login(env)
    with env["app"].state.sessions() as session:
        for i in range(23):
            cid, lid, did = (str(uuid.uuid4()) for _ in range(3))
            session.add(Customer(id=cid, name=f"Synthetic Pharmacy {i:02d}"))
            session.flush()
            session.add(License(id=lid, customer_id=cid, activation_hash=digest(lid, env["settings"].pepper),
                expires_at=env["clock"].now()+timedelta(days=10),max_devices=2,status="ACTIVE"))
            session.flush()
            session.add(Device(id=did,secret_hash=digest(did,env["settings"].pepper),license_id=lid,
                app_version=f"2.0.{i}",status="AUTHORIZED",first_seen=env["clock"].now(),
                first_activation=env["clock"].now(),last_seen=env["clock"].now()))
        session.commit()
    api = env["api"]
    first = api.get("/admin/devices?limit=20").json()
    second = api.get("/admin/devices?offset=20&limit=20").json()
    assert first["total"] == second["total"] == 24
    assert len(first["devices"]) == 20 and len(second["devices"]) == 4
    assert not set(d["device_id"] for d in first["devices"]) & set(d["device_id"] for d in second["devices"])
    result = api.get("/admin/devices", params={"q":"synthetic pharmacy 22"}).json()
    assert result["total"] == 1 and result["devices"][0]["app_version"] == "2.0.22"
    license_result = api.get("/admin/licenses",params={"q":"SYNTHETIC PHARMACY 22"}).json()
    assert license_result["total"] == 1
    assert api.get("/admin/devices",params={"license_id":license_result["licenses"][0]["license_id"]}).json()["total"] == 1
    for route in ("devices", "licenses"):
        assert api.get(f"/admin/{route}",params={"q":"%"}).json()["total"] == 0
        assert api.get(f"/admin/{route}",params={"q":"x"*201}).status_code == 422


def test_effective_authorization_filters_and_alert_enrichment(activated):
    env = activated
    admin_login(env)
    api = env["api"]
    assert api.get("/admin/devices?status=NEW").json()["total"] == 1
    assert api.get("/admin/devices?status=AUTHORIZED").json()["total"] == 1
    with env["app"].state.sessions() as session:
        session.get(License,env["license_id"]).status = "DISABLED"
        session.commit()
    assert api.get("/admin/devices?status=REVOKED").json()["total"] == 1
    assert api.get("/admin/devices?status=AUTHORIZED").json()["total"] == 0
    assert api.get("/admin/licenses?status=REVOKED").json()["total"] == 1
    with env["app"].state.sessions() as session:
        license = session.get(License,env["license_id"])
        license.status, license.expires_at = "ACTIVE", env["clock"].now()
        session.commit()
    assert api.get("/admin/devices?status=EXPIRED").json()["total"] == 1
    assert api.get("/admin/licenses?status=EXPIRED").json()["total"] == 1
    alert = api.get("/admin/alerts").json()[0]
    assert alert["customer"] == "Test pharmacy" and alert["app_version"] == "1.0.0"
    assert alert["license_id"] == env["license_id"] and alert["first_seen"] and alert["acknowledged"] is False


def test_device_detail_auth_audit_and_public_assets(activated):
    env = activated
    did = env["client"].state["device_id"]
    assert env["api"].get(f"/admin/devices/{did}").status_code == 401
    admin_login(env)
    response = env["api"].get(f"/admin/devices/{did}")
    assert response.status_code == 200 and response.json()["device_id"] == did
    for secret in (env["client"].state["device_secret"], env["activation"],env["settings"].pepper):
        assert secret not in response.text
    assert any(a["event"] == "admin_device_details_viewed" for a in env["api"].get("/admin/audit").json())
    assert env["api"].get(f"/admin/devices/{uuid.uuid4()}").status_code == 404
    for file in ("network.js","three.module.min.js","THREE-LICENSE.txt"):
        assert env["api"].get("/admin/assets/"+file).status_code == 200
    assert env["api"].get("/admin/assets/routes.py").status_code == 422

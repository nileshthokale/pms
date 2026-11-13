"""Tests verifying device IP and fingerprint tracking in Super Admin API."""
from licensing.client import LicenseClient
from licensing.fingerprint import collect_device_fingerprint
from license_server.models import Device
from tests.licensing.conftest import MemoryStore, admin_login


def test_collect_device_fingerprint():
    fp = collect_device_fingerprint("1.0.0")
    assert isinstance(fp, dict)
    assert "os" in fp
    assert "hardware" in fp
    assert "network" in fp
    assert "runtime" in fp
    assert "security" in fp
    assert "session" in fp
    assert fp["runtime"]["app_version"] == "1.0.0"
    assert "machine_id" in fp["hardware"]


def test_device_fingerprint_and_ip_e2e(env):
    headers = admin_login(env)
    license_id = env["license_id"]

    # 1. Device validates with initial connection (sends fingerprint automatically)
    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    val = client.validate(activation_key=license_id)
    assert val.allowed is True
    dev_id = client.state["device_id"]

    # Check database model directly
    with env["app"].state.sessions() as session:
        dev = session.get(Device, dev_id)
        assert dev is not None
        assert dev.ip_address is not None
        assert dev.device_info is not None
        assert "os" in dev.device_info
        assert "hardware" in dev.device_info
        initial_ip = dev.ip_address

    # 2. Super Admin API listing returns ip_address and device_info
    resp = env["api"].get("/admin/devices", headers=headers)
    assert resp.status_code == 200
    devices = resp.json()["devices"]
    matching = [d for d in devices if d["device_id"] == dev_id]
    assert len(matching) == 1
    assert matching[0]["ip_address"] == initial_ip
    assert matching[0]["device_info"] is not None
    assert matching[0]["device_info"]["runtime"]["app_version"] is not None

    # 3. Super Admin Device details API returns ip_address and device_info
    detail_resp = env["api"].get(f"/admin/devices/{dev_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["ip_address"] == initial_ip
    assert detail["device_info"] is not None
    assert "security" in detail["device_info"]


def test_device_fingerprint_updates_on_heartbeat(env):
    license_id = env["license_id"]

    store = MemoryStore()
    client = LicenseClient(env["config"], store, clock=env["clock"], transport=env["transport"])
    client.validate(activation_key=license_id)
    dev_id = client.state["device_id"]

    # Simulate heartbeat
    hb_val = client.validate(heartbeat=True)
    assert hb_val.allowed is True

    with env["app"].state.sessions() as session:
        dev = session.get(Device, dev_id)
        assert dev.device_info is not None
        assert "runtime" in dev.device_info

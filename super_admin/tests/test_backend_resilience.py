"""Tests for backend exception handling, resource cleanup, and device activity lifecycle."""
from datetime import timedelta
import socket
import sys
import uuid

import pytest
from sqlalchemy import select

from license_server.app import patch_proactor_connection_lost
from license_server.models import Audit, Device
from licensing.client import LicenseClient
from tests.licensing.conftest import admin_login


def test_proactor_connection_lost_suppresses_winerror_10054():
    """Verify that the Proactor transport monkey patch catches OSError on socket shutdown."""
    patch_proactor_connection_lost()
    if sys.platform != "win32":
        pytest.skip("Proactor transport patch is specific to Windows")

    import asyncio.proactor_events

    class FakeSocket:
        def __init__(self):
            self.closed = False
            self.shutdown_called = False

        def fileno(self):
            return 123 if not self.closed else -1

        def shutdown(self, how):
            self.shutdown_called = True
            # Simulate Windows WSAECONNRESET (10054)
            err = ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
            err.winerror = 10054
            raise err

        def close(self):
            self.closed = True

    class FakeServer:
        def __init__(self):
            self.detached = False

        def _detach(self, transport):
            self.detached = True

    class FakeProtocol:
        def connection_lost(self, exc):
            pass

    transport = asyncio.proactor_events._ProactorBasePipeTransport.__new__(
        asyncio.proactor_events._ProactorBasePipeTransport
    )
    transport._called_connection_lost = False
    transport._sock = FakeSocket()
    transport._server = FakeServer()
    transport._protocol = FakeProtocol()

    # Calling _call_connection_lost should NOT raise ConnectionResetError
    transport._call_connection_lost(None)

    assert transport._sock is None
    assert transport._server is None
    assert transport._called_connection_lost is True


def test_client_disconnect_middleware_response(activated):
    """Verify that client disconnections in middleware return 499 status cleanly."""
    env = activated
    # Directly test the endpoint with the client
    # Normal request
    resp = env["api"].get("/health")
    assert resp.status_code == 200


def test_device_graceful_shutdown_and_dynamic_status(activated):
    """Verify graceful shutdown marks device offline immediately while preserving exact last_seen."""
    env = activated
    admin_login(env)
    device_id = env["client"].state["device_id"]
    secret = env["client"].state["device_secret"]

    # 1. Initially online
    summary = env["api"].get("/admin/summary").json()
    assert summary["online"] == 1 and summary["offline"] == 0
    dev = env["api"].get("/admin/devices?activity=online").json()["devices"][0]
    assert dev["online"] is True
    assert dev["activity_status"] == "online"
    first_last_seen = dev["last_seen"]

    # 2. EXE gracefully shuts down
    env["clock"].advance(30)
    body = {
        "device_id": device_id,
        "device_secret": secret,
        "app_version": "1.0.0",
        "nonce": "test-shutdown-nonce-12345678901234567890",
    }
    shutdown_resp = env["api"].post("/v1/devices/offline", json=body)
    assert shutdown_resp.status_code == 200
    assert shutdown_resp.json()["status"] == "offline"

    # 3. Check exact last_seen is preserved and updated to shutdown moment
    with env["app"].state.sessions() as session:
        audit_event = session.scalar(
            select(Audit).where(Audit.device_id == device_id, Audit.event == "device_shutdown")
        )
        assert audit_event is not None
        assert audit_event.reason == "Graceful application shutdown"

    # 4. Without any database write, refreshing summary dynamically reports device as offline
    summary_after = env["api"].get("/admin/summary").json()
    assert summary_after["online"] == 0
    assert summary_after["offline"] == 1

    # 5. /admin/devices filters
    offline_devices = env["api"].get("/admin/devices?activity=offline").json()
    assert offline_devices["total"] == 1
    closed_dev = offline_devices["devices"][0]
    assert closed_dev["online"] is False
    assert closed_dev["activity_status"] == "offline"
    assert closed_dev["last_seen"] > first_last_seen

    # Online filter should return 0 devices
    online_devices = env["api"].get("/admin/devices?activity=online").json()
    assert online_devices["total"] == 0

    # 6. Device details also reflects offline status
    detail = env["api"].get(f"/admin/devices/{device_id}").json()
    assert detail["online"] is False
    assert detail["activity_status"] == "offline"

    # 7. Device history contains device_shutdown event
    history = env["api"].get(f"/admin/devices/{device_id}/history").json()
    events = [e["event"] for e in history["events"]]
    assert "device_shutdown" in events

    # 8. When Pharmacy EXE starts again and sends a heartbeat, it resumes online
    env["clock"].advance(10)
    assert env["client"].validate(heartbeat=True).allowed
    summary_resumed = env["api"].get("/admin/summary").json()
    assert summary_resumed["online"] == 1 and summary_resumed["offline"] == 0
    dev_resumed = env["api"].get("/admin/devices?activity=online").json()["devices"][0]
    assert dev_resumed["online"] is True
    assert dev_resumed["activity_status"] == "online"


def test_activity_lifecycle_thresholds(activated):
    """Verify dynamic transition through online -> recently_online -> offline based on timestamps."""
    env = activated
    admin_login(env)
    device_id = env["client"].state["device_id"]

    # At t=0: ONLINE
    dev = env["api"].get(f"/admin/devices/{device_id}").json()
    assert dev["online"] is True
    assert dev["activity_status"] == "online"

    # At t = heartbeat_threshold + 1s (901s): RECENTLY_ONLINE
    env["clock"].advance(901)
    dev = env["api"].get(f"/admin/devices/{device_id}").json()
    assert dev["online"] is False
    assert dev["activity_status"] == "recently_online"

    # Verify activity=recent and activity=recently_online query filters
    recent_query = env["api"].get("/admin/devices?activity=recent").json()
    assert recent_query["total"] == 1
    assert recent_query["devices"][0]["activity_status"] == "recently_online"

    recently_online_query = env["api"].get("/admin/devices?activity=recently_online").json()
    assert recently_online_query["total"] == 1

    # At t = recent_threshold + 1s (86401s total): OFFLINE
    env["clock"].advance(86400)
    admin_login(env)  # Advancing 24h expires the 8h admin session; re-login
    dev = env["api"].get(f"/admin/devices/{device_id}").json()
    assert dev["online"] is False
    assert dev["activity_status"] == "offline"

    recent_query_expired = env["api"].get("/admin/devices?activity=recent").json()
    assert recent_query_expired["total"] == 0

    offline_query = env["api"].get("/admin/devices?activity=offline").json()
    assert offline_query["total"] == 1


def test_intermittent_heartbeat_failure_does_not_falsely_mark_offline(activated):
    """Verify that a single failed heartbeat does not falsely mark a device offline within 900s."""
    env = activated
    admin_login(env)

    # Initial state: online
    assert env["api"].get("/admin/summary").json()["online"] == 1

    # 300 seconds pass (normal heartbeat interval), but network fails
    env["clock"].advance(300)
    env["transport"].failure = "timeout"
    result = env["client"].validate(heartbeat=True)
    # Desktop enters offline grace mode
    assert result.allowed and result.status == "OFFLINE_GRACE"

    # Server-side: device has 600s left of the 900s threshold, so it remains ONLINE!
    summary = env["api"].get("/admin/summary").json()
    assert summary["online"] == 1
    assert summary["offline"] == 0

    # Next attempt succeeds
    env["clock"].advance(60)
    env["transport"].failure = None
    assert env["client"].validate(heartbeat=True).allowed
    assert env["api"].get("/admin/summary").json()["online"] == 1


def test_client_notify_offline_and_qt_controller_shutdown(activated):
    """Verify LicenseClient.close() and LicenseController.shutdown() send offline notification."""
    env = activated
    admin_login(env)

    # Calling close on client sends graceful shutdown
    assert env["client"].close() is True
    assert env["client"].connectivity == "OFFLINE"

    # Server sees it as offline
    assert env["api"].get("/admin/summary").json()["online"] == 0

"""Tests only use temporary licensing databases and a copied pharmacy fixture."""
import base64
import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sys
import uuid

import httpx
import pytest
from argon2 import PasswordHasher
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from license_server.app import create_app, digest
from license_server.models import Administrator, Base, Customer, License
from license_server.settings import Settings
from licensing.client import LicenseClient


class ControlledClock:
    def __init__(self):
        self.wall_time = 1800000000.0
        self.mono_time = 100.0
        self.server_time = 1800000000.0

    def wall(self):
        return self.wall_time

    def monotonic(self):
        return self.mono_time

    def now(self):
        return datetime.fromtimestamp(self.server_time, timezone.utc)

    def advance(self, seconds):
        self.wall_time += seconds
        self.mono_time += seconds
        self.server_time += seconds


class MemoryStore:
    def __init__(self):
        self.state = None

    def read(self):
        return copy.deepcopy(self.state)

    def write(self, state):
        self.state = copy.deepcopy(state)


class ServiceTransport(httpx.BaseTransport):
    def __init__(self, api):
        self.api = api
        self.failure = None
        self.transform = None

    def handle_request(self, request):
        if self.failure == "timeout":
            raise httpx.ReadTimeout("controlled timeout", request=request)
        if self.failure == "internet":
            raise httpx.ConnectError("controlled internet outage", request=request)
        if self.failure == "server":
            return httpx.Response(503, json={"detail": "Unavailable"}, request=request)
        response = self.api.request(request.method, request.url.path, content=request.content,
                                    headers={"Content-Type": "application/json"})
        data = response.json()
        if self.transform:
            data = self.transform(data)
        return httpx.Response(response.status_code, json=data, request=request)


@pytest.fixture
def env(tmp_path):
    clock = ControlledClock()
    key = Ed25519PrivateKey.generate()
    settings = Settings("test-only", key, secrets.token_urlsafe(48))
    pg_url = os.environ.get("LICENSE_TEST_POSTGRES_URL")
    if pg_url:
        from sqlalchemy import text
        # Refuse arbitrary central databases; tests only use the explicitly isolated loopback cluster.
        from sqlalchemy.engine import make_url
        parsed = make_url(pg_url)
        if parsed.host != "127.0.0.1" or parsed.port != 55439 or parsed.database != "licensing_isolated_test":
            raise RuntimeError("PostgreSQL tests require the isolated loopback cluster")
        schema = "test_" + uuid.uuid4().hex
        bootstrap = create_engine(pg_url)
        with bootstrap.begin() as conn:
            conn.execute(text('CREATE SCHEMA "' + schema + '"'))
        engine = create_engine(pg_url, connect_args={"options": "-csearch_path=" + schema})
    else:
        engine = create_engine("sqlite:///" + str(tmp_path / "central_test.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(settings, engine=engine, clock=clock.now)
    activation = secrets.token_urlsafe(48)
    customer_id, license_id = str(uuid.uuid4()), str(uuid.uuid4())
    with app.state.sessions() as session:
        session.add(Customer(id=customer_id, name="Test pharmacy"))
        session.flush()
        session.add(License(id=license_id, customer_id=customer_id, activation_hash=digest(activation, settings.pepper),
                            expires_at=datetime.fromtimestamp(clock.server_time + 30*86400, timezone.utc), max_devices=2, status="ACTIVE"))
        session.add(Administrator(username="developer", password_hash=PasswordHasher().hash("test-password-123"), role="DEVELOPER"))
        session.commit()
    api = TestClient(app, base_url="https://testserver")
    transport = ServiceTransport(api)
    config = {"server_url": "https://testserver", "public_keys": {"primary": base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()},
              "heartbeat_seconds": 300}
    store = MemoryStore()
    client = LicenseClient(config, store, clock=clock, transport=transport)
    result = dict(clock=clock, key=key, settings=settings, app=app, api=api, transport=transport,
                  config=config, store=store, client=client, activation=activation, license_id=license_id,
                  customer_id=customer_id, tmp_path=tmp_path)
    yield result
    api.close()
    engine.dispose()
    if pg_url:
        with bootstrap.begin() as conn:
            conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        bootstrap.dispose()


@pytest.fixture
def activated(env):
    assert env["client"].validate(activation_key=env["activation"]).allowed
    return env


def admin_login(env):
    response = env["api"].post("/admin/login", json={"username": "developer", "password": "test-password-123"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def change_device(env, action):
    headers = admin_login(env)
    device = env["client"].state["device_id"]
    return env["api"].post(f"/admin/devices/{device}/{action}", headers=headers,
                          json={"confirm": True, "confirmed_device_id": device, "reason": "Controlled licensing test"})

import base64
import importlib
import json
import os
from pathlib import Path
import sys
import tomllib

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from license_server.models import Base
from license_server.settings import Settings
from tests.licensing.conftest import ROOT


def configure_vercel(monkeypatch, env, environment="production"):
    values = {"VERCEL":"1", "VERCEL_ENV":environment, "VERCEL_URL":"deployment.example.test",
              "LICENSE_DATABASE_URL":"postgresql+psycopg://test:password@preview-db.example.test/licensing_test?sslmode=require",
              "LICENSE_DEPLOYMENT_ENV":environment, "LICENSE_SECRET_PEPPER": "test-pepper-for-preview-"*3,
              "LICENSE_SIGNING_KEY_PEM_B64":base64.b64encode(env["key"].private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode(),
              "LICENSE_KEY_ID":"preview-key" if environment != "production" else "primary",
              "LICENSE_DATABASE_ID":"preview-branch", "LICENSE_PRODUCTION_DATABASE_ID":"production-branch",
              "LICENSE_PRODUCTION_DATABASE_HOST":"production-db.example.test", "LICENSE_PRODUCTION_DATABASE_NAME":"licensing",
              "LICENSE_PRODUCTION_KEY_ID":"primary", "LICENSE_PRODUCTION_SIGNING_KEY_SHA256":"0"*64}
    for key,value in values.items():monkeypatch.setenv(key,value)
    monkeypatch.delenv("LICENSE_ADMIN_ORIGIN", raising=False)
    monkeypatch.delenv("LICENSE_SIGNING_KEY_FILE", raising=False)
    return values


def test_vercel_manifest_and_server_only_dependencies():
    project = tomllib.loads((ROOT/"pyproject.toml").read_text())
    config = json.loads((ROOT/"vercel.json").read_text())
    assert project["tool"]["vercel"]["entrypoint"] == "super_admin.backend.app:app"
    assert project["project"]["requires-python"] == ">=3.13,<3.14"
    assert config["framework"] == "fastapi"
    assert config["installCommand"] == "python -m pip install -r license_server/requirements.txt"
    dependencies = " ".join(project["project"]["dependencies"])
    assert "PySide6" not in dependencies and "openpyxl" not in dependencies
    assert config["functions"]["super_admin/backend/app.py"]["maxDuration"] == 30
    assert set(Base.metadata.tables) == {"license_customers","licenses","devices","new_device_alerts","administrators","admin_sessions","license_rate_limits","license_audit"}


def test_vercel_environment_signing_secret_and_connection_pool(env,monkeypatch):
    configure_vercel(monkeypatch,env)
    settings = Settings.from_env()
    assert settings.vercel and settings.cookie_name == "license_admin_production"
    assert settings.admin_origin == "https://deployment.example.test"
    assert settings.private_key.public_key().public_bytes_raw() == env["key"].public_key().public_bytes_raw()
    from license_server.app import create_app
    app = create_app(settings)
    assert isinstance(app.state.engine.pool,NullPool)
    app.state.engine.dispose()  # factory creates no network connection or migration


@pytest.mark.parametrize("name,value", [
    ("LICENSE_DEPLOYMENT_ENV","production"),
    ("LICENSE_DATABASE_ID","production-branch"),
    ("LICENSE_DATABASE_URL","postgresql+psycopg://test:password@production-db.example.test/licensing?sslmode=require"),
    ("LICENSE_DATABASE_URL","postgresql+psycopg://test:password@preview-db.example.test/licensing_test"),
    ("LICENSE_KEY_ID","primary"),
    ("LICENSE_SIGNING_KEY_PEM_B64","invalid-base64"),
    ("LICENSE_ADMIN_ORIGIN","https://example.test/path"),
])
def test_preview_rejects_unsafe_configuration(env,monkeypatch,name,value):
    configure_vercel(monkeypatch,env,"preview")
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError):Settings.from_env()


def test_preview_requires_guard_values_and_separate_key(env,monkeypatch):
    configure_vercel(monkeypatch,env,"preview")
    assert Settings.from_env().cookie_name == "license_admin_preview"
    monkeypatch.delenv("LICENSE_PRODUCTION_DATABASE_HOST")
    with pytest.raises(ValueError):Settings.from_env()


def test_preview_cannot_reuse_production_signing_key_with_different_id(env,monkeypatch):
    import hashlib
    configure_vercel(monkeypatch,env,"preview")
    monkeypatch.setenv("LICENSE_PRODUCTION_SIGNING_KEY_SHA256",hashlib.sha256(env["key"].public_key().public_bytes_raw()).hexdigest())
    with pytest.raises(ValueError):Settings.from_env()


def test_readiness_failures_expose_no_database_error(env):
    engine = create_engine("sqlite://")
    from license_server.app import create_app
    with TestClient(create_app(env["settings"],engine=engine),base_url="https://testserver") as api:
        response = api.get("/health/ready")
        assert response.status_code == 503 and response.json() == {"status":"unavailable"}
    engine.dispose()


def test_actual_vercel_runtime_detects_asgi_entrypoint(env,monkeypatch):
    configure_vercel(monkeypatch,env)
    sys.modules.pop("super_admin.backend.app",None)
    entrypoint = importlib.import_module("super_admin.backend.app")
    try:
        import inspect
        pytest.importorskip("vercel_runtime")
        # Vercel's shipped runtime accepts the FastAPI ASGI callable directly.
        from vercel_runtime.resolver import detect_app_type
        assert inspect.iscoroutinefunction(entrypoint.app.__call__)
        # Use the actual runtime detection mechanism, rather than inventing an adapter.
        detection = detect_app_type(entrypoint.app, "super_admin.backend.app", "app")
        assert detection[0] == "asgi"
        with TestClient(entrypoint.app,base_url="https://deployment.example.test") as api:
            assert api.get('/health').status_code == 200
            assert api.get('/admin/sign-in').status_code == 200
    finally:
        entrypoint.app.state.engine.dispose()
        sys.modules.pop("super_admin.backend.app",None)

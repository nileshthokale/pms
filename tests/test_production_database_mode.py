from pathlib import Path

import pytest

from database import connection


def _set_production_env(monkeypatch, path):
    monkeypatch.setenv("PHARMACY_MODE", "PRODUCTION")
    monkeypatch.setenv("PHARMACY_DB", str(path))
    for name in (
        "PHARMACY_DB_PATH",
        "PHARMACY_STAGING_MODE",
        "PHARMACY_TEST_PROTECTED_DB",
        "PHARMACY_TEST_SAFE_DB",
        "PHARMACY_TEST_RELEASE",
        "PHARMACY_REQUIRE_EXISTING_DB",
    ):
        monkeypatch.delenv(name, raising=False)


def test_production_mode_resolves_only_to_the_source_database(monkeypatch, tmp_path):
    production_db = tmp_path / "data" / "pharmacy.db"
    monkeypatch.setattr(connection, "_DB_PATH", str(production_db))
    _set_production_env(monkeypatch, production_db)

    assert Path(connection.get_db_path()) == production_db.resolve()


def test_production_mode_rejects_an_override_to_staging(monkeypatch, tmp_path):
    production_db = tmp_path / "data" / "pharmacy.db"
    staging_db = tmp_path / "staging" / "pharmacy_staging.db"
    monkeypatch.setattr(connection, "_DB_PATH", str(production_db))
    _set_production_env(monkeypatch, staging_db)

    with pytest.raises(RuntimeError, match="restricted to the existing production"):
        connection.get_db_path()


def test_production_mode_refuses_to_create_a_missing_database(monkeypatch, tmp_path):
    production_db = tmp_path / "data" / "pharmacy.db"
    monkeypatch.setattr(connection, "_DB_PATH", str(production_db))
    _set_production_env(monkeypatch, production_db)

    with pytest.raises(RuntimeError, match="Refusing to create an empty production database"):
        connection._open_connection()

    assert not production_db.exists()
    assert not production_db.parent.exists()


def test_production_mode_refuses_to_initialize_an_empty_database(monkeypatch, tmp_path):
    production_db = tmp_path / "data" / "pharmacy.db"
    production_db.parent.mkdir()
    production_db.touch()
    monkeypatch.setattr(connection, "_DB_PATH", str(production_db))
    _set_production_env(monkeypatch, production_db)

    with pytest.raises(RuntimeError, match="Production database is empty"):
        connection._open_connection()

    assert production_db.stat().st_size == 0

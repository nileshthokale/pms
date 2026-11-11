import copy
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tests.licensing.conftest import MemoryStore, ROOT, ServiceTransport, admin_login, change_device
from licensing.client import LicenseClient
from licensing.gate import LicenseRestricted, OperationGate, install_gate
from licensing.protocol import InvalidLicense, OFFLINE_SECONDS, verify_license
from licensing.storage import DPAPIStore
from license_server.models import Administrator, Alert, Audit, Base, Device, License


def test_first_registration_and_alert_mode(env):
    result = env["client"].validate(activation_key=env["activation"])
    assert result.allowed and result.status == "AUTHORIZED"
    with env["app"].state.sessions() as session:
        device = session.get(Device, env["client"].state["device_id"])
        assert device.license_id == env["license_id"]
        assert device.first_activation is not None
        assert device.app_version == "1.0.0"
        assert session.scalar(select(func.count()).select_from(Alert)) == 1
    admin_login(env)
    data = env["api"].get("/admin/devices").json()["devices"][0]
    assert data["detection"] == "NEW" and data["status"] == "AUTHORIZED"
    assert data["customer"] == "Test pharmacy"


def test_pending_unassociated_device_and_invalid_activation(env):
    assert env["client"].validate().status == "PENDING"
    assert env["client"].validate(activation_key="invalid").status == "PENDING"
    assert env["client"].validate(activation_key=env["activation"]).allowed
    with env["app"].state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 1


def test_existing_installation_restart_and_idempotent_registration(activated):
    env = activated
    before = env["client"].state["device_id"]
    restart = LicenseClient(env["config"], env["store"], clock=env["clock"], transport=env["transport"])
    assert restart.state["device_id"] == before
    assert restart.decision().allowed
    assert restart.validate(activation_key=env["activation"]).allowed
    with env["app"].state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Device)) == 1
        assert session.scalar(select(func.count()).select_from(Alert)) == 1


def test_heartbeats_online_offline_recent_and_alert_acknowledgement(activated):
    env = activated
    headers = admin_login(env)
    assert env["api"].get("/admin/summary").json()["online"] == 1
    env["clock"].advance(901)
    summary = env["api"].get("/admin/summary").json()
    assert summary["online"] == 0 and summary["recently_seen"] == 1
    assert not env["api"].get("/admin/devices").json()["devices"][0]["online"]
    assert env["client"].validate(heartbeat=True).allowed
    assert env["api"].get("/admin/summary").json()["online"] == 1
    alert = env["api"].get("/admin/alerts").json()[0]
    assert env["api"].post(f'/admin/alerts/{alert["id"]}/acknowledge', headers=headers, json={}).status_code == 200
    assert env["api"].get("/admin/devices").json()["devices"][0]["detection"] == "SEEN"
    env["clock"].advance(86401)
    admin_login(env)  # The controlled clock also expires the eight-hour admin session.
    assert env["api"].get("/admin/summary").json()["recently_seen"] == 0


@pytest.mark.parametrize("failure,connectivity", [("timeout", "TIMEOUT"), ("server", "SERVER_UNAVAILABLE"), ("internet", "NETWORK_UNAVAILABLE")])
def test_outages_are_not_revocations_and_recover(activated, failure, connectivity):
    env = activated
    lease = copy.deepcopy(env["client"].state["license"])
    env["transport"].failure = failure
    result = env["client"].validate()
    assert result.allowed and result.status == "OFFLINE_GRACE" and result.connectivity == connectivity
    assert env["client"].state["license"] == lease
    env["transport"].failure = None
    assert env["client"].validate().status == "AUTHORIZED"


def test_48_hours_expiry_and_restart_does_not_reset_timer(activated):
    env = activated
    env["transport"].failure = "timeout"
    env["clock"].advance(OFFLINE_SECONDS - 1)
    restart = LicenseClient(env["config"], env["store"], clock=env["clock"], transport=env["transport"])
    assert restart.validate().allowed
    env["clock"].advance(1)
    assert restart.decision().status == "OFFLINE_EXPIRED"
    restart2 = LicenseClient(env["config"], env["store"], clock=env["clock"], transport=env["transport"])
    assert not restart2.decision().allowed
    env["transport"].failure = None
    assert restart2.validate().allowed


def test_rollback_is_persistent_until_signed_validation(activated):
    env = activated
    env["clock"].advance(3600)
    env["client"].decision()
    env["clock"].wall_time -= 7200
    assert env["client"].decision().status == "CLOCK_ROLLBACK"
    restart = LicenseClient(env["config"], env["store"], clock=env["clock"], transport=env["transport"])
    assert restart.decision().status == "CLOCK_ROLLBACK"
    assert restart.validate().allowed


def test_repeated_small_rollbacks_cannot_renew_lease(activated):
    env = activated
    for _ in range(600):
        env["clock"].mono_time += 300
        assert env["client"].state["last_successful_validation"] == env["clock"].server_time
        env["client"].decision()
    assert env["client"].decision().status == "OFFLINE_EXPIRED"


def test_revocation_persists_offline_after_restart_and_reactivation(activated):
    env = activated
    assert change_device(env, "revoke").status_code == 200
    assert env["client"].validate().status == "REVOKED"
    env["transport"].failure = "server"
    restart = LicenseClient(env["config"], env["store"], clock=env["clock"], transport=env["transport"])
    assert restart.validate().status == "REVOKED"
    assert change_device(env, "reactivate").status_code == 200
    env["transport"].failure = None
    assert restart.validate().allowed


def test_activation_key_cannot_override_revocation(activated):
    env = activated
    assert change_device(env, "revoke").status_code == 200
    assert env["client"].validate(activation_key=env["activation"]).status == "REVOKED"


def test_invalid_unsigned_tampered_wrong_device_replay_and_nonce(activated):
    env = activated
    original = copy.deepcopy(env["client"].state["license"])
    transforms = [lambda data: {"status": "REVOKED"},
                  lambda data: {**data, "payload": {**data["payload"], "status": "REVOKED"}},
                  lambda data: original]
    for transform in transforms:
        env["transport"].transform = transform
        result = env["client"].validate()
        assert result.allowed and result.connectivity == "INVALID_RESPONSE"
        assert env["client"].state["license"] == original
    with pytest.raises(InvalidLicense):
        verify_license(original, env["config"]["public_keys"], str(uuid.uuid4()))
    env["transport"].transform = None
    assert env["client"].validate().allowed


def test_license_expiry_beats_offline_grace(activated):
    env = activated
    with env["app"].state.sessions() as session:
        session.get(License, env["license_id"]).expires_at = datetime.fromtimestamp(env["clock"].server_time + 120, timezone.utc)
        session.commit()
    assert env["client"].validate().allowed
    env["clock"].advance(120)
    assert env["client"].decision().status == "EXPIRED"
    assert env["client"].validate().status == "EXPIRED"


def test_seat_limits_and_reactivation_cannot_bypass_limits(activated):
    env = activated
    with env["app"].state.sessions() as session:
        session.get(License, env["license_id"]).max_devices = 1
        session.commit()
    other = LicenseClient(env["config"], MemoryStore(), clock=env["clock"], transport=env["transport"])
    assert other.validate(activation_key=env["activation"]).status == "LIMIT_REACHED"
    assert change_device(env, "revoke").status_code == 200
    assert other.validate(activation_key=env["activation"]).allowed
    assert change_device(env, "reactivate").status_code == 409


def test_disabled_license_does_not_authorize(activated):
    env = activated
    with env["app"].state.sessions() as session:
        session.get(License, env["license_id"]).status = "DISABLED"
        session.commit()
    assert env["client"].validate().status == "REVOKED"


def test_admin_auth_authorization_csrf_confirmation_and_audit(activated):
    env = activated
    for path in ["/admin", "/admin/me", "/admin/devices", "/admin/summary", "/admin/alerts", "/admin/audit"]:
        assert env["api"].get(path).status_code == 401
    headers = admin_login(env)
    device = env["client"].state["device_id"]
    path = f"/admin/devices/{device}/revoke"
    body = {"confirm": True, "confirmed_device_id": device, "reason": "Fraud investigation"}
    assert env["api"].post(path, json=body).status_code == 403
    assert env["api"].post(path, headers=headers, json={**body, "confirm": False}).status_code == 422
    assert env["api"].post(path, headers=headers, json={**body, "confirmed_device_id": str(uuid.uuid4())}).status_code == 400
    assert env["api"].post(path, headers={**headers,"Origin":"https://evil.test"}, json=body).status_code == 403
    assert env["api"].post(path, headers=headers, json=body).status_code == 200
    audit = env["api"].get("/admin/audit").json()
    event = next(row for row in audit if row["event"] == "device_revoked")
    assert event["actor"] == "developer" and event["device_id"] == device and event["reason"] == body["reason"]
    with env["app"].state.sessions() as session:
        session.get(Administrator, "developer").role = "VIEWER"
        session.commit()
    assert env["api"].get("/admin/devices").status_code == 403


def test_https_enforcement_and_secure_cookie(activated):
    env = activated
    assert env["api"].get("http://testserver/health").status_code == 400
    response = env["api"].post("/admin/login", json={"username":"developer","password":"test-password-123"})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    env["client"].config = {**env["config"], "server_url": "http://testserver"}
    assert env["client"].validate().connectivity == "CONFIGURATION_ERROR"


def test_wrong_device_secret_is_not_revocation_and_is_audited(activated):
    env = activated
    env["client"].state["device_secret"] = "wrong" * 12
    assert env["client"].validate().connectivity == "AUTHENTICATION_ERROR"
    assert env["client"].decision().allowed
    with env["app"].state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Audit).where(Audit.event == "license_check_failed")) == 1


def test_admin_login_rate_limit(env):
    for _ in range(10):
        assert env["api"].post("/admin/login",json={"username":"developer","password":"wrong"}).status_code == 401
    assert env["api"].post("/admin/login",json={"username":"developer","password":"wrong"}).status_code == 429


def test_invalid_request_does_not_echo_credentials(env):
    secret = "do-not-echo-secret"
    response = env["api"].post("/v1/devices/register", json={"device_id": "invalid", "device_secret":secret})
    assert response.status_code == 422 and secret not in response.text


def test_parallel_registration_cannot_oversubscribe_license(activated):
    if not os.environ.get("LICENSE_TEST_POSTGRES_URL"):
        pytest.skip("Concurrent registration requires PostgreSQL row locking")
    from concurrent.futures import ThreadPoolExecutor
    env = activated
    with env["app"].state.sessions() as session:
        session.get(License, env["license_id"]).max_devices = 2
        session.commit()
    def register_new(_):
        client = LicenseClient(env["config"], MemoryStore(), clock=env["clock"], transport=ServiceTransport(env["api"]))
        return client.validate(activation_key=env["activation"]).status
    with ThreadPoolExecutor(max_workers=4) as workers:
        statuses = list(workers.map(register_new, range(4)))
    assert statuses.count("AUTHORIZED") == 1 and statuses.count("LIMIT_REACHED") == 3


def test_dpapi_encryption_roundtrip_and_corruption(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows DPAPI test")
    store = DPAPIStore(tmp_path)
    secret = "secret-test-device-token"
    store.write({"device_secret":secret})
    assert secret.encode() not in store.path.read_bytes()
    assert store.read()["device_secret"] == secret
    store.path.write_bytes(b"corrupt")
    from licensing.storage import StorageError
    with pytest.raises(StorageError):
        store.read()


def test_licensing_schema_compiles_for_postgresql():
    assert len(Base.metadata.tables) == 8
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl


def test_production_clone_integrity_and_gate_transaction_safety(activated, monkeypatch, tmp_path):
    env = activated
    source = ROOT / "temp/license_validation/pharmacy_clone.db"
    assert source.is_file(), "Create a protected clone before running pharmacy licensing tests"
    target = tmp_path / "pharmacy_transaction_test.db"
    shutil.copyfile(source, target)
    monkeypatch.setenv("PHARMACY_DB", str(target))
    monkeypatch.setenv("PHARMACY_TEST_PROTECTED_DB", str(ROOT / "data/pharmacy.db"))
    monkeypatch.setenv("PHARMACY_TEST_SAFE_DB", str(target))
    from database.connection import get_connection
    gate = OperationGate()
    gate.set_access(True, "Authorized")
    install_gate(gate)
    try:
        conn = get_connection()
        conn.execute("CREATE TABLE licensing_transaction_probe(value TEXT)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO licensing_transaction_probe VALUES ('active sale transaction')")
        assert change_device(env, "revoke").status_code == 200
        decision = env["client"].validate()
        gate.set_access(decision.allowed, decision.message)
        assert decision.status == "REVOKED" and not gate.ready_to_lock
        with pytest.raises(LicenseRestricted):
            get_connection()
        conn.commit()  # an already-running transaction is never terminated or rolled back by licensing
        conn.close()
        assert gate.ready_to_lock
        with sqlite3.connect(target) as check:
            assert check.execute("SELECT value FROM licensing_transaction_probe").fetchone()[0] == "active sale transaction"
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
        assert change_device(env, "reactivate").status_code == 200
        decision = env["client"].validate()
        gate.set_access(decision.allowed, decision.message)
        conn = get_connection(); conn.close()
    finally:
        install_gate(None)


def test_qt_lock_deferred_until_transaction_finishes_and_recovers(activated, monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMainWindow
    from licensing.qt import LicenseController
    app = QApplication.instance() or QApplication([])
    env = activated
    controller = LicenseController(env["client"])
    window = QMainWindow()
    controller.window = window
    controller._checked(env["client"].decision())
    controller.gate.acquire()
    assert change_device(env, "revoke").status_code == 200
    controller._checked(env["client"].validate())
    assert controller.dialog is None
    controller.gate.release()
    controller._present()
    assert controller.dialog.isVisible()
    assert "revoked" in controller.dialog.message.text()
    assert change_device(env, "reactivate").status_code == 200
    controller._checked(env["client"].validate())
    assert controller.dialog is None
    controller.shutdown()
    window.close()
    controller.deleteLater()
    app.processEvents()
    install_gate(None)


def test_revocation_during_real_sale_commits_stock_and_ledger(activated, monkeypatch, tmp_path):
    env = activated
    target = tmp_path / "real_sale.db"
    monkeypatch.setenv("PHARMACY_DB", str(target))
    from database.connection import init_database, get_connection
    from database.account_roles import ensure_system_ledgers
    from database.company_dao import CompanyDAO
    from database.customer_dao import CustomerDAO
    from database.item_dao import ItemDAO
    from database.stock_dao import StockDAO
    from database.unit_dao import UnitDAO
    from database.supplier_dao import SupplierDAO
    from database.purchase_dao import PurchaseDAO
    from database.sales_dao import SalesDAO
    from database.accounting_posting import posting_engine
    init_database()
    ensure_system_ledgers()
    company = CompanyDAO.insert("Licensing test company", "LTC")
    unit = UnitDAO.insert("Unit")
    customer = CustomerDAO.insert("Licensing test customer")
    supplier = SupplierDAO.insert("Licensing test supplier")
    item = ItemDAO.insert(item_name="Licensing test medicine", unit_id=unit, company_id=company, pack_size="1")
    PurchaseDAO.insert_invoice(voucher_no="LICENSE-P1", voucher_date="2026-11-09", voucher_time="12:00",
        purchase_type="Cash", supplier_id=supplier, invoice_no="LICENSE-INV", invoice_date="2026-11-09",
        invoice_net_amount=400, bill_discount=0, due_date="", total_amount=400, gst_amount=0,
        debit_note_amount=0, other_amount=0, paid_amount=400, round_off=0, net_amount=400, remarks="",
        items=[{"item_id":item,"pack_size":"1","pay_qty":10,"free_qty":0,"batch_no":"LICENSE-B1",
                "expiry":"12/30","rate":40,"mrp":50,"discount":0,"gst_percent":0,"gst_amount":0,
                "amount":400,"purchase_rate":40,"net_rate":40,"pp":40}])
    batch = StockDAO.get_stock_batches_for_item(item)[0]
    gate = OperationGate()
    gate.set_access(True, "Authorized")
    install_gate(gate)
    original_post = posting_engine.post_counter_sale
    observed = []
    def revoke_before_post(invoice_id, *, cur=None):
        assert cur.connection.in_transaction
        assert change_device(env, "revoke").status_code == 200
        decision = env["client"].validate()
        gate.set_access(decision.allowed, decision.message)
        observed.append((decision.status, gate.ready_to_lock))
        return original_post(invoice_id, cur=cur)
    monkeypatch.setattr(posting_engine, "post_counter_sale", revoke_before_post)
    try:
        invoice = SalesDAO.insert_invoice(bill_no="LICENSE-S1", sale_date="2026-11-09", sale_time="12:05",
            sale_type="Credit", customer_id=customer, patient_name="Test patient", doctor_id=None,
            discount=0, paid_amount=0, total_amount=100, round_off=0, net_amount=100, remarks="",
            items=[{"item_id":item,"stock_batch_id":batch["id"],"pack_size":"1","location":"",
                    "batch_no":"LICENSE-B1","expiry":"12/30","mrp":50,"sale_qty":2,"discount_amount":0,"amount":100}])
        assert observed == [("REVOKED", False)]
        assert gate.ready_to_lock
        with pytest.raises(LicenseRestricted):
            get_connection()
        with sqlite3.connect(target) as conn:
            assert conn.execute("SELECT net_amount FROM sales_invoices WHERE id=?", (invoice,)).fetchone()[0] == 100
            assert conn.execute("SELECT stock_qty FROM stock_batches WHERE id=?", (batch["id"],)).fetchone()[0] == batch["stock_qty"] - 2
            assert conn.execute("SELECT COUNT(*) FROM ledger_transactions WHERE reference_type='COUNTER_SALE' AND reference_id=?", (invoice,)).fetchone()[0] >= 2
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        install_gate(None)

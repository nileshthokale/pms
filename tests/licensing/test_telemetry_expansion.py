"""Unit and integration tests for the 5 expanded telemetry categories in licensing/fingerprint.py."""
import os
import sqlite3
import tempfile
import time
from datetime import datetime

import pytest

from licensing.fingerprint import (
    collect_device_fingerprint,
    _collect_pos_peripherals,
    _collect_integrity_info,
    _detect_vm,
    _collect_database_health,
    _collect_diagnostics_info,
    _collect_store_activity,
    _get_screen_info,
    _get_bios_serial,
)


def test_fingerprint_contains_all_five_telemetry_categories():
    """Verify that collect_device_fingerprint includes all 5 required categories and preserves base keys."""
    fp = collect_device_fingerprint("1.2.0")
    assert isinstance(fp, dict)

    # Base categories
    for key in ("os", "hardware", "network", "runtime", "security", "session"):
        assert key in fp, f"Missing base category: {key}"

    # 5 New Telemetry Categories
    for key in ("pos_peripherals", "integrity", "database", "diagnostics", "store_activity"):
        assert key in fp, f"Missing new telemetry category: {key}"

    # Hardware enriched fields
    assert "bios_serial" in fp["hardware"]
    assert "screen" in fp["hardware"]


def test_category_1_pos_peripherals():
    """Verify Hardware & POS Peripherals fields."""
    pos = _collect_pos_peripherals()
    assert isinstance(pos, dict)

    assert "printers" in pos
    assert isinstance(pos["printers"], list)
    for p in pos["printers"]:
        assert "name" in p
        assert "is_default" in p
        assert "port" in p
        assert "driver" in p
        assert "is_pos_printer" in p

    assert "thermal_receipt_printers" in pos
    assert isinstance(pos["thermal_receipt_printers"], list)
    assert "has_receipt_printer" in pos
    assert isinstance(pos["has_receipt_printer"], bool)

    assert "barcode_scanners" in pos
    assert isinstance(pos["barcode_scanners"], list)
    assert "has_barcode_scanner" in pos
    assert isinstance(pos["has_barcode_scanner"], bool)

    assert "screen" in pos
    screen = pos["screen"]
    assert "resolution" in screen
    assert "dpi" in screen
    assert "dpi_scaling_percent" in screen
    assert screen["dpi"] > 0
    assert screen["dpi_scaling_percent"] > 0

    assert "bios_serial" in pos
    assert pos["bios_serial"] is not None


def test_category_2_integrity_and_vm_detection():
    """Verify Anti-Piracy, integrity, VM detection and hypervisor identification."""
    integrity = _collect_integrity_info()
    assert isinstance(integrity, dict)

    assert "is_vm" in integrity
    assert isinstance(integrity["is_vm"], bool)
    assert "vm_hypervisor" in integrity
    assert "vm_indicators" in integrity
    assert isinstance(integrity["vm_indicators"], list)

    assert "clock_rollback_detected" in integrity
    assert isinstance(integrity["clock_rollback_detected"], bool)
    assert "clock_delta_seconds" in integrity
    assert isinstance(integrity["clock_delta_seconds"], (int, float))

    assert "concurrent_instances" in integrity
    assert isinstance(integrity["concurrent_instances"], int)
    assert integrity["concurrent_instances"] >= 1

    # VM Detection logic unit test with synthetic MAC OUIs
    vm_tests = [
        ("00:05:69:aa:bb:cc", "VMware"),
        ("00:0c:29:11:22:33", "VMware"),
        ("08:00:27:12:34:56", "VirtualBox"),
        ("00:15:5d:ab:cd:ef", "Hyper-V"),
        ("52:54:00:12:34:56", "QEMU"),
    ]
    for mac, expected_hv in vm_tests:
        detected = _detect_vm([mac])
        assert detected["is_vm"] is True, f"Failed to detect VM for MAC {mac}"
        assert detected["hypervisor"] == expected_hv, f"Expected {expected_hv}, got {detected['hypervisor']}"


def test_category_3_database_health(monkeypatch):
    """Verify Database Health read-only metrics and low disk warning."""
    # Test with live DB
    health = _collect_database_health()
    assert isinstance(health, dict)
    assert "db_found" in health
    assert "disk_free_gb" in health
    assert health["disk_free_gb"] is not None and health["disk_free_gb"] > 0
    assert "low_disk_warning" in health
    assert isinstance(health["low_disk_warning"], bool)

    # Test with custom temporary database via PHARMACY_DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name
        f.write(b"x" * 1024 * 1024)  # Exactly 1 MB

    try:
        monkeypatch.setenv("PHARMACY_DB", temp_db_path)
        custom_health = _collect_database_health()
        assert custom_health["db_found"] is True
        assert custom_health["db_path"] == os.path.abspath(temp_db_path)
        assert custom_health["db_size_mb"] == 1.0
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_category_4_technical_diagnostics():
    """Verify Technical Diagnostics metrics."""
    diag = _collect_diagnostics_info()
    assert isinstance(diag, dict)

    assert "process_ram_mb" in diag
    assert isinstance(diag["process_ram_mb"], (int, float))
    assert diag["process_ram_mb"] > 0

    assert "process_uptime_seconds" in diag
    assert isinstance(diag["process_uptime_seconds"], int)
    assert diag["process_uptime_seconds"] >= 0

    assert "process_uptime_formatted" in diag
    assert isinstance(diag["process_uptime_formatted"], str)

    assert "startup_seconds" in diag
    assert isinstance(diag["startup_seconds"], (int, float))
    assert diag["startup_seconds"] > 0

    assert "pending_reboot" in diag
    assert isinstance(diag["pending_reboot"], bool)
    assert "pending_reboot_reasons" in diag
    assert isinstance(diag["pending_reboot_reasons"], list)


def test_category_5_store_activity(monkeypatch):
    """Verify Business & Store Activity read-only queries with chronological time resolution."""
    # Create an isolated temporary SQLite database with sales invoices
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        conn = sqlite3.connect(temp_db_path)
        conn.execute("""
            CREATE TABLE sales_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_no TEXT,
                sale_date TEXT,
                sale_time TEXT,
                net_amount REAL
            )
        """)
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Insert test invoices for today with out-of-order 12-hour timestamps
        conn.execute("INSERT INTO sales_invoices (bill_no, sale_date, sale_time, net_amount) VALUES (?, ?, ?, ?)",
                     ("INV-001", today_str, "06:45 PM", 120.0))
        conn.execute("INSERT INTO sales_invoices (bill_no, sale_date, sale_time, net_amount) VALUES (?, ?, ?, ?)",
                     ("INV-002", today_str, "09:15 AM", 55.0))
        conn.execute("INSERT INTO sales_invoices (bill_no, sale_date, sale_time, net_amount) VALUES (?, ?, ?, ?)",
                     ("INV-003", today_str, "01:30 PM", 340.0))
        conn.commit()
        conn.close()

        # Record file mtime before read-only collection to guarantee zero-mutation
        mtime_before = os.path.getmtime(temp_db_path)

        monkeypatch.setenv("PHARMACY_DB", temp_db_path)
        activity = _collect_store_activity()

        assert activity["status"] == "available"
        assert activity["invoices_today"] == 3
        # Chronological sorting: 09:15 AM is earliest, 06:45 PM is latest
        assert activity["earliest_invoice_today"] == "09:15 AM"
        assert activity["latest_invoice_today"] == "06:45 PM"
        assert activity["active_store_hours"] == "09:15 AM - 06:45 PM"
        assert activity["total_invoices_all_time"] == 3

        # Zero modification check
        mtime_after = os.path.getmtime(temp_db_path)
        assert mtime_before == mtime_after, "Database file mtime was modified! Read-only invariant violated."

    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

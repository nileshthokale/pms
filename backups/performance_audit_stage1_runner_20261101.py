"""Stage 1 benchmark harness. Runs only against an explicit clone database."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
import tracemalloc
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rank95(values: list[float | int]) -> float | int | None:
    if not values:
        return None
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def child() -> None:
    start = time.perf_counter()
    metrics: dict = {"page_constructors_ms": {}, "errors": []}
    interval_samples: list[float] = []
    tracemalloc.start()

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(MemoryCounters), ctypes.wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    rss_samples: list[float] = []
    monitor_stop = threading.Event()

    def sample_rss() -> None:
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            rss_samples.append(counters.WorkingSetSize / 1024 / 1024)

    def monitor_rss() -> None:
        while not monitor_stop.is_set():
            sample_rss()
            monitor_stop.wait(0.02)

    monitor = threading.Thread(target=monitor_rss, daemon=True)
    monitor.start()

    try:
        from time import perf_counter
        import main as app_main
        import screens
        from PySide6.QtCore import QDate, QTimer, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QDialog
        from screens.login import LoginDialog
        from database.connection import get_db_path

        expected_db = Path(os.environ["STAGE1_EXPECTED_DB"]).resolve()
        resolved_db = Path(get_db_path()).resolve()
        if resolved_db != expected_db:
            raise RuntimeError(f"Database path guard failed: {resolved_db} != {expected_db}")
        metrics["resolved_db"] = str(resolved_db)
        metrics["phase"] = os.environ.get("STAGE1_PHASE", "unknown")
        metrics["startup_to_login_visible_ms"] = None
        metrics["authentication_submit_ms"] = None
        login_completed_at = [None]

        for class_name in ("ItemMasterPage", "CounterSalePage", "CustomerMasterPage", "SalesHistoryPage", "SalesReportPage"):
            cls = getattr(screens, class_name)
            original_init = cls.__init__

            def measured_init(self, *args, _original=original_init, _name=class_name, **kwargs):
                began = perf_counter()
                _original(self, *args, **kwargs)
                metrics["page_constructors_ms"].setdefault(_name, []).append((perf_counter() - began) * 1000)

            cls.__init__ = measured_init

        heartbeat_last = [None]
        heartbeat = QTimer()
        heartbeat.setInterval(10)

        def heartbeat_tick() -> None:
            now = perf_counter()
            if heartbeat_last[0] is not None:
                interval_samples.append((now - heartbeat_last[0]) * 1000)
            heartbeat_last[0] = now

        heartbeat.timeout.connect(heartbeat_tick)

        def timed_login() -> bool:
            dialog = LoginDialog()
            dialog._username.setText(os.environ["STAGE1_BENCH_USER"])
            dialog._password.setText(os.environ["STAGE1_BENCH_PASSWORD"])
            dialog.show()
            QApplication.processEvents()
            metrics["startup_to_login_visible_ms"] = (
                perf_counter() - float(os.environ["STAGE1_PROCESS_T0"])
            ) * 1000
            began = perf_counter()
            dialog._submit()
            metrics["authentication_submit_ms"] = (perf_counter() - began) * 1000
            metrics["login_dialog_visible"] = dialog.isVisible()
            metrics["login_accepted"] = dialog.result() == QDialog.DialogCode.Accepted
            login_completed_at[0] = perf_counter()
            return metrics["login_accepted"]

        app_main.run_login = timed_login
        original_window = app_main.PharmacyMainWindow

        def run_operations(window) -> None:
            try:
                QApplication.processEvents()
                metrics["login_to_dashboard_first_frame_ms"] = (perf_counter() - login_completed_at[0]) * 1000
                metrics["dashboard_visible"] = bool(window.isVisible())
                metrics["dashboard_page_count"] = window._stack.count()
                heartbeat.start()
                QTest.qWait(30)

                def timed(key: str, operation):
                    began = perf_counter()
                    try:
                        result = operation()
                        QApplication.processEvents()
                        metrics[key] = (perf_counter() - began) * 1000
                        return result
                    except Exception as exc:
                        metrics["errors"].append(f"{key}: {type(exc).__name__}: {exc}")
                        metrics[key] = None
                        return None

                item_page = window._stack.widget(window._page_map["Master:Item Master"])
                metrics["item_master_constructor_cold_ms"] = metrics["page_constructors_ms"].get("ItemMasterPage", [None])[0]
                timed("item_master_full_refresh_first_ms", item_page._refresh)
                item_page._search_edit.setText("PROTONIX")
                timed("item_master_search_first_ms", item_page._on_search)
                timed("item_master_search_repeat_ms", item_page._on_search)

                sales_page = window._stack.widget(window._page_map["Sales:New Bill"])
                metrics["sales_page_constructor_cold_ms"] = metrics["page_constructors_ms"].get("CounterSalePage", [None])[0]
                timed("sales_page_navigation_first_ms", lambda: window._on_menu_action("Sales", "New Bill"))
                timed("sales_page_navigation_repeat_ms", lambda: window._on_menu_action("Sales", "New Bill"))

                # A second construction in the same process measures page-load cost after modules/DB are warm.
                timed("item_master_constructor_warm_ms", lambda: screens.ItemMasterPage())
                timed("sales_page_constructor_warm_ms", lambda: screens.CounterSalePage())

                from database.customer_dao import CustomerDAO
                customer_page = window._stack.widget(window._page_map["Master:Customer Master"])

                def customer_cycle(label: str) -> None:
                    customer_name = "PERF AUDIT " + uuid.uuid4().hex[:12]
                    began = perf_counter()
                    customer_id = CustomerDAO.insert(customer_name, city="AUDIT")
                    customer_page._refresh()
                    QApplication.processEvents()
                    metrics[label + "_customer_add_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    metrics[label + "_customer_add_visible"] = any(
                        customer_page._table.item(row, col) and customer_page._table.item(row, col).text() == customer_name
                        for row in range(customer_page._table.rowCount()) for col in range(customer_page._table.columnCount())
                    )

                    edited_name = customer_name + " EDIT"
                    began = perf_counter()
                    CustomerDAO.update(customer_id, edited_name, city="AUDIT")
                    customer_page._refresh()
                    QApplication.processEvents()
                    metrics[label + "_customer_edit_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    metrics[label + "_customer_edit_visible"] = any(
                        customer_page._table.item(row, col) and customer_page._table.item(row, col).text() == edited_name
                        for row in range(customer_page._table.rowCount()) for col in range(customer_page._table.columnCount())
                    )

                    began = perf_counter()
                    metrics[label + "_customer_delete_result"] = CustomerDAO.delete(customer_id)
                    customer_page._refresh()
                    QApplication.processEvents()
                    metrics[label + "_customer_delete_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    metrics[label + "_customer_delete_absent"] = not any(
                        customer_page._table.item(row, col) and customer_page._table.item(row, col).text() == edited_name
                        for row in range(customer_page._table.rowCount()) for col in range(customer_page._table.columnCount())
                    )

                customer_cycle("first")
                customer_cycle("repeat")

                from database.sales_dao import SalesDAO
                history_page = window._stack.widget(window._page_map["Sales:Patient Bill History"])

                def sale_cycle(label: str) -> None:
                    bill_no = "PERF-AUDIT-" + uuid.uuid4().hex[:16]
                    item = {"item_id": 1625, "stock_batch_id": 7125, "pack_size": "10", "location": "", "batch_no": "C-26056", "expiry": "2028-06-30", "mrp": 120.0, "sale_qty": 1.0, "discount_amount": 0.0, "amount": 120.0}
                    began = perf_counter()
                    sale_id = SalesDAO.insert_invoice(bill_no=bill_no, sale_date=date.today().isoformat(), sale_time="12:00", sale_type="Cash", customer_id=159, patient_name="PERFORMANCE AUDIT", doctor_id=None, discount=0.0, paid_amount=120.0, total_amount=120.0, round_off=0.0, net_amount=120.0, remarks="STAGE1 BENCHMARK CLONE", items=[item])
                    persisted = SalesDAO.get_by_id(sale_id) is not None
                    history_page._perform_search()
                    QApplication.processEvents()
                    metrics[label + "_sale_add_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    visible = lambda: any(history_page._table.item(row, 0) and history_page._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == sale_id for row in range(history_page._table.rowCount()))
                    metrics[label + "_sale_add_persisted_visible"] = persisted and visible()

                    item2 = dict(item, sale_qty=2.0, amount=240.0)
                    began = perf_counter()
                    SalesDAO.update_invoice(invoice_id=sale_id, bill_no=bill_no, sale_date=date.today().isoformat(), sale_time="12:01", sale_type="Cash", customer_id=159, patient_name="PERFORMANCE AUDIT", doctor_id=None, discount=0.0, paid_amount=240.0, total_amount=240.0, round_off=0.0, net_amount=240.0, remarks="STAGE1 BENCHMARK CLONE EDIT", items=[item2])
                    updated = SalesDAO.get_by_id(sale_id)
                    history_page._perform_search()
                    QApplication.processEvents()
                    metrics[label + "_sale_edit_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    metrics[label + "_sale_edit_persisted_visible"] = bool(updated and float(updated.get("net_amount") or 0) == 240.0 and visible())

                    began = perf_counter()
                    SalesDAO.delete_invoice(sale_id)
                    absent = SalesDAO.get_by_id(sale_id) is None
                    history_page._perform_search()
                    QApplication.processEvents()
                    metrics[label + "_sale_delete_commit_refresh_ms"] = (perf_counter() - began) * 1000
                    metrics[label + "_sale_delete_persisted_absent"] = absent and not visible()

                sale_cycle("first")
                sale_cycle("repeat")

                from PySide6.QtCore import QDate
                report_page = window._stack.widget(window._page_map["Reports:Sales Report"])
                report_page._from_date.blockSignals(True)
                report_page._to_date.blockSignals(True)
                report_page._from_date.setDate(QDate(2026, 4, 1))
                report_page._to_date.setDate(QDate(2027, 3, 31))
                report_page._from_date.blockSignals(False)
                report_page._to_date.blockSignals(False)
                timed("sales_report_generation_first_ms", report_page._on_generate)
                metrics["sales_report_pages_first"] = len(report_page._pages)
                timed("sales_report_generation_repeat_ms", report_page._on_generate)
                metrics["sales_report_pages_repeat"] = len(report_page._pages)
            except Exception as exc:
                metrics["errors"].append(f"UI benchmark: {type(exc).__name__}: {exc}")
            finally:
                heartbeat.stop()
                QTimer.singleShot(0, QApplication.instance().quit)

        class TimedWindow(original_window):
            def __init__(self, *args, **kwargs):
                began = perf_counter()
                super().__init__(*args, **kwargs)
                metrics["dashboard_constructor_ms"] = (perf_counter() - began) * 1000
                QTimer.singleShot(0, lambda: run_operations(self))

        app_main.PharmacyMainWindow = TimedWindow
        try:
            app_main.main()
        except SystemExit:
            pass
    except Exception as exc:
        metrics["errors"].append(f"startup: {type(exc).__name__}: {exc}")
    finally:
        monitor_stop.set()
        monitor.join(timeout=1)
        sample_rss()
        heap_current, heap_peak = tracemalloc.get_traced_memory()
        metrics["working_set_peak_mb"] = max(rss_samples) if rss_samples else None
        metrics["working_set_final_mb"] = rss_samples[-1] if rss_samples else None
        metrics["python_heap_peak_mb"] = heap_peak / 1024 / 1024
        delays = [max(0.0, interval - 10.0) for interval in interval_samples]
        metrics["event_loop_tick_count"] = len(interval_samples)
        metrics["event_loop_stall_p95_ms"] = rank95(delays)
        metrics["event_loop_stall_max_ms"] = max(delays) if delays else None
        metrics["total_process_elapsed_ms"] = (time.perf_counter() - start) * 1000
        print("PERFJSON " + json.dumps(metrics, default=str), flush=True)


def parent() -> None:
    import sqlite3
    from database.auth import ROLE_ADMIN, hash_password

    source = Path(os.environ["STAGE1_SOURCE_DB"]).resolve()
    clone = Path(os.environ["STAGE1_EXPECTED_DB"]).resolve()
    expected_hash = os.environ["STAGE1_ORIGINAL_SHA256"].lower()
    initial_hash = sha256(source)
    if initial_hash != expected_hash:
        raise SystemExit(f"Original DB hash mismatch before benchmarks: {initial_hash}")
    if Path(os.environ.get("PHARMACY_DB", "")).resolve() != clone:
        raise SystemExit("PHARMACY_DB is not the retained benchmark clone")

    username = os.environ["STAGE1_BENCH_USER"]
    password = os.environ["STAGE1_BENCH_PASSWORD"]
    conn = sqlite3.connect(clone, timeout=30)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE app_users SET password_hash=?, role=?, is_active=1, updated_at=? WHERE username=? COLLATE NOCASE",
            (hash_password(password), ROLE_ADMIN, now, username),
        )
        if conn.execute("SELECT changes()").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO app_users(username,password_hash,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (username, hash_password(password), ROLE_ADMIN, 1, now, now),
            )
        conn.commit()
    finally:
        conn.close()

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PHARMACY_DB"] = str(clone)
    env["PHARMACY_TEST_PROTECTED_DB"] = str(source)
    env["PHARMACY_TEST_SAFE_DB"] = str(clone)
    results = {"cold_process": [], "warm_cache_process": []}
    for phase in results:
        for run_number in range(1, 6):
            env["STAGE1_PHASE"] = phase
            env["STAGE1_PROCESS_T0"] = repr(time.perf_counter())
            print(f"Launching {phase} run {run_number}/5", flush=True)
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
            if proc.stderr.strip():
                print(proc.stderr.strip(), file=sys.stderr, flush=True)
            line = next((line for line in reversed(proc.stdout.splitlines()) if line.startswith("PERFJSON ")), None)
            if line is None:
                results[phase].append({"run": run_number, "return_code": proc.returncode, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:]})
                continue
            record = json.loads(line[len("PERFJSON "):])
            record["run"] = run_number
            record["return_code"] = proc.returncode
            results[phase].append(record)
            print(f"Finished {phase} run {run_number}/5: startup={record.get('startup_to_login_visible_ms')} ms, dashboard={record.get('login_to_dashboard_first_frame_ms')} ms, errors={len(record.get('errors', []))}", flush=True)

    final_hash = sha256(source)
    summaries = {}
    metric_map = {
        "startup_to_login_ms": ("startup_to_login_visible_ms", "startup_to_login_visible_ms"),
        "login_to_dashboard_ms": ("login_to_dashboard_first_frame_ms", "login_to_dashboard_first_frame_ms"),
        "dashboard_constructor_ms": ("dashboard_constructor_ms", "dashboard_constructor_ms"),
        "item_master_page_load_ms": ("item_master_constructor_cold_ms", "item_master_constructor_warm_ms"),
        "item_master_search_ms": ("item_master_search_first_ms", "item_master_search_repeat_ms"),
        "sales_page_load_ms": ("sales_page_constructor_cold_ms", "sales_page_constructor_warm_ms"),
        "sales_entry_commit_refresh_ms": ("first_sale_add_commit_refresh_ms", "repeat_sale_add_commit_refresh_ms"),
        "customer_add_commit_refresh_ms": ("first_customer_add_commit_refresh_ms", "repeat_customer_add_commit_refresh_ms"),
        "customer_edit_commit_refresh_ms": ("first_customer_edit_commit_refresh_ms", "repeat_customer_edit_commit_refresh_ms"),
        "customer_delete_commit_refresh_ms": ("first_customer_delete_commit_refresh_ms", "repeat_customer_delete_commit_refresh_ms"),
        "sale_edit_commit_refresh_ms": ("first_sale_edit_commit_refresh_ms", "repeat_sale_edit_commit_refresh_ms"),
        "sale_delete_commit_refresh_ms": ("first_sale_delete_commit_refresh_ms", "repeat_sale_delete_commit_refresh_ms"),
        "sales_report_generation_ms": ("sales_report_generation_first_ms", "sales_report_generation_repeat_ms"),
        "working_set_peak_mb": ("working_set_peak_mb", "working_set_peak_mb"),
        "python_heap_peak_mb": ("python_heap_peak_mb", "python_heap_peak_mb"),
        "event_loop_stall_max_ms": ("event_loop_stall_max_ms", "event_loop_stall_max_ms"),
        "event_loop_stall_p95_ms": ("event_loop_stall_p95_ms", "event_loop_stall_p95_ms"),
    }
    for label, (cold_key, warm_key) in metric_map.items():
        cold_vals = [r.get(cold_key) for r in results["cold_process"] if isinstance(r.get(cold_key), (int, float))]
        warm_vals = [r.get(warm_key) for r in results["warm_cache_process"] if isinstance(r.get(warm_key), (int, float))]
        summaries[label] = {
            "cold_n": len(cold_vals), "cold_median": statistics.median(cold_vals) if cold_vals else None, "cold_p95_nearest_rank": rank95(cold_vals),
            "warm_n": len(warm_vals), "warm_median": statistics.median(warm_vals) if warm_vals else None, "warm_p95_nearest_rank": rank95(warm_vals),
            "cold_samples": cold_vals, "warm_samples": warm_vals,
        }
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        pyside_version = PySide6.__version__
        qt_version = qVersion()
    except Exception:
        pyside_version = qt_version = None
    output = {
        "source_db": str(source), "source_sha256_before": initial_hash, "source_sha256_after": final_hash,
        "source_unchanged": final_hash == initial_hash, "benchmark_clone": str(clone),
        "platform": "Windows; PySide6 offscreen Qt platform", "python_version": sys.version.split()[0],
        "pyside6_version": pyside_version, "qt_version": qt_version, "runs_per_phase": 5,
        "phase_definitions": {"cold_process": "new process with no in-process Qt/SQLite state; OS cache not flushed", "warm_cache_process": "new process after cold group has primed filesystem cache; OS cache not controlled"},
        "results": results, "summaries": summaries,
    }
    result_path = clone.with_suffix(".results.json")
    if result_path.exists():
        raise SystemExit(f"Refusing to overwrite benchmark results: {result_path}")
    result_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print("AGGJSON " + json.dumps({"result_file": str(result_path), "source_unchanged": final_hash == initial_hash, "summaries": summaries, "run_errors": {phase: [r.get("errors", []) for r in rows if r.get("errors")] for phase, rows in results.items()}}, default=str), flush=True)


if __name__ == "__main__":
    if "--child" in sys.argv:
        child()
    else:
        parent()

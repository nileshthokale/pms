"""Isolated Stage 2 startup/page/report benchmark runner.

Run from the repository root with PHARMACY_DB set to the Stage 2 working
clone. The parent launches fresh app processes and stores raw observations.
"""
from __future__ import annotations

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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rank95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def worker() -> int:
    from time import perf_counter

    process_started = perf_counter()
    print("stage2-worker: start", flush=True)
    expected_db = Path(os.environ["STAGE2_EXPECTED_DB"]).resolve()
    metrics: dict = {
        "phase": os.environ.get("STAGE2_PHASE", "unknown"),
        "run": int(os.environ.get("STAGE2_RUN", "0")),
        "errors": [],
        "page_constructors_ms": {},
    }
    tracemalloc.start()

    rss_samples: list[float] = []
    monitor_stop = threading.Event()
    monitor = None
    try:
        import ctypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        from ctypes import wintypes
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()

        def sample_rss() -> None:
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                rss_samples.append(counters.WorkingSetSize / 1024 / 1024)

        def monitor_rss() -> None:
            while not monitor_stop.is_set():
                sample_rss()
                monitor_stop.wait(0.02)

        monitor = threading.Thread(target=monitor_rss, daemon=True)
        monitor.start()

        import main as app_main
        from database import auth
        from database.connection import get_db_path
        from PySide6.QtCore import QDate, QTimer, Qt
        from PySide6.QtWidgets import QApplication, QDialog
        from screens.login import LoginDialog

        resolved = Path(get_db_path()).resolve()
        if resolved != expected_db:
            raise RuntimeError(f"Database guard mismatch: {resolved} != {expected_db}")
        metrics["resolved_db"] = str(resolved)
        print("stage2-worker: database guard verified", flush=True)

        init_database = app_main.init_database
        def timed_init_database():
            began = perf_counter()
            result = init_database()
            metrics["database_init_ms"] = (perf_counter() - began) * 1000
            return result
        app_main.init_database = timed_init_database

        ensure_fy = app_main.ensure_default_financial_year
        def timed_ensure_fy():
            began = perf_counter()
            result = ensure_fy()
            metrics["financial_year_ensure_ms"] = (perf_counter() - began) * 1000
            return result
        app_main.ensure_default_financial_year = timed_ensure_fy

        from ui import main_window as main_window_module
        window_init_calls = {"count": 0}
        original_window_init_database = main_window_module.init_database
        def count_window_init_database():
            window_init_calls["count"] += 1
            return original_window_init_database()
        main_window_module.init_database = count_window_init_database

        original_ensure_page = main_window_module.PharmacyMainWindow._create_page
        def timed_create_page(self, menu_name, item_name, sub_title):
            began = perf_counter()
            page = original_ensure_page(self, menu_name, item_name, sub_title)
            class_name = type(page).__name__
            metrics["page_constructors_ms"].setdefault(class_name, []).append(
                (perf_counter() - began) * 1000
            )
            return page
        main_window_module.PharmacyMainWindow._create_page = timed_create_page

        heartbeat_intervals: list[float] = []
        heartbeat_last = [None]
        heartbeat = QTimer()
        heartbeat.setInterval(10)

        def heartbeat_tick() -> None:
            now = perf_counter()
            if heartbeat_last[0] is not None:
                heartbeat_intervals.append((now - heartbeat_last[0]) * 1000)
            heartbeat_last[0] = now

        heartbeat.timeout.connect(heartbeat_tick)
        login_completed_at = [None]

        def timed_login() -> bool:
            auth_started = perf_counter()
            auth.ensure_auth_schema()
            metrics["auth_schema_ensure_ms"] = (perf_counter() - auth_started) * 1000
            dialog = LoginDialog()
            dialog._username.setText(os.environ["STAGE2_BENCH_USER"])
            dialog._password.setText(os.environ["STAGE2_BENCH_PASSWORD"])
            dialog.show()
            QApplication.processEvents()
            metrics["startup_to_login_visible_ms"] = (perf_counter() - process_started) * 1000
            began = perf_counter()
            dialog._submit()
            metrics["authentication_submit_ms"] = (perf_counter() - began) * 1000
            metrics["login_accepted"] = dialog.result() == QDialog.DialogCode.Accepted
            if not metrics["login_accepted"]:
                raise RuntimeError("Clone benchmark login was rejected")
            login_completed_at[0] = perf_counter()
            print("stage2-worker: login accepted", flush=True)
            return True

        app_main.run_login = timed_login
        original_window = app_main.PharmacyMainWindow

        def run_operations(window) -> None:
            try:
                QApplication.processEvents()
                metrics["login_to_dashboard_first_frame_ms"] = (
                    perf_counter() - login_completed_at[0]
                ) * 1000
                metrics["dashboard_visible"] = bool(window.isVisible())
                metrics["dashboard_route_count"] = window._stack.count()
                metrics["initial_page_count"] = len(window._page_instances)
                metrics["window_init_database_calls"] = window_init_calls["count"]
                print("stage2-worker: dashboard first frame", flush=True)
                heartbeat.start()
                QTimer.singleShot(30, lambda: measure_pages(window))
            except Exception as exc:
                metrics["errors"].append(f"dashboard: {type(exc).__name__}: {exc}")
                QTimer.singleShot(0, QApplication.instance().quit)

        def timed(key: str, operation):
            began = perf_counter()
            result = operation()
            print("stage2-worker: operation returned", key, flush=True)
            QApplication.processEvents()
            print("stage2-worker: events processed", key, flush=True)
            metrics[key] = (perf_counter() - began) * 1000
            return result

        def measure_pages(window) -> None:
            try:
                print("stage2-worker: item page", flush=True)
                from screens import SalesReportPage
                from database.sales_report_dao import SalesReportDAO
                print("stage2-worker: page modules imported", flush=True)

                item_index = window._page_map["Master:Item Master"]
                print("stage2-worker: item route navigation start", flush=True)
                timed("item_master_first_navigation_ms", lambda: window._on_menu_action("Master", "Item Master"))
                print("stage2-worker: item route navigation done", flush=True)
                item_page = window._stack.widget(item_index)
                metrics["item_master_initial_rows"] = item_page._table.rowCount()
                print("stage2-worker: explicit item refresh start", flush=True)
                timed("item_master_full_refresh_ms", item_page._refresh)
                print("stage2-worker: explicit item refresh done", flush=True)
                item_page._search_edit.setText("PROTONIX")
                print("stage2-worker: item search start", flush=True)
                timed("item_master_search_first_ms", item_page._on_search)
                print("stage2-worker: item search done", flush=True)
                timed("item_master_search_repeat_ms", item_page._on_search)

                print("stage2-worker: counter sale navigation", flush=True)
                sales_index = window._page_map["Sales:New Bill"]
                sale_page = window._stack.widget(sales_index)
                metrics["counter_sale_cached_on_dashboard"] = sale_page is window._page_instances[sales_index]
                timed("counter_sale_navigation_ms", lambda: window._on_menu_action("Sales", "New Bill"))
                timed("counter_sale_repeat_navigation_ms", lambda: window._on_menu_action("Sales", "New Bill"))

                report_index = window._page_map["Reports:Sales Report"]
                generation_calls = {"count": 0}
                original_report = SalesReportDAO.get_sales_report
                def count_report(*args, **kwargs):
                    generation_calls["count"] += 1
                    return original_report(*args, **kwargs)
                SalesReportDAO.get_sales_report = count_report

                print("stage2-worker: report page", flush=True)
                timed("sales_report_page_navigation_ms", lambda: window._on_menu_action("Reports", "Sales Report"))
                report_page = window._stack.widget(report_index)
                metrics["sales_report_constructor_generated_report"] = generation_calls["count"] > 0
                metrics["sales_report_empty_at_open"] = (
                    isinstance(report_page, SalesReportPage)
                    and report_page._last_report is None
                    and not report_page._pages
                )
                report_page._from_date.blockSignals(True)
                report_page._to_date.blockSignals(True)
                report_page._from_date.setDate(QDate(2026, 4, 1))
                report_page._to_date.setDate(QDate(2027, 3, 31))
                report_page._from_date.blockSignals(False)
                report_page._to_date.blockSignals(False)
                print("stage2-worker: report generation", flush=True)
                timed("sales_report_generation_first_ms", report_page.btn_show_report.click)
                metrics["sales_report_pages_first"] = len(report_page._pages)
                metrics["sales_report_rows_first"] = len((report_page._last_report or {}).get("rows", []))
                timed("sales_report_generation_repeat_ms", report_page.btn_show_report.click)
                metrics["sales_report_pages_repeat"] = len(report_page._pages)
                metrics["sales_report_generation_calls_after_request"] = generation_calls["count"]
                QApplication.processEvents()
                print("stage2-worker: reports complete", flush=True)
            except Exception as exc:
                metrics["errors"].append(f"page/report: {type(exc).__name__}: {exc}")
            finally:
                heartbeat.stop()
                delays = [max(0.0, interval - 10.0) for interval in heartbeat_intervals]
                metrics["event_loop_tick_count"] = len(heartbeat_intervals)
                metrics["event_loop_stall_p95_ms"] = rank95(delays)
                metrics["event_loop_stall_max_ms"] = max(delays) if delays else None
                metrics["process_elapsed_ms"] = (perf_counter() - process_started) * 1000
                metrics["working_set_peak_mib"] = max(rss_samples) if rss_samples else None
                metrics["python_heap_peak_mib"] = tracemalloc.get_traced_memory()[1] / 1024 / 1024
                QTimer.singleShot(0, QApplication.instance().quit)

        class TimedWindow(original_window):
            def __init__(self, *args, **kwargs):
                began = perf_counter()
                super().__init__(*args, **kwargs)
                metrics["dashboard_constructor_ms"] = (perf_counter() - began) * 1000
                print("stage2-worker: window constructed", metrics["dashboard_constructor_ms"], flush=True)
                QTimer.singleShot(0, lambda: run_operations(self))

        app_main.PharmacyMainWindow = TimedWindow
        original_exit = sys.exit
        sys.exit = lambda _code=0: None
        try:
            app_main.main()
        finally:
            sys.exit = original_exit
    except Exception as exc:
        metrics["errors"].append(f"worker: {type(exc).__name__}: {exc}")
    finally:
        monitor_stop.set()
        if monitor is not None:
            monitor.join(timeout=1)
        print("STAGE2_PERFJSON " + json.dumps(metrics, default=str), flush=True)
    return 0 if not metrics["errors"] else 1


def parent() -> int:
    from database.connection import get_db_path
    from database import auth

    clone = Path(os.environ["PHARMACY_DB"]).resolve()
    source = Path(os.environ["PHARMACY_TEST_PROTECTED_DB"]).resolve()
    if Path(get_db_path()).resolve() != clone:
        raise RuntimeError("Parent database path does not resolve to the Stage 2 clone")
    if clone == source:
        raise RuntimeError("Refusing to benchmark against the protected source database")
    if not clone.is_file():
        raise RuntimeError(f"Stage 2 clone is missing: {clone}")

    source_hash_before = sha256(source)
    clone_hash_before = sha256(clone)
    auth.ensure_auth_schema()
    admins = [u for u in auth.list_users() if u.get("role") == auth.ROLE_ADMIN and u.get("is_active")]
    if not admins:
        raise RuntimeError("The working clone has no active admin account for benchmark setup")
    username = "stage2_perf_" + uuid.uuid4().hex[:10]
    password = "Stage2-" + uuid.uuid4().hex + "9!"
    auth.create_user(admins[0], username, password, auth.ROLE_ADMIN)

    results: dict[str, list[dict]] = {"cold_process": [], "warm_cache_process": []}
    for phase in results:
        for run_number in range(1, 6):
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["PHARMACY_DB"] = str(clone)
            env["PHARMACY_TEST_PROTECTED_DB"] = str(source)
            env["PHARMACY_TEST_SAFE_DB"] = str(clone)
            env["PHARMACY_REQUIRE_EXISTING_DB"] = "1"
            env["STAGE2_EXPECTED_DB"] = str(clone)
            env["STAGE2_BENCH_USER"] = username
            env["STAGE2_BENCH_PASSWORD"] = password
            env["STAGE2_PHASE"] = phase
            env["STAGE2_RUN"] = str(run_number)
            process = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            records = [
                line.removeprefix("STAGE2_PERFJSON ")
                for line in process.stdout.splitlines()
                if line.startswith("STAGE2_PERFJSON ")
            ]
            if not records:
                raise RuntimeError(
                    f"{phase} run {run_number} emitted no result; "
                    f"exit={process.returncode}; stderr={process.stderr[-2000:]}"
                )
            result = json.loads(records[-1])
            result["return_code"] = process.returncode
            results[phase].append(result)
            print(
                f"{phase} {run_number}/5: "
                f"dashboard={result.get('dashboard_constructor_ms')} ms; "
                f"report={result.get('sales_report_generation_first_ms')} ms; "
                f"errors={len(result.get('errors', []))}",
                flush=True,
            )

    summaries: dict[str, dict] = {}
    numeric_fields = (
        "startup_to_login_visible_ms",
        "authentication_submit_ms",
        "auth_schema_ensure_ms",
        "database_init_ms",
        "financial_year_ensure_ms",
        "login_to_dashboard_first_frame_ms",
        "dashboard_constructor_ms",
        "item_master_first_navigation_ms",
        "item_master_full_refresh_ms",
        "item_master_search_first_ms",
        "item_master_search_repeat_ms",
        "counter_sale_navigation_ms",
        "sales_report_page_navigation_ms",
        "sales_report_generation_first_ms",
        "sales_report_generation_repeat_ms",
        "working_set_peak_mib",
        "python_heap_peak_mib",
        "event_loop_stall_max_ms",
        "event_loop_stall_p95_ms",
    )
    for phase, runs in results.items():
        summaries[phase] = {}
        for field in numeric_fields:
            values = [r.get(field) for r in runs if isinstance(r.get(field), (int, float))]
            if values:
                summaries[phase][field] = {
                    "median": statistics.median(values),
                    "p95": rank95(values),
                    "samples": values,
                }

    source_hash_after = sha256(source)
    result_path = Path(
        os.environ.get(
            "STAGE2_RESULTS_PATH",
            str(Path(__file__).with_name("pharmacy_performance_stage2_20261101.results.json")),
        )
    ).resolve()
    payload = {
        "source_db": str(source),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_unchanged": source_hash_before == source_hash_after,
        "benchmark_clone": str(clone),
        "benchmark_clone_sha256_before_perf": clone_hash_before,
        "benchmark_clone_sha256_after_perf": sha256(clone),
        "phase_definitions": {
            "cold_process": "fresh process; filesystem cache not flushed",
            "warm_cache_process": "fresh process after cold group; OS cache uncontrolled",
        },
        "runs_per_phase": 5,
        "results": results,
        "summaries": summaries,
    }
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("results_path", result_path)
    print("source_unchanged", payload["source_unchanged"])
    if not payload["source_unchanged"]:
        raise RuntimeError("Protected source database hash changed")
    if any(r.get("errors") or r.get("return_code") != 0 for runs in results.values() for r in runs):
        return 1
    return 0


if __name__ == "__main__":
    if "--worker" in sys.argv:
        raise SystemExit(worker())
    raise SystemExit(parent())

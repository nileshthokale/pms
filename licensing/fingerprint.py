"""Device fingerprint collection for licensing and admin visibility."""
from __future__ import annotations
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Any

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import ctypes
    WINDOWS = (sys.platform == "win32")
    if WINDOWS:
        import winreg
    else:
        winreg = None
except ImportError:
    WINDOWS = False
    winreg = None

CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

_STARTUP_PERF = time.perf_counter()
_STARTUP_TIME = time.time()
_last_wall_time = time.time()

_cached_security: dict[str, Any] | None = None
_cached_os: dict[str, Any] | None = None
_cached_hardware: dict[str, Any] | None = None
_cached_pos: dict[str, Any] | None = None
_cached_bios_serial: str | None = None
_cached_vm: dict[str, Any] | None = None
_cached_screen: dict[str, Any] | None = None

# POS & Peripheral Keyword Signatures
POS_PRINTER_KEYWORDS = (
    "pos", "thermal", "receipt", "tm-", "tsp", "star", "epson tm", "tvs",
    "rp-", "rp3", "ngx", "everycom", "bixolon", "xprinter", "pos-58",
    "pos-80", "58mm", "80mm", "citizen", "zebra", "tsc", "gprinter",
    "hprt", "rongta", "sewoo", "snbc", "zywell", "munbyn", "direct thermal",
    "receipt printer", "label"
)

SCANNER_KEYWORDS = (
    "barcode", "scanner", "symbol", "zebra", "honeywell", "datalogic",
    "newland", "opticon", "inateck", "netum", "eyoyo", "tera", "pos scanner"
)

# Hypervisor Signatures for Anti-Piracy / VM Detection
VM_BIOS_SIGNATURES: dict[str, tuple[str, ...]] = {
    "VirtualBox": ("vbox", "virtualbox", "innotek"),
    "VMware": ("vmware", "vmw"),
    "Hyper-V": ("hyper-v", "virtual machine"),
    "QEMU": ("qemu", "bochs", "kvm", "red hat", "standard pc"),
    "Parallels": ("parallels",),
    "Xen": ("xen",),
}

VM_MAC_OUIS: dict[str, str] = {
    "00:05:69": "VMware",
    "00:0c:29": "VMware",
    "00:50:56": "VMware",
    "00:1c:14": "VMware",
    "08:00:27": "VirtualBox",
    "00:15:5d": "Hyper-V",
    "52:54:00": "QEMU",
    "00:1c:42": "Parallels",
    "00:16:3e": "Xen",
}


def collect_device_fingerprint(app_version: str) -> dict[str, Any]:
    """
    Collect legitimate device metadata for licensing admin visibility.
    Includes the 5 key telemetry categories for the Pharmacy Management System:
      1. Hardware & POS Peripherals (receipt printers, barcode scanners, screen, BIOS)
      2. Anti-Piracy & Integrity (VM detection, clock rollback, concurrent instances)
      3. Database Health (read-only pharmacy.db size, low disk flag)
      4. Technical Diagnostics (RAM usage, uptime, startup speed, pending reboot)
      5. Business & Store Activity (read-only count of invoices today, earliest/latest times)
    """
    net_info = _collect_network_info()
    fp = {
        "os": _collect_os_info(),
        "hardware": _collect_hardware_info(),
        "network": net_info,
        "runtime": _collect_runtime_info(app_version),
        "security": _collect_security_posture(),
        "session": _collect_session_info(),
        # 5 Enhanced Telemetry Categories
        "pos_peripherals": _collect_pos_peripherals(),
        "integrity": _collect_integrity_info(net_info.get("mac_addresses")),
        "database": _collect_database_health(),
        "diagnostics": _collect_diagnostics_info(),
        "store_activity": _collect_store_activity(),
    }
    return fp


# ─────────────────────────────────────────────────────────────────────────────
# 1. Hardware & POS Peripherals
# ─────────────────────────────────────────────────────────────────────────────

def _get_screen_info() -> dict[str, Any]:
    """Detect screen resolution and DPI scaling factor."""
    global _cached_screen
    if _cached_screen is not None:
        return _cached_screen.copy()

    screen = {
        "width": None,
        "height": None,
        "resolution": "Unknown",
        "dpi": 96,
        "dpi_scaling_percent": 100,
    }

    if WINDOWS:
        try:
            user32 = ctypes.windll.user32
            # Attempt to set process per-monitor DPI awareness for accurate resolution
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    user32.SetProcessDPIAware()
                except Exception:
                    pass

            w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            if w and h:
                screen["width"] = int(w)
                screen["height"] = int(h)
                screen["resolution"] = f"{w}x{h}"

            dpi = 96
            try:
                get_dpi_fn = getattr(user32, "GetDpiForSystem", None)
                if get_dpi_fn:
                    dpi = get_dpi_fn()
                else:
                    hdc = user32.GetDC(0)
                    if hdc:
                        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                        user32.ReleaseDC(0, hdc)
            except Exception:
                dpi = 96

            screen["dpi"] = dpi or 96
            screen["dpi_scaling_percent"] = round((screen["dpi"] / 96.0) * 100)
        except Exception:
            pass

    _cached_screen = screen
    return screen.copy()


def _get_bios_serial() -> str | None:
    """Query system BIOS serial number for anti-cloning protection."""
    global _cached_bios_serial
    if _cached_bios_serial is not None:
        return _cached_bios_serial

    serial = None
    if WINDOWS:
        # Method 1: PowerShell CIM instance query (zero window, non-interactive)
        try:
            cmd = [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_Bios).SerialNumber"
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=CREATE_NO_WINDOW
            )
            out = res.stdout.strip()
            if out and out.lower() not in ("to be filled by o.e.m.", "default string", "none", "system serial number", "0", ""):
                serial = out
        except Exception:
            pass

        # Method 2: Registry fallback
        if not serial and winreg is not None:
            for subkey in (r"HARDWARE\DESCRIPTION\System\BIOS", r"SYSTEM\CurrentControlSet\Control\SystemInformation"):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as k:
                        for val_name in ("SystemSerialNumber", "BaseBoardSerialNumber", "BIOSSerialNumber"):
                            try:
                                val, _ = winreg.QueryValueEx(k, val_name)
                                val_str = str(val).strip()
                                if val_str and val_str.lower() not in ("to be filled by o.e.m.", "default string", "none", ""):
                                    serial = val_str
                                    break
                            except Exception:
                                pass
                        if serial:
                            break
                except Exception:
                    pass

        # Method 3: WMIC fallback
        if not serial:
            try:
                res = subprocess.run(
                    ["wmic", "bios", "get", "serialnumber"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    creationflags=CREATE_NO_WINDOW
                )
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and "serialnumber" not in l.lower()]
                if lines and lines[0].lower() not in ("to be filled by o.e.m.", "default string", "none", ""):
                    serial = lines[0]
            except Exception:
                pass

    _cached_bios_serial = serial or "Unknown"
    return _cached_bios_serial


def _detect_barcode_scanners() -> list[dict[str, str]]:
    """Scan USB and HID device trees for connected POS barcode scanners."""
    scanners = []
    if not WINDOWS or winreg is None:
        return scanners

    for root_path in (r"SYSTEM\CurrentControlSet\Enum\USB", r"SYSTEM\CurrentControlSet\Enum\HID"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path) as k:
                sub_count = winreg.QueryInfoKey(k)[0]
                for i in range(sub_count):
                    try:
                        sub = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, sub) as sk:
                            dev_count = winreg.QueryInfoKey(sk)[0]
                            for j in range(dev_count):
                                dev = winreg.EnumKey(sk, j)
                                with winreg.OpenKey(sk, dev) as dk:
                                    desc = ""
                                    friendly = ""
                                    try:
                                        desc, _ = winreg.QueryValueEx(dk, "DeviceDesc")
                                        if ";" in str(desc):
                                            desc = desc.split(";")[-1]
                                    except Exception:
                                        pass
                                    try:
                                        friendly, _ = winreg.QueryValueEx(dk, "FriendlyName")
                                    except Exception:
                                        pass
                                    text = f"{desc} {friendly}".lower()
                                    if any(kw in text for kw in SCANNER_KEYWORDS):
                                        name = friendly or desc or sub
                                        scanners.append({
                                            "name": str(name).strip(),
                                            "device_id": f"{sub}/{dev}",
                                        })
                    except Exception:
                        pass
        except Exception:
            pass
    return scanners


def _collect_pos_peripherals() -> dict[str, Any]:
    """Connected receipt/thermal printers, barcode scanners, screen and BIOS."""
    global _cached_pos
    if _cached_pos is not None:
        return _cached_pos.copy()

    printers: list[dict[str, Any]] = []
    thermal_printers: list[str] = []
    default_printer: str | None = None

    if WINDOWS:
        # Query printers via Windows Get-CimInstance Win32_Printer
        try:
            cmd = [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Printer | Select-Object Name, Default, PortName, DriverName, PrinterStatus | ConvertTo-Json"
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.5,
                creationflags=CREATE_NO_WINDOW
            )
            if res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list):
                    for item in data:
                        name = str(item.get("Name") or "")
                        driver = str(item.get("DriverName") or "")
                        port = str(item.get("PortName") or "")
                        is_def = bool(item.get("Default"))
                        if is_def:
                            default_printer = name

                        combined = f"{name} {driver} {port}".lower()
                        is_pos = any(kw in combined for kw in POS_PRINTER_KEYWORDS)
                        if is_pos:
                            thermal_printers.append(name)

                        printers.append({
                            "name": name,
                            "is_default": is_def,
                            "port": port,
                            "driver": driver,
                            "is_pos_printer": is_pos,
                        })
        except Exception:
            pass

        # Registry fallback for printers if powershell was unavailable or timed out
        if not printers and winreg is not None:
            try:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Windows") as k:
                        dev_val, _ = winreg.QueryValueEx(k, "Device")
                        default_printer = dev_val.split(",")[0]
                except Exception:
                    pass

                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Print\Printers") as k:
                    count = winreg.QueryInfoKey(k)[0]
                    for i in range(count):
                        name = winreg.EnumKey(k, i)
                        is_def = (name == default_printer)
                        driver = ""
                        port = ""
                        try:
                            with winreg.OpenKey(k, name) as sk:
                                driver, _ = winreg.QueryValueEx(sk, "Printer Driver")
                                port, _ = winreg.QueryValueEx(sk, "Port")
                        except Exception:
                            pass
                        combined = f"{name} {driver} {port}".lower()
                        is_pos = any(kw in combined for kw in POS_PRINTER_KEYWORDS)
                        if is_pos:
                            thermal_printers.append(name)
                        printers.append({
                            "name": name,
                            "is_default": is_def,
                            "port": str(port),
                            "driver": str(driver),
                            "is_pos_printer": is_pos,
                        })
            except Exception:
                pass

    scanners = _detect_barcode_scanners()
    screen_info = _get_screen_info()
    bios_serial = _get_bios_serial()

    info = {
        "printers": printers,
        "thermal_receipt_printers": thermal_printers,
        "has_receipt_printer": len(thermal_printers) > 0,
        "default_printer": default_printer,
        "barcode_scanners": scanners,
        "has_barcode_scanner": len(scanners) > 0,
        "screen": screen_info,
        "bios_serial": bios_serial,
    }
    _cached_pos = info
    return info.copy()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Anti-Piracy & Integrity
# ─────────────────────────────────────────────────────────────────────────────

def _detect_vm(mac_addrs: list[Any] | None = None) -> dict[str, Any]:
    """Detect virtual machine execution (VirtualBox, VMware, Hyper-V, QEMU via BIOS, Disk, MAC)."""
    indicators: list[str] = []
    hypervisor: str | None = None

    if WINDOWS:
        # 1. BIOS inspection
        if winreg is not None:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
                    for val_name in ("SystemManufacturer", "SystemProductName", "BIOSVersion", "BaseBoardManufacturer"):
                        try:
                            data, _ = winreg.QueryValueEx(k, val_name)
                            data_str = str(data).lower()
                            for hv, sigs in VM_BIOS_SIGNATURES.items():
                                if any(s in data_str for s in sigs):
                                    indicators.append(f"BIOS {val_name}: {data}")
                                    if not hypervisor:
                                        hypervisor = hv
                        except Exception:
                            pass
            except Exception:
                pass

        # 2. Disk model inspection
        if winreg is not None:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\disk\Enum") as k:
                    count, _ = winreg.QueryValueEx(k, "Count")
                    for i in range(count):
                        disk_id, _ = winreg.QueryValueEx(k, str(i))
                        disk_str = str(disk_id).lower()
                        for hv, sigs in VM_BIOS_SIGNATURES.items():
                            if any(s in disk_str for s in sigs):
                                indicators.append(f"Virtual Disk: {disk_id}")
                                if not hypervisor:
                                    hypervisor = hv
            except Exception:
                pass

        # 3. Known VM driver / filesystem traces
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        vm_driver_checks = [
            (os.path.join(sys_root, r"System32\drivers\VBoxMouse.sys"), "VirtualBox", "Driver VBoxMouse.sys"),
            (os.path.join(sys_root, r"System32\drivers\VBoxGuest.sys"), "VirtualBox", "Driver VBoxGuest.sys"),
            (os.path.join(sys_root, r"System32\drivers\vmmouse.sys"), "VMware", "Driver vmmouse.sys"),
            (os.path.join(sys_root, r"System32\drivers\vm3dmp.sys"), "VMware", "Driver vm3dmp.sys"),
        ]
        for path, hv, label in vm_driver_checks:
            if os.path.exists(path):
                indicators.append(label)
                if not hypervisor:
                    hypervisor = hv

    # 4. MAC address OUI inspection
    mac_list: list[str] = []
    if mac_addrs:
        for m in mac_addrs:
            if isinstance(m, dict):
                mac_list.append(str(m.get("mac", "")))
            elif isinstance(m, str):
                mac_list.append(m)

    if not mac_list:
        try:
            node_mac = f"{uuid.getnode():012x}"
            mac_list.append(":".join(node_mac[i:i+2] for i in range(0, 12, 2)))
        except Exception:
            pass

    for raw_mac in mac_list:
        clean = raw_mac.lower().replace("-", ":")
        if len(clean) == 12 and ":" not in clean:
            clean = ":".join(clean[i:i+2] for i in range(0, 12, 2))
        for oui, hv in VM_MAC_OUIS.items():
            if clean.startswith(oui):
                indicators.append(f"MAC OUI ({raw_mac}): {hv}")
                if not hypervisor:
                    hypervisor = hv

    return {
        "is_vm": len(indicators) > 0,
        "hypervisor": hypervisor,
        "indicators": indicators,
    }


def _count_app_instances() -> int:
    """Count concurrent running instances of the pharmacy application."""
    instances = 0
    if PSUTIL_AVAILABLE:
        try:
            for p in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = (p.info.get("name") or "").lower()
                    cmd = p.info.get("cmdline") or []
                    is_match = False
                    if getattr(sys, "frozen", False):
                        exe_name = os.path.basename(sys.executable).lower()
                        if name == exe_name:
                            is_match = True
                    else:
                        if any("main.py" in str(arg).lower() for arg in cmd):
                            is_match = True
                    if is_match:
                        instances += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    return max(1, instances)


def _collect_integrity_info(mac_addrs: list[Any] | None = None) -> dict[str, Any]:
    """Anti-Piracy & Integrity posture checks."""
    global _cached_vm, _last_wall_time

    if _cached_vm is None:
        _cached_vm = _detect_vm(mac_addrs)

    clock_rollback = False
    delta_seconds = 0.0
    now = time.time()

    # Clock rollback detection: wall time moved backwards since last recorded step
    if now < _last_wall_time - 5.0:
        clock_rollback = True
        delta_seconds = round(_last_wall_time - now, 1)

    # Check database file modification time vs current time
    db_path = _find_database_path()
    if db_path and os.path.exists(db_path):
        try:
            mtime = os.path.getmtime(db_path)
            if mtime > now + 60.0:
                clock_rollback = True
                delta_seconds = max(delta_seconds, round(mtime - now, 1))
        except Exception:
            pass

    # Check anchor release timestamp (Jan 1, 2025 = 1735689600)
    if now < 1735689600:
        clock_rollback = True
        delta_seconds = max(delta_seconds, round(1735689600 - now, 1))

    _last_wall_time = max(_last_wall_time, now)
    instances = _count_app_instances()

    return {
        "is_vm": _cached_vm["is_vm"],
        "vm_hypervisor": _cached_vm["hypervisor"],
        "vm_indicators": _cached_vm["indicators"],
        "clock_rollback_detected": clock_rollback,
        "clock_delta_seconds": delta_seconds,
        "concurrent_instances": instances,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Database Health
# ─────────────────────────────────────────────────────────────────────────────

def _find_database_path() -> str | None:
    """Safely resolve the pharmacy.db file location without mutating state."""
    env_db = os.environ.get("PHARMACY_DB") or os.environ.get("PHARMACY_DB_PATH")
    if env_db and os.path.exists(env_db):
        return os.path.abspath(env_db)

    candidates = [
        os.path.join("data", "pharmacy.db"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pharmacy.db"),
        os.path.join(os.getcwd(), "data", "pharmacy.db"),
    ]
    app_data = os.environ.get("LOCALAPPDATA")
    if app_data:
        candidates.append(os.path.join(app_data, "PharmacyManagementSystem", "pharmacy.db"))

    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)

    return None


def _collect_database_health() -> dict[str, Any]:
    """Database file size (read-only) and low disk space warning (< 2 GB)."""
    db_path = _find_database_path()
    info = {
        "db_found": False,
        "db_path": None,
        "db_size_mb": None,
        "disk_free_gb": None,
        "low_disk_warning": False,
    }

    drive = os.environ.get("SystemDrive", "C:")
    if db_path and os.path.exists(db_path):
        info["db_found"] = True
        info["db_path"] = db_path
        try:
            size_bytes = os.path.getsize(db_path)
            info["db_size_mb"] = round(size_bytes / (1024 * 1024), 2)
            drive = os.path.splitdrive(db_path)[0] or drive
        except Exception:
            pass

    try:
        root_dir = drive + os.sep if not drive.endswith(os.sep) else drive
        usage = shutil.disk_usage(root_dir)
        free_bytes = usage.free
        info["disk_free_gb"] = round(free_bytes / (1024**3), 2)
        info["low_disk_warning"] = free_bytes < (2 * 1024 * 1024 * 1024)
    except Exception:
        pass

    return info


# ─────────────────────────────────────────────────────────────────────────────
# 4. Technical Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def _check_pending_reboot() -> tuple[bool, list[str]]:
    """Check Windows pending reboot flags via registry."""
    reasons: list[str] = []
    if not WINDOWS or winreg is None:
        return False, reasons

    # 1. Component Based Servicing
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"):
            reasons.append("Component Based Servicing (CBS)")
    except Exception:
        pass

    # 2. Windows Update
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"):
            reasons.append("Windows Update (RebootRequired)")
    except Exception:
        pass

    # 3. PendingFileRenameOperations in Session Manager
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager") as k:
            val, _ = winreg.QueryValueEx(k, "PendingFileRenameOperations")
            if val:
                reasons.append("PendingFileRenameOperations")
    except Exception:
        pass

    # 4. Pending ComputerName rename
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName") as k1:
            active_name, _ = winreg.QueryValueEx(k1, "ComputerName")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\ComputerName\ComputerName") as k2:
            pending_name, _ = winreg.QueryValueEx(k2, "ComputerName")
        if active_name != pending_name:
            reasons.append("ComputerName change pending")
    except Exception:
        pass

    return len(reasons) > 0, reasons


def _collect_diagnostics_info() -> dict[str, Any]:
    """Technical diagnostics: Process RAM, uptime, startup speed, pending reboot."""
    global _STARTUP_PERF, _STARTUP_TIME

    # Process RAM in MB
    ram_mb: float | None = None
    if PSUTIL_AVAILABLE:
        try:
            proc = psutil.Process(os.getpid())
            ram_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass

    if ram_mb is None and WINDOWS:
        try:
            from ctypes import wintypes
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            h = ctypes.windll.kernel32.GetCurrentProcess()
            if fn(h, ctypes.byref(counters), counters.cb):
                ram_mb = round(counters.WorkingSetSize / (1024 * 1024), 1)
        except Exception:
            pass

    # Process Uptime
    uptime_sec: int | None = None
    if PSUTIL_AVAILABLE:
        try:
            create_time = psutil.Process(os.getpid()).create_time()
            uptime_sec = max(0, int(time.time() - create_time))
        except Exception:
            pass

    if uptime_sec is None and WINDOWS:
        try:
            from ctypes import wintypes
            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]
            c_t, e_t, k_t, u_t = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            fn = ctypes.windll.kernel32.GetProcessTimes
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
            fn.restype = wintypes.BOOL
            h = ctypes.windll.kernel32.GetCurrentProcess()
            if fn(h, ctypes.byref(c_t), ctypes.byref(e_t), ctypes.byref(k_t), ctypes.byref(u_t)):
                c_val = (c_t.dwHighDateTime << 32) + c_t.dwLowDateTime
                unix_c = (c_val - 116444736000000000) / 10000000
                uptime_sec = max(0, int(time.time() - unix_c))
        except Exception:
            pass

    if uptime_sec is None:
        uptime_sec = max(0, int(time.time() - _STARTUP_TIME))

    if uptime_sec < 60:
        uptime_fmt = f"{uptime_sec}s"
    elif uptime_sec < 3600:
        uptime_fmt = f"{uptime_sec // 60}m {uptime_sec % 60}s"
    else:
        hours = uptime_sec // 3600
        mins = (uptime_sec % 3600) // 60
        uptime_fmt = f"{hours}h {mins}m"

    startup_sec = round(max(0.001, time.perf_counter() - _STARTUP_PERF), 3)
    pending_reboot, reboot_reasons = _check_pending_reboot()

    return {
        "process_ram_mb": ram_mb if ram_mb is not None else 0.0,
        "process_uptime_seconds": uptime_sec,
        "process_uptime_formatted": uptime_fmt,
        "startup_seconds": startup_sec,
        "pending_reboot": pending_reboot,
        "pending_reboot_reasons": reboot_reasons,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Business & Store Activity
# ─────────────────────────────────────────────────────────────────────────────

def _collect_store_activity() -> dict[str, Any]:
    """Safe read-only query of count of invoices today and earliest/latest times."""
    info: dict[str, Any] = {
        "status": "unavailable",
        "invoices_today": 0,
        "earliest_invoice_today": None,
        "latest_invoice_today": None,
        "active_store_hours": None,
        "last_invoice_date": None,
        "last_invoice_time": None,
        "total_invoices_all_time": None,
    }

    db_path = _find_database_path()
    if not db_path or not os.path.exists(db_path):
        return info

    import sqlite3
    conn = None
    try:
        # STRICT read-only connection: uri=True with mode=ro.
        # SQLite will never create journal/wal files or acquire write locks.
        uri = f"file:{os.path.abspath(db_path)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.5)
        cur = conn.cursor()

        # Check if sales_invoices table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales_invoices'")
        if not cur.fetchone():
            return info

        info["status"] = "available"
        today_str = datetime.now().strftime("%Y-%m-%d")

        cur.execute("SELECT sale_time FROM sales_invoices WHERE sale_date = ?", (today_str,))
        times = [r[0] for r in cur.fetchall() if r[0]]
        info["invoices_today"] = len(times)

        if times:
            def _parse_time(t_str: str):
                for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M", "%I:%M:%S %p"):
                    try:
                        return datetime.strptime(t_str.strip(), fmt).time()
                    except ValueError:
                        pass
                return None

            parsed = [(_parse_time(t), t) for t in times if _parse_time(t)]
            if parsed:
                parsed.sort(key=lambda x: x[0])
                info["earliest_invoice_today"] = parsed[0][1]
                info["latest_invoice_today"] = parsed[-1][1]
                info["active_store_hours"] = f"{parsed[0][1]} - {parsed[-1][1]}"

        # Last invoice overall in DB for store activity context
        cur.execute("SELECT sale_date, sale_time FROM sales_invoices ORDER BY id DESC LIMIT 1")
        last_row = cur.fetchone()
        if last_row:
            info["last_invoice_date"] = last_row[0]
            info["last_invoice_time"] = last_row[1]

        # Total count
        cur.execute("SELECT COUNT(*) FROM sales_invoices")
        tot = cur.fetchone()
        if tot:
            info["total_invoices_all_time"] = tot[0]

    except Exception:
        # Failsafe: on any read error, return safe default without failing the fingerprint
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return info


# ─────────────────────────────────────────────────────────────────────────────
# Existing Base Collection Functions (Preserved for backwards compatibility)
# ─────────────────────────────────────────────────────────────────────────────

def _collect_os_info() -> dict[str, Any]:
    """Operating system details."""
    global _cached_os
    if _cached_os is not None:
        return _cached_os.copy()
    info = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version.split()[0],
    }
    if WINDOWS and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
                build_num = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
                info["build_number"] = build_num
                info["display_version"] = winreg.QueryValueEx(key, "DisplayVersion")[0] if _has_value(key, "DisplayVersion") else None
                prod_name = winreg.QueryValueEx(key, "ProductName")[0]
                # Windows 11 registry retains 'Windows 10' in ProductName for legacy compatibility.
                # Windows 11 official builds start at 22000+.
                try:
                    if int(build_num) >= 22000 and "Windows 10" in prod_name:
                        prod_name = prod_name.replace("Windows 10", "Windows 11")
                except (ValueError, TypeError):
                    pass
                info["product_name"] = prod_name
        except Exception:
            pass
    _cached_os = info
    return info.copy()


def _has_value(key, name: str) -> bool:
    try:
        winreg.QueryValueEx(key, name)
        return True
    except Exception:
        return False


def _collect_hardware_info() -> dict[str, Any]:
    """Hardware specifications with multi-tier fallbacks."""
    global _cached_hardware
    if _cached_hardware is not None:
        return _cached_hardware.copy()
    info = {
        "cpu": {
            "physical_cores": None,
            "logical_cores": None,
            "frequency_mhz": None,
        },
        "memory": {
            "total_gb": None,
            "available_gb": None,
        },
        "disk": {
            "total_gb": None,
            "free_gb": None,
        },
        "machine_id": _get_stable_machine_id(),
        "bios_serial": _get_bios_serial(),
        "screen": _get_screen_info(),
    }

    if PSUTIL_AVAILABLE:
        try:
            info["cpu"]["physical_cores"] = psutil.cpu_count(logical=False)
            info["cpu"]["logical_cores"] = psutil.cpu_count(logical=True)
            freq = psutil.cpu_freq()
            if freq:
                info["cpu"]["frequency_mhz"] = round(freq.current, 1)

            mem = psutil.virtual_memory()
            info["memory"]["total_gb"] = round(mem.total / (1024**3), 1)
            info["memory"]["available_gb"] = round(mem.available / (1024**3), 1)

            disk = psutil.disk_usage(os.sep)
            info["disk"]["total_gb"] = round(disk.total / (1024**3), 1)
            info["disk"]["free_gb"] = round(disk.free / (1024**3), 1)
        except Exception:
            pass

    # Standard library / Win32 fallbacks if psutil missing or partially null
    if info["cpu"]["logical_cores"] is None:
        try:
            info["cpu"]["logical_cores"] = os.cpu_count()
        except Exception:
            pass

    if info["disk"]["total_gb"] is None:
        try:
            root_drive = os.environ.get("SystemDrive", "C:") + os.sep
            usage = shutil.disk_usage(root_drive)
            info["disk"]["total_gb"] = round(usage.total / (1024**3), 1)
            info["disk"]["free_gb"] = round(usage.free / (1024**3), 1)
        except Exception:
            pass

    if info["memory"]["total_gb"] is None and WINDOWS:
        try:
            from ctypes import wintypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                info["memory"]["total_gb"] = round(stat.ullTotalPhys / (1024**3), 1)
                info["memory"]["available_gb"] = round(stat.ullAvailPhys / (1024**3), 1)
        except Exception:
            pass

    _cached_hardware = info
    return info.copy()


def _get_stable_machine_id() -> str | None:
    """Get a stable hardware identifier (Windows MachineGuid or MAC-based)."""
    if WINDOWS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                return winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            pass
    # Fallback: MAC address based
    try:
        return f"mac-{uuid.getnode():012x}"
    except Exception:
        return None


def _detect_outbound_ip() -> str | None:
    """Detect active outbound IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
            return ip
    except Exception:
        pass
    return None


def _collect_network_info() -> dict[str, Any]:
    """Network interfaces and addresses (filtering out dormant/APIPA/virtual loopbacks)."""
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interfaces": [],
        "primary_ipv4": _detect_outbound_ip(),
        "mac_addresses": [],
    }

    if PSUTIL_AVAILABLE:
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                iface_info: dict[str, Any] = {"name": iface, "addresses": []}
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        if not addr.address.startswith("127.") and not addr.address.startswith("169.254."):
                            iface_info["addresses"].append({"type": "IPv4", "address": addr.address, "netmask": addr.netmask})
                            if info["primary_ipv4"] is None:
                                info["primary_ipv4"] = addr.address
                    elif addr.family == socket.AF_INET6:
                        if not addr.address.lower().startswith("fe80:") and addr.address != "::1":
                            iface_info["addresses"].append({"type": "IPv6", "address": addr.address})
                    elif hasattr(socket, "AF_LINK") and addr.family == socket.AF_LINK:
                        if iface_info["addresses"]:
                            info["mac_addresses"].append({"interface": iface, "mac": addr.address})
                            iface_info["addresses"].append({"type": "MAC", "address": addr.address})
                if iface_info["addresses"]:
                    info["interfaces"].append(iface_info)
        except Exception:
            pass

    if not info["interfaces"]:
        try:
            host = socket.gethostname()
            _, _, ips = socket.gethostbyname_ex(host)
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    info["interfaces"].append({"name": "Active Network", "addresses": [{"type": "IPv4", "address": ip}]})
                    if info["primary_ipv4"] is None:
                        info["primary_ipv4"] = ip
        except Exception:
            pass

    return info


def _collect_runtime_info(app_version: str) -> dict[str, Any]:
    """Application runtime context."""
    return {
        "app_version": app_version,
        "process_id": os.getpid(),
        "command_line": sys.argv,
        "working_directory": os.getcwd(),
        "executable": sys.executable,
        "frozen": getattr(sys, "frozen", False),
        "timezone": time.tzname[0] if time.tzname else "UTC",
        "utc_offset_seconds": -time.timezone if hasattr(time, "timezone") else 0,
        "locale": _get_locale(),
    }


def _get_locale() -> dict[str, str]:
    import locale
    try:
        return {
            "language": locale.getlocale(locale.LC_MESSAGES)[0] or "unknown",
            "encoding": locale.getlocale(locale.LC_MESSAGES)[1] or "unknown",
        }
    except Exception:
        return {"language": "unknown", "encoding": "unknown"}


def _collect_security_posture() -> dict[str, Any]:
    """Security-relevant system state (read-only, no elevated privileges)."""
    global _cached_security
    if _cached_security is not None:
        return _cached_security.copy()

    info = {
        "is_admin": False,
        "antivirus": None,
        "firewall_enabled": None,
        "disk_encryption": None,
        "auto_lock_enabled": None,
        "screen_saver_timeout_sec": None,
    }

    if WINDOWS:
        try:
            info["is_admin"] = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            pass

        # Antivirus via WMI (requires wbem, may fail without perms)
        try:
            import wmi
            c = wmi.WMI(namespace="root\\SecurityCenter2")
            av_products = c.AntiVirusProduct()
            if av_products:
                info["antivirus"] = [{"name": p.displayName, "enabled": p.productState & 0x10 != 0} for p in av_products]
        except Exception:
            pass

        # Antivirus fallback via PowerShell CIM instance if WMI module not installed
        if not info["antivirus"]:
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", 
                     "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object -Property displayName, productState | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=2.5,
                    creationflags=CREATE_NO_WINDOW
                )
                if res.stdout.strip():
                    data = json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    if isinstance(data, list):
                        info["antivirus"] = [{"name": item.get("displayName", "Antivirus"), "enabled": True} for item in data]
            except Exception:
                pass

        # Firewall
        try:
            result = subprocess.run(
                ["netsh", "advfirewall", "show", "allprofiles", "state"],
                capture_output=True, text=True, timeout=2,
                creationflags=CREATE_NO_WINDOW
            )
            info["firewall_enabled"] = "ON" in result.stdout
        except Exception:
            pass

        # BitLocker: only attempt if admin (manage-bde hangs without elevation)
        if info["is_admin"]:
            try:
                result = subprocess.run(
                    ["manage-bde", "-status", "C:"],
                    capture_output=True, text=True, timeout=1.5,
                    creationflags=CREATE_NO_WINDOW
                )
                info["disk_encryption"] = "BitLocker" if "Protection On" in result.stdout else "Not Encrypted"
            except Exception:
                info["disk_encryption"] = "Unavailable"
        else:
            info["disk_encryption"] = "Standard User"

        # Auto-lock / screensaver
        try:
            if winreg is not None:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
                    active = winreg.QueryValueEx(key, "ScreenSaveActive")[0]
                    timeout = winreg.QueryValueEx(key, "ScreenSaveTimeOut")[0]
                    info["auto_lock_enabled"] = str(active) == "1"
                    info["screen_saver_timeout_sec"] = int(timeout)
        except Exception:
            pass

    _cached_security = info
    return info.copy()


def _collect_session_info() -> dict[str, Any]:
    """User session context."""
    info = {
        "username": "unknown",
        "session_type": "Console",
        "boot_time": None,
        "uptime_seconds": None,
    }

    try:
        info["username"] = os.getlogin()
    except Exception:
        info["username"] = os.environ.get("USERNAME", "unknown")

    if WINDOWS:
        try:
            user32 = ctypes.windll.user32
            sm_remote = user32.GetSystemMetrics(0x1000) != 0
            sm_control = user32.GetSystemMetrics(0x2001) != 0

            env_session = os.environ.get("SESSIONNAME", "")
            is_rdp_env = env_session.upper().startswith("RDP-") or bool(os.environ.get("CLIENTNAME"))

            kernel32 = ctypes.windll.kernel32
            current_session = ctypes.c_ulong()
            kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(current_session))
            console_session = kernel32.WTSGetActiveConsoleSessionId()
            is_detached = (console_session != 0xFFFFFFFF and current_session.value != console_session)

            if sm_remote or sm_control or is_rdp_env or is_detached:
                info["session_type"] = "RDP"
            else:
                info["session_type"] = "Console"
        except Exception:
            env_session = os.environ.get("SESSIONNAME", "")
            if env_session.upper().startswith("RDP-") or os.environ.get("CLIENTNAME"):
                info["session_type"] = "RDP"
            else:
                info["session_type"] = "Console"

    if PSUTIL_AVAILABLE:
        try:
            boot = psutil.boot_time()
            info["boot_time"] = boot
            info["uptime_seconds"] = int(time.time() - boot)
        except Exception:
            pass

    if info["boot_time"] is None and WINDOWS:
        try:
            uptime_ms = ctypes.windll.kernel32.GetTickCount64()
            uptime_sec = int(uptime_ms / 1000)
            info["uptime_seconds"] = uptime_sec
            info["boot_time"] = int(time.time() - uptime_sec)
        except Exception:
            pass

    return info

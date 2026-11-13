"""Device fingerprint collection for licensing and admin visibility."""
from __future__ import annotations
import os
import platform
import socket
import sys
import time
import uuid
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


_cached_security: dict[str, Any] | None = None
_cached_os: dict[str, Any] | None = None
_cached_hardware: dict[str, Any] | None = None


def collect_device_fingerprint(app_version: str) -> dict[str, Any]:
    """
    Collect legitimate device metadata for licensing admin visibility.
    All fields are non-invasive and standard for device management.
    """
    fp = {
        "os": _collect_os_info(),
        "hardware": _collect_hardware_info(),
        "network": _collect_network_info(),
        "runtime": _collect_runtime_info(app_version),
        "security": _collect_security_posture(),
        "session": _collect_session_info(),
    }
    return fp


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
                info["build_number"] = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
                info["display_version"] = winreg.QueryValueEx(key, "DisplayVersion")[0] if _has_value(key, "DisplayVersion") else None
                info["product_name"] = winreg.QueryValueEx(key, "ProductName")[0]
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
            import shutil
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
            import winreg
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
    info = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interfaces": [],
        "primary_ipv4": _detect_outbound_ip(),
        "mac_addresses": [],
    }

    if PSUTIL_AVAILABLE:
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                iface_info = {"name": iface, "addresses": []}
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        # Exclude loopback (127.x.x.x) and unassigned/disconnected APIPA (169.254.x.x)
                        if not addr.address.startswith("127.") and not addr.address.startswith("169.254."):
                            iface_info["addresses"].append({"type": "IPv4", "address": addr.address, "netmask": addr.netmask})
                            if info["primary_ipv4"] is None:
                                info["primary_ipv4"] = addr.address
                    elif addr.family == socket.AF_INET6:
                        # Exclude link-local IPv6 (fe80::) and localhost (::1)
                        if not addr.address.lower().startswith("fe80:") and addr.address != "::1":
                            iface_info["addresses"].append({"type": "IPv6", "address": addr.address})
                    elif hasattr(socket, "AF_LINK") and addr.family == socket.AF_LINK:
                        if iface_info["addresses"]:  # Only record MAC if adapter has valid active addresses
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
                import json as _json
                import subprocess
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", 
                     "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object -Property displayName, productState | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=2.5,
                    creationflags=CREATE_NO_WINDOW
                )
                if res.stdout.strip():
                    data = _json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    if isinstance(data, list):
                        info["antivirus"] = [{"name": item.get("displayName", "Antivirus"), "enabled": True} for item in data]
            except Exception:
                pass

        # Firewall
        try:
            import subprocess
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
                import subprocess
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
            # 0x1000 = SM_REMOTESESSION: Nonzero if the current session is a Remote Desktop / Terminal Services session
            sm_remote = user32.GetSystemMetrics(0x1000) != 0
            # 0x2001 = SM_REMOTECONTROL: Nonzero if remotely controlled
            sm_control = user32.GetSystemMetrics(0x2001) != 0

            # Check environment variables set by Remote Desktop
            env_session = os.environ.get("SESSIONNAME", "")
            is_rdp_env = env_session.upper().startswith("RDP-") or bool(os.environ.get("CLIENTNAME"))

            # Check Session ID vs Active Physical Console Session ID
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
            # Fallback: check environment
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
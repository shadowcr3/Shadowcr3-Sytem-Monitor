import platform
import socket
import time

import sys

import psutil

def _cpu_name() -> str:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as k:
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except Exception:
        return platform.processor() or "Unknown"
    
def _os_name() -> str:
    if sys.platform != "win32":
        return f"{platform.system()} {platform.release()}"
    build = sys.getwindowsversion().build
    name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as k:
            ver = winreg.QueryValueEx(k, "DisplayVersion")[0]  # e.g. 24H2
        return f"{name} {ver} (build {build})"
    except Exception:
        return f"{name} (build {build})"

def static_info() -> dict[str, str]:
    vm = psutil.virtual_memory()
    return {
        "Host": socket.gethostname(),
        "OS": _os_name(),
        "Architecture": platform.machine(),
        "CPU": _cpu_name(),
        "Cores / threads": f"{psutil.cpu_count(logical=False)} / {psutil.cpu_count(logical=True)}",
        "RAM": f"{vm.total / 2**30:.1f} GB",
        "Python": platform.python_version(),
    }

def uptime() -> str:
    s = int(time.time() - psutil.boot_time())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return f"{d}d {h}h {s // 60}m"
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
from dataclasses import dataclass

# ASUS ATK WMI device ids, read-only DSTS calls
_DEVICES = (
    ("CPU fan", 0x00110013),
    ("GPU fan", 0x00110014),
    ("Mid fan", 0x00110031),
)
_MAX_RPM = 12000


@dataclass(frozen=True)
class Fan:
    name: str
    rpm: int


def _script(parent_pid: int) -> str:
    ids = ",".join(f"0x{d:08X}" for _, d in _DEVICES)
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$w = Get-WmiObject -Namespace root\\wmi -Class AsusAtkWmi_WMNB; "
        f"while (Get-Process -Id {parent_pid} -ErrorAction SilentlyContinue) {{ "
        f"$o = foreach ($d in {ids}) {{ [uint32]$w.DSTS($d).device_status }}; "
        "Write-Output ($o -join ' '); "
        "[Console]::Out.Flush(); "
        "Start-Sleep -Seconds 2 }"
    )


def _decode(v: int) -> int | None:
    """DSTS status -> RPM, or None if the device is absent or the value is junk."""
    if v >= 0xFFFF0000 or not (v & 0x10000):
        return None
    rpm = (v & 0xFFFF) * 100
    return rpm if rpm <= _MAX_RPM else None


def _parse(line: str) -> tuple[Fan, ...]:
    try:
        values = [int(x) for x in line.split()]
    except ValueError:
        return ()
    fans = []
    for (name, _), v in zip(_DEVICES, values):
        rpm = _decode(v)
        if rpm is not None:
            fans.append(Fan(name, rpm))
    return tuple(fans)


class FanReader:
    """Reads ASUS fan RPM through one long-lived hidden PowerShell child process.

    latest() -> tuple of Fan (maybe empty), or None if the reader failed or the
    machine has no ASUS ATK WMI interface.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fans: tuple[Fan, ...] | None = ()
        self._proc: subprocess.Popen | None = None
        if sys.platform == "win32":
            atexit.register(self.close)
            threading.Thread(target=self._run, daemon=True).start()
        else:
            self._fans = None

    def _run(self) -> None:
        try:
            self._proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-Command", _script(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in self._proc.stdout:
                with self._lock:
                    self._fans = _parse(line)
        except Exception:
            pass
        with self._lock:
            self._fans = None  # process ended or never started

    def latest(self) -> tuple[Fan, ...] | None:
        with self._lock:
            return self._fans

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

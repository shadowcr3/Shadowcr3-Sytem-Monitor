from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass

URL = "http://localhost:8085/data.json"
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
_CPU_IDS = ("/intelcpu/", "/amdcpu/")
_GPU_IDS = ("/gpu-nvidia/", "/gpu-amd/")
_BATT = ("/battery/",)
_CPU_PREF = ("package", "tctl", "tdie", "average", "max")


@dataclass(frozen=True)
class Sensor:
    hardware: str
    name: str
    value: float


@dataclass(frozen=True)
class Sensors:
    fans: tuple[Sensor, ...]
    temps: tuple[Sensor, ...]
    cpu_temp: float | None
    cpu_power: float | None
    gpu_power: float | None
    battery_pct: float | None
    battery_rate: float | None
    battery_wear: float | None


def _walk(node: dict, path: list[str], out: list) -> None:
    kids = node.get("Children") or []
    if kids:
        for c in kids:
            _walk(c, path + [node.get("Text", "")], out)
        return
    sid, typ = node.get("SensorId"), node.get("Type")
    if not sid or not typ or len(path) < 2:
        return  # hardware node with no sensors, or header row
    m = _NUM.search(node.get("RawValue") or node.get("Value") or "")
    if m:
        out.append((path[-2], sid, typ, node.get("Text", ""), float(m.group().replace(",", "."))))


def _first(rows: list, typ: str, prefixes: tuple[str, ...], name: str) -> float | None:
    for _hw, sid, t, n, v in rows:
        if t == typ and sid.startswith(prefixes) and n == name:
            return v
    return None


def parse(tree: dict) -> Sensors:
    rows: list = []
    _walk(tree, [], rows)
    fans = tuple(Sensor(hw, n, v) for hw, _, t, n, v in rows if t == "Fan")
    temps = tuple(Sensor(hw, n, v) for hw, _, t, n, v in rows if t == "Temperature")
    # "Distance to TjMax" is headroom, not a temperature, and contains "max"
    cpu = [s for (hw, sid, t, n, _), s in zip(rows, (Sensor(r[0], r[3], r[4]) for r in rows))
           if t == "Temperature" and sid.startswith(_CPU_IDS) and "distance" not in n.lower()]
    cpu_temp = None
    for key in _CPU_PREF:
        hit = next((s.value for s in cpu if key in s.name.lower()), None)
        if hit is not None:
            cpu_temp = hit
            break
    if cpu_temp is None and cpu:
        cpu_temp = max(s.value for s in cpu)
    return Sensors(
        fans, temps, cpu_temp,
        _first(rows, "Power", _CPU_IDS, "CPU Package"),
        _first(rows, "Power", _GPU_IDS, "GPU Package"),
        _first(rows, "Level", _BATT, "Charge Level"),
        _first(rows, "Power", _BATT, "Charge/Discharge Rate"),
        _first(rows, "Level", _BATT, "Degradation Level"),
    )

class Poller:
    """Polls LHM on a background thread so a slow HTTP call never freezes the GUI."""

    def __init__(self, interval: float = 2.0) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._data: Sensors | None = None
        # empty ProxyHandler: never route localhost through a system proxy
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                with self._opener.open(URL, timeout=1.5) as r:
                    data = parse(json.load(r))
            except Exception:  # LHM not running / port closed / bad JSON
                data = None
            with self._lock:
                self._data = data
            time.sleep(self._interval)

    def latest(self) -> Sensors | None:
        with self._lock:
            return self._data
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from gpu import GpuInfo, read as read_gpu
from lhm import Poller, Sensors
from fans import Fan, FanReader


@dataclass(frozen=True)
class Snapshot:
    cpu_percent: float
    cpu_cores: int
    cpu_threads: int
    cpu_per_core: tuple[float, ...]
    mem_total: int
    mem_available: int
    mem_percent: float
    swap_percent: float
    disk_total: int
    disk_used: int
    disk_free: int
    disk_percent: float
    disk_read_bps: float
    disk_write_bps: float
    net_up_bps: float
    net_down_bps: float
    gpu: GpuInfo | None
    sensors: Sensors | None
    acpi_fans: tuple[Fan, ...] | None


class Collector:
    def __init__(self, disk_path: str | None = None) -> None:
        self._disk_path = disk_path or Path.home().anchor
        self._cores = psutil.cpu_count(logical=False) or 0
        self._threads = psutil.cpu_count(logical=True) or 0
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        net = psutil.net_io_counters()
        self._last_net = (time.monotonic(), net.bytes_sent, net.bytes_recv)
        io = psutil.disk_io_counters()
        self._last_disk = (time.monotonic(), io.read_bytes, io.write_bytes) if io else None
        self._lhm = Poller()
        self._fans = FanReader()

    def sample(self) -> Snapshot:
        cpu = psutil.cpu_percent(interval=None)
        per_cpu = tuple(psutil.cpu_percent(interval=None, percpu=True))
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory().percent
        du = psutil.disk_usage(self._disk_path)
        up, down = self._net_rates()
        dr, dw = self._disk_rates()
        return Snapshot(
            cpu_percent=cpu,
            cpu_cores=self._cores,
            cpu_threads=self._threads,
            cpu_per_core=per_cpu,
            mem_total=vm.total,
            mem_available=vm.available,
            mem_percent=vm.percent,
            swap_percent=swap,
            disk_total=du.total,
            disk_used=du.used,
            disk_free=du.free,
            disk_percent=du.percent,
            disk_read_bps=dr,
            disk_write_bps=dw,
            net_up_bps=up,
            net_down_bps=down,
            gpu=read_gpu(),
            sensors=self._lhm.latest(),
            acpi_fans=self._fans.latest(),
        )

    def _net_rates(self) -> tuple[float, float]:
        now = time.monotonic()
        net = psutil.net_io_counters()
        t0, sent0, recv0 = self._last_net
        self._last_net = (now, net.bytes_sent, net.bytes_recv)
        dt = now - t0
        if dt <= 0:
            return 0.0, 0.0
        return (
            max(net.bytes_sent - sent0, 0) / dt,
            max(net.bytes_recv - recv0, 0) / dt,
        )

    def _disk_rates(self) -> tuple[float, float]:
        io = psutil.disk_io_counters()
        if io is None or self._last_disk is None:
            return 0.0, 0.0
        now = time.monotonic()
        t0, r0, w0 = self._last_disk
        self._last_disk = (now, io.read_bytes, io.write_bytes)
        dt = now - t0
        if dt <= 0:
            return 0.0, 0.0
        return max(io.read_bytes - r0, 0) / dt, max(io.write_bytes - w0, 0) / dt
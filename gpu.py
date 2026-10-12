from __future__ import annotations

from dataclasses import dataclass

try:
    import pynvml
    pynvml.nvmlInit()
    _h = pynvml.nvmlDeviceGetHandleByIndex(0)
    _name = pynvml.nvmlDeviceGetName(_h)
    if isinstance(_name, bytes):
        _name = _name.decode()
except Exception:
    pynvml = None
    _h = None
    _name = ""


@dataclass(frozen=True)
class GpuInfo:
    name: str
    util: float
    vram_used: int
    vram_total: int
    temp_c: float

def read() -> GpuInfo | None:
    if _h is None:
        return None
    try:
        u = pynvml.nvmlDeviceGetUtilizationRates(_h)
        m = pynvml.nvmlDeviceGetMemoryInfo(_h)
        t = pynvml.nvmlDeviceGetTemperature(_h, pynvml.NVML_TEMPERATURE_GPU)
    except pynvml.NVMLError:
        return None
    return GpuInfo(_name, float(u.gpu), m.used, m.total, float(t))
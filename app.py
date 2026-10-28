import sys

import traceback

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QFontComboBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

import sysinfo

from collector import Collector, Snapshot

APP_NAME = "Shadowcr3 System Monitor"
VERSION = "0.4.0"
REFRESH_MS = 1000
ACCENT = "#2ec5ff"

def build_style(accent: str, font: str) -> str:
    return f"""
QWidget {{ background: transparent; color: #e6e6e6; font-family: "{font}"; font-size: 13px; }}
QWidget#root {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #14111f, stop:1 #2a1a3a); }}
QFrame#panel {{ background: rgba(255,255,255,0.05); border-radius: 14px; }}
QLabel#title {{ font-size: 20px; font-weight: bold; }}
QLabel#detail {{ color: #9aa0a6; }}
QProgressBar {{ background: rgba(255,255,255,0.08); border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
QScrollArea {{ border: none; }}
QPushButton {{ background: rgba(255,255,255,0.08); border: none; border-radius: 8px; padding: 8px 14px; }}
QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
QPushButton#nav {{ text-align: left; padding: 10px 16px; background: transparent; }}
QPushButton#nav:hover {{ background: rgba(255,255,255,0.06); }}
QPushButton#nav:checked {{ background: rgba(255,255,255,0.12); color: {accent}; }}
"""


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class Gauge(QWidget):
    def __init__(self, size: int = 140) -> None:
        super().__init__()
        self.value = 0.0
        self.setFixedSize(size, size)

    def set_value(self, v: float) -> None:
        self.value = max(0.0, min(v, 100.0))
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 10
        rect = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        p.setPen(QPen(QColor(255, 255, 255, 20), w))
        p.drawEllipse(rect)
        pen = QPen(QColor(ACCENT), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, int(-self.value / 100 * 360 * 16))
        p.setPen(QColor("#e6e6e6"))
        f = p.font()
        f.setPointSize(20)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.value:.0f}%")


class BarRow(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.peak = 1024 * 1024  # rate bars scale to the highest value seen (min 1 MB/s)
        self.name = QLabel(label)
        self.val = QLabel("-")
        self.val.setObjectName("detail")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.name)
        top.addStretch()
        top.addWidget(self.val)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addLayout(top)
        lay.addWidget(self.bar)

    def set_pct(self, pct: float, text: str | None = None) -> None:
        self.bar.setValue(int(max(0.0, min(pct, 100.0)) * 10))
        self.val.setText(text if text is not None else f"{pct:.0f}%")

    def set_rate(self, bps: float) -> None:
        self.peak = max(self.peak, bps)
        self.set_pct(bps / self.peak * 100, f"{fmt_bytes(bps)}/s")


class Panel(QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("panel")
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("detail")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 16, 20, 16)
        self.lay.setSpacing(10)
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.sub)


class CpuPanel(Panel):
    def __init__(self) -> None:
        super().__init__("CPU")
        self.gauge = Gauge()
        self.rows: list[BarRow] = []
        inner = QWidget()
        self.rows_lay = QVBoxLayout(inner)
        self.rows_lay.setContentsMargins(0, 0, 10, 0)
        self.rows_lay.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFixedHeight(150)
        h = QHBoxLayout()
        h.addWidget(self.gauge)
        h.addWidget(scroll, 1)
        self.lay.addLayout(h)

    def update_from(self, s: Snapshot) -> None:
        self.sub.setText(f"{s.cpu_cores} cores / {s.cpu_threads} threads")
        if not self.rows:  # thread count is only known at runtime
            for i in range(len(s.cpu_per_core)):
                r = BarRow(f"Thread {i + 1}")
                self.rows.append(r)
                self.rows_lay.addWidget(r)
        self.gauge.set_value(s.cpu_percent)
        for r, v in zip(self.rows, s.cpu_per_core):
            r.set_pct(v)


class RamPanel(Panel):
    def __init__(self) -> None:
        super().__init__("RAM")
        self.gauge = Gauge()
        self.virt = BarRow("Virtual memory")
        self.used = BarRow("In use")
        col = QVBoxLayout()
        col.addWidget(self.virt)
        col.addWidget(self.used)
        col.addStretch()
        h = QHBoxLayout()
        h.addWidget(self.gauge)
        h.addLayout(col, 1)
        self.lay.addLayout(h)

    def update_from(self, s: Snapshot) -> None:
        used = s.mem_total - s.mem_available
        self.sub.setText(f"{fmt_bytes(used)} / {fmt_bytes(s.mem_total)}")
        self.gauge.set_value(s.mem_percent)
        self.virt.set_pct(s.swap_percent)
        self.used.set_pct(s.mem_percent, f"{fmt_bytes(s.mem_available)} free")


class GpuPanel(Panel):
    def __init__(self) -> None:
        super().__init__("GPU", "No NVIDIA GPU detected")
        self.gauge = Gauge()
        self.vram = BarRow("VRAM")
        self.temp = BarRow("Temperature")
        col = QVBoxLayout()
        col.addWidget(self.vram)
        col.addWidget(self.temp)
        col.addStretch()
        h = QHBoxLayout()
        h.addWidget(self.gauge)
        h.addLayout(col, 1)
        self.lay.addLayout(h)

    def update_from(self, s: Snapshot) -> None:
        g = s.gpu
        if g is None:
            return
        self.sub.setText(g.name)
        self.gauge.set_value(g.util)
        self.vram.set_pct(g.vram_used / g.vram_total * 100,
                          f"{fmt_bytes(g.vram_used)} / {fmt_bytes(g.vram_total)}")
        self.temp.set_pct(g.temp_c, f"{g.temp_c:.0f} °C")  # bar = temp out of 100 °C


class RatePanel(Panel):
    def __init__(self, title: str, a: str, b: str) -> None:
        super().__init__(title)
        self.a, self.b = BarRow(a), BarRow(b)
        self.lay.addWidget(self.a)
        self.lay.addWidget(self.b)
        self.lay.addStretch()


class StoragePanel(Panel):
    def __init__(self) -> None:
        super().__init__("Storage")
        self.row = BarRow("Usage")
        self.free = QLabel("-")
        self.free.setObjectName("detail")
        self.lay.addWidget(self.row)
        self.lay.addWidget(self.free)
        self.lay.addStretch()

    def update_from(self, s: Snapshot) -> None:
        self.row.set_pct(s.disk_percent,
                         f"{fmt_bytes(s.disk_used)} / {fmt_bytes(s.disk_total)}")
        self.free.setText(f"{fmt_bytes(s.disk_free)} free")


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cpu, self.ram, self.gpu = CpuPanel(), RamPanel(), GpuPanel()
        self.drives = RatePanel("Drives", "Read speed", "Write speed")
        self.nics = RatePanel("Interfaces", "Download", "Upload")
        self.storage = StoragePanel()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        for i, w in enumerate((self.cpu, self.ram, self.gpu)):
            grid.addWidget(w, 0, i)
        for i, w in enumerate((self.drives, self.nics, self.storage)):
            grid.addWidget(w, 1, i)
        for c in range(3):
            grid.setColumnStretch(c, 1)

    def update_from(self, s: Snapshot) -> None:
        self.cpu.update_from(s)
        self.ram.update_from(s)
        self.gpu.update_from(s)
        self.storage.update_from(s)
        self.drives.a.set_rate(s.disk_read_bps)
        self.drives.b.set_rate(s.disk_write_bps)
        self.nics.a.set_rate(s.net_down_bps)
        self.nics.b.set_rate(s.net_up_bps)


class SysInfoPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        panel = Panel("System information", "Static details plus live uptime")
        self.values: dict[str, QLabel] = {}
        rows = {**sysinfo.static_info(), "GPU": "-", "Uptime": "-"}
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for r, (k, v) in enumerate(rows.items()):
            key = QLabel(k)
            key.setObjectName("detail")
            val = QLabel(v)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.values[k] = val
            grid.addWidget(key, r, 0)
            grid.addWidget(val, r, 1)
        grid.setColumnStretch(1, 1)
        panel.lay.addLayout(grid)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
        lay.addStretch()

    def update_from(self, s: Snapshot) -> None:
        self.values["Uptime"].setText(sysinfo.uptime())
        if s.gpu:
            self.values["GPU"].setText(s.gpu.name)


class SettingsPage(QWidget):
    def __init__(self, cfg: QSettings, on_change) -> None:
        super().__init__()
        self.cfg, self.on_change = cfg, on_change
        panel = Panel("Settings", "Changes apply immediately")

        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(cfg.value("font", "Segoe UI")))
        self.font_box.currentFontChanged.connect(self._font)

        self.interval = QSpinBox()
        self.interval.setRange(250, 10000)
        self.interval.setSingleStep(250)
        self.interval.setSuffix(" ms")
        self.interval.setValue(cfg.value("refresh_ms", 1000, type=int))
        self.interval.valueChanged.connect(self._interval)

        accent = QPushButton("Pick accent colour")
        accent.clicked.connect(self._accent)

        for label, w in (("Font", self.font_box), ("Refresh interval", self.interval),
                         ("Accent", accent)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addStretch()
            row.addWidget(w)
            panel.lay.addLayout(row)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
        lay.addStretch()

    def _font(self, f: QFont) -> None:
        self.cfg.setValue("font", f.family())
        self.on_change()

    def _interval(self, v: int) -> None:
        self.cfg.setValue("refresh_ms", v)
        self.on_change()

    def _accent(self) -> None:
        c = QColorDialog.getColor(QColor(self.cfg.value("accent", ACCENT)), self)
        if c.isValid():
            self.cfg.setValue("accent", c.name())
            self.on_change()

class SensorsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.fans = Panel("Fans", "Waiting for fan data...")
        self.fans.sub.setWordWrap(True)
        self.power = Panel("Power", "Waiting for LibreHardwareMonitor...")
        self.battery = Panel("Battery")
        self.cpu_t = Panel("CPU temperature")
        self.gpu_t = Panel("GPU temperature", "No NVIDIA GPU detected")
        self.peak: dict[str, float] = {}
        self.fan_rows: dict[str, BarRow] = {}
        self.cpu_w, self.gpu_w = BarRow("CPU package"), BarRow("GPU package")
        self.charge, self.wear = BarRow("Charge"), BarRow("Wear")
        self.cpu_row, self.gpu_row = BarRow("Package"), BarRow("Core")
        for panel, rows in (
            (self.power, (self.cpu_w, self.gpu_w)),
            (self.battery, (self.charge, self.wear)),
            (self.cpu_t, (self.cpu_row,)),
            (self.gpu_t, (self.gpu_row,)),
        ):
            for r in rows:
                panel.lay.addWidget(r)
            panel.lay.addStretch()
        self.fans.lay.addStretch()  # fan rows are inserted before this

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        panels = (self.fans, self.power, self.battery, self.cpu_t, self.gpu_t)
        for i, w in enumerate(panels):
            grid.addWidget(w, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(2, 1)

    def _watts(self, row: BarRow, key: str, w: float) -> None:
        peak = self.peak[key] = max(self.peak.get(key, 0.0), w, 10.0)
        row.set_pct(w / peak * 100, f"{w:.1f} W")

    def _fan(self, name: str, rpm: float) -> None:
        row = self.fan_rows.get(name)
        if row is None:
            row = self.fan_rows[name] = BarRow(name)
            self.fans.lay.insertWidget(self.fans.lay.count() - 1, row)
        peak = self.peak[name] = max(self.peak.get(name, 0.0), rpm, 3000.0)
        row.set_pct(rpm / peak * 100, f"{rpm:.0f} RPM")

    def update_from(self, s: Snapshot) -> None:
        sn = s.sensors

        readings = [(f.name, float(f.rpm)) for f in (s.acpi_fans or ())]
        if sn is not None:
            readings += [(f.name, f.value) for f in sn.fans]
        for name, rpm in readings:
            self._fan(name, rpm)
        if readings:
            self.fans.sub.setText("")
        elif s.acpi_fans is None:
            self.fans.sub.setText(
                "No fan data. Needs an ASUS laptop with the ASUS driver "
                "(try running as admin), or LibreHardwareMonitor fan sensors."
            )
        else:
            self.fans.sub.setText("No fan sensors exposed")

        if sn is None:
            msg = "LibreHardwareMonitor not reachable (port 8085)"
            for p in (self.power, self.battery, self.cpu_t):
                p.sub.setText(msg)
        else:
            self.power.sub.setText("")
            if sn.cpu_power is not None:
                self._watts(self.cpu_w, "cpu", sn.cpu_power)
            if sn.gpu_power is not None:
                self._watts(self.gpu_w, "gpu", sn.gpu_power)

            if sn.battery_pct is None:
                self.battery.sub.setText("No battery sensors")
            else:
                self.charge.set_pct(sn.battery_pct)
                if sn.battery_wear is not None:
                    self.wear.set_pct(sn.battery_wear)
                self.battery.sub.setText(
                    f"Rate {sn.battery_rate:+.1f} W" if sn.battery_rate is not None else ""
                )

            if sn.cpu_temp is None:
                self.cpu_t.sub.setText("No CPU temperature exposed")
            else:
                self.cpu_t.sub.setText("")
                self.cpu_row.set_pct(sn.cpu_temp, f"{sn.cpu_temp:.0f} °C")

        if s.gpu:
            self.gpu_t.sub.setText(s.gpu.name)
            self.gpu_row.set_pct(s.gpu.temp_c, f"{s.gpu.temp_c:.0f} °C")


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1250, 700)
        self.cfg = QSettings("Shadowcr3", "SystemMonitor")
        self.collector = Collector()

        self.dashboard = DashboardPage()
        self.sensors = SensorsPage()
        self.sysinfo = SysInfoPage()
        self.settings = SettingsPage(self.cfg, self.apply_settings)
        self.pages = QStackedWidget()

        side = QVBoxLayout()
        side.setSpacing(4)
        group = QButtonGroup(self)
        entries = (
            ("Dashboard", self.dashboard),
            ("Sensors", self.sensors),
            ("System info", self.sysinfo),
            ("Settings", self.settings),
        )
        for i, (name, page) in enumerate(entries):
            self.pages.addWidget(page)
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _, i=i: self.pages.setCurrentIndex(i))
            group.addButton(b)
            side.addWidget(b)
        side.addStretch()
        sidebar = QWidget()
        sidebar.setFixedWidth(170)
        sidebar.setLayout(side)

        self.status = QLabel("")
        self.status.setObjectName("detail")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right = QVBoxLayout()
        right.addWidget(self.pages, 1)
        right.addWidget(self.status)
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 12)
        root.setSpacing(20)
        root.addWidget(sidebar)
        root.addLayout(right, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.apply_settings()
        self.timer.start()
        self.refresh()

    def apply_settings(self) -> None:
        global ACCENT
        ACCENT = self.cfg.value("accent", "#2ec5ff")
        font = self.cfg.value("font", "Segoe UI")
        QApplication.instance().setStyleSheet(build_style(ACCENT, font))
        self.timer.setInterval(self.cfg.value("refresh_ms", 1000, type=int))
        for g in self.findChildren(Gauge):
            g.update()

    def refresh(self) -> None:
        try:
            s = self.collector.sample()
        except Exception as exc:
            traceback.print_exc()
            self.status.setText(f"Read error: {exc}")
            return
        self.status.setText("")
        self.dashboard.update_from(s)
        self.sysinfo.update_from(s)
        self.sensors.update_from(s)

def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
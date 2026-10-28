# Shadowcr3 System Monitor

A Windows desktop system monitor built with Python, PySide6 and psutil.

## Features
- Dashboard: CPU (total and per-thread), RAM, GPU, disk and network rates, storage
- Sensors: CPU temperature, CPU/GPU power, battery charge and wear, GPU temperature
- System info page
- Customisable font, accent colour and refresh interval (saved between runs)

## Run from source
```
pip install -r requirements.txt
python app.py
```

## Optional: CPU temperature, power and battery
These come from [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor):
1. Run it as administrator.
2. Options -> Remote Web Server -> Run (port 8085).

Without it, the app still runs and the Sensors page shows "not reachable".
The web server may listen on all interfaces. Don't allow it through the firewall on untrusted networks.

## Limitations
- GPU stats are NVIDIA-only (NVML), first GPU only
- Disk panel covers only the drive with your user profile
- Network totals include virtual adapters (WSL, VPN, Hyper-V)

## License
MIT
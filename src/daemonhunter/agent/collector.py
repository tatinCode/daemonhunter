import math
import platform
import socket
import time

import psutil


CPU_TEMPERATURE_SENSORS = (
        "coretemp",
        "k10temp",
        "cpu_thermal",
        )


def collect_cpu_temperature() -> float | None:
    read_temperatures = getattr(
            psutil,
            "sensors_temperatures",
            None,
            )

    if read_temperatures is None:
        return None

    try:
        temperatures = read_temperatures() or {}
    except (NotImplementedError, OSError, psutil.Error):
        return None

    for sensor_name in CPU_TEMPERATURE_SENSORS:
        for reading in temperatures.get(sensor_name, []):
            temperature = getattr(reading, "current", None)

            if temperature is not None and math.isfinite(temperature):
                return float(temperature)

    return None


def collect_metrics() -> dict[str, str | int | float | None]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    temperature = collect_cpu_temperature()

    return {
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": memory.percent,
            "memory_total": memory.total,
            "memory_used": memory.used,
            "disk_percent": disk.percent,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "temperature_celsius": temperature,
            "uptime_seconds": max(
                0,
                int(time.time() - psutil.boot_time()),
                ),
            }

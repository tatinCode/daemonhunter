from types import SimpleNamespace

import pytest

from daemonhunter.agent import collector


@pytest.fixture(autouse=True)
def isolated_local_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unit tests must not sample the test machine or wait for CPU sampling.
    monkeypatch.setattr(collector.socket, "gethostname", lambda: "test-server")
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.psutil, "cpu_percent", lambda interval: 25.5)
    monkeypatch.setattr(
            collector.psutil,
            "virtual_memory",
            lambda: SimpleNamespace(percent=50.0, total=8000, used=4000),
            )
    monkeypatch.setattr(
            collector.psutil,
            "disk_usage",
            lambda path: SimpleNamespace(percent=40.0, total=10000, used=4000),
            )
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {},
            raising=False,
            )
    monkeypatch.setattr(collector.psutil, "boot_time", lambda: 1000.0)
    monkeypatch.setattr(collector.time, "time", lambda: 4600.0)


def test_collect_metrics(monkeypatch):
    monkeypatch.setattr(
            collector.socket,
            "gethostname",
            lambda: "test-server",
            )

    monkeypatch.setattr(
            collector.platform,
            "system",
            lambda: "Linux",
            )

    monkeypatch.setattr(
            collector.psutil,
            "cpu_percent",
            lambda interval: 25.5,
            )

    monkeypatch.setattr(
            collector.psutil,
            "virtual_memory",
            lambda: SimpleNamespace(
                percent=50.0,
                total=8000,
                used=4000,
                ),
            )

    monkeypatch.setattr(
            collector.psutil,
            "disk_usage",
            lambda path: SimpleNamespace(
                percent=40.0,
                total=10000,
                used=4000,
                ),
            )

    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {
                "coretemp": [
                    SimpleNamespace(current=45.5),
                    ],
                },
            )

    monkeypatch.setattr(
            collector.psutil,
            "boot_time",
            lambda: 1000.0,
            )

    monkeypatch.setattr(
            collector.time,
            "time",
            lambda: 4600.0,
            )

    metrics = collector.collect_metrics()

    assert metrics == {
        "hostname": "test-server",
        "os": "Linux",
        "cpu_percent": 25.5,
        "memory_percent": 50.0,
        "memory_total": 8000,
        "memory_used": 4000,
        "disk_percent": 40.0,
        "disk_total": 10000,
        "disk_used": 4000,
        "temperature_celsius": 45.5,
        "uptime_seconds": 3600,
    }


def test_collect_metrics_without_temperature(monkeypatch):
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {},
            )

    metrics = collector.collect_metrics()

    assert metrics["temperature_celsius"] is None


def test_collect_metrics_negative_uptime(monkeypatch):
    monkeypatch.setattr(
            collector.psutil,
            "boot_time",
            lambda: 5000.0,
            )

    monkeypatch.setattr(
            collector.time,
            "time",
            lambda: 4000.0,
            )

    metrics = collector.collect_metrics()

    assert metrics["uptime_seconds"] == 0


def test_temperature_api_can_be_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(collector.psutil, "sensors_temperatures")

    assert collector.collect_cpu_temperature() is None
    assert collector.collect_metrics()["temperature_celsius"] is None


@pytest.mark.parametrize("error", [
        NotImplementedError("Temperature collection is unsupported"),
        OSError("Sensor cannot be read"),
        collector.psutil.AccessDenied(),
        ])
def test_temperature_errors_are_optional(
        monkeypatch: pytest.MonkeyPatch,
        error: Exception,
        ) -> None:
    def unavailable():
        raise error

    monkeypatch.setattr(collector.psutil, "sensors_temperatures", unavailable)

    metrics = collector.collect_metrics()

    assert metrics["temperature_celsius"] is None
    assert metrics["memory_total"] == 8000
    assert metrics["cpu_percent"] == 25.5


@pytest.mark.parametrize("sensor", ["coretemp", "k10temp", "cpu_thermal"])
def test_supported_cpu_temperature_sensors(
        monkeypatch: pytest.MonkeyPatch,
        sensor: str,
        ) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {sensor: [SimpleNamespace(current=42.5)]},
            )

    assert collector.collect_cpu_temperature() == 42.5


def test_cpu_sensor_priority_does_not_depend_on_dictionary_order(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {
                "cpu_thermal": [SimpleNamespace(current=30.0)],
                "k10temp": [SimpleNamespace(current=40.0)],
                "coretemp": [SimpleNamespace(current=50.0)],
                },
            )

    assert collector.collect_cpu_temperature() == 50.0


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -float("inf")])
def test_invalid_temperature_readings_do_not_hide_valid_readings(
        monkeypatch: pytest.MonkeyPatch,
        invalid: float | None,
        ) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {"coretemp": [
                SimpleNamespace(current=invalid),
                SimpleNamespace(current=44.0),
                ]},
            )

    assert collector.collect_cpu_temperature() == 44.0


def test_invalid_cpu_sensor_falls_back_to_next_supported_sensor(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {
                "coretemp": [SimpleNamespace(), SimpleNamespace(current=float("nan"))],
                "k10temp": [SimpleNamespace(current=43.0)],
                },
            )

    assert collector.collect_cpu_temperature() == 43.0


def test_unusable_cpu_readings_do_not_report_an_unrelated_sensor(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {
                "coretemp": [SimpleNamespace(current=float("nan"))],
                "gpu": [SimpleNamespace(current=60.0)],
                },
            )

    assert collector.collect_cpu_temperature() is None


def test_zero_degrees_is_a_valid_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
            collector.psutil,
            "sensors_temperatures",
            lambda: {"cpu_thermal": [SimpleNamespace(current=0.0)]},
            )

    assert collector.collect_cpu_temperature() == 0.0


@pytest.mark.parametrize("metric", ["virtual_memory", "disk_usage", "cpu_percent", "boot_time"])
def test_essential_collection_errors_are_not_silenced(
        monkeypatch: pytest.MonkeyPatch,
        metric: str,
        ) -> None:
    def unavailable(*args, **kwargs):
        raise OSError("Essential metric cannot be read")

    monkeypatch.setattr(collector.psutil, metric, unavailable)

    with pytest.raises(OSError, match="Essential metric cannot be read"):
        collector.collect_metrics()

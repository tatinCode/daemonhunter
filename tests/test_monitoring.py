import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import Device, DeviceStatusEvent
from daemonhunter.monitoring import (
        FAILURE_THRESHOLD,
        ping_host,
        record_check,
        run_monitor_cycle,
        )


def create_device(
        session: Session,
        name: str = "Test Pi",
        host: str = "192.168.1.10",
        status: str = "unknown",
        consecutive_failures: int = 0,
        ) -> Device:
    device = Device(
            name=name,
            host=host,
            status=status,
            consecutive_failures=consecutive_failures,
            )
    session.add(device)
    session.commit()

    return device


def device_events(
        session: Session,
        device: Device,
        ) -> list[DeviceStatusEvent]:
    statement = (
            select(DeviceStatusEvent)
            .where(DeviceStatusEvent.device_id == device.id)
            .order_by(DeviceStatusEvent.id)
            )

    return list(session.scalars(statement))


def test_ping_host_returns_true_for_successful_ping(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(
            "daemonhunter.monitoring.subprocess.run",
            fake_run,
            )

    assert ping_host("192.168.1.10") is True
    assert commands == [["ping", "-c", "1", "-W", "2", "192.168.1.10"]]


def test_ping_host_returns_false_for_failed_ping(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    def fake_run(command, **kwargs):
        return type("Result", (), {"returncode": 1})()

    monkeypatch.setattr(
            "daemonhunter.monitoring.subprocess.run",
            fake_run,
            )

    assert ping_host("192.168.1.10") is False


def test_ping_host_returns_false_when_ping_is_missing(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    def fake_run(command, **kwargs):
        raise FileNotFoundError("ping not found")

    monkeypatch.setattr(
            "daemonhunter.monitoring.subprocess.run",
            fake_run,
            )

    assert ping_host("192.168.1.10") is False


def test_success_marks_unknown_device_online(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session)

        record_check(session, device, lambda host: True)

        assert device.status == "online"
        assert device.consecutive_failures == 0

        events = device_events(session, device)
        assert len(events) == 1
        assert events[0].previous_status == "unknown"
        assert events[0].new_status == "online"


def test_success_marks_offline_device_online_and_resets_failures(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(
                session,
                status="offline",
                consecutive_failures=FAILURE_THRESHOLD,
                )

        record_check(session, device, lambda host: True)

        assert device.status == "online"
        assert device.consecutive_failures == 0

        events = device_events(session, device)
        assert len(events) == 1
        assert events[0].previous_status == "offline"
        assert events[0].new_status == "online"


def test_success_keeps_online_status_without_new_event(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session, status="online")

        record_check(session, device, lambda host: True)

        assert device.status == "online"
        assert device.consecutive_failures == 0
        assert device_events(session, device) == []


def test_failures_below_threshold_keep_online_status(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session, status="online")

        record_check(session, device, lambda host: False)

        assert device.status == "online"
        assert device.consecutive_failures == 1
        assert device_events(session, device) == []

        record_check(session, device, lambda host: False)

        assert device.status == "online"
        assert device.consecutive_failures == 2
        assert device_events(session, device) == []


def test_failures_below_threshold_keep_unknown_status(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session, status="unknown")

        record_check(session, device, lambda host: False)
        record_check(session, device, lambda host: False)

        assert device.status == "unknown"
        assert device.consecutive_failures == 2
        assert device_events(session, device) == []


def test_third_failure_marks_online_device_offline(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(
                session,
                status="online",
                consecutive_failures=FAILURE_THRESHOLD - 1,
                )

        record_check(session, device, lambda host: False)

        assert device.status == "offline"
        assert device.consecutive_failures == FAILURE_THRESHOLD

        events = device_events(session, device)
        assert len(events) == 1
        assert events[0].previous_status == "online"
        assert events[0].new_status == "offline"


def test_third_failure_marks_unknown_device_offline(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(
                session,
                status="unknown",
                consecutive_failures=FAILURE_THRESHOLD - 1,
                )

        record_check(session, device, lambda host: False)

        assert device.status == "offline"
        assert device.consecutive_failures == FAILURE_THRESHOLD

        events = device_events(session, device)
        assert len(events) == 1
        assert events[0].previous_status == "unknown"
        assert events[0].new_status == "offline"


def test_failure_keeps_offline_status_without_new_event(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(
                session,
                status="offline",
                consecutive_failures=FAILURE_THRESHOLD,
                )

        record_check(session, device, lambda host: False)

        assert device.status == "offline"
        assert device.consecutive_failures == FAILURE_THRESHOLD + 1
        assert device_events(session, device) == []


def test_probe_receives_device_host(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session, host="10.0.0.5")
        probed_hosts: list[str] = []

        def probe(host: str) -> bool:
            probed_hosts.append(host)
            return True

        record_check(session, device, probe)

        assert probed_hosts == ["10.0.0.5"]


def test_device_recovers_and_fails_again(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(session)

        record_check(session, device, lambda host: True)
        for _ in range(FAILURE_THRESHOLD):
            record_check(session, device, lambda host: False)
        record_check(session, device, lambda host: True)

        assert device.status == "online"
        assert device.consecutive_failures == 0

        events = device_events(session, device)
        transitions = [
                (event.previous_status, event.new_status)
                for event in events
                ]
        assert transitions == [
                ("unknown", "online"),
                ("online", "offline"),
                ("offline", "online"),
                ]


def test_monitor_cycle_checks_every_device(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        reachable = create_device(
                session,
                name="Reachable Pi",
                host="192.168.1.10",
                )
        unreachable = create_device(
                session,
                name="Unreachable Pi",
                host="192.168.1.11",
                )

        def probe(host: str) -> bool:
            return host == "192.168.1.10"

        run_monitor_cycle(session, probe)

    with test_session_factory() as session:
        reachable = session.get(Device, reachable.id)
        unreachable = session.get(Device, unreachable.id)

        assert reachable is not None
        assert reachable.status == "online"
        assert reachable.consecutive_failures == 0

        assert unreachable is not None
        assert unreachable.status == "unknown"
        assert unreachable.consecutive_failures == 1

        assert len(device_events(session, reachable)) == 1
        assert device_events(session, unreachable) == []


def test_monitor_cycle_commits_changes(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        device = create_device(
                session,
                status="online",
                consecutive_failures=FAILURE_THRESHOLD - 1,
                )
        device_id = device.id

    with test_session_factory() as session:
        run_monitor_cycle(session, lambda host: False)

    with test_session_factory() as session:
        persisted = session.get(Device, device_id)

        assert persisted is not None
        assert persisted.status == "offline"
        assert persisted.consecutive_failures == FAILURE_THRESHOLD
        assert len(device_events(session, persisted)) == 1


def test_monitor_cycle_with_no_devices(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        run_monitor_cycle(session, lambda host: True)

    with test_session_factory() as session:
        devices = session.scalars(select(Device)).all()
        events = session.scalars(select(DeviceStatusEvent)).all()

    assert devices == []
    assert events == []

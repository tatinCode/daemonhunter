import subprocess

from collections.abc import Callable
from sqlalchemy import select
from sqlalchemy.orm import Session

from daemonhunter.models import Device, DeviceStatusEvent

FAILURE_THRESHOLD = 3


def ping_host(host: str, timeout: int = 2) -> bool:
    try:
        result = subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout), host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                )
    except OSError:
        return False

    return result.returncode == 0


def record_check(
        session: Session,
        device: Device,
        probe: Callable[[str], bool],
        ) -> None:
    if probe(device.host):
        previous_status = device.status
        device.consecutive_failures = 0

        if previous_status != "online":
            device.status = "online"

            session.add(
                    DeviceStatusEvent(
                        device_id=device.id,
                        previous_status=previous_status,
                        new_status="online",
                        ),
                    )

        return

    device.consecutive_failures += 1

    if (
            device.consecutive_failures >= FAILURE_THRESHOLD
            and device.status != "offline"
            ):
        previous_status = device.status
        device.status = "offline"

        session.add(
                DeviceStatusEvent(
                    device_id=device.id,
                    previous_status=previous_status,
                    new_status="offline",
                    ),
                )


def run_monitor_cycle(
        session: Session,
        probe: Callable[[str], bool] = ping_host,
        ) -> None:
    devices = session.scalars(select(Device)).all()

    for device in devices:
        record_check(session, device, probe)

    session.commit()

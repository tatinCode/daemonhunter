from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from daemonhunter.database import Base
from daemonhunter.models import Device


def test_create_and_retrieve_device(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{database_path}")

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        device = Device(
                name="Test Server",
                host="192.168.1.10",
                )

        session.add(device)
        session.commit()
        session.refresh(device)

        device_id = device.id

    with Session(engine) as session:
        saved_device = session.scalar(
                select(Device).where(Device.id == device_id)
                )

        assert saved_device is not None
        assert saved_device.name == "Test Server"
        assert saved_device.host == "192.168.1.10"
        assert saved_device.status == "unknown"
        assert saved_device.guest_visible is False
        assert saved_device.created_at is not None
        assert saved_device.updated_at is not None

    engine.dispose()

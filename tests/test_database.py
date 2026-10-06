from pathlib import Path
from stat import S_IMODE

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

import daemonhunter.database as database
from daemonhunter.database import Base
from daemonhunter.models import Device, User


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


def test_prepares_default_database_storage(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = (
            tmp_path
            / "daemonhunter"
            / "daemonhunter.db"
            )

    monkeypatch.setattr(
            database,
            "USING_DEFAULT_DATABASE",
            True,
            )
    monkeypatch.setattr(
            database,
            "DEFAULT_DATABASE_PATH",
            database_path,
            )

    database.prepare_database_storage()

    assert database_path.exists()
    assert S_IMODE(
            database_path.parent.stat().st_mode
            ) == 0o700
    assert S_IMODE(
            database_path.stat().st_mode
            ) == 0o600

    database_path.parent.chmod(0o755)
    database_path.chmod(0o644)

    database.prepare_database_storage()

    assert S_IMODE(
            database_path.parent.stat().st_mode
            ) == 0o700
    assert S_IMODE(
            database_path.stat().st_mode
            ) == 0o600


def test_does_not_prepare_explicit_database_storage(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = (
            tmp_path
            / "explicit"
            / "daemonhunter.db"
            )

    monkeypatch.setattr(
            database,
            "USING_DEFAULT_DATABASE",
            False,
            )
    monkeypatch.setattr(
            database,
            "DEFAULT_DATABASE_PATH",
            database_path,
            )

    database.prepare_database_storage()

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_rejects_stale_user_update(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        user = User(
                username="versioned-user",
                password_hash="password-hash",
                session_secret="session-secret",
                role="admin",
                active=True,
                must_change_password=False,
                )
        session.add(user)
        session.commit()
        user_id = user.id

    with (
            test_session_factory() as first_session,
            test_session_factory() as stale_session,
            ):
        first_user = first_session.get(User, user_id)
        stale_user = stale_session.get(User, user_id)

        assert first_user is not None
        assert stale_user is not None
        assert first_user.version_id == 1

        first_user.username = "updated-user"
        first_session.commit()

        assert first_user.version_id == 2

        stale_user.active = False

        with pytest.raises(StaleDataError):
            stale_session.commit()

        stale_session.rollback()

    with test_session_factory() as session:
        saved_user = session.get(User, user_id)

        assert saved_user is not None
        assert saved_user.username == "updated-user"
        assert saved_user.active is True


def test_rejects_stale_user_delete(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        user = User(
                username="delete-version-user",
                password_hash="password-hash",
                session_secret="session-secret",
                role="admin",
                active=True,
                must_change_password=False,
                )
        session.add(user)
        session.commit()
        user_id = user.id

    with (
            test_session_factory() as update_session,
            test_session_factory() as delete_session,
            ):
        updated_user = update_session.get(User, user_id)
        stale_user = delete_session.get(User, user_id)

        assert updated_user is not None
        assert stale_user is not None

        updated_user.username = "preserved-user"
        update_session.commit()

        delete_session.delete(stale_user)

        with pytest.raises(StaleDataError):
            delete_session.commit()

        delete_session.rollback()

    with test_session_factory() as session:
        saved_user = session.get(User, user_id)

        assert saved_user is not None
        assert saved_user.username == "preserved-user"

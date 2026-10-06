import pytest

from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import User
from daemonhunter.routers.user_writes import committed_user_write


def test_stale_user_write_returns_conflict(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        user = User(
                username="conflicting-user",
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

        first_user.username = "updated-user"
        first_session.commit()

        with pytest.raises(HTTPException) as error:
            with committed_user_write(stale_session):
                stale_user.active = False

        assert error.value.status_code == 409
        assert error.value.detail == (
                "User was modified by another request; reload and retry"
                )

    with test_session_factory() as session:
        saved_user = session.get(User, user_id)

        assert saved_user is not None
        assert saved_user.username == "updated-user"
        assert saved_user.active is True


def test_sqlite_contention_returns_service_unavailable(
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory() as session:
        user = User(
                username="locked-user",
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
            test_session_factory() as locking_session,
            test_session_factory() as contending_session,
            ):
        locking_user = locking_session.get(User, user_id)
        contending_user = contending_session.get(User, user_id)

        assert locking_user is not None
        assert contending_user is not None

        contending_session.connection().exec_driver_sql(
                "PRAGMA busy_timeout = 0",
                )

        locking_user.username = "uncommitted-username"
        locking_session.flush()

        with pytest.raises(HTTPException) as error:
            with committed_user_write(contending_session):
                contending_user.active = False

        assert error.value.status_code == 503
        assert error.value.detail == "Database is busy; retry the request"
        assert error.value.headers == {"Retry-After": "1"}
        assert contending_session.in_transaction() is False

        locking_session.rollback()

    with test_session_factory() as session:
        saved_user = session.get(User, user_id)

        assert saved_user is not None
        assert saved_user.username == "locked-user"
        assert saved_user.active is True

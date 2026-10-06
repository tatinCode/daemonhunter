from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from daemonhunter.database import is_sqlite_busy_error


@contextmanager
def committed_user_write(
        session: Session,
        ) -> Iterator[None]:
    try:
        yield
        session.commit()

    except StaleDataError as error:
        session.rollback()

        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "User was modified by another request; "
                    "reload and retry"
                    ),
                ) from error

    except OperationalError as error:
        session.rollback()

        if not is_sqlite_busy_error(error):
            raise

        raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is busy; retry the request",
                headers={"Retry-After": "1"},
                ) from error

    except Exception:
        session.rollback()
        raise

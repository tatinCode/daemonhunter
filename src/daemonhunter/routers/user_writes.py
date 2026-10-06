from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError


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

    except Exception:
        session.rollback()
        raise

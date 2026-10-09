import os
import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from daemonhunter.config import (
        DATABASE_URL,
        DEFAULT_DATABASE_PATH,
        USING_DEFAULT_DATABASE,
        )

connect_args = (
        {"check_same_thread": False}
        if DATABASE_URL.startswith("sqlite")
        else {}
        )

engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        )

SessionFactory = sessionmaker(
        bind=engine,
        expire_on_commit=False
        )


class Base(DeclarativeBase):
    pass


def is_sqlite_busy_error(
        error: OperationalError,
        ) -> bool:
    original_error = error.orig

    if not isinstance(
            original_error,
            sqlite3.OperationalError,
            ):
        return False

    error_code = getattr(
            original_error,
            "sqlite_errorcode",
            None,
            )

    return (
            isinstance(error_code, int)
            and (error_code & 0xFF) in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
                }
            )


def prepare_database_storage() -> None:
    if not USING_DEFAULT_DATABASE:
        return

    database_directory = DEFAULT_DATABASE_PATH.parent

    database_directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
            )

    database_directory.chmod(0o700)

    file_descriptor = os.open(
            DEFAULT_DATABASE_PATH,
            os.O_CREAT | os.O_WRONLY,
            0o600,
            )

    os.close(file_descriptor)

    DEFAULT_DATABASE_PATH.chmod(0o600)


def get_session() -> Generator[Session, None, None]:
    prepare_database_storage()

    with SessionFactory() as session:
        yield session

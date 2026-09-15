from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from daemonhunter.config import DATABASE_URL

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


def get_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session

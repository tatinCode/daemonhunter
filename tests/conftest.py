from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.database import Base, get_session
from daemonhunter.main import app


@pytest.fixture
def api_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "api-test.db"
    engine = create_engine(f"sqlite:///{database_path}")
    test_session_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            )

    Base.metadata.create_all(engine)

    def override_get_session() -> Generator[Session, None, None]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    engine.dispose()

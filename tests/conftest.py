from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.database import Base, get_session
from daemonhunter.main import app
from daemonhunter.auth import get_setup_token


TEST_SETUP_TOKEN = (
        "daemonhunter-test-setup-token-1234567890"
        )


@pytest.fixture
def test_session_factory(
        tmp_path: Path,
        ) -> Generator[sessionmaker[Session], None, None]:
    database_path = tmp_path / "api-test.db"
    engine = create_engine(f"sqlite:///{database_path}")
    test_session_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            )

    Base.metadata.create_all(engine)

    yield test_session_factory

    engine.dispose()


@pytest.fixture
def api_client(
        test_session_factory: sessionmaker[Session],
        ) -> Generator[TestClient, None, None]:

    def override_get_session() -> Generator[Session, None, None]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_setup_token] = (
            lambda: TEST_SETUP_TOKEN
            )
    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(api_client: TestClient) -> TestClient:
    response = api_client.post(
            "/api/v1/auth/setup",
            json={
                "username": "owner",
                "password": "correct horse battery staple",
                "setup_token": TEST_SETUP_TOKEN,
                },
            )

    assert response.status_code == 201
    return api_client


@pytest.fixture
def secondary_client(
        api_client: TestClient,
        ) -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client

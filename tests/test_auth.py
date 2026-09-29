from fastapi.testclient import TestClient

OWNER_CREDENTIALS = {
        "username": "owner",
        "password": "correct horse battery staple",
        }


def test_reports_setup_status(
        api_client: TestClient,
        ) -> None:
    before_setup = api_client.get(
            "/api/v1/auth/setup-status",
            )

    assert before_setup.status_code == 200
    assert before_setup.json() == {
            "setup_required": True,
            }

    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_CREDENTIALS,
            )

    assert setup_response.status_code == 201

    after_setup = api_client.get(
            "/api/v1/auth/setup-status",
            )

    assert after_setup.status_code == 200
    assert after_setup.json() == {
            "setup_required": False,
            }


def test_setup_creates_and_logs_in_owner(
        api_client: TestClient,
        ) -> None:
    response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_CREDENTIALS
            )

    assert response.status_code == 201

    owner = response.json()

    assert owner["username"] == "owner"
    assert owner["role"] == "owner"
    assert owner["active"] is True
    assert owner["must_change_password"] is False
    assert owner["created_at"] is not None
    assert owner["updated_at"] is not None

    assert "password" not in owner
    assert "password_hash" not in owner
    assert "session_secret" not in owner
    assert "daemonhunter_session" in api_client.cookies

    current_user = api_client.get("/api/v1/auth/me")

    assert current_user.status_code == 200
    assert current_user.json()["username"] == "owner"

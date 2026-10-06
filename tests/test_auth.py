from fastapi.testclient import TestClient

SETUP_TOKEN = (
                "daemonhunter-test-setup-token-1234567890"
                )

OWNER_CREDENTIALS = {
        "username": "owner",
        "password": "correct horse battery staple",
        }

OWNER_SETUP = {
        **OWNER_CREDENTIALS,
        "setup_token": SETUP_TOKEN,
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
            json=OWNER_SETUP,
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
            json=OWNER_SETUP,
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


def test_rejects_duplicate_owner_setup(
        api_client: TestClient,
        ) -> None:
    first_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )
    second_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )

    assert first_response.status_code == 201
    assert second_response.status_code == 409

    assert second_response.json() == {
            "detail": "Owner account already configured",
            }


def test_rejects_short_owner_password(
        api_client: TestClient,
        ) -> None:
    response = api_client.post(
            "/api/v1/auth/setup",
            json={
                "username": "owner",
                "password": "short",
                "setup_token": SETUP_TOKEN,
                },
            )

    assert response.status_code == 422

    setup_status = api_client.get(
            "/api/v1/auth/setup-status",
            )

    assert setup_status.json() == {
            "setup_required": True,
            }


def test_logout_and_login(
        api_client: TestClient,
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )

    assert setup_response.status_code == 201

    logout_response = api_client.post(
            "/api/v1/auth/logout",
            )

    assert logout_response.status_code == 204
    assert api_client.get(
            "/api/v1/auth/me"
            ).status_code == 401

    login_response = api_client.post(
            "/api/v1/auth/login",
            json=OWNER_CREDENTIALS
            )

    assert login_response.status_code == 200
    assert login_response.json()["username"] == "owner"
    assert login_response.json()["role"] == "owner"
    assert api_client.get(
            "/api/v1/auth/me"
            ).status_code == 200


def test_rejects_invalid_login(
        api_client: TestClient
        ) -> None:
    status_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP
            )
    assert status_response.status_code == 201

    api_client.post(
            "/api/v1/auth/logout",
            )

    wrong_password = api_client.post(
            "/api/v1/auth/login",
            json={
                "username": "owner",
                "password": "this password is incorrect",
                },
            )

    unknown_user = api_client.post(
            "/api/v1/auth/login",
            json={
                "username": "unknown",
                "password": "this password is incorrect",
                },
            )

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401

    expected_error = {
            "detail": "Invalid username or password",
            }
    assert wrong_password.json() == expected_error
    assert unknown_user.json() == expected_error


def test_requires_session_cookie(
        api_client: TestClient
        ) -> None:
    response = api_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
            "detail": "Authentication Required",
            }


def test_admin_routes_require_session(
        api_client: TestClient,
        ) -> None:
    response = api_client.get("/api/v1/admin/devices")

    assert response.status_code == 401
    assert response.json() == {
            "detail": "Authentication Required",
            }


def test_rejects_tampered_session_cookie(
        api_client: TestClient
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP
            )
    assert setup_response.status_code == 201

    api_client.cookies.clear()

    response = api_client.get(
            "/api/v1/auth/me",
            headers={
                "Cookie": "daemonhunter_session=1.tampered",
                },
            )

    assert response.status_code == 401
    assert response.json() == {
            "detail": "Authentication Required",
            }


def test_changes_owner_password(
        api_client: TestClient,
        ) -> None:
    api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )

    change_response = api_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": OWNER_CREDENTIALS["password"],
                "new_password": "an even better owner password",
                },
            )

    assert change_response.status_code == 200
    assert change_response.json()["must_change_password"] is False

    api_client.post("/api/v1/auth/logout")

    old_password_login = api_client.post(
            "/api/v1/auth/login",
            json=OWNER_CREDENTIALS,
            )
    new_password_login = api_client.post(
            "/api/v1/auth/login",
            json={
                "username": "owner",
                "password": "an even better owner password",
                },
            )

    assert old_password_login.status_code == 401
    assert new_password_login.status_code == 200


def test_rejects_incorrect_current_password(
        api_client: TestClient,
        ) -> None:
    api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )

    response = api_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "this is not the current password",
                "new_password": "an even better owner password",
                },
            )

    assert response.status_code == 400
    assert response.json() == {
            "detail": "Current password is incorrect",
            }
    assert api_client.get("/api/v1/auth/me").status_code == 200


def test_rejects_missing_setup_token(
        api_client: TestClient,
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json={
                "username": "owner",
                "password": "correct horse battery sample",
                },
            )

    assert setup_response.status_code == 422


def test_rejects_invalid_setup_token(
        api_client: TestClient,
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json={
                "username": "owner",
                "password": "correct horse battery sample",
                "setup_token": "invalid-setup-token-12345678901234567890",
                },
            )

    assert setup_response.status_code == 403
    assert setup_response.json() == {
            "detail": "Invalid setup token",
            }

    setup_status = api_client.get(
            "/api/v1/auth/setup-status",
            )

    assert setup_status.json() == {
            "setup_required": True,
            }


def test_rejects_reused_owner_password(
        api_client: TestClient,
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )
    assert setup_response.status_code == 201

    response = api_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": OWNER_CREDENTIALS["password"],
                "new_password": OWNER_CREDENTIALS["password"],
                },
            )

    assert response.status_code == 400
    assert response.json() == {
            "detail": (
                "New password must be different from current password"
                ),
            }
    assert api_client.get("/api/v1/auth/me").status_code == 200


def test_logout_revokes_copied_session(
        api_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    setup_response = api_client.post(
            "/api/v1/auth/setup",
            json=OWNER_SETUP,
            )
    assert setup_response.status_code == 201

    session_cookie = api_client.cookies.get(
            "daemonhunter_session"
            )
    assert session_cookie is not None

    copied_cookie = {
            "Cookie": (
                f"daemonhunter_session={session_cookie}"
                ),
            }

    assert secondary_client.get(
            "/api/v1/auth/me",
            headers=copied_cookie,
            ).status_code == 200

    logout_response = api_client.post(
            "/api/v1/auth/logout"
            )

    assert logout_response.status_code == 204
    assert api_client.get(
            "/api/v1/auth/me"
            ).status_code == 401
    assert secondary_client.get(
            "/api/v1/auth/me",
            headers=copied_cookie,
            ).status_code == 401


def test_logout_requires_authentication(
        api_client: TestClient,
        ) -> None:
    response = api_client.post("/api/v1/auth/logout")

    assert response.status_code == 401
    assert response.json() == {
            "detail": "Authentication Required",
            }

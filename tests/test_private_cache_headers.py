from fastapi.testclient import TestClient


def test_login_response_with_session_cookie_disables_caching(
        admin_client: TestClient,
        ) -> None:
    response = admin_client.post(
            "/api/v1/auth/login",
            json={
                "username": "owner",
                "password": "correct horse battery staple",
                },
            )

    assert response.status_code == 200
    assert "set-cookie" in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_auth_error_disables_caching(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_admin_success_and_not_found_disable_caching(
        admin_client: TestClient,
        ) -> None:
    success = admin_client.get("/api/v1/admin/users")
    missing = admin_client.get("/api/v1/admin/users/999999")

    assert success.status_code == 200
    assert success.headers["cache-control"] == "no-store"
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"


def test_unauthenticated_admin_error_disables_caching(
        api_client: TestClient,
        ) -> None:
    response = api_client.get("/api/v1/admin/users")

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_health_response_does_not_inherit_private_cache_header(
        api_client: TestClient,
        ) -> None:
    response = api_client.get("/api/v1/health")

    assert response.status_code == 200
    assert "cache-control" not in response.headers

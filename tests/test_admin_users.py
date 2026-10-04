from fastapi.testclient import TestClient


OWNER_CREDENTIALS = {
        "username": "owner",
        "password": "correct horse battery staple",
        }

ADMIN_CREDENTIALS = {
        "username": "secondary-admin",
        "password": "temporary admin password",
        }

NEW_ADMIN_PASSWORD = "permanent admin password"


def create_secondary_admin(
        admin_client: TestClient,
        ) -> dict:
    response = admin_client.post(
            "/api/v1/admin/users",
            json={
                "username": ADMIN_CREDENTIALS["username"],
                "temporary_password": ADMIN_CREDENTIALS["password"],
                },
            )

    assert response.status_code == 201
    return response.json()


def activate_secondary_admin(client: TestClient) -> None:
    login_response = client.post(
            "/api/v1/auth/login",
            json=ADMIN_CREDENTIALS,
            )
    assert login_response.status_code == 200

    change_response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": ADMIN_CREDENTIALS["password"],
                "new_password": NEW_ADMIN_PASSWORD,
                },
            )
    assert change_response.status_code == 200


def test_owner_creates_and_lists_secondary_admin(
        admin_client: TestClient,
        ) -> None:
    user = create_secondary_admin(admin_client)

    assert user["username"] == "secondary-admin"
    assert user["role"] == "admin"
    assert user["active"] is True
    assert user["must_change_password"] is True
    assert "password_hash" not in user
    assert "session_secret" not in user

    response = admin_client.get("/api/v1/admin/users")

    assert response.status_code == 200
    assert [item["role"] for item in response.json()] == [
            "owner",
            "admin",
            ]


def test_rejects_duplicate_admin_username(
        admin_client: TestClient,
        ) -> None:
    create_secondary_admin(admin_client)

    response = admin_client.post(
            "/api/v1/admin/users",
            json={
                "username": ADMIN_CREDENTIALS["username"],
                "temporary_password": ADMIN_CREDENTIALS["password"],
                },
            )

    assert response.status_code == 409
    assert response.json() == {
            "detail": "A user with this username already exists",
            }


def test_temporary_password_blocks_admin_actions(
        admin_client: TestClient,
        ) -> None:
    create_secondary_admin(admin_client)
    admin_client.post("/api/v1/auth/logout")

    login_response = admin_client.post(
            "/api/v1/auth/login",
            json=ADMIN_CREDENTIALS,
            )
    assert login_response.status_code == 200
    assert login_response.json()["must_change_password"] is True

    blocked_response = admin_client.get("/api/v1/admin/devices")

    assert blocked_response.status_code == 403
    assert blocked_response.json() == {
            "detail": "Password change required",
            }

    change_response = admin_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": ADMIN_CREDENTIALS["password"],
                "new_password": NEW_ADMIN_PASSWORD,
                },
            )
    allowed_response = admin_client.get("/api/v1/admin/devices")

    assert change_response.status_code == 200
    assert change_response.json()["must_change_password"] is False
    assert allowed_response.status_code == 200


def test_secondary_admin_cannot_manage_accounts(
        admin_client: TestClient,
        ) -> None:
    create_secondary_admin(admin_client)
    admin_client.post("/api/v1/auth/logout")
    activate_secondary_admin(admin_client)

    response = admin_client.get("/api/v1/admin/users")

    assert response.status_code == 403
    assert response.json() == {
            "detail": "Owner access required",
            }


def test_owner_account_cannot_be_modified(
        admin_client: TestClient,
        ) -> None:
    owner_id = admin_client.get("/api/v1/auth/me").json()["id"]

    update_response = admin_client.patch(
            f"/api/v1/admin/users/{owner_id}",
            json={"active": False},
            )
    reset_response = admin_client.post(
            f"/api/v1/admin/users/{owner_id}/reset-password",
            json={"temporary_password": "replacement owner password"},
            )
    delete_response = admin_client.delete(
            f"/api/v1/admin/users/{owner_id}",
            )

    expected_error = {
            "detail": "The owner account cannot be modified",
            }
    assert update_response.status_code == 403
    assert reset_response.status_code == 403
    assert delete_response.status_code == 403
    assert update_response.json() == expected_error
    assert reset_response.json() == expected_error
    assert delete_response.json() == expected_error


def test_owner_updates_and_deletes_secondary_admin(
        admin_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]

    update_response = admin_client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={
                "username": "renamed-admin",
                "active": False,
                },
            )

    assert update_response.status_code == 200
    assert update_response.json()["username"] == "renamed-admin"
    assert update_response.json()["active"] is False

    login_response = admin_client.post(
            "/api/v1/auth/login",
            json={
                "username": "renamed-admin",
                "password": ADMIN_CREDENTIALS["password"],
                },
            )
    assert login_response.status_code == 401

    enable_response = admin_client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"active": True},
            )
    delete_response = admin_client.delete(
            f"/api/v1/admin/users/{user_id}",
            )
    missing_response = admin_client.get(
            f"/api/v1/admin/users/{user_id}",
            )

    assert enable_response.status_code == 200
    assert delete_response.status_code == 204
    assert missing_response.status_code == 404


def test_password_reset_invalidates_admin_session(
        admin_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]
    activate_secondary_admin(secondary_client)

    reset_response = admin_client.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"temporary_password": "replacement admin password"},
            )

    assert reset_response.status_code == 200
    assert reset_response.json()["must_change_password"] is True
    assert secondary_client.get("/api/v1/auth/me").status_code == 401

    old_password_login = secondary_client.post(
            "/api/v1/auth/login",
            json={
                "username": ADMIN_CREDENTIALS["username"],
                "password": NEW_ADMIN_PASSWORD,
                },
            )
    new_password_login = secondary_client.post(
            "/api/v1/auth/login",
            json={
                "username": ADMIN_CREDENTIALS["username"],
                "password": "replacement admin password",
                },
            )

    assert old_password_login.status_code == 401
    assert new_password_login.status_code == 200
    assert new_password_login.json()["must_change_password"] is True


def test_disabling_admin_invalidates_existing_session(
        admin_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]
    activate_secondary_admin(secondary_client)

    response = admin_client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"active": False},
            )

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert secondary_client.get("/api/v1/auth/me").status_code == 401


def test_transfer_rejects_unready_or_inactive_admin(
        admin_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]
    transfer_data = {
            "current_password": OWNER_CREDENTIALS["password"],
            "confirm_username": ADMIN_CREDENTIALS["username"],
            }

    unready_response = admin_client.post(
            f"/api/v1/admin/users/{user_id}/transfer-ownership",
            json=transfer_data,
            )
    admin_client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"active": False},
            )
    inactive_response = admin_client.post(
            f"/api/v1/admin/users/{user_id}/transfer-ownership",
            json=transfer_data,
            )

    assert unready_response.status_code == 409
    assert unready_response.json() == {
            "detail": "The target admin must change their temporary password",
            }
    assert inactive_response.status_code == 409
    assert inactive_response.json() == {
            "detail": "Ownership cannot be transferred to an inactive admin",
            }


def test_transfer_requires_owner_password_and_username_confirmation(
        admin_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]
    activate_secondary_admin(secondary_client)

    mismatched_username = admin_client.post(
            f"/api/v1/admin/users/{user_id}/transfer-ownership",
            json={
                "current_password": OWNER_CREDENTIALS["password"],
                "confirm_username": "wrong-admin",
                },
            )
    wrong_password = admin_client.post(
            f"/api/v1/admin/users/{user_id}/transfer-ownership",
            json={
                "current_password": "this is not the owner password",
                "confirm_username": ADMIN_CREDENTIALS["username"],
                },
            )

    assert mismatched_username.status_code == 400
    assert mismatched_username.json() == {
            "detail": "Confirmation username does not match",
            }
    assert wrong_password.status_code == 400
    assert wrong_password.json() == {
            "detail": "Current password is incorrect",
            }
    assert admin_client.get("/api/v1/auth/me").json()["role"] == "owner"
    assert secondary_client.get("/api/v1/auth/me").json()["role"] == "admin"


def test_transfer_ownership_swaps_roles_and_sessions(
        admin_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    user_id = create_secondary_admin(admin_client)["id"]
    activate_secondary_admin(secondary_client)

    response = admin_client.post(
            f"/api/v1/admin/users/{user_id}/transfer-ownership",
            json={
                "current_password": OWNER_CREDENTIALS["password"],
                "confirm_username": ADMIN_CREDENTIALS["username"],
                },
            )

    assert response.status_code == 204
    assert admin_client.get("/api/v1/auth/me").status_code == 401
    assert secondary_client.get("/api/v1/auth/me").status_code == 401

    previous_owner_login = admin_client.post(
            "/api/v1/auth/login",
            json=OWNER_CREDENTIALS,
            )
    new_owner_login = secondary_client.post(
            "/api/v1/auth/login",
            json={
                "username": ADMIN_CREDENTIALS["username"],
                "password": NEW_ADMIN_PASSWORD,
                },
            )

    assert previous_owner_login.status_code == 200
    assert previous_owner_login.json()["role"] == "admin"
    assert admin_client.get("/api/v1/admin/users").status_code == 403

    assert new_owner_login.status_code == 200
    assert new_owner_login.json()["role"] == "owner"
    assert secondary_client.get("/api/v1/admin/users").status_code == 200

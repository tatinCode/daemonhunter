from fastapi.testclient import TestClient


def test_public_device_list_does_not_require_authentication(
        api_client: TestClient,
        ) -> None:
    response = api_client.get("/api/v1/devices")

    assert response.status_code == 200
    assert response.json() == []


def test_guests_only_see_visible_devices(
        admin_client: TestClient,
        ) -> None:
    hidden = admin_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "Hidden Pi",
                "host": "192.168.1.10",
                },
            ).json()
    visible = admin_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "Visible Pi",
                "host": "192.168.1.11",
                "guest_visible": True,
                },
            ).json()

    admin_client.post("/api/v1/auth/logout")
    response = admin_client.get("/api/v1/devices")

    assert response.status_code == 200
    assert response.json() == [
            {
                "id": visible["id"],
                "name": "Visible Pi",
                "host": "192.168.1.11",
                "status": "unknown",
                },
            ]
    assert all(
            device["id"] != hidden["id"]
            for device in response.json()
            )


def test_hidden_device_detail_returns_not_found(
        admin_client: TestClient,
        ) -> None:
    hidden = admin_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "Hidden Pi",
                "host": "192.168.1.10",
                },
            ).json()
    visible = admin_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "Visible Pi",
                "host": "192.168.1.11",
                "guest_visible": True,
                },
            ).json()

    admin_client.post("/api/v1/auth/logout")
    hidden_response = admin_client.get(
            f"/api/v1/devices/{hidden['id']}",
            )
    visible_response = admin_client.get(
            f"/api/v1/devices/{visible['id']}",
            )

    assert hidden_response.status_code == 404
    assert hidden_response.json() == {
            "detail": "Device not found",
            }
    assert visible_response.status_code == 200
    assert visible_response.json() == {
            "id": visible["id"],
            "name": "Visible Pi",
            "host": "192.168.1.11",
            "status": "unknown",
            }

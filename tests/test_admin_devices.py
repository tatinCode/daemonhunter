from fastapi.testclient import TestClient


def test_create_device(api_client: TestClient) -> None:
    response = api_client.post(
            "/api/v1/admin/devices",
            json={
                "name": " Test Pi ",
                "host": " 192.168.1.10 ",
                },
            )

    assert response.status_code == 201

    device = response.json()
    assert device["id"] == 1
    assert device["name"] == "Test Pi"
    assert device["host"] == "192.168.1.10"
    assert device["status"] == "unknown"
    assert device["guest_visible"] is False
    assert device["created_at"] is not None
    assert device["updated_at"] is not None


def test_list_devices(api_client: TestClient) -> None:
    api_client.post(
            "/api/v1/admin/devices",
            json={"name": "Pi One", "host": "192.168.1.10"},
            )
    api_client.post(
            "/api/v1/admin/devices",
            json={"name": "Pi Two", "host": "192.168.1.11"},
            )

    response = api_client.get("/api/v1/admin/devices")

    assert response.status_code == 200
    assert [device["name"] for device in response.json()] == [
            "Pi One",
            "Pi Two",
            ]


def test_rejects_duplicate_device(api_client: TestClient) -> None:
    payload = {
            "name": "Test Pi",
            "host": "192.168.1.10",
            }

    first_response = api_client.post(
            "/api/v1/admin/devices",
            json=payload,
            )

    duplicate_response = api_client.post(
            "/api/v1/admin/devices",
            json=payload,
            )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
            "detail": "A device with this name or host already exists"
            }


def test_rejects_invalid_device(api_client: TestClient) -> None:
    response = api_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "   ",
                "host": "192.168.1.10",
                },
            )

    assert response.status_code == 422

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


def test_retrieve_device(api_client: TestClient) -> None:
    created = api_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()

    response = api_client.get(f"/api/v1/admin/devices/{created['id']}")

    assert response.status_code == 200
    assert response.json()["name"] == "Test Pi"


def test_rejects_missing_devices(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/admin/devices/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_updates_device(api_client: TestClient) -> None:
    created = api_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"}
            ).json()

    response = api_client.patch(
            f"/api/v1/admin/devices/{created['id']}",
            json={"name": " Updated Pi ", "guest_visible": True},
            )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Pi"
    assert response.json()["host"] == "192.168.1.10"
    assert response.json()["guest_visible"] is True


def test_rejects_empty_device_update(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    response = api_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={},
    )

    assert response.status_code == 422


def test_rejects_null_or_unknown_device_update(
    api_client: TestClient,
) -> None:
    created = api_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    null_response = api_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={"name": None},
    )
    unknown_response = api_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={"status": "online"},
    )

    assert null_response.status_code == 422
    assert unknown_response.status_code == 422


def test_rejects_duplicate_device_update(api_client: TestClient) -> None:
    api_client.post(
        "/api/v1/admin/devices",
        json={"name": "Pi One", "host": "192.168.1.10"},
    )
    second = api_client.post(
        "/api/v1/admin/devices",
        json={"name": "Pi Two", "host": "192.168.1.11"},
    ).json()

    response = api_client.patch(
        f"/api/v1/admin/devices/{second['id']}",
        json={"host": "192.168.1.10"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "A device with this name or host already exists"
    }


def test_deletes_device(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    response = api_client.delete(
        f"/api/v1/admin/devices/{created['id']}",
    )

    assert response.status_code == 204
    assert response.content == b""

    missing_response = api_client.get(
        f"/api/v1/admin/devices/{created['id']}",
    )
    assert missing_response.status_code == 404


def test_rejects_deleting_missing_device(api_client: TestClient) -> None:
    response = api_client.delete("/api/v1/admin/devices/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_rejects_updating_missing_device(api_client: TestClient) -> None:
    response = api_client.patch(
            "/api/v1/admin/devices/999",
            json={"name": "Updated Pi"},
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}

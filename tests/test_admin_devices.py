from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import DeviceStatusEvent


def create_status_events(
        test_session_factory: sessionmaker[Session],
        device_id: int,
        count: int,
        ) -> list[int]:
    event_ids: list[int] = []

    with test_session_factory() as session:
        for index in range(count):
            event = DeviceStatusEvent(
                    device_id=device_id,
                    previous_status="unknown" if index == 0 else "online",
                    new_status="online" if index == 0 else "offline",
                    )
            session.add(event)

        session.commit()
        event_ids = [
                event.id
                for event in session.scalars(
                    select(DeviceStatusEvent).order_by(DeviceStatusEvent.id)
                    )
                ]

    return event_ids


def test_create_device(admin_client: TestClient) -> None:
    response = admin_client.post(
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


def test_list_devices(admin_client: TestClient) -> None:
    admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Pi One", "host": "192.168.1.10"},
            )
    admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Pi Two", "host": "192.168.1.11"},
            )

    response = admin_client.get("/api/v1/admin/devices")

    assert response.status_code == 200
    assert [device["name"] for device in response.json()] == [
            "Pi One",
            "Pi Two",
            ]


def test_rejects_duplicate_device(admin_client: TestClient) -> None:
    payload = {
            "name": "Test Pi",
            "host": "192.168.1.10",
            }

    first_response = admin_client.post(
            "/api/v1/admin/devices",
            json=payload,
            )

    duplicate_response = admin_client.post(
            "/api/v1/admin/devices",
            json=payload,
            )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
            "detail": "A device with this name or host already exists"
            }


def test_rejects_invalid_device(admin_client: TestClient) -> None:
    response = admin_client.post(
            "/api/v1/admin/devices",
            json={
                "name": "   ",
                "host": "192.168.1.10",
                },
            )

    assert response.status_code == 422


def test_retrieve_device(admin_client: TestClient) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()

    response = admin_client.get(f"/api/v1/admin/devices/{created['id']}")

    assert response.status_code == 200
    assert response.json()["name"] == "Test Pi"


def test_rejects_missing_devices(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/admin/devices/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_updates_device(admin_client: TestClient) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"}
            ).json()

    response = admin_client.patch(
            f"/api/v1/admin/devices/{created['id']}",
            json={"name": " Updated Pi ", "guest_visible": True},
            )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Pi"
    assert response.json()["host"] == "192.168.1.10"
    assert response.json()["guest_visible"] is True


def test_rejects_empty_device_update(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    response = admin_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={},
    )

    assert response.status_code == 422


def test_rejects_null_or_unknown_device_update(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    null_response = admin_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={"name": None},
    )
    unknown_response = admin_client.patch(
        f"/api/v1/admin/devices/{created['id']}",
        json={"status": "online"},
    )

    assert null_response.status_code == 422
    assert unknown_response.status_code == 422


def test_rejects_duplicate_device_update(admin_client: TestClient) -> None:
    admin_client.post(
        "/api/v1/admin/devices",
        json={"name": "Pi One", "host": "192.168.1.10"},
    )
    second = admin_client.post(
        "/api/v1/admin/devices",
        json={"name": "Pi Two", "host": "192.168.1.11"},
    ).json()

    response = admin_client.patch(
        f"/api/v1/admin/devices/{second['id']}",
        json={"host": "192.168.1.10"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "A device with this name or host already exists"
    }


def test_deletes_device(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/v1/admin/devices",
        json={"name": "Test Pi", "host": "192.168.1.10"},
    ).json()

    response = admin_client.delete(
        f"/api/v1/admin/devices/{created['id']}",
    )

    assert response.status_code == 204
    assert response.content == b""

    missing_response = admin_client.get(
        f"/api/v1/admin/devices/{created['id']}",
    )
    assert missing_response.status_code == 404


def test_deleting_device_removes_status_history(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()

    with test_session_factory() as session:
        event = DeviceStatusEvent(
                device_id=created["id"],
                previous_status="unknown",
                new_status="online",
                )
        session.add(event)
        session.commit()
        event_id = event.id

    response = admin_client.delete(
            f"/api/v1/admin/devices/{created['id']}",
            )

    assert response.status_code == 204
    with test_session_factory() as session:
        assert session.get(DeviceStatusEvent, event_id) is None


def test_rejects_deleting_missing_device(admin_client: TestClient) -> None:
    response = admin_client.delete("/api/v1/admin/devices/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_rejects_updating_missing_device(admin_client: TestClient) -> None:
    response = admin_client.patch(
            "/api/v1/admin/devices/999",
            json={"name": "Updated Pi"},
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_lists_status_events_newest_first(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()
    event_ids = create_status_events(
            test_session_factory,
            created["id"],
            count=3,
            )

    response = admin_client.get(
            f"/api/v1/admin/devices/{created['id']}/status-events"
            )

    assert response.status_code == 200
    events = response.json()

    assert [event["id"] for event in events] == list(reversed(event_ids))
    assert all(event["device_id"] == created["id"] for event in events)
    assert all(event["occurred_at"] is not None for event in events)
    assert events[0]["new_status"] == "offline"
    assert events[-1]["previous_status"] == "unknown"


def test_limits_status_events(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()
    event_ids = create_status_events(
            test_session_factory,
            created["id"],
            count=3,
            )

    response = admin_client.get(
            f"/api/v1/admin/devices/{created['id']}/status-events?limit=2"
            )

    assert response.status_code == 200
    events = response.json()

    assert [event["id"] for event in events] == list(reversed(event_ids))[:2]


def test_rejects_invalid_status_events_limit(
        admin_client: TestClient,
        ) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()

    too_small = admin_client.get(
            f"/api/v1/admin/devices/{created['id']}/status-events?limit=0"
            )
    too_large = admin_client.get(
            f"/api/v1/admin/devices/{created['id']}/status-events?limit=501"
            )

    assert too_small.status_code == 422
    assert too_large.status_code == 422


def test_lists_empty_status_events_for_new_device(
        admin_client: TestClient,
        ) -> None:
    created = admin_client.post(
            "/api/v1/admin/devices",
            json={"name": "Test Pi", "host": "192.168.1.10"},
            ).json()

    response = admin_client.get(
            f"/api/v1/admin/devices/{created['id']}/status-events"
            )

    assert response.status_code == 200
    assert response.json() == []


def test_rejects_status_events_for_missing_device(
        admin_client: TestClient,
        ) -> None:
    response = admin_client.get(
            "/api/v1/admin/devices/999/status-events"
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_status_events_require_authentication(
        api_client: TestClient,
        ) -> None:
    response = api_client.get("/api/v1/admin/devices/1/status-events")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication Required"}

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import Device, DeviceStatusEvent, User


ACTIVITY_URL = "/api/v1/admin/status-events"


def seed_activity(factory: sessionmaker[Session], count: int = 60) -> tuple[int, int]:
    with factory.begin() as session:
        first = Device(name="Pi 100%_ready", host="first.local", guest_visible=True)
        second = Device(name="Private NAS", host="nas.local")
        session.add_all([first, second])
        session.flush()
        for index in range(count):
            session.add(DeviceStatusEvent(
                    device_id=first.id if index % 2 == 0 else second.id,
                    previous_status="online" if index % 2 else "offline",
                    new_status="offline" if index % 2 else "online",
                    occurred_at=datetime(2026, 10, 13, 12, tzinfo=timezone.utc) + timedelta(minutes=index),
                    ))
    return first.id, second.id


def test_activity_is_paginated_and_newest_first(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    seed_activity(test_session_factory)
    response = admin_client.get(ACTIVITY_URL)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["total"] == 60
    assert data["page"] == 1
    assert data["limit"] == 25
    assert len(data["items"]) == 25
    assert [item["id"] for item in data["items"]] == list(range(60, 35, -1))
    assert data["items"][0]["name"] == "Private NAS"
    assert data["items"][0]["host"] == "nas.local"
    assert data["items"][0]["occurred_at"] == "2026-10-13T12:59:00Z"


def test_activity_pagination_snapshot_excludes_new_records(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    first_id, _ = seed_activity(test_session_factory)
    first = admin_client.get(ACTIVITY_URL, params={"limit": 25}).json()
    with test_session_factory.begin() as session:
        session.add(DeviceStatusEvent(
                device_id=first_id,
                previous_status="unknown",
                new_status="online",
                occurred_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
                ))
    second = admin_client.get(ACTIVITY_URL, params={
            "limit": 25, "page": 2, "snapshot_id": first["snapshot_id"],
            }).json()
    assert second["total"] == 60
    assert [item["id"] for item in second["items"]] == list(range(35, 10, -1))
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
    latest = admin_client.get(ACTIVITY_URL).json()
    assert latest["total"] == 61
    assert latest["items"][0]["id"] == 61


def test_activity_filters_combine_device_status_search_and_utc_date_bounds(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    first_id, _ = seed_activity(test_session_factory)
    response = admin_client.get(ACTIVITY_URL, params={
            "device_id": first_id,
            "new_status": "online",
            "q": "FIRST.LOCAL",
            "start": "2026-10-13T14:10:00+02:00",
            "end": "2026-10-13T12:14:00Z",
            })
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["id"] for item in data["items"]] == [15, 13, 11]
    assert all(item["device_id"] == first_id and item["new_status"] == "online" for item in data["items"])


@pytest.mark.parametrize("search, expected", [("100%_", 30), ("Private", 30), ("not-found", 0)])
def test_activity_search_uses_literal_substrings(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        search: str,
        expected: int,
        ) -> None:
    seed_activity(test_session_factory)
    data = admin_client.get(ACTIVITY_URL, params={"q": search}).json()
    assert data["total"] == expected


def test_activity_orders_timestamp_then_id_and_clamps_deleted_pages(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    first_id, _ = seed_activity(test_session_factory, count=2)
    with test_session_factory.begin() as session:
        session.add_all([
                DeviceStatusEvent(device_id=first_id, previous_status="online", new_status="offline", occurred_at=datetime(2026, 10, 13, 11)),
                DeviceStatusEvent(device_id=first_id, previous_status="offline", new_status="online", occurred_at=datetime(2026, 10, 13, 12, 1)),
                ])
    data = admin_client.get(ACTIVITY_URL).json()
    assert [item["id"] for item in data["items"]] == [4, 2, 1, 3]
    assert admin_client.delete(f"/api/v1/admin/devices/{first_id}").status_code == 204
    response = admin_client.get(ACTIVITY_URL, params={"page": 3, "limit": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert [item["id"] for item in data["items"]] == [2]


def test_activity_empty_snapshot_and_missing_device_filter(
        admin_client: TestClient,
        ) -> None:
    response = admin_client.get(ACTIVITY_URL)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "limit": 25, "snapshot_id": 0}
    assert admin_client.get(ACTIVITY_URL, params={"snapshot_id": 0}).json()["items"] == []
    assert admin_client.get(ACTIVITY_URL, params={"device_id": 999}).json()["items"] == []


@pytest.mark.parametrize("params", [
        {"limit": 0}, {"limit": 101}, {"page": 0}, {"page": 1_000_001},
        {"device_id": -1}, {"new_status": "invalid"}, {"snapshot_id": -1},
        {"q": "x" * 101}, {"start": "invalid"},
        {"snapshot_id": 2**63}, {"device_id": 2**63},
        {"start": "2026-10-14T00:00:00Z", "end": "2026-10-13T00:00:00Z"},
        ])
def test_activity_rejects_invalid_filters(admin_client: TestClient, params: dict) -> None:
    response = admin_client.get(ACTIVITY_URL, params=params)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_activity_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(ACTIVITY_URL)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_activity_blocks_required_password_change_and_revoked_session(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory.begin() as session:
        owner = session.scalar(select(User).where(User.role == "owner"))
        owner.must_change_password = True
    assert admin_client.get(ACTIVITY_URL).status_code == 403
    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).session_secret = "revoked"
    assert admin_client.get(ACTIVITY_URL).status_code == 401

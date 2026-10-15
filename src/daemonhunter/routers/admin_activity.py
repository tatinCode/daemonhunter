from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from daemonhunter.auth import SessionDependency, require_ready_admin
from daemonhunter.models import Device, DeviceStatusEvent
from daemonhunter.schemas import StatusActivityItem, StatusActivityPage


router = APIRouter(
        prefix="/api/v1/admin",
        tags=["admin-activity"],
        dependencies=[Depends(require_ready_admin)],
        )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/status-events", response_model=StatusActivityPage)
def list_status_activity(
        session: SessionDependency,
        device_id: Annotated[int | None, Query(ge=1, le=9_223_372_036_854_775_807)] = None,
        new_status: Literal["online", "offline", "unknown"] | None = None,
        q: Annotated[str, Query(max_length=100)] = "",
        start: datetime | None = None,
        end: datetime | None = None,
        page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        snapshot_id: Annotated[int | None, Query(ge=0, le=9_223_372_036_854_775_807)] = None,
        ) -> StatusActivityPage:
    start = as_utc(start) if start is not None else None
    end = as_utc(end) if end is not None else None
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="Start must not be after end")

    if snapshot_id is None:
        snapshot_id = session.scalar(select(func.max(DeviceStatusEvent.id))) or 0
    statement = (
            select(DeviceStatusEvent, Device.name, Device.host)
            .join(Device, Device.id == DeviceStatusEvent.device_id)
            .where(DeviceStatusEvent.id <= snapshot_id)
            )
    if device_id is not None:
        statement = statement.where(DeviceStatusEvent.device_id == device_id)
    if new_status is not None:
        statement = statement.where(DeviceStatusEvent.new_status == new_status)
    if q.strip():
        statement = statement.where(or_(
                Device.name.icontains(q.strip(), autoescape=True),
                Device.host.icontains(q.strip(), autoescape=True),
                ))
    if start is not None:
        statement = statement.where(DeviceStatusEvent.occurred_at >= start)
    if end is not None:
        statement = statement.where(DeviceStatusEvent.occurred_at <= end)

    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    page = min(page, max(1, (total + limit - 1) // limit))
    rows = session.execute(
            statement.order_by(
                DeviceStatusEvent.occurred_at.desc(),
                DeviceStatusEvent.id.desc(),
                )
            .offset((page - 1) * limit)
            .limit(limit)
            ).all()
    return StatusActivityPage(
            items=[
                StatusActivityItem(
                    id=event.id,
                    device_id=event.device_id,
                    name=name,
                    host=host,
                    previous_status=event.previous_status,
                    new_status=event.new_status,
                    occurred_at=as_utc(event.occurred_at),
                    )
                for event, name, host in rows
                ],
            total=total,
            page=page,
            limit=limit,
            snapshot_id=snapshot_id,
            )

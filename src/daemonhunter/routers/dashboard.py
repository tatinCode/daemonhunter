from datetime import datetime, timezone
from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from daemonhunter.auth import SessionDependency, get_current_user
from daemonhunter.models import Device, DeviceStatusEvent, User


router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(
        directory=Path(__file__).resolve().parents[1] / "templates",
        )


def utc_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def dashboard_data(
        request: Request,
        session: SessionDependency,
        selected_id: int | None = None,
        ) -> dict:
    try:
        user = get_current_user(request, session)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        user = None

    can_manage = user is not None and not user.must_change_password
    statement = select(Device).order_by(Device.name, Device.id)
    if not can_manage:
        statement = statement.where(Device.guest_visible.is_(True))
    devices = session.scalars(statement).all()
    visible_ids = {device.id for device in devices}
    if selected_id not in visible_ids:
        selected_id = devices[0].id if devices else None

    events = []
    selected_events = []
    last_changes = {}
    if can_manage:
        last_changes = dict(session.execute(
                select(DeviceStatusEvent.device_id, func.max(DeviceStatusEvent.occurred_at))
                .group_by(DeviceStatusEvent.device_id)
                ).all())
        event_rows = session.execute(
                select(DeviceStatusEvent, Device.name, Device.host)
                .join(Device, Device.id == DeviceStatusEvent.device_id)
                .order_by(DeviceStatusEvent.id.desc())
                .limit(50)
                ).all()
        events = [
                {
                    "id": event.id,
                    "device_id": event.device_id,
                    "name": name,
                    "host": host,
                    "previous_status": event.previous_status,
                    "new_status": event.new_status,
                    "occurred_at": utc_timestamp(event.occurred_at),
                    }
                for event, name, host in event_rows
                ]
        selected_events = [
                {
                    "id": event.id,
                    "previous_status": event.previous_status,
                    "new_status": event.new_status,
                    "occurred_at": utc_timestamp(event.occurred_at),
                    }
                for event in session.scalars(
                    select(DeviceStatusEvent)
                    .where(DeviceStatusEvent.device_id == selected_id)
                    .order_by(DeviceStatusEvent.id.desc())
                    .limit(50)
                    )
                ] if selected_id is not None else []

    rows = []
    for device in devices:
        row = {
                "id": device.id,
                "name": device.name,
                "host": device.host,
                "status": device.status,
                }
        if can_manage:
            row.update(
                    guest_visible=device.guest_visible,
                    consecutive_failures=device.consecutive_failures,
                    last_status_change=utc_timestamp(last_changes.get(device.id)),
                    )
        rows.append(row)

    counts = {status: sum(d.status == status for d in devices)
              for status in ("online", "offline", "unknown")}
    return {
            "devices": rows,
            "counts": {
                "total": len(rows),
                **counts,
                "attention": counts["offline"] + counts["unknown"],
                },
            "events": events,
            "selected_events": selected_events,
            "selected_id": selected_id,
            "can_manage": can_manage,
            "user": {
                "username": user.username,
                "role": user.role,
                "must_change_password": user.must_change_password,
                } if user is not None else None,
            "setup_required": session.scalar(
                select(User.id).where(User.role == "owner")
                ) is None,
            "refreshed_at": utc_timestamp(datetime.now(timezone.utc)),
            }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: SessionDependency) -> HTMLResponse:
    return render_page(request, session, "overview")


def render_page(
        request: Request,
        session: SessionDependency,
        page: str,
        selected_id: int | None = None,
        ) -> HTMLResponse:
    state = dashboard_data(request, session, selected_id)
    status_code = 200
    if page in {"account", "users"} and state["user"] is None:
        status_code = 401
    elif page == "users" and not (
            state["can_manage"] and state["user"]["role"] == "owner"
            ):
        status_code = 403
    return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "state": state,
                "page": page,
                },
            headers={"Cache-Control": "no-store"},
            status_code=status_code,
            )


@router.get("/devices", response_class=HTMLResponse)
def dashboard_devices(
        request: Request,
        session: SessionDependency,
        selected_id: Annotated[int | None, Query(ge=1)] = None,
        ) -> HTMLResponse:
    return render_page(request, session, "devices", selected_id)


@router.get("/activity", response_class=HTMLResponse)
def dashboard_activity(request: Request, session: SessionDependency) -> HTMLResponse:
    return render_page(request, session, "activity")


@router.get("/account", response_class=HTMLResponse)
def dashboard_account(request: Request, session: SessionDependency) -> HTMLResponse:
    return render_page(request, session, "account")


@router.get("/users", response_class=HTMLResponse)
def dashboard_users(request: Request, session: SessionDependency) -> HTMLResponse:
    return render_page(request, session, "users")


@router.get("/dashboard/state", response_class=JSONResponse)
def dashboard_state(
        request: Request,
        session: SessionDependency,
        selected_id: Annotated[int | None, Query(ge=1)] = None,
        ) -> JSONResponse:
    return JSONResponse(
            dashboard_data(request, session, selected_id),
            headers={"Cache-Control": "no-store"},
            )

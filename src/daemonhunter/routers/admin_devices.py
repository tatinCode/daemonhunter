from typing import Annotated

from fastapi import (
        APIRouter,
        Depends,
        HTTPException,
        Response,
        status,
        )
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from daemonhunter.database import get_session
from daemonhunter.models import Device
from daemonhunter.schemas import (
        DeviceCreate,
        DeviceResponse,
        DeviceUpdate,
        )


router = APIRouter(
        prefix="/api/v1/admin",
        tags=["admin-devices"],
        )

SessionDependency = Annotated[Session, Depends(get_session)]


def get_device_or_404(
        session: Session,
        device_id: int,
        ) -> Device:
    device = session.get(Device, device_id)

    if device is None:
        raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found",
                )

    return device


@router.post(
        "/devices",
        response_model=DeviceResponse,
        status_code=status.HTTP_201_CREATED,
        )
def create_device(
        device_data: DeviceCreate,
        session: SessionDependency
        ) -> Device:
    device = Device(**device_data.model_dump())
    session.add(device)

    try:
        session.commit()

    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A device with this name or host already exists",
                ) from error

    session.refresh(device)
    return device


@router.get("/devices/{device_id}", response_model=DeviceResponse)
def retrieve_device(
        device_id: int,
        session: SessionDependency,
        ) -> Device:
    return get_device_or_404(session, device_id)


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(session: SessionDependency) -> list[Device]:
    statement = select(Device).order_by(Device.id)

    return list(session.scalars(statement))


@router.patch(
        "/devices/{device_id}",
        response_model=DeviceResponse,
        )
def update_device(
        device_id: int,
        device_data: DeviceUpdate,
        session: SessionDependency,
        ) -> Device:
    device = get_device_or_404(session, device_id)

    for field, value in device_data.model_dump(
            exclude_unset=True
            ).items():
        setattr(device, field, value)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A device with this name or host already exists",
        ) from error

    session.refresh(device)

    return device


@router.delete(
        "/devices/{device_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        )
def delete_device(
        device_id: int,
        session: SessionDependency,
        ) -> Response:
    device = get_device_or_404(session, device_id)

    session.delete(device)
    session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

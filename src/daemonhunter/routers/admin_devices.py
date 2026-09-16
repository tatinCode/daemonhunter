from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from daemonhunter.database import get_session
from daemonhunter.models import Device
from daemonhunter.schemas import DeviceCreate, DeviceResponse


router = APIRouter(
        prefix="/api/v1/admin",
        tags=["admin-devices"],
        )

SessionDependency = Annotated[Session, Depends(get_session)]


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


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(session: SessionDependency) -> list[Device]:
    statement = select(Device).order_by(Device.id)

    return list(session.scalars(statement))

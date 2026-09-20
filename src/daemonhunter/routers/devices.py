from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from daemonhunter.database import get_session
from daemonhunter.models import Device
from daemonhunter.schemas import PublicDeviceResponse


router = APIRouter(
        prefix="/api/v1/device",
        tags=["Devices"],
        )


SessionDependency = Annotated[Session, Depends(get_session)]


@router.get(
        "",
        response_model=list[PublicDeviceResponse],
        )
def list_public_devices(
        session: SessionDependency,
        ) -> list[Device]:
    statement = (
            select(Device)
            .where(Device.guest_visible.is_(True))
            .order_by(Device.id)
            )

    return list(session.scalars(statement))


@router.get(
        "/{device_id}",
        response_model=PublicDeviceResponse,
        )
def retrieve_public_device(
        device_id: int,
        session: SessionDependency,
        ) -> Device:
    statement = select(Device).where(
            Device.id == device_id,
            Device.guest_visible.is_(True),
            )

    device = session.scalar(statement)

    if device is None:
        raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found",
                )

    return device

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


DeviceName = Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
        ]

DeviceHost = Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
        ]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class DeviceCreate(BaseModel):
    name: DeviceName
    host: DeviceHost
    guest_visible: bool = False


class DeviceUpdate(BaseModel):
    name: DeviceName | None = None
    host: DeviceHost | None = None
    guest_visible: bool | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    status: Literal["unknown", "online", "offline"]
    guest_visible: bool
    created_at: datetime
    updated_at: datetime

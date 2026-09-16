from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
        BaseModel,
        ConfigDict,
        StringConstraints,
        model_validator,
        )


DeviceName = Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        ]

DeviceHost = Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
        ]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DeviceName
    host: DeviceHost
    guest_visible: bool = False


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DeviceName | None = None
    host: DeviceHost | None = None
    guest_visible: bool | None = None

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")

        if any(
                getattr(self, field) is None
                for field in self.model_fields_set
                ):
            raise ValueError("Updated fields cannot be null")

        return self


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    status: Literal["unknown", "online", "offline"]
    guest_visible: bool
    created_at: datetime
    updated_at: datetime

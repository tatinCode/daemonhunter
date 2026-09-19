from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        SecretStr,
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

UserName = Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=100,
            ),
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


class OwnerSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    password: SecretStr = Field(
            min_length=12,
            max_lenght=128,
            )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    password: SecretStr = Field(
            min_lenght=1,
            max_length=128,
            )


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(
            min_lenght=1,
            max_length=128,
            )

    new_password: SecretStr = Field(
            min_lenght=12,
            max_length=128,
            )


class AdminCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    temporary_password: SecretStr = Field(
            min_lenght=12,
            max_length=128,
            )


class AdminUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName | None = None
    active: bool | None = None

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


class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    temporary_password: SecretStr = Field(
            min_lenght=12,
            max_length=128,
            )


class OwnerShipTransferRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["owner", "admin"]
    active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class SetupStatusResponse(BaseModel):
    setup_required: bool


class PublicDeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    status: Literal["unknown", "offline", "online"]

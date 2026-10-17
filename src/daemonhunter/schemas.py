from datetime import datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        SecretStr,
        StringConstraints,
        model_validator,
        field_validator,
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

MetricPercentage = Annotated[
        float,
        Field(
            strict=True,
            ge=0,
            le=100,
            allow_inf_nan=False,
            ),
        ]

MetricCount = Annotated[
        int,
        Field(
            strict=True,
            ge=0,
            le=9223372036854775807,
            ),
        ]

MetricTemperature = Annotated[
        float,
        Field(
            strict=True,
            allow_inf_nan=False,
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


class DeviceStatusEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    previous_status: Literal["unknown", "online", "offline"]
    new_status: Literal["unknown", "online", "offline"]
    occurred_at: datetime


class StatusActivityItem(DeviceStatusEventResponse):
    name: str
    host: str


class StatusActivityPage(BaseModel):
    items: list[StatusActivityItem]
    total: int
    page: int
    limit: int
    snapshot_id: int


class OwnerSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    password: SecretStr = Field(
            min_length=12,
            max_length=128,
            )
    setup_token: SecretStr = Field(
            min_length=32,
            max_length=256,
            )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    password: SecretStr = Field(
            min_length=1,
            max_length=128,
            )


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(
            min_length=1,
            max_length=128,
            )

    new_password: SecretStr = Field(
            min_length=12,
            max_length=128,
            )


class AdminCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: UserName
    temporary_password: SecretStr = Field(
            min_length=12,
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

    temporary_password: SecretStr = Field(
            min_length=12,
            max_length=128,
            )


class OwnershipTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(
            min_length=1,
            max_length=128,
            )
    confirm_username: UserName


class SetupStatusResponse(BaseModel):
    setup_required: bool


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: Literal["owner", "admin"]
    active: bool
    must_change_password: bool
    updated_at: datetime
    created_at: datetime


class PublicDeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    status: Literal["unknown", "offline", "online"]


class AgentMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=255,
                ),
            ]
    os: Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=64,
                ),
            ]
    cpu_percent: MetricPercentage
    memory_percent: MetricPercentage
    memory_total: MetricCount
    memory_used: MetricCount
    disk_percent: MetricPercentage
    disk_total: MetricCount
    disk_used: MetricCount
    temperature_celsius: MetricTemperature | None = None
    uptime_seconds: MetricCount

    @model_validator(mode="after")
    def validate_sizes(self) -> Self:
        if self.memory_used > self.memory_total:
            raise ValueError("memory_used cannot exceed memory_total")

        if self.disk_used > self.disk_total:
            raise ValueError("disk_used cannot exceed disk_total")

        return self


class DeviceMetricsResponse(AgentMetricsRequest):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)


class AgentTokenResponse(BaseModel):
    device_id: int
    agent_token: str = Field(repr=False)
    issued_at: datetime

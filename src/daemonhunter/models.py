from datetime import datetime

from sqlalchemy import (
        Boolean,
        BigInteger,
        Float,
        UniqueConstraint,
        Integer,
        CheckConstraint,
        ForeignKey,
        DateTime,
        Index,
        String,
        false,
        func,
        text,
        true,
        )
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional

from daemonhunter.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
            CheckConstraint(
                "role IN ('owner', 'admin')",
                name="ck_users_role",
                ),
            Index(
                "uq_users_single_owner",
                "role",
                unique=True,
                sqlite_where=text("role = 'owner'"),
                ),
            )

    id: Mapped[int] = mapped_column(primary_key=True)

    version_id: Mapped[int] = mapped_column(
            Integer,
            default=1,
            server_default=text("1"),
            nullable=False,
            )

    __mapper_args__ = {
            "version_id_col": version_id,
            }

    username: Mapped[str] = mapped_column(
            String(100),
            unique=True,
            )
    password_hash: Mapped[str] = mapped_column(String(255))
    session_secret: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))

    active: Mapped[bool] = mapped_column(
            Boolean,
            default=True,
            server_default=true(),
            )
    must_change_password: Mapped[bool] = mapped_column(
            Boolean,
            default=True,
            server_default=true(),
            )

    created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            )
    updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            )


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
            CheckConstraint(
                "status IN ('unknown', 'online', 'offline')",
                name="ck_devices_status",
                ),
            CheckConstraint(
                "consecutive_failures >= 0",
                name="ck_devices_consecutive_failures_nonnegative",
                ),
            )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    host: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(
            String(16),
            default="unknown",
            server_default="unknown",
            )

    consecutive_failures: Mapped[int] = mapped_column(
            Integer,
            default=0,
            server_default=text("0"),
            nullable=False,
            )

    created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            )

    updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            )

    guest_visible: Mapped[bool] = mapped_column(
            Boolean,
            default=False,
            server_default=false(),
            )

    status_events: Mapped[list["DeviceStatusEvent"]] = relationship(
            back_populates="device",
            cascade="all, delete-orphan",
            )

    agent_credential: Mapped[Optional["DeviceAgentCredential"]] = relationship(
            back_populates="device",
            cascade="all, delete-orphan",
            uselist=False,
            )
    latest_metrics: Mapped[Optional["DeviceMetrics"]] = relationship(
            back_populates="device",
            cascade="all, delete-orphan",
            uselist=False,
            )


class DeviceStatusEvent(Base):
    __tablename__ = "device_status_events"
    __table_args__ = (
            CheckConstraint(
                "previous_status IN ('unknown', 'online', 'offline')",
                name="ck_device_status_events_previous_status",
            ),
            CheckConstraint(
                "new_status IN ('unknown', 'online', 'offline')",
                name="ck_device_status_events_new_status",
            ),
            CheckConstraint(
                "previous_status <> new_status",
                name="ck_device_status_events_changed",
            ),
            Index(
                "ix_device_status_events_device_id_id",
                "device_id",
                "id",
                ),
            )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
            ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            )
    previous_status: Mapped[str] = mapped_column(
            String(16),
            nullable=False,
            )
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            )

    device: Mapped[Device] = relationship(back_populates="status_events")


class DeviceAgentCredential(Base):
    __tablename__ = "device_agent_credentials"
    __table_args__ = (
            UniqueConstraint(
                "token_hash",
                name="uq_device_agent_credentials_token_hash",
                ),
            CheckConstraint(
                "token_hash IS NULL OR length(token_hash) = 64",
                name="ck_device_agent_credentials_token_hash_length",
                ),
            )

    device_id: Mapped[int] = mapped_column(
            ForeignKey("devices.id", ondelete="CASCADE"),
            primary_key=True,
            )

    token_hash: Mapped[Optional[str]] = mapped_column(
            String(64),
            nullable=True,
            )

    issued_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
            DateTime(timezone=True),
            nullable=True,
            )

    device: Mapped[Device] = relationship(
            back_populates="agent_credential",
            )


class DeviceMetrics(Base):
    __tablename__ = "device_metrics"
    __table_args__ = (
            CheckConstraint(
                "cpu_percent >= 0 AND cpu_percent <= 100",
                name="ck_device_metrics_cpu_percent",
                ),
            CheckConstraint(
                "memory_percent >= 0 AND memory_percent <= 100",
                name="ck_device_metrics_memory_percent",
                ),
            CheckConstraint(
                "disk_percent >= 0 AND disk_percent <= 100",
                name="ck_device_metrics_disk_percent",
                ),
            CheckConstraint(
                "memory_total >= 0 AND memory_used >= 0 "
                "AND memory_used <= memory_total",
                name="ck_device_metrics_memory_sizes",
                ),
            CheckConstraint(
                "disk_total >= 0 AND disk_used >= 0 "
                "AND disk_used <= disk_total",
                name="ck_device_metrics_disk_sizes",
                ),
            CheckConstraint(
                "uptime_seconds >= 0",
                name="ck_device_metrics_uptime",
                ),
            )

    device_id: Mapped[int] = mapped_column(
            ForeignKey("devices.id", ondelete="CASCADE"),
            primary_key=True,
            )
    hostname: Mapped[str] = mapped_column(String(255))
    os: Mapped[str] = mapped_column(String(64))
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    memory_total: Mapped[int] = mapped_column(BigInteger)
    memory_used: Mapped[int] = mapped_column(BigInteger)
    disk_percent: Mapped[float] = mapped_column(Float)
    disk_total: Mapped[int] = mapped_column(BigInteger)
    disk_used: Mapped[int] = mapped_column(BigInteger)
    temperature_celsius: Mapped[Optional[float]] = mapped_column(
            Float,
            nullable=True,
            )
    uptime_seconds: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            )

    device: Mapped[Device] = relationship(
            back_populates="latest_metrics",
            )

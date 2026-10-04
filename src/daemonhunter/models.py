from datetime import datetime

from sqlalchemy import (
        Boolean,
        CheckConstraint,
        DateTime,
        Index,
        String,
        false,
        func,
        text,
        true,
        )
from sqlalchemy.orm import Mapped, mapped_column

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
            )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    host: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(
            String(16),
            default="unknown",
            server_default="unknown",
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

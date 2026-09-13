from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from daemonhunter.database import Base


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
    host: Mapped[str] = mapped_column(String(100), unique=True)
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

    guest_visible: Mapped(bool) = mapped_column(
            Boolean,
            default=True,
            server_default=false(),
            )

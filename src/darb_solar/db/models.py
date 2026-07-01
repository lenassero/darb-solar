"""SQLAlchemy ORM models for FusionSolar Postgres tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from darb_solar.db.types import DeviceRole, SyncWindowCheckpointStatus


class Base(DeclarativeBase):
    """Declarative base for FusionSolar ORM models."""


class Plant(Base):
    """Row stored in the ``plants`` table."""

    __tablename__ = "plants"

    plant_code: Mapped[str] = mapped_column(Text, primary_key=True)
    plant_name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="Africa/Casablanca",
    )


class Device(Base):
    """Row stored in the ``devices`` table."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "role IN ('inverter', 'meter')",
            name="devices_role_check",
        ),
        Index("idx_devices_plant_code", "plant_code"),
    )

    dev_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plant_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("plants.plant_code"),
        nullable=False,
    )
    dev_dn: Mapped[str] = mapped_column(Text, nullable=False)
    dev_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[DeviceRole] = mapped_column(
        Enum(DeviceRole, native_enum=False),
        nullable=False,
    )


class DevicePowerReading(Base):
    """Row stored in the ``device_power_readings`` table."""

    __tablename__ = "device_power_readings"
    __table_args__ = (
        Index("idx_device_power_readings_collected_at", "collected_at"),
    )

    dev_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("devices.dev_id"),
        primary_key=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    active_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PlantPowerReading(Base):
    """Row stored in the ``plant_power_readings`` table."""

    __tablename__ = "plant_power_readings"
    __table_args__ = (
        Index("idx_plant_power_readings_collected_at", "collected_at"),
    )

    plant_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("plants.plant_code"),
        primary_key=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    pv_production_kw: Mapped[float] = mapped_column(Float, nullable=False)
    grid_export_kw: Mapped[float] = mapped_column(Float, nullable=False)
    consumption_kw: Mapped[float] = mapped_column(Float, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SyncWindow(Base):
    """Row stored in the ``sync_windows`` table.

    The ``status`` field uses ``SyncWindowCheckpointStatus`` only; run-only
    outcomes such as ``skipped`` never appear here.
    """

    __tablename__ = "sync_windows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'failed')",
            name="sync_windows_status_check",
        ),
        Index("idx_sync_windows_status", "status"),
    )

    dev_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("devices.dev_id"),
        primary_key=True,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[SyncWindowCheckpointStatus] = mapped_column(
        Enum(SyncWindowCheckpointStatus, native_enum=False),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

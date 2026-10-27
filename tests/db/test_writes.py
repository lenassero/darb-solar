"""Tests for ``darb_solar.db.writes``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest
from pytest_mock import MockType
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from darb_solar.db import writes
from darb_solar.db.models import (
    Base,
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
)
from darb_solar.db.types import SyncWindowCheckpointStatus

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _compile(statement: ClauseElement) -> str:
    """Return the Postgres SQL of `statement` as a single-spaced string.

    Parameters
    ----------
    statement : sqlalchemy.sql.ClauseElement
        Upsert statement to compile.

    Returns
    -------
    str
        Compiled SQL text.
    """
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def _device_power_reading() -> DevicePowerReading:
    return DevicePowerReading(
        dev_id="1000000001",
        collected_at=NOW,
        active_power_kw=3.5,
        synced_at=NOW,
    )


def _plant_power_reading() -> PlantPowerReading:
    return PlantPowerReading(
        plant_code="NE=12345678",
        collected_at=NOW,
        pv_production_kw=4.0,
        grid_export_kw=1.0,
        consumption_kw=3.0,
        synced_at=NOW,
    )


def _sync_window() -> SyncWindow:
    return SyncWindow(
        dev_id="1000000001",
        window_start=NOW,
        window_end=NOW,
        status=SyncWindowCheckpointStatus.PENDING,
        error_message=None,
        updated_at=NOW,
    )


def test_as_mapping_returns_every_column_value(inverter: Device) -> None:
    """All mapped columns are returned, including unset ones as ``None``."""
    mapping = writes._as_mapping(inverter)

    assert mapping == {
        "dev_id": inverter.dev_id,
        "plant_code": inverter.plant_code,
        "dev_dn": inverter.dev_dn,
        "dev_type_id": inverter.dev_type_id,
        "role": inverter.role,
    }


def test_as_mapping_includes_unset_columns_as_none() -> None:
    """Columns that were never assigned map to ``None``."""
    mapping = writes._as_mapping(Plant(plant_code="NE=1", plant_name="Plant"))

    assert mapping == {"plant_code": "NE=1", "plant_name": "Plant", "timezone": None}


def test_upsert_executes_statement_with_mapping(
    db_session: MockType,
    plant: Plant,
) -> None:
    """The private helper passes the statement and the instance mapping."""
    statement = object()

    writes._upsert(db_session, statement, plant)

    db_session.execute.assert_called_once_with(statement, writes._as_mapping(plant))


@pytest.mark.parametrize(
    ("upsert", "statement_name", "instance_factory"),
    [
        (writes.upsert_plant, "_PLANT_UPSERT", lambda: Plant(plant_code="NE=1")),
        (
            writes.upsert_device,
            "_DEVICE_UPSERT",
            lambda: Device(dev_id="1", plant_code="NE=1"),
        ),
        (
            writes.upsert_device_power_reading,
            "_DEVICE_POWER_READING_UPSERT",
            _device_power_reading,
        ),
        (
            writes.upsert_plant_power_reading,
            "_PLANT_POWER_READING_UPSERT",
            _plant_power_reading,
        ),
        (writes.upsert_sync_window, "_SYNC_WINDOW_UPSERT", _sync_window),
    ],
)
def test_public_upserts_execute_matching_statement(
    db_session: MockType,
    upsert: Callable[[Any, Any], None],
    statement_name: str,
    instance_factory: Callable[[], Base],
) -> None:
    """Each public upsert executes its own statement with the row mapping."""
    instance = instance_factory()

    upsert(db_session, instance)

    db_session.execute.assert_called_once_with(
        getattr(writes, statement_name),
        writes._as_mapping(instance),
    )


@pytest.mark.parametrize(
    ("statement_name", "conflict_target", "updated_columns"),
    [
        ("_PLANT_UPSERT", "plant_code", ["plant_name", "timezone"]),
        (
            "_DEVICE_UPSERT",
            "dev_id",
            ["plant_code", "dev_dn", "dev_type_id", "role"],
        ),
        (
            "_DEVICE_POWER_READING_UPSERT",
            "dev_id, collected_at",
            ["active_power_kw", "synced_at"],
        ),
        (
            "_PLANT_POWER_READING_UPSERT",
            "plant_code, collected_at",
            [
                "pv_production_kw",
                "grid_export_kw",
                "consumption_kw",
                "synced_at",
            ],
        ),
        (
            "_SYNC_WINDOW_UPSERT",
            "dev_id, window_start",
            ["window_end", "status", "error_message", "updated_at"],
        ),
    ],
)
def test_upsert_statements_compile_to_on_conflict_do_update(
    statement_name: str,
    conflict_target: str,
    updated_columns: list[str],
) -> None:
    """Each statement conflicts on its primary key and updates its value columns."""
    sql = _compile(getattr(writes, statement_name))

    assert f"ON CONFLICT ({conflict_target}) DO UPDATE SET" in sql
    update_clause = sql.split("DO UPDATE SET", 1)[1]
    for column in updated_columns:
        assert f"{column} = excluded.{column}" in update_clause
    assert update_clause.count("excluded.") == len(updated_columns)

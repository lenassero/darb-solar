"""Tests for ``darb_solar.db.reads``."""

from __future__ import annotations

from datetime import datetime, timezone

from pytest_mock import MockType
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from darb_solar.db import reads
from darb_solar.db.models import Device, DevicePowerReading, Plant, SyncWindow

DEV_ID = "1000000001"
PLANT_CODE = "NE=12345678"
START = datetime(2026, 6, 1, tzinfo=timezone.utc)
END = datetime(2026, 6, 2, tzinfo=timezone.utc)


def _compile(statement: ClauseElement) -> str:
    """Return the Postgres SQL of `statement` with bound parameters inlined.

    Parameters
    ----------
    statement : sqlalchemy.sql.ClauseElement
        Statement passed to a mocked session method.

    Returns
    -------
    str
        Compiled SQL text with a single space between tokens.
    """
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).split())


def test_get_plant_returns_scalar_result(db_session: MockType, plant: Plant) -> None:
    """The plant is selected by ``plant_code`` and returned unchanged."""
    db_session.scalar.return_value = plant

    assert reads.get_plant(db_session, PLANT_CODE) is plant

    (statement,), _ = db_session.scalar.call_args
    sql = _compile(statement)
    assert "FROM plants" in sql
    assert f"WHERE plants.plant_code = '{PLANT_CODE}'" in sql


def test_get_plant_returns_none_when_missing(db_session: MockType) -> None:
    """A missing plant yields ``None``."""
    db_session.scalar.return_value = None

    assert reads.get_plant(db_session, PLANT_CODE) is None


def test_list_devices_orders_by_role_then_dev_id(
    db_session: MockType,
    inverter: Device,
    meter: Device,
) -> None:
    """Devices are filtered by plant and returned as a list."""
    db_session.scalars.return_value = iter([inverter, meter])

    devices = reads.list_devices(db_session, plant_code=PLANT_CODE)

    assert devices == [inverter, meter]
    (statement,), _ = db_session.scalars.call_args
    sql = _compile(statement)
    assert f"WHERE devices.plant_code = '{PLANT_CODE}'" in sql
    assert "ORDER BY devices.role, devices.dev_id" in sql


def test_get_sync_window_filters_on_device_and_start(db_session: MockType) -> None:
    """The checkpoint is selected by its composite primary key."""
    checkpoint = SyncWindow(dev_id=DEV_ID, window_start=START)
    db_session.scalar.return_value = checkpoint

    assert reads.get_sync_window(db_session, DEV_ID, START) is checkpoint

    (statement,), _ = db_session.scalar.call_args
    sql = _compile(statement)
    assert "FROM sync_windows" in sql
    assert f"sync_windows.dev_id = '{DEV_ID}'" in sql
    assert "sync_windows.window_start = '2026-06-01 00:00:00+00:00'" in sql


def test_get_latest_collected_at_takes_newest_reading(db_session: MockType) -> None:
    """The newest ``collected_at`` is selected with a descending limit of one."""
    db_session.scalar.return_value = END

    assert reads.get_latest_collected_at(db_session, DEV_ID) == END

    (statement,), _ = db_session.scalar.call_args
    sql = _compile(statement)
    assert sql.startswith("SELECT device_power_readings.collected_at FROM")
    assert f"WHERE device_power_readings.dev_id = '{DEV_ID}'" in sql
    assert "ORDER BY device_power_readings.collected_at DESC" in sql
    assert "LIMIT 1" in sql


def test_get_latest_collected_at_returns_none_without_readings(
    db_session: MockType,
) -> None:
    """A device without readings yields ``None``."""
    db_session.scalar.return_value = None

    assert reads.get_latest_collected_at(db_session, DEV_ID) is None


def test_get_latest_plant_collected_at_uses_max_in_half_open_range(
    db_session: MockType,
) -> None:
    """The aggregate is bounded by ``[collected_from, collected_to)``."""
    db_session.scalar.return_value = START

    result = reads.get_latest_plant_collected_at(
        db_session,
        plant_code=PLANT_CODE,
        collected_from=START,
        collected_to=END,
    )

    assert result == START
    (statement,), _ = db_session.scalar.call_args
    sql = _compile(statement)
    assert "max(plant_power_readings.collected_at)" in sql
    assert f"plant_power_readings.plant_code = '{PLANT_CODE}'" in sql
    assert "plant_power_readings.collected_at >= '2026-06-01 00:00:00+00:00'" in sql
    assert "plant_power_readings.collected_at < '2026-06-02 00:00:00+00:00'" in sql


def test_list_device_power_readings_orders_by_collected_at(
    db_session: MockType,
) -> None:
    """Readings are filtered on the half-open range and ordered by time."""
    readings = [
        DevicePowerReading(dev_id=DEV_ID, collected_at=START, active_power_kw=1.0),
        DevicePowerReading(dev_id=DEV_ID, collected_at=END, active_power_kw=2.0),
    ]
    db_session.scalars.return_value = iter(readings)

    result = reads.list_device_power_readings(
        db_session,
        dev_id=DEV_ID,
        collected_from=START,
        collected_to=END,
    )

    assert result == readings
    (statement,), _ = db_session.scalars.call_args
    sql = _compile(statement)
    assert f"device_power_readings.dev_id = '{DEV_ID}'" in sql
    assert "device_power_readings.collected_at >= '2026-06-01 00:00:00+00:00'" in sql
    assert "device_power_readings.collected_at < '2026-06-02 00:00:00+00:00'" in sql
    assert sql.endswith("ORDER BY device_power_readings.collected_at")

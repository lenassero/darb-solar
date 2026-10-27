"""Tests for ``darb_solar.intraday_sync.sync``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pytest_mock import MockerFixture, MockType

from darb_solar.db.models import Device, DevicePowerReading, Plant
from darb_solar.db.types import DeviceRole
from darb_solar.history_sync.types import (
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)
from darb_solar.intraday_sync import sync
from darb_solar.time import datetime_to_epoch_ms

UTC_NOW = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)


@pytest.fixture
def now(casablanca_tz: ZoneInfo) -> datetime:
    """Return the fixed plant-local "current" time used by the tests.

    Parameters
    ----------
    casablanca_tz : zoneinfo.ZoneInfo
        Plant-local timezone.

    Returns
    -------
    datetime.datetime
        ``2026-06-02 10:00`` in Casablanca.
    """
    return datetime(2026, 6, 2, 10, tzinfo=casablanca_tz)


@pytest.fixture
def get_session_mock(mocker: MockerFixture, db_session: MockType) -> MockType:
    """Patch ``get_session`` to yield the mock database session.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    db_session : pytest_mock.MockType
        Mock session yielded by the patched context manager.

    Returns
    -------
    pytest_mock.MockType
        Patched ``get_session``.
    """
    get_session = mocker.patch.object(sync, "get_session")
    get_session.return_value.__enter__.return_value = db_session
    return get_session


@pytest.fixture
def fixed_now(mocker: MockerFixture, now: datetime) -> MockType:
    """Freeze ``datetime.now`` as used by the intraday module.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    now : datetime.datetime
        Value returned by the patched ``datetime.now``.

    Returns
    -------
    pytest_mock.MockType
        Patched ``datetime`` class.
    """
    datetime_mock = mocker.patch.object(sync, "datetime")
    datetime_mock.now.return_value = now
    return datetime_mock


def _reading(dev_id: str, collected_at: datetime) -> DevicePowerReading:
    return DevicePowerReading(
        dev_id=dev_id,
        collected_at=collected_at,
        active_power_kw=1.0,
        synced_at=UTC_NOW,
    )


@pytest.mark.parametrize(
    ("latest_offset", "expected_start"),
    [
        pytest.param(None, "midnight", id="no-reading"),
        pytest.param(
            timedelta(days=-2, hours=2), "midnight", id="older-than-yesterday"
        ),
        pytest.param(timedelta(days=-1), "latest", id="exactly-start-of-yesterday"),
        pytest.param(timedelta(hours=-3), "latest", id="yesterday-night"),
        pytest.param(timedelta(hours=-1), "latest", id="today"),
    ],
)
def test_intraday_bounds(
    db_session: MockType,
    mocker: MockerFixture,
    inverter: Device,
    now: datetime,
    latest_offset: timedelta | None,
    expected_start: str,
) -> None:
    """Fetching starts at the latest reading from yesterday or today onward."""
    start_of_today = now.replace(hour=0)
    latest = None if latest_offset is None else start_of_today + latest_offset
    mocker.patch.object(sync, "get_latest_collected_at", return_value=latest)

    start_dt, end_dt = sync._intraday_bounds(db_session, inverter, now=now)

    assert start_dt == (start_of_today if expected_start == "midnight" else latest)
    assert end_dt == now


def test_intraday_bounds_queries_device_latest_reading(
    db_session: MockType,
    mocker: MockerFixture,
    inverter: Device,
    now: datetime,
) -> None:
    """The latest reading is looked up for the given device."""
    latest_mock = mocker.patch.object(
        sync,
        "get_latest_collected_at",
        return_value=None,
    )

    sync._intraday_bounds(db_session, inverter, now=now)

    latest_mock.assert_called_once_with(db_session, inverter.dev_id)


def test_plant_derive_bounds_uses_one_hour_lookback(now: datetime) -> None:
    """Plant derivation covers the last hour up to ``now``."""
    assert sync._plant_derive_bounds(now) == (now - timedelta(hours=1), now)


@pytest.fixture
def device_intraday_deps(mocker: MockerFixture) -> dict[str, MockType]:
    """Patch the collaborators of ``sync_device_intraday``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    dict[str, pytest_mock.MockType]
        Patched helpers keyed by function name.
    """
    names = [
        "_fetch_device_history",
        "history_records_to_readings",
        "upsert_device_power_reading",
    ]
    deps = {name: mocker.patch.object(sync, name) for name in names}
    deps["_fetch_device_history"].return_value = [{"collectTime": 1}]
    deps["history_records_to_readings"].return_value = ["r1", "r2", "r3"]
    mocker.patch.object(sync, "utc_now", return_value=UTC_NOW)
    return deps


def test_sync_device_intraday_skips_short_gap(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """A gap shorter than ``min_gap`` skips the device without any call."""
    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(minutes=4),
        end_dt=now,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.SKIPPED)
    device_intraday_deps["_fetch_device_history"].assert_not_called()
    db_session.begin_nested.assert_not_called()


def test_sync_device_intraday_syncs_gap_equal_to_minimum(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """A gap equal to ``min_gap`` is not skipped."""
    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(minutes=5),
        end_dt=now,
    )

    assert result.outcome is SyncRunOutcome.DONE


def test_sync_device_intraday_honors_custom_min_gap(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """A larger `min_gap` skips gaps that the default would sync."""
    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(minutes=10),
        end_dt=now,
        min_gap=timedelta(minutes=30),
    )

    assert result.outcome is SyncRunOutcome.SKIPPED


def test_sync_device_intraday_upserts_readings_in_savepoint(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """Readings are fetched for the gap and upserted inside a savepoint."""
    start_dt = now - timedelta(hours=1)

    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=start_dt,
        end_dt=now,
    )

    assert result == DeviceSyncResult(3, SyncRunOutcome.DONE)
    device_intraday_deps["_fetch_device_history"].assert_called_once_with(
        fusionsolar_session,
        inverter,
        start_ms=datetime_to_epoch_ms(start_dt),
        end_ms=datetime_to_epoch_ms(now),
    )
    device_intraday_deps["history_records_to_readings"].assert_called_once_with(
        [{"collectTime": 1}],
        dev_id=inverter.dev_id,
        dev_type_id=inverter.dev_type_id,
        synced_at=UTC_NOW,
        tz=casablanca_tz,
    )
    db_session.begin_nested.assert_called_once_with()
    assert device_intraday_deps["upsert_device_power_reading"].call_count == 3


def test_sync_device_intraday_reports_failure_when_savepoint_fails(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """A database error maps to FAILED instead of propagating."""
    db_session.begin_nested.side_effect = RuntimeError("savepoint failed")

    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(hours=1),
        end_dt=now,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.FAILED)
    device_intraday_deps["upsert_device_power_reading"].assert_not_called()


def test_sync_device_intraday_reports_failure_when_upsert_fails(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    casablanca_tz: ZoneInfo,
    now: datetime,
    device_intraday_deps: dict[str, MockType],
) -> None:
    """An upsert error inside the savepoint maps to FAILED."""
    device_intraday_deps["upsert_device_power_reading"].side_effect = RuntimeError(
        "constraint"
    )

    result = sync.sync_device_intraday(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(hours=1),
        end_dt=now,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.FAILED)
    exit_args = db_session.begin_nested.return_value.__exit__.call_args.args
    assert exit_args[0] is RuntimeError


def test_sync_plant_intraday_derives_and_upserts(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
) -> None:
    """Device readings in the range are joined into plant rows."""
    t0 = now - timedelta(minutes=30)
    list_readings = mocker.patch.object(
        sync,
        "list_device_power_readings",
        side_effect=[
            [_reading(inverter.dev_id, t0)],
            [_reading(meter.dev_id, t0)],
        ],
    )
    upsert = mocker.patch.object(sync, "upsert_plant_power_reading")
    mocker.patch.object(sync, "utc_now", return_value=UTC_NOW)
    collected_from = now - timedelta(hours=1)

    count = sync.sync_plant_intraday(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        collected_from=collected_from,
        collected_to=now,
    )

    assert count == 1
    assert list_readings.call_args_list == [
        mocker.call(
            db_session,
            dev_id=inverter.dev_id,
            collected_from=collected_from,
            collected_to=now,
        ),
        mocker.call(
            db_session,
            dev_id=meter.dev_id,
            collected_from=collected_from,
            collected_to=now,
        ),
    ]
    upsert.assert_called_once_with(db_session, mocker.ANY)
    plant_reading = upsert.call_args.args[1]
    assert plant_reading.plant_code == plant.plant_code
    assert plant_reading.synced_at == UTC_NOW


def test_sync_plant_intraday_returns_zero_without_overlap(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
) -> None:
    """No joined timestamps means no plant rows are written."""
    mocker.patch.object(
        sync,
        "list_device_power_readings",
        side_effect=[[_reading(inverter.dev_id, now)], []],
    )
    upsert = mocker.patch.object(sync, "upsert_plant_power_reading")

    count = sync.sync_plant_intraday(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        collected_from=now - timedelta(hours=1),
        collected_to=now,
    )

    assert count == 0
    upsert.assert_not_called()


def test_sync_intraday_devices_syncs_every_device(
    fusionsolar_session: MockType,
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
    casablanca_tz: ZoneInfo,
    fixed_now: MockType,
) -> None:
    """Without a role filter, every device is synced from its own bounds."""
    bounds = mocker.patch.object(
        sync,
        "_intraday_bounds",
        side_effect=lambda session, device, now: (now - timedelta(hours=1), now),
    )
    results = [
        DeviceSyncResult(3, SyncRunOutcome.DONE),
        DeviceSyncResult(0, SyncRunOutcome.SKIPPED),
    ]
    device_sync = mocker.patch.object(
        sync,
        "sync_device_intraday",
        side_effect=results,
    )

    device_results, derive_from, derive_to = sync.sync_intraday_devices(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        min_gap=timedelta(minutes=10),
    )

    assert device_results == results
    assert (derive_from, derive_to) == (now - timedelta(hours=1), now)
    fixed_now.now.assert_called_once_with(casablanca_tz)
    assert [call.args for call in bounds.call_args_list] == [
        (db_session, inverter),
        (db_session, meter),
    ]
    assert all(call.kwargs == {"now": now} for call in bounds.call_args_list)
    assert [call.args[2] for call in device_sync.call_args_list] == [inverter, meter]
    device_sync.assert_any_call(
        fusionsolar_session,
        db_session,
        inverter,
        tz=casablanca_tz,
        start_dt=now - timedelta(hours=1),
        end_dt=now,
        min_gap=timedelta(minutes=10),
    )


def test_sync_intraday_devices_filters_by_role(
    fusionsolar_session: MockType,
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
    fixed_now: MockType,
) -> None:
    """With `device_role`, only the matching device is synced."""
    mocker.patch.object(sync, "_intraday_bounds", return_value=(now, now))
    device_sync = mocker.patch.object(
        sync,
        "sync_device_intraday",
        return_value=DeviceSyncResult(1, SyncRunOutcome.DONE),
    )

    device_results, _, _ = sync.sync_intraday_devices(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        device_role=DeviceRole.METER,
    )

    assert len(device_results) == 1
    device_sync.assert_called_once()
    assert device_sync.call_args.args[2] is meter


@pytest.fixture
def intraday_deps(
    mocker: MockerFixture,
    get_session_mock: MockType,
    fusionsolar_session: MockType,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
) -> dict[str, MockType]:
    """Patch the collaborators of ``sync_intraday``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    get_session_mock : pytest_mock.MockType
        Patched ``get_session``.
    fusionsolar_session : pytest_mock.MockType
        Session returned by the patched login.
    plant : Plant
        Plant fixture returned by the patched config loader.
    inverter : Device
        Inverter fixture returned by the patched config loader.
    meter : Device
        Meter fixture returned by the patched config loader.
    now : datetime.datetime
        Upper derive bound returned by the patched device sync.

    Returns
    -------
    dict[str, pytest_mock.MockType]
        Patched helpers keyed by name.
    """
    derive_from = now - timedelta(hours=1)
    return {
        "login": mocker.patch.object(
            sync,
            "login_fusionsolar",
            return_value=fusionsolar_session,
        ),
        "load_plant_config": mocker.patch.object(
            sync,
            "load_plant_config",
            return_value=(plant, [inverter, meter]),
        ),
        "sync_intraday_devices": mocker.patch.object(
            sync,
            "sync_intraday_devices",
            return_value=(
                [
                    DeviceSyncResult(4, SyncRunOutcome.DONE),
                    DeviceSyncResult(0, SyncRunOutcome.SKIPPED),
                    DeviceSyncResult(0, SyncRunOutcome.FAILED),
                    DeviceSyncResult(6, SyncRunOutcome.DONE),
                ],
                derive_from,
                now,
            ),
        ),
        "sync_plant_intraday": mocker.patch.object(
            sync,
            "sync_plant_intraday",
            return_value=9,
        ),
    }


def test_sync_intraday_counts_outcomes_and_derives_plant(
    intraday_deps: dict[str, MockType],
    get_session_mock: MockType,
    db_session: MockType,
    fusionsolar_session: MockType,
    plant: Plant,
    inverter: Device,
    meter: Device,
    now: datetime,
) -> None:
    """Counters summarize the device outcomes and the derived plant rows."""
    result = sync.sync_intraday(plant_code=plant.plant_code, database_url="db-url")

    assert result == SyncRunResult(
        synced=2,
        skipped=1,
        failed=1,
        readings_upserted=10,
        plant_readings_upserted=9,
    )
    intraday_deps["login"].assert_called_once_with()
    get_session_mock.assert_called_once_with("db-url")
    intraday_deps["sync_intraday_devices"].assert_called_once_with(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        min_gap=sync._MIN_SYNC_GAP,
        device_role=None,
    )
    intraday_deps["sync_plant_intraday"].assert_called_once_with(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        collected_from=now - timedelta(hours=1),
        collected_to=now,
    )


def test_sync_intraday_can_skip_plant_derivation(
    intraday_deps: dict[str, MockType],
    fusionsolar_session: MockType,
    plant: Plant,
) -> None:
    """With ``derive_plant=False`` no plant rows are derived."""
    result = sync.sync_intraday(
        plant_code=plant.plant_code,
        fusionsolar_session=fusionsolar_session,
        device_role=DeviceRole.INVERTER,
        min_gap=timedelta(minutes=1),
        derive_plant=False,
    )

    assert result.plant_readings_upserted == 0
    assert result.synced == 2
    intraday_deps["login"].assert_not_called()
    intraday_deps["sync_plant_intraday"].assert_not_called()
    call_kwargs = intraday_deps["sync_intraday_devices"].call_args.kwargs
    assert call_kwargs["device_role"] is DeviceRole.INVERTER
    assert call_kwargs["min_gap"] == timedelta(minutes=1)

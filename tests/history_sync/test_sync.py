"""Tests for ``darb_solar.history_sync.sync``."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pytest_mock import MockerFixture, MockType

from darb_solar.db.models import Device, DevicePowerReading, Plant
from darb_solar.db.types import DeviceRole, SyncWindowCheckpointStatus
from darb_solar.history_sync import sync
from darb_solar.history_sync.types import (
    DayWindow,
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)

HOUR_MS = 60 * 60 * 1000
NOW = datetime(2026, 6, 3, 8, tzinfo=timezone.utc)
DAY = date(2026, 6, 1)

API_INVERTER = {"id": 1000000001, "devDn": "NE=1000000001", "devTypeId": 1}
API_METER = {"id": 1000000002, "devDn": "NE=1000000002", "devTypeId": 47}
API_STATION = {"plantCode": "NE=12345678", "plantName": "Darb Test Plant"}


@pytest.fixture
def day_window(casablanca_tz: ZoneInfo) -> DayWindow:
    """Return the ``2026-06-01`` plant-local day window.

    Parameters
    ----------
    casablanca_tz : zoneinfo.ZoneInfo
        Plant-local timezone.

    Returns
    -------
    DayWindow
        Window spanning one normal 24h day.
    """
    return next(iter(sync.iter_day_windows(DAY, DAY, tz=casablanca_tz)))


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


def _reading(
    dev_id: str,
    collected_at: datetime,
    active_power_kw: float,
) -> DevicePowerReading:
    return DevicePowerReading(
        dev_id=dev_id,
        collected_at=collected_at,
        active_power_kw=active_power_kw,
        synced_at=NOW,
    )


def test_require_single_device_returns_the_only_device() -> None:
    """Exactly one device is returned as-is."""
    assert sync._require_single_device([API_INVERTER], role="inverter") is (
        API_INVERTER
    )


@pytest.mark.parametrize(
    ("devices", "count"),
    [([], 0), ([API_INVERTER, API_INVERTER], 2)],
)
def test_require_single_device_rejects_zero_or_many(
    devices: list[dict[str, Any]],
    count: int,
) -> None:
    """Zero or several devices raise a descriptive ``ValueError``."""
    with pytest.raises(ValueError, match=f"exactly one inverter.*found {count}"):
        sync._require_single_device(devices, role="inverter")


def test_device_from_api_maps_fields() -> None:
    """API fields map to the ORM device, with ``id`` stringified."""
    device = sync._device_from_api(
        API_METER,
        plant_code="NE=1",
        role=DeviceRole.METER,
    )

    assert device.dev_id == "1000000002"
    assert device.plant_code == "NE=1"
    assert device.dev_dn == "NE=1000000002"
    assert device.dev_type_id == 47
    assert device.role == DeviceRole.METER


def test_bootstrap_plant_seeds_plant_and_devices(
    fusionsolar_session: MockType,
    get_session_mock: MockType,
    db_session: MockType,
    mocker: MockerFixture,
) -> None:
    """The station and the inverter and meter rows are upserted."""
    mocker.patch.object(sync, "_fetch_station", return_value=API_STATION)
    upsert_plant = mocker.patch.object(sync, "upsert_plant")
    upsert_device = mocker.patch.object(sync, "upsert_device")
    fusionsolar_session.client.list_devices.return_value = [
        API_INVERTER,
        API_METER,
        {"id": 3, "devDn": "NE=3", "devTypeId": 62},
    ]

    result = sync.bootstrap_plant(
        plant_code="NE=12345678",
        timezone="Africa/Casablanca",
        database_url="postgresql://db",
        fusionsolar_session=fusionsolar_session,
    )

    get_session_mock.assert_called_once_with("postgresql://db")
    assert result.plant.plant_code == "NE=12345678"
    assert result.plant.plant_name == "Darb Test Plant"
    assert result.plant.timezone == "Africa/Casablanca"
    assert [(d.dev_id, d.role) for d in result.devices] == [
        ("1000000001", "inverter"),
        ("1000000002", "meter"),
    ]
    upsert_plant.assert_called_once_with(db_session, result.plant)
    assert upsert_device.call_args_list == [
        mocker.call(db_session, device) for device in result.devices
    ]


def test_bootstrap_plant_logs_in_when_no_session_is_given(
    fusionsolar_session: MockType,
    get_session_mock: MockType,
    mocker: MockerFixture,
) -> None:
    """Without a session, ``login_fusionsolar`` provides one."""
    login = mocker.patch.object(
        sync,
        "login_fusionsolar",
        return_value=fusionsolar_session,
    )
    mocker.patch.object(sync, "_fetch_station", return_value=API_STATION)
    mocker.patch.object(sync, "upsert_plant")
    mocker.patch.object(sync, "upsert_device")
    fusionsolar_session.client.list_devices.return_value = [API_INVERTER, API_METER]

    sync.bootstrap_plant(plant_code="NE=12345678")

    login.assert_called_once_with()


@pytest.mark.parametrize(
    ("api_devices", "role"),
    [
        ([API_METER], "inverter"),
        ([API_INVERTER, API_INVERTER, API_METER], "inverter"),
        ([API_INVERTER], "meter"),
        ([API_INVERTER, API_METER, API_METER], "meter"),
    ],
)
def test_bootstrap_plant_requires_one_inverter_and_one_meter(
    fusionsolar_session: MockType,
    get_session_mock: MockType,
    mocker: MockerFixture,
    api_devices: list[dict[str, Any]],
    role: str,
) -> None:
    """Zero or two devices of a role abort bootstrap before any write."""
    mocker.patch.object(sync, "_fetch_station", return_value=API_STATION)
    upsert_plant = mocker.patch.object(sync, "upsert_plant")
    fusionsolar_session.client.list_devices.return_value = api_devices

    with pytest.raises(ValueError, match=f"exactly one {role}"):
        sync.bootstrap_plant(
            plant_code="NE=12345678",
            fusionsolar_session=fusionsolar_session,
        )

    upsert_plant.assert_not_called()


def test_load_plant_config_returns_plant_and_devices(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
) -> None:
    """The seeded plant and its devices are returned."""
    mocker.patch.object(sync, "get_plant", return_value=plant)
    mocker.patch.object(sync, "list_devices", return_value=[inverter, meter])

    assert sync.load_plant_config(db_session, plant.plant_code) == (
        plant,
        [inverter, meter],
    )


def test_load_plant_config_requires_plant(
    db_session: MockType,
    mocker: MockerFixture,
) -> None:
    """A plant missing from the database raises ``ValueError``."""
    mocker.patch.object(sync, "get_plant", return_value=None)

    with pytest.raises(ValueError, match="'NE=1' is not in the database"):
        sync.load_plant_config(db_session, "NE=1")


def test_load_plant_config_requires_devices(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
) -> None:
    """A plant without devices raises ``ValueError``."""
    mocker.patch.object(sync, "get_plant", return_value=plant)
    mocker.patch.object(sync, "list_devices", return_value=[])

    with pytest.raises(ValueError, match="No devices registered"):
        sync.load_plant_config(db_session, plant.plant_code)


def test_plant_timezone_returns_zoneinfo(plant: Plant) -> None:
    """The stored timezone name is converted to ``ZoneInfo``."""
    assert sync.plant_timezone(plant) == ZoneInfo("Africa/Casablanca")


def test_default_sync_end_date_is_yesterday_in_plant_timezone(
    mocker: MockerFixture,
    casablanca_tz: ZoneInfo,
) -> None:
    """The default end date is the day before the current local day."""
    datetime_mock = mocker.patch.object(sync, "datetime")
    datetime_mock.now.return_value = datetime(2026, 6, 2, 0, 30, tzinfo=casablanca_tz)

    assert sync.default_sync_end_date(tz=casablanca_tz) == date(2026, 6, 1)
    datetime_mock.now.assert_called_once_with(casablanca_tz)


def test_iter_day_windows_is_inclusive(casablanca_tz: ZoneInfo) -> None:
    """Both boundary dates are included, one window per calendar day."""
    windows = list(
        sync.iter_day_windows(date(2026, 6, 1), date(2026, 6, 3), tz=casablanca_tz)
    )

    assert [window.day for window in windows] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]
    first = windows[0]
    assert first.window_start == datetime(2026, 6, 1, tzinfo=casablanca_tz)
    assert first.window_end == datetime(2026, 6, 2, tzinfo=casablanca_tz)
    assert first.end_ms - first.start_ms == 24 * HOUR_MS
    assert windows[1].start_ms == first.end_ms


def test_iter_day_windows_is_empty_when_range_is_inverted(
    casablanca_tz: ZoneInfo,
) -> None:
    """A start date after the end date yields nothing."""
    assert (
        list(
            sync.iter_day_windows(
                date(2026, 6, 2),
                date(2026, 6, 1),
                tz=casablanca_tz,
            )
        )
        == []
    )


@pytest.mark.parametrize(
    ("day", "expected_hours"),
    [(date(2026, 2, 15), 25), (date(2026, 3, 22), 23)],
)
def test_iter_day_windows_spans_clock_change_days(
    casablanca_tz: ZoneInfo,
    day: date,
    expected_hours: int,
) -> None:
    """Days with a Casablanca clock change last 23h or 25h in epoch time."""
    (window,) = sync.iter_day_windows(day, day, tz=casablanca_tz)

    assert window.end_ms - window.start_ms == expected_hours * HOUR_MS


def test_history_records_to_readings_converts_units_and_timezone(
    casablanca_tz: ZoneInfo,
) -> None:
    """Meter watts become kW and timestamps use the plant timezone."""
    collect_ms = int(datetime(2026, 6, 1, 12, tzinfo=timezone.utc).timestamp() * 1000)

    readings = sync.history_records_to_readings(
        [{"collectTime": collect_ms, "dataItems": {"active_power": 2500}}],
        dev_id="1000000002",
        dev_type_id=47,
        synced_at=NOW,
        tz=casablanca_tz,
    )

    assert len(readings) == 1
    assert readings[0].dev_id == "1000000002"
    assert readings[0].active_power_kw == pytest.approx(2.5)
    assert readings[0].synced_at == NOW
    assert readings[0].collected_at == datetime(2026, 6, 1, 13, tzinfo=casablanca_tz)
    assert readings[0].collected_at.tzinfo == casablanca_tz


def test_history_records_to_readings_skips_records_without_collect_time(
    casablanca_tz: ZoneInfo,
) -> None:
    """Records lacking ``collectTime`` are dropped."""
    readings = sync.history_records_to_readings(
        [
            {"dataItems": {"active_power": 1.0}},
            {"collectTime": None, "dataItems": {"active_power": 1.0}},
            {"collectTime": 1_780_000_000_000, "dataItems": {"active_power": 3.0}},
        ],
        dev_id="1000000001",
        dev_type_id=1,
        synced_at=NOW,
        tz=casablanca_tz,
    )

    assert [reading.active_power_kw for reading in readings] == [3.0]


def test_ensure_session_alive_pings_database(db_session: MockType) -> None:
    """A healthy connection only runs ``SELECT 1``."""
    sync._ensure_session_alive(db_session)

    (statement,), _ = db_session.execute.call_args
    assert str(statement) == "SELECT 1"
    db_session.rollback.assert_not_called()


def test_ensure_session_alive_rolls_back_on_dead_connection(
    db_session: MockType,
) -> None:
    """A failing ping clears the dead transaction without raising."""
    db_session.execute.side_effect = RuntimeError("connection closed")

    sync._ensure_session_alive(db_session)

    db_session.rollback.assert_called_once_with()


def test_device_by_role_returns_matching_device(
    inverter: Device,
    meter: Device,
) -> None:
    """The unique device with the role is returned."""
    assert sync._device_by_role([inverter, meter], "meter") is meter


def test_device_by_role_rejects_missing_device(inverter: Device) -> None:
    """A role without devices raises ``ValueError``."""
    with pytest.raises(ValueError, match="role 'meter'; found 0"):
        sync._device_by_role([inverter], "meter")


def test_device_by_role_rejects_duplicate_devices(
    inverter: Device,
    plant: Plant,
) -> None:
    """A role shared by two devices raises ``ValueError``."""
    other = Device(
        dev_id="other",
        plant_code=plant.plant_code,
        dev_dn="NE=other",
        dev_type_id=1,
        role=DeviceRole.INVERTER,
    )

    with pytest.raises(ValueError, match="role 'inverter'; found 2"):
        sync._device_by_role([inverter, other], "inverter")


@pytest.mark.parametrize(
    ("windows", "expected"),
    [
        pytest.param(
            {"1000000001": "done", "1000000002": "done"},
            True,
            id="all-done",
        ),
        pytest.param({"1000000001": "done"}, False, id="missing-window"),
        pytest.param(
            {"1000000001": "done", "1000000002": "failed"},
            False,
            id="failed-window",
        ),
        pytest.param(
            {"1000000001": "done", "1000000002": "pending"},
            False,
            id="pending-window",
        ),
    ],
)
def test_device_windows_complete(
    db_session: MockType,
    mocker: MockerFixture,
    inverter: Device,
    meter: Device,
    windows: dict[str, str],
    expected: bool,
) -> None:
    """The day is complete only when every device window is ``done``."""

    def _get_sync_window(
        session: Any,
        dev_id: str,
        window_start: datetime,
    ) -> Any:
        status = windows.get(dev_id)
        if status is None:
            return None
        return mocker.Mock(status=SyncWindowCheckpointStatus(status))

    mocker.patch.object(sync, "get_sync_window", side_effect=_get_sync_window)

    assert sync._device_windows_complete(db_session, [inverter, meter], NOW) is expected


def test_derive_plant_power_readings_joins_on_timestamp(
    casablanca_tz: ZoneInfo,
) -> None:
    """Only timestamps present for both devices produce a plant row."""
    t0 = datetime(2026, 6, 1, 12, tzinfo=casablanca_tz)
    t1 = t0 + timedelta(minutes=5)
    t2 = t0 + timedelta(minutes=10)
    inverter_readings = [
        _reading("inv", t0, 5.0),
        _reading("inv", t1, 4.0),
    ]
    meter_readings = [
        _reading("met", t0, 2.0),
        _reading("met", t2, 1.0),
    ]

    plant_readings = sync.derive_plant_power_readings(
        plant_code="NE=1",
        inverter_readings=inverter_readings,
        meter_readings=meter_readings,
        synced_at=NOW,
    )

    assert len(plant_readings) == 1
    reading = plant_readings[0]
    assert reading.plant_code == "NE=1"
    assert reading.collected_at == t0
    assert reading.pv_production_kw == 5.0
    assert reading.grid_export_kw == 2.0
    assert reading.consumption_kw == 3.0
    assert reading.synced_at == NOW


def test_derive_plant_power_readings_clips_negative_meter_export(
    casablanca_tz: ZoneInfo,
) -> None:
    """Imports (negative meter power) count as consumption, not export."""
    t0 = datetime(2026, 6, 1, 12, tzinfo=casablanca_tz)

    (reading,) = sync.derive_plant_power_readings(
        plant_code="NE=1",
        inverter_readings=[_reading("inv", t0, 1.0)],
        meter_readings=[_reading("met", t0, -2.0)],
        synced_at=NOW,
    )

    assert reading.grid_export_kw == 0.0
    assert reading.consumption_kw == 3.0


@pytest.fixture
def day_window_deps(mocker: MockerFixture) -> dict[str, MockType]:
    """Patch the collaborators of ``sync_device_day_window``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    dict[str, pytest_mock.MockType]
        Patched helpers keyed by their function name.
    """
    names = [
        "should_skip_window",
        "persist_sync_window",
        "_fetch_device_history",
        "_ensure_session_alive",
        "history_records_to_readings",
        "upsert_device_power_reading",
    ]
    deps = {name: mocker.patch.object(sync, name) for name in names}
    deps["should_skip_window"].return_value = False
    deps["_fetch_device_history"].return_value = [{"collectTime": 1}]
    deps["history_records_to_readings"].return_value = ["r1", "r2"]
    mocker.patch.object(sync, "utc_now", return_value=NOW)
    return deps


def _persisted_statuses(persist_mock: MockType) -> list[SyncWindowCheckpointStatus]:
    return [call.kwargs["status"] for call in persist_mock.call_args_list]


def test_sync_device_day_window_skips_done_window(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    day_window: DayWindow,
    casablanca_tz: ZoneInfo,
    day_window_deps: dict[str, MockType],
) -> None:
    """A done checkpoint short-circuits without fetching or writing."""
    day_window_deps["should_skip_window"].return_value = True

    result = sync.sync_device_day_window(
        fusionsolar_session,
        db_session,
        inverter,
        day_window,
        tz=casablanca_tz,
        resume=True,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.SKIPPED)
    day_window_deps["should_skip_window"].assert_called_once_with(
        db_session,
        dev_id=inverter.dev_id,
        window_start=day_window.window_start,
        resume=True,
    )
    day_window_deps["_fetch_device_history"].assert_not_called()
    day_window_deps["persist_sync_window"].assert_not_called()
    db_session.commit.assert_not_called()


def test_sync_device_day_window_persists_pending_then_done(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    day_window: DayWindow,
    casablanca_tz: ZoneInfo,
    day_window_deps: dict[str, MockType],
) -> None:
    """A successful sync checkpoints PENDING, upserts readings, then DONE."""
    result = sync.sync_device_day_window(
        fusionsolar_session,
        db_session,
        inverter,
        day_window,
        tz=casablanca_tz,
    )

    assert result == DeviceSyncResult(2, SyncRunOutcome.DONE)
    assert _persisted_statuses(day_window_deps["persist_sync_window"]) == [
        SyncWindowCheckpointStatus.PENDING,
        SyncWindowCheckpointStatus.DONE,
    ]
    day_window_deps["_fetch_device_history"].assert_called_once_with(
        fusionsolar_session,
        inverter,
        start_ms=day_window.start_ms,
        end_ms=day_window.end_ms,
    )
    day_window_deps["history_records_to_readings"].assert_called_once_with(
        [{"collectTime": 1}],
        dev_id=inverter.dev_id,
        dev_type_id=inverter.dev_type_id,
        synced_at=NOW,
        tz=casablanca_tz,
    )
    assert day_window_deps["upsert_device_power_reading"].call_count == 2
    assert db_session.commit.call_count == 2
    db_session.rollback.assert_not_called()


def test_sync_device_day_window_passes_resume_flag(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    day_window: DayWindow,
    casablanca_tz: ZoneInfo,
    day_window_deps: dict[str, MockType],
) -> None:
    """``resume=False`` is forwarded to the checkpoint skip check."""
    sync.sync_device_day_window(
        fusionsolar_session,
        db_session,
        inverter,
        day_window,
        tz=casablanca_tz,
        resume=False,
    )

    assert day_window_deps["should_skip_window"].call_args.kwargs["resume"] is False


def test_sync_device_day_window_records_failure(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    day_window: DayWindow,
    casablanca_tz: ZoneInfo,
    day_window_deps: dict[str, MockType],
) -> None:
    """A fetch error rolls back and persists a FAILED checkpoint."""
    day_window_deps["_fetch_device_history"].side_effect = RuntimeError("api down")

    result = sync.sync_device_day_window(
        fusionsolar_session,
        db_session,
        inverter,
        day_window,
        tz=casablanca_tz,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.FAILED)
    persist_mock = day_window_deps["persist_sync_window"]
    assert _persisted_statuses(persist_mock) == [
        SyncWindowCheckpointStatus.PENDING,
        SyncWindowCheckpointStatus.FAILED,
    ]
    assert persist_mock.call_args.kwargs["error_message"] == "api down"
    day_window_deps["upsert_device_power_reading"].assert_not_called()
    db_session.rollback.assert_called_once_with()
    assert db_session.commit.call_count == 2


def test_sync_device_day_window_survives_failed_checkpoint_write(
    fusionsolar_session: MockType,
    db_session: MockType,
    inverter: Device,
    day_window: DayWindow,
    casablanca_tz: ZoneInfo,
    day_window_deps: dict[str, MockType],
) -> None:
    """If the FAILED checkpoint cannot be saved, the run still reports FAILED."""
    day_window_deps["_fetch_device_history"].side_effect = RuntimeError("api down")
    day_window_deps["persist_sync_window"].side_effect = [
        None,
        RuntimeError("db down"),
    ]

    result = sync.sync_device_day_window(
        fusionsolar_session,
        db_session,
        inverter,
        day_window,
        tz=casablanca_tz,
    )

    assert result == DeviceSyncResult(0, SyncRunOutcome.FAILED)
    assert db_session.rollback.call_count == 2
    assert db_session.commit.call_count == 1


def test_sync_plant_day_window_skips_incomplete_day(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    day_window: DayWindow,
) -> None:
    """Nothing is derived while a device window is not done."""
    mocker.patch.object(sync, "_device_windows_complete", return_value=False)
    list_readings = mocker.patch.object(sync, "list_device_power_readings")

    count = sync.sync_plant_day_window(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        window=day_window,
    )

    assert count == 0
    list_readings.assert_not_called()
    db_session.commit.assert_not_called()


def test_sync_plant_day_window_derives_and_upserts(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
    day_window: DayWindow,
) -> None:
    """Device readings for the day are joined, upserted and committed."""
    mocker.patch.object(sync, "_device_windows_complete", return_value=True)
    mocker.patch.object(sync, "utc_now", return_value=NOW)
    t0 = day_window.window_start + timedelta(hours=12)
    inverter_readings = [_reading(inverter.dev_id, t0, 5.0)]
    meter_readings = [_reading(meter.dev_id, t0, 2.0)]
    list_readings = mocker.patch.object(
        sync,
        "list_device_power_readings",
        side_effect=[inverter_readings, meter_readings],
    )
    upsert = mocker.patch.object(sync, "upsert_plant_power_reading")

    count = sync.sync_plant_day_window(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        window=day_window,
    )

    assert count == 1
    assert list_readings.call_args_list == [
        mocker.call(
            db_session,
            dev_id=inverter.dev_id,
            collected_from=day_window.window_start,
            collected_to=day_window.window_end,
        ),
        mocker.call(
            db_session,
            dev_id=meter.dev_id,
            collected_from=day_window.window_start,
            collected_to=day_window.window_end,
        ),
    ]
    upsert.assert_called_once_with(db_session, mocker.ANY)
    assert upsert.call_args.args[1].pv_production_kw == 5.0
    db_session.commit.assert_called_once_with()


def test_sync_plant_power_readings_counts_skipped_days(
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
) -> None:
    """Days with incomplete devices are counted, the others are derived."""
    mocker.patch.object(
        sync,
        "_device_windows_complete",
        side_effect=[True, False, True],
    )
    day_mock = mocker.patch.object(
        sync,
        "sync_plant_day_window",
        side_effect=[10, 20],
    )

    upserted, skipped = sync.sync_plant_power_readings(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 3),
    )

    assert (upserted, skipped) == (30, 1)
    assert day_mock.call_count == 2


def test_sync_device_history_returns_zero_counters_for_empty_range(
    fusionsolar_session: MockType,
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
) -> None:
    """An inverted date range does no work."""
    window_mock = mocker.patch.object(sync, "sync_device_day_window")
    plant_mock = mocker.patch.object(sync, "sync_plant_power_readings")

    result = sync.sync_device_history(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter],
        from_date=date(2026, 6, 2),
        to_date=date(2026, 6, 1),
    )

    assert result == SyncRunResult(0, 0, 0, 0, 0, 0)
    window_mock.assert_not_called()
    plant_mock.assert_not_called()


def test_sync_device_history_aggregates_outcomes(
    fusionsolar_session: MockType,
    db_session: MockType,
    mocker: MockerFixture,
    plant: Plant,
    inverter: Device,
    meter: Device,
) -> None:
    """Counters tally outcomes across every device and day."""
    window_mock = mocker.patch.object(
        sync,
        "sync_device_day_window",
        side_effect=[
            DeviceSyncResult(5, SyncRunOutcome.DONE),
            DeviceSyncResult(0, SyncRunOutcome.SKIPPED),
            DeviceSyncResult(0, SyncRunOutcome.FAILED),
            DeviceSyncResult(7, SyncRunOutcome.DONE),
        ],
    )
    plant_mock = mocker.patch.object(
        sync,
        "sync_plant_power_readings",
        return_value=(11, 1),
    )

    result = sync.sync_device_history(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 2),
        resume=False,
    )

    assert result == SyncRunResult(
        synced=2,
        skipped=1,
        failed=1,
        readings_upserted=12,
        plant_readings_upserted=11,
        plant_skipped=1,
    )
    assert window_mock.call_count == 4
    assert [call.args[2] for call in window_mock.call_args_list] == [
        inverter,
        inverter,
        meter,
        meter,
    ]
    assert all(call.kwargs["resume"] is False for call in window_mock.call_args_list)
    plant_mock.assert_called_once_with(
        db_session,
        plant=plant,
        devices=[inverter, meter],
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 2),
    )


@pytest.fixture
def history_deps(
    mocker: MockerFixture,
    get_session_mock: MockType,
    plant: Plant,
    inverter: Device,
    meter: Device,
    fusionsolar_session: MockType,
) -> dict[str, MockType]:
    """Patch the collaborators of ``sync_history``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    get_session_mock : pytest_mock.MockType
        Patched ``get_session``.
    plant : Plant
        Plant fixture returned by the patched config loader.
    inverter : Device
        Inverter fixture returned by the patched config loader.
    meter : Device
        Meter fixture returned by the patched config loader.
    fusionsolar_session : pytest_mock.MockType
        Session returned by the patched login.

    Returns
    -------
    dict[str, pytest_mock.MockType]
        Patched helpers keyed by name.
    """
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
        "sync_device_history": mocker.patch.object(sync, "sync_device_history"),
        "default_sync_end_date": mocker.patch.object(
            sync,
            "default_sync_end_date",
            return_value=date(2026, 6, 10),
        ),
    }


def test_sync_history_uses_defaults(
    history_deps: dict[str, MockType],
    get_session_mock: MockType,
    db_session: MockType,
    fusionsolar_session: MockType,
    plant: Plant,
    inverter: Device,
    meter: Device,
    casablanca_tz: ZoneInfo,
) -> None:
    """Dates default to the backfill start and yesterday; login is performed."""
    result = sync.sync_history(plant_code=plant.plant_code, database_url="db-url")

    assert result is history_deps["sync_device_history"].return_value
    history_deps["login"].assert_called_once_with()
    get_session_mock.assert_called_once_with("db-url")
    history_deps["default_sync_end_date"].assert_called_once_with(tz=casablanca_tz)
    history_deps["sync_device_history"].assert_called_once_with(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        from_date=sync.DEFAULT_BACKFILL_START,
        to_date=date(2026, 6, 10),
        resume=True,
    )


def test_sync_history_uses_explicit_arguments(
    history_deps: dict[str, MockType],
    db_session: MockType,
    fusionsolar_session: MockType,
    plant: Plant,
    inverter: Device,
    meter: Device,
) -> None:
    """Explicit dates, resume flag and session are forwarded unchanged."""
    sync.sync_history(
        plant_code=plant.plant_code,
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 5),
        resume=False,
        fusionsolar_session=fusionsolar_session,
    )

    history_deps["login"].assert_not_called()
    history_deps["default_sync_end_date"].assert_not_called()
    history_deps["sync_device_history"].assert_called_once_with(
        fusionsolar_session,
        db_session,
        plant=plant,
        devices=[inverter, meter],
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 5),
        resume=False,
    )


def test_sync_history_rejects_inverted_date_range(
    history_deps: dict[str, MockType],
    plant: Plant,
) -> None:
    """A start date after the end date raises before syncing."""
    with pytest.raises(ValueError, match="from_date 2026-06-05 is after"):
        sync.sync_history(
            plant_code=plant.plant_code,
            from_date=date(2026, 6, 5),
            to_date=date(2026, 6, 1),
        )

    history_deps["sync_device_history"].assert_not_called()


def test_sync_history_rejects_default_end_before_start(
    history_deps: dict[str, MockType],
    plant: Plant,
) -> None:
    """A start date later than the default end date also raises."""
    history_deps["default_sync_end_date"].return_value = date(2025, 12, 31)

    with pytest.raises(ValueError, match="is after to_date 2025-12-31"):
        sync.sync_history(plant_code=plant.plant_code)

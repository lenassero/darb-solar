"""Bootstrap, transforms, and history sync orchestration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from loguru import logger

from darb_solar.db import (
    DEFAULT_TIMEZONE_NAME,
    DbSession,
    Device,
    DevicePowerReading,
    DeviceRole,
    Plant,
    PlantPowerReading,
    SyncWindowCheckpointStatus,
    get_plant,
    get_session,
    get_sync_window,
    list_device_power_readings,
    list_devices,
    upsert_device,
    upsert_device_power_reading,
    upsert_plant,
    upsert_plant_power_reading,
    utc_now,
)
from darb_solar.fusionsolar import (
    FusionSolarClient,
    device_dn,
    device_type_id,
    filter_inverters,
    filter_meters,
    active_power_kw_from_history_record,
)
from darb_solar.time import (
    DEFAULT_TIMEZONE,
    day_bounds_epoch_ms,
    datetime_from_epoch_ms,
)

from darb_solar.history_sync.api import _fetch_device_history, _fetch_station
from darb_solar.history_sync.checkpoints import (
    persist_sync_window,
    should_skip_window,
)
from darb_solar.history_sync.session import FusionSolarSession, login_fusionsolar
from darb_solar.history_sync.types import (
    BootstrapResult,
    DayWindow,
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)

DEFAULT_BACKFILL_START = date(2026, 1, 1)


def _require_single_device(
    devices: list[dict[str, Any]],
    *,
    role: str,
) -> dict[str, Any]:
    """Return the sole device in ``devices`` or raise.

    Parameters
    ----------
    devices : list[dict[str, Any]]
        Filtered API device rows.
    role : str
        Role label used in error messages.

    Returns
    -------
    dict[str, Any]
        Selected device row.

    Raises
    ------
    ValueError
        If zero or more than one device is present.
    """
    if len(devices) != 1:
        raise ValueError(
            f"Expected exactly one {role} for bootstrap; found {len(devices)}."
        )
    return devices[0]


def _device_from_api(
    device: dict[str, Any],
    *,
    plant_code: str,
    role: DeviceRole,
) -> Device:
    """Map a FusionSolar device dict to a database row."""
    return Device(
        dev_id=str(device["id"]),
        plant_code=plant_code,
        dev_dn=device_dn(device),
        dev_type_id=device_type_id(device),
        role=role,
    )


def bootstrap_plant(
    *,
    plant_code: str,
    timezone: str = DEFAULT_TIMEZONE_NAME,
    database_url: str | None = None,
    fusionsolar_session: FusionSolarSession | None = None,
) -> BootstrapResult:
    """Fetch plant metadata from FusionSolar and seed reference tables.

    Parameters
    ----------
    plant_code : str
        FusionSolar plant code to register.
    timezone : str, optional
        IANA timezone stored on the plant row.
    database_url : str or None, optional
        Postgres connection URL.
    fusionsolar_session : FusionSolarSession or None, optional
        Existing authenticated session. When omitted, a new login is performed.

    Returns
    -------
    BootstrapResult
        Plant and device rows written to the database.

    Raises
    ------
    ValueError
        If the plant or required devices cannot be resolved from the API.
    """
    active_fusionsolar_session = fusionsolar_session or login_fusionsolar()
    station = _fetch_station(active_fusionsolar_session, plant_code)
    api_devices = active_fusionsolar_session.client.list_devices(plant_code)
    inverter = _require_single_device(
        filter_inverters(api_devices),
        role="inverter",
    )
    meter = _require_single_device(
        filter_meters(api_devices),
        role="meter",
    )

    plant = Plant(
        plant_code=plant_code,
        plant_name=str(station["plantName"]),
        timezone=timezone,
    )
    devices = [
        _device_from_api(inverter, plant_code=plant_code, role="inverter"),
        _device_from_api(meter, plant_code=plant_code, role="meter"),
    ]

    with get_session(database_url) as session:
        upsert_plant(session, plant)
        for device in devices:
            upsert_device(session, device)
        session.commit()

    logger.info(
        f"Bootstrapped plant {plant_code}: "
        f"inverter dev_id={devices[0].dev_id}, "
        f"meter dev_id={devices[1].dev_id}"
    )
    return BootstrapResult(plant=plant, devices=devices)


def load_plant_config(
    session: DbSession,
    plant_code: str,
) -> tuple[Plant, list[Device]]:
    """Load static plant and device rows seeded in the database.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.

    Returns
    -------
    tuple[Plant, list[Device]]
        Plant metadata and its registered devices.

    Raises
    ------
    ValueError
        If the plant or its devices are missing from the database.
    """
    plant = get_plant(session, plant_code)
    if plant is None:
        raise ValueError(
            f"Plant {plant_code!r} is not in the database; "
            "run bootstrap before syncing history."
        )

    devices = list_devices(session, plant_code=plant_code)
    if not devices:
        raise ValueError(
            f"No devices registered for plant {plant_code!r}; "
            "run bootstrap before syncing history."
        )
    return plant, devices


def plant_timezone(plant: Plant) -> ZoneInfo:
    """Return the plant timezone as a ``ZoneInfo`` object."""
    return ZoneInfo(plant.timezone)


def default_sync_end_date(*, tz: ZoneInfo = DEFAULT_TIMEZONE) -> date:
    """Return yesterday's calendar date in the plant timezone."""
    now = datetime.now(tz)
    return (now - timedelta(days=1)).date()


def iter_day_windows(
    from_date: date,
    to_date: date,
    *,
    tz: ZoneInfo,
) -> Iterable[DayWindow]:
    """Yield inclusive calendar-day windows between ``from_date`` and ``to_date``.

    Parameters
    ----------
    from_date : date
        First calendar day to include.
    to_date : date
        Last calendar day to include.
    tz : ZoneInfo
        Plant-local timezone used for day boundaries.

    Yields
    ------
    DayWindow
        Day metadata with window bounds and epoch milliseconds.
    """
    if from_date > to_date:
        return

    current = from_date
    while current <= to_date:
        start_dt = datetime(
            current.year,
            current.month,
            current.day,
            tzinfo=tz,
        )
        end_dt = start_dt + timedelta(days=1)
        start_ms, end_ms = day_bounds_epoch_ms(start_dt, tz=tz)
        yield DayWindow(
            day=current,
            window_start=start_dt,
            window_end=end_dt,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        current += timedelta(days=1)


def history_records_to_readings(
    records: list[dict[str, Any]],
    *,
    dev_id: str,
    dev_type_id: int,
    synced_at: datetime,
    tz: ZoneInfo,
) -> list[DevicePowerReading]:
    """Normalize historical API rows to device power readings in kW.

    Parameters
    ----------
    records : list[dict[str, Any]]
        Raw rows from ``get_device_history``.
    dev_id : str
        Device primary key stored in the database.
    dev_type_id : int
        FusionSolar device type ID used for unit conversion.
    synced_at : datetime
        UTC ingest timestamp recorded on each row.
    tz : ZoneInfo
        Plant-local timezone for ``collected_at``.

    Returns
    -------
    list[DevicePowerReading]
        Rows ready for upsert into ``device_power_readings``.
    """
    readings: list[DevicePowerReading] = []
    for record in records:
        collect_time = record.get("collectTime")
        if collect_time is None:
            continue
        collected_at = datetime_from_epoch_ms(int(collect_time), tz=tz)
        if collected_at is None:
            continue
        readings.append(
            DevicePowerReading(
                dev_id=dev_id,
                collected_at=collected_at,
                active_power_kw=active_power_kw_from_history_record(
                    record, dev_type_id
                ),
                synced_at=synced_at,
            )
        )
    return readings


def sync_device_day_window(
    fusionsolar_session: FusionSolarSession,
    session: DbSession,
    device: Device,
    window: DayWindow,
    *,
    tz: ZoneInfo,
    resume: bool = True,
) -> DeviceSyncResult:
    """Fetch one device-day window and persist readings plus checkpoint state.

    Parameters
    ----------
    fusionsolar_session : FusionSolarSession
        Authenticated FusionSolar session.
    session : DbSession
        Open SQLAlchemy session.
    device : Device
        Device metadata loaded from the database.
    window : DayWindow
        Day window to fetch.
    tz : ZoneInfo
        Plant-local timezone for timestamps.
    resume : bool, optional
        When ``True``, skip windows already marked ``done``.

    Returns
    -------
    DeviceSyncResult
        Number of readings upserted and the window sync outcome.
    """
    dev_id = device.dev_id
    if should_skip_window(
        session,
        dev_id=dev_id,
        window_start=window.window_start,
        resume=resume,
    ):
        logger.info(
            f"Skipping dev_id={dev_id} day={window.day} "
            "(checkpoint already done)"
        )
        return DeviceSyncResult(0, SyncRunOutcome.SKIPPED)

    persist_sync_window(
        session,
        dev_id=dev_id,
        window_start=window.window_start,
        window_end=window.window_end,
        status=SyncWindowCheckpointStatus.PENDING,
        error_message=None,
    )
    session.commit()

    try:
        records = _fetch_device_history(
            fusionsolar_session,
            device,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
        )
        synced_at = utc_now()
        readings = history_records_to_readings(
            records,
            dev_id=dev_id,
            dev_type_id=device.dev_type_id,
            synced_at=synced_at,
            tz=tz,
        )
        for reading in readings:
            upsert_device_power_reading(session, reading)
        persist_sync_window(
            session,
            dev_id=dev_id,
            window_start=window.window_start,
            window_end=window.window_end,
            status=SyncWindowCheckpointStatus.DONE,
            error_message=None,
        )
        session.commit()
        logger.info(
            f"Synced dev_id={dev_id} day={window.day}: "
            f"{len(readings)} reading(s)"
        )
        return DeviceSyncResult(len(readings), SyncRunOutcome.DONE)
    except Exception as exc:
        persist_sync_window(
            session,
            dev_id=dev_id,
            window_start=window.window_start,
            window_end=window.window_end,
            status=SyncWindowCheckpointStatus.FAILED,
            error_message=str(exc),
        )
        session.commit()
        logger.error(
            f"Failed dev_id={dev_id} day={window.day}: {exc}"
        )
        return DeviceSyncResult(0, SyncRunOutcome.FAILED)


def _device_by_role(devices: list[Device], role: str) -> Device:
    """Return the single device registered with ``role``.

    Parameters
    ----------
    devices : list[Device]
        Devices registered for a plant.
    role : str
        Device role, for example ``inverter`` or ``meter``.

    Returns
    -------
    Device
        Matching device row.

    Raises
    ------
    ValueError
        If no device or more than one device matches ``role``.
    """
    matches = [device for device in devices if device.role == role]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one device with role {role!r}; "
            f"found {len(matches)}."
        )
    return matches[0]


def _device_windows_complete(
    session: DbSession,
    devices: list[Device],
    window_start: datetime,
) -> bool:
    """Return whether every device window is marked ``done``."""
    for device in devices:
        window = get_sync_window(session, device.dev_id, window_start)
        if window is None or window.status != SyncWindowCheckpointStatus.DONE:
            return False
    return True


def derive_plant_power_readings(
    *,
    plant_code: str,
    inverter_readings: list[DevicePowerReading],
    meter_readings: list[DevicePowerReading],
    synced_at: datetime,
) -> list[PlantPowerReading]:
    """Inner-join inverter and meter readings and compute plant metrics.

    Parameters
    ----------
    plant_code : str
        FusionSolar plant code.
    inverter_readings : list[DevicePowerReading]
        Inverter rows for one calendar day.
    meter_readings : list[DevicePowerReading]
        Meter rows for the same day.
    synced_at : datetime
        UTC ingest timestamp recorded on each derived row.

    Returns
    -------
    list[PlantPowerReading]
        Derived rows for timestamps present on both devices.
    """
    meter_kw_by_time = {
        reading.collected_at: reading.active_power_kw
        for reading in meter_readings
    }
    plant_readings: list[PlantPowerReading] = []
    for inverter_reading in inverter_readings:
        collected_at = inverter_reading.collected_at
        meter_kw = meter_kw_by_time.get(collected_at)
        if meter_kw is None:
            continue
        balance = FusionSolarClient.compute_energy_balance(
            inverter_reading.active_power_kw,
            meter_kw,
        )
        plant_readings.append(
            PlantPowerReading(
                plant_code=plant_code,
                collected_at=collected_at,
                pv_production_kw=balance.pv_production_kw,
                grid_export_kw=balance.grid_export_kw,
                consumption_kw=balance.consumption_kw,
                synced_at=synced_at,
            )
        )
    return plant_readings


def sync_plant_day_window(
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    window: DayWindow,
) -> int:
    """Derive and persist plant metrics for one completed calendar day.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant : Plant
        Plant metadata loaded from the database.
    devices : list[Device]
        Devices registered for the plant.
    window : DayWindow
        Day window to derive.

    Returns
    -------
    int
        Number of plant rows upserted.
    """
    if not _device_windows_complete(session, devices, window.window_start):
        logger.debug(
            f"Skipping plant metrics for day={window.day}: "
            "device windows incomplete"
        )
        return 0

    inverter = _device_by_role(devices, "inverter")
    meter = _device_by_role(devices, "meter")
    inverter_readings = list_device_power_readings(
        session,
        dev_id=inverter.dev_id,
        collected_from=window.window_start,
        collected_to=window.window_end,
    )
    meter_readings = list_device_power_readings(
        session,
        dev_id=meter.dev_id,
        collected_from=window.window_start,
        collected_to=window.window_end,
    )
    synced_at = utc_now()
    plant_readings = derive_plant_power_readings(
        plant_code=plant.plant_code,
        inverter_readings=inverter_readings,
        meter_readings=meter_readings,
        synced_at=synced_at,
    )
    for reading in plant_readings:
        upsert_plant_power_reading(session, reading)
    session.commit()
    logger.info(
        f"Derived plant metrics for day={window.day}: "
        f"{len(plant_readings)} reading(s)"
    )
    return len(plant_readings)


def sync_plant_power_readings(
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    from_date: date,
    to_date: date,
) -> tuple[int, int]:
    """Align device readings per day and upsert derived plant metrics.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant : Plant
        Plant metadata loaded from the database.
    devices : list[Device]
        Devices registered for the plant.
    from_date : date
        First calendar day to derive (plant-local).
    to_date : date
        Last calendar day to derive (plant-local).

    Returns
    -------
    tuple[int, int]
        Counts of plant rows upserted and days skipped because device
        windows were incomplete.
    """
    tz = plant_timezone(plant)
    windows = list(iter_day_windows(from_date, to_date, tz=tz))
    plant_readings_upserted = 0
    plant_days_skipped = 0

    for window in windows:
        if not _device_windows_complete(session, devices, window.window_start):
            plant_days_skipped += 1
            continue
        plant_readings_upserted += sync_plant_day_window(
            session,
            plant=plant,
            devices=devices,
            window=window,
        )

    return plant_readings_upserted, plant_days_skipped


def sync_device_history(
    fusionsolar_session: FusionSolarSession,
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    from_date: date,
    to_date: date,
    resume: bool = True,
) -> SyncRunResult:
    """Backfill device history for all registered devices across day windows.

    Parameters
    ----------
    fusionsolar_session : FusionSolarSession
        Authenticated FusionSolar session.
    session : DbSession
        Open SQLAlchemy session.
    plant : Plant
        Plant metadata loaded from the database.
    devices : list[Device]
        Devices registered for the plant.
    from_date : date
        First calendar day to sync (plant-local).
    to_date : date
        Last calendar day to sync (plant-local).
    resume : bool, optional
        When ``True``, skip windows already marked ``done``.

    Returns
    -------
    SyncRunResult
        Counters summarizing the run.
    """
    tz = plant_timezone(plant)
    windows = list(iter_day_windows(from_date, to_date, tz=tz))
    if not windows:
        return SyncRunResult(
            synced=0,
            skipped=0,
            readings_upserted=0,
            failed=0,
            plant_readings_upserted=0,
            plant_skipped=0,
        )

    synced = 0
    skipped = 0
    readings_upserted = 0
    failed = 0

    for device in devices:
        for window in windows:
            result = sync_device_day_window(
                fusionsolar_session,
                session,
                device,
                window,
                tz=tz,
                resume=resume,
            )
            match result.outcome:
                case SyncRunOutcome.DONE:
                    synced += 1
                    readings_upserted += result.readings_upserted
                case SyncRunOutcome.SKIPPED:
                    skipped += 1
                case SyncRunOutcome.FAILED:
                    failed += 1

    plant_readings_upserted, plant_skipped = sync_plant_power_readings(
        session,
        plant=plant,
        devices=devices,
        from_date=from_date,
        to_date=to_date,
    )

    return SyncRunResult(
        synced=synced,
        skipped=skipped,
        readings_upserted=readings_upserted,
        failed=failed,
        plant_readings_upserted=plant_readings_upserted,
        plant_skipped=plant_skipped,
    )


def sync_history(
    *,
    plant_code: str,
    from_date: date | None = None,
    to_date: date | None = None,
    resume: bool = True,
    database_url: str | None = None,
    fusionsolar_session: FusionSolarSession | None = None,
) -> SyncRunResult:
    """Login, load DB config, and sync device history for a plant.

    Parameters
    ----------
    plant_code : str
        FusionSolar plant code stored in the ``plants`` table.
    from_date : date or None, optional
        First calendar day to sync. Defaults to ``DEFAULT_BACKFILL_START``.
    to_date : date or None, optional
        Last calendar day to sync. Defaults to yesterday in the plant timezone.
    resume : bool, optional
        When ``True``, skip windows already marked ``done``.
    database_url : str or None, optional
        Postgres connection URL.
    fusionsolar_session : FusionSolarSession or None, optional
        Existing authenticated session. When omitted, a new login is performed.

    Returns
    -------
    SyncRunResult
        Counters summarizing the run.
    """
    resolved_from_date = from_date or DEFAULT_BACKFILL_START
    active_fusionsolar_session = fusionsolar_session or login_fusionsolar()

    with get_session(database_url) as session:
        plant, devices = load_plant_config(session, plant_code)
        tz = plant_timezone(plant)
        resolved_to_date = to_date or default_sync_end_date(tz=tz)

        if resolved_from_date > resolved_to_date:
            raise ValueError(
                f"from_date {resolved_from_date} is after "
                f"to_date {resolved_to_date}"
            )

        logger.info(
            f"Syncing plant {plant_code} from {resolved_from_date} "
            f"to {resolved_to_date} for {len(devices)} device(s)"
        )
        return sync_device_history(
            active_fusionsolar_session,
            session,
            plant=plant,
            devices=devices,
            from_date=resolved_from_date,
            to_date=resolved_to_date,
            resume=resume,
        )

"""Incremental history backfill for the current calendar day."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from darb_solar.db import (
    DbSession,
    Device,
    Plant,
    get_latest_collected_at,
    get_session,
    list_device_power_readings,
    upsert_device_power_reading,
    upsert_plant_power_reading,
    utc_now,
)
from darb_solar.history_sync.api import _fetch_device_history
from darb_solar.history_sync.session import FusionSolarSession, login_fusionsolar
from darb_solar.history_sync.sync import (
    _device_by_role,
    derive_plant_power_readings,
    history_records_to_readings,
    load_plant_config,
    plant_timezone,
)
from darb_solar.history_sync.types import (
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)
from darb_solar.time import datetime_to_epoch_ms

_MIN_SYNC_GAP = timedelta(minutes=5)


def _intraday_bounds(
    session: DbSession,
    device: Device,
    *,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return ``(start_dt, end_dt)`` for an intraday history fetch.

    ``start_dt`` is the later of the device's latest stored reading and
    midnight today in ``now``'s timezone. ``end_dt`` is ``now``.
    """
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    latest_collected_at = get_latest_collected_at(session, device.dev_id)
    if latest_collected_at is None:
        return start_of_today, now
    return max(latest_collected_at, start_of_today), now


def sync_device_intraday(
    fusionsolar_session: FusionSolarSession,
    session: DbSession,
    device: Device,
    *,
    tz: ZoneInfo,
    start_dt: datetime,
    end_dt: datetime,
    min_gap: timedelta = _MIN_SYNC_GAP,
) -> DeviceSyncResult:
    """Fetch incremental history for one device from the last reading to now.

    Does not read or write ``sync_windows`` checkpoints.

    Parameters
    ----------
    fusionsolar_session : FusionSolarSession
        Authenticated FusionSolar session.
    session : DbSession
        Open SQLAlchemy session.
    device : Device
        Device metadata loaded from the database.
    tz : ZoneInfo
        Plant-local timezone for timestamps.
    start_dt : datetime
        Inclusive lower bound for the history fetch.
    end_dt : datetime
        Upper bound for the history fetch (typically the run's ``now``).
    min_gap : timedelta, optional
        Skip when ``end_dt - start_dt`` is shorter than this interval.

    Returns
    -------
    DeviceSyncResult
        Number of readings upserted and the per-device outcome.
    """
    dev_id = device.dev_id

    if end_dt - start_dt < min_gap:
        logger.info(
            f"Skipping dev_id={dev_id} intraday sync: "
            f"gap {end_dt - start_dt} < {min_gap}"
        )
        return DeviceSyncResult(0, SyncRunOutcome.SKIPPED)

    start_ms = datetime_to_epoch_ms(start_dt)
    end_ms = datetime_to_epoch_ms(end_dt)

    try:
        records = _fetch_device_history(
            fusionsolar_session,
            device,
            start_ms=start_ms,
            end_ms=end_ms,
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
        session.commit()
        logger.info(
            f"Intraday synced dev_id={dev_id}: {len(readings)} reading(s)"
        )
        return DeviceSyncResult(len(readings), SyncRunOutcome.DONE)
    except Exception as exc:
        session.rollback()
        logger.error(f"Intraday sync failed dev_id={dev_id}: {exc}")
        return DeviceSyncResult(0, SyncRunOutcome.FAILED)


def sync_plant_intraday(
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    collected_from: datetime,
    collected_to: datetime,
) -> int:
    """Derive and persist plant metrics for a half-open intraday range.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant : Plant
        Plant metadata loaded from the database.
    devices : list[Device]
        Devices registered for the plant.
    collected_from : datetime
        Inclusive lower bound.
    collected_to : datetime
        Exclusive upper bound.

    Returns
    -------
    int
        Number of plant rows upserted.
    """
    inverter = _device_by_role(devices, "inverter")
    meter = _device_by_role(devices, "meter")
    inverter_readings = list_device_power_readings(
        session,
        dev_id=inverter.dev_id,
        collected_from=collected_from,
        collected_to=collected_to,
    )
    meter_readings = list_device_power_readings(
        session,
        dev_id=meter.dev_id,
        collected_from=collected_from,
        collected_to=collected_to,
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
        f"Intraday derived plant metrics: {len(plant_readings)} reading(s)"
    )
    return len(plant_readings)


def sync_intraday_devices(
    fusionsolar_session: FusionSolarSession,
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    min_gap: timedelta = _MIN_SYNC_GAP,
) -> tuple[list[DeviceSyncResult], datetime, datetime]:
    """Incrementally sync all devices and return per-device results.

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
    min_gap : timedelta, optional
        Skip a device when ``now - start`` is shorter than this interval.

    Returns
    -------
    tuple[list[DeviceSyncResult], datetime, datetime]
        Per-device outcomes plus ``(collected_from, collected_to)`` bounds
        for plant derivation: earliest per-device ``start_dt`` from
        ``_intraday_bounds`` through ``now``.
    """
    tz = plant_timezone(plant)
    now = datetime.now(tz)
    earliest_start: datetime | None = None
    device_results: list[DeviceSyncResult] = []

    for device in devices:
        start_dt, end_dt = _intraday_bounds(session, device, now=now)
        if earliest_start is None or start_dt < earliest_start:
            earliest_start = start_dt
        device_results.append(
            sync_device_intraday(
                fusionsolar_session,
                session,
                device,
                tz=tz,
                start_dt=start_dt,
                end_dt=end_dt,
                min_gap=min_gap,
            )
        )

    if earliest_start is None:
        earliest_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return device_results, earliest_start, now


def sync_intraday(
    *,
    plant_code: str,
    database_url: str | None = None,
    fusionsolar_session: FusionSolarSession | None = None,
    min_gap: timedelta = _MIN_SYNC_GAP,
) -> SyncRunResult:
    """Login, load DB config, and incrementally sync today for a plant.

    Fetches history from each device's latest ``collected_at`` (or start of
    today) through now, without touching ``sync_windows`` checkpoints.

    Parameters
    ----------
    plant_code : str
        FusionSolar plant code stored in the ``plants`` table.
    database_url : str or None, optional
        Postgres connection URL.
    fusionsolar_session : FusionSolarSession or None, optional
        Existing authenticated session. When omitted, a new login is performed.
    min_gap : timedelta, optional
        Skip a device when ``now - start`` is shorter than this interval.

    Returns
    -------
    SyncRunResult
        Counters summarizing the run.
    """
    active_fusionsolar_session = fusionsolar_session or login_fusionsolar()

    with get_session(database_url) as session:
        plant, devices = load_plant_config(session, plant_code)

        logger.info(
            f"Intraday sync for plant {plant_code} "
            f"across {len(devices)} device(s)"
        )

        device_results, collected_from, collected_to = sync_intraday_devices(
            active_fusionsolar_session,
            session,
            plant=plant,
            devices=devices,
            min_gap=min_gap,
        )

        synced = 0
        skipped = 0
        failed = 0
        readings_upserted = 0

        for result in device_results:
            match result.outcome:
                case SyncRunOutcome.DONE:
                    synced += 1
                    readings_upserted += result.readings_upserted
                case SyncRunOutcome.SKIPPED:
                    skipped += 1
                case SyncRunOutcome.FAILED:
                    failed += 1

        plant_readings_upserted = 0
        if synced > 0:
            plant_readings_upserted = sync_plant_intraday(
                session,
                plant=plant,
                devices=devices,
                collected_from=collected_from,
                collected_to=collected_to,
            )

        return SyncRunResult(
            synced=synced,
            skipped=skipped,
            failed=failed,
            readings_upserted=readings_upserted,
            plant_readings_upserted=plant_readings_upserted,
        )

"""Incremental history backfill for today and the overnight gap."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from darb_solar.db import (
    DbSession,
    Device,
    DeviceRole,
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
_PLANT_DERIVE_LOOKBACK = timedelta(hours=1)


def _intraday_bounds(
    session: DbSession,
    device: Device,
    *,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return ``(start_dt, end_dt)`` for an intraday history fetch.

    ``end_dt`` is ``now``. ``start_dt`` is the device's latest stored reading when that
    reading falls on today or yesterday, so the first post-midnight run can close the
    overnight gap. Older gaps stay with the daily history sync: when there is no latest
    reading, or it is older than yesterday, ``start_dt`` is midnight today in ``now``'s
    timezone.
    """
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_yesterday = start_of_today - timedelta(days=1)
    latest_collected_at = get_latest_collected_at(session, device.dev_id)
    if latest_collected_at is None or latest_collected_at < start_of_yesterday:
        return start_of_today, now
    return latest_collected_at, now


def _plant_derive_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return ``(derive_from, derive_to)`` for plant metric derivation.

    Uses a fixed lookback from ``now`` so staggered device syncs can still heal
    interior ``:00``/``:30`` holes after a later ``:05``/``:10`` row already
    exists.

    Parameters
    ----------
    now : datetime
        Current plant-local time (timezone-aware).

    Returns
    -------
    tuple[datetime, datetime]
        Inclusive lower bound and exclusive-style upper bound (``now``).
    """
    return now - _PLANT_DERIVE_LOOKBACK, now


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

    try:
        # Savepoint rollback is automatic on any exception in this block.
        with session.begin_nested():
            for reading in readings:
                upsert_device_power_reading(session, reading)
    except Exception as exc:
        logger.error(f"Intraday sync failed dev_id={dev_id}: {exc}")
        return DeviceSyncResult(0, SyncRunOutcome.FAILED)

    logger.info(f"Intraday synced dev_id={dev_id}: {len(readings)} reading(s)")
    return DeviceSyncResult(len(readings), SyncRunOutcome.DONE)


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
    logger.info(f"Intraday derived plant metrics: {len(plant_readings)} reading(s)")
    return len(plant_readings)


def sync_intraday_devices(
    fusionsolar_session: FusionSolarSession,
    session: DbSession,
    *,
    plant: Plant,
    devices: list[Device],
    min_gap: timedelta = _MIN_SYNC_GAP,
    device_role: DeviceRole | None = None,
) -> tuple[list[DeviceSyncResult], datetime, datetime]:
    """Incrementally sync devices and return per-device results.

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
    device_role : DeviceRole or None, optional
        When set, sync only the device with this role.

    Returns
    -------
    tuple[list[DeviceSyncResult], datetime, datetime]
        Per-device outcomes plus ``(derive_from, derive_to)`` bounds
        for plant derivation from ``_plant_derive_bounds`` (1h lookback).
    """
    tz = plant_timezone(plant)
    now = datetime.now(tz)

    devices_to_sync = (
        [_device_by_role(devices, device_role)] if device_role is not None else devices
    )
    device_results: list[DeviceSyncResult] = []
    for device in devices_to_sync:
        start_dt, end_dt = _intraday_bounds(session, device, now=now)
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

    # Re-derive plant metrics over the last hour, not from the latest plant
    # row. Inverter (:00/:30) and meter (:06/:36) syncs are staggered, so a
    # :00/:30 plant hole (reading not available then, but present in a later
    # sync) can sit behind newer :05/:10 rows; a forward-only cursor would
    # never revisit it.
    derive_from, derive_to = _plant_derive_bounds(now)
    return device_results, derive_from, derive_to


def sync_intraday(
    *,
    plant_code: str,
    database_url: str | None = None,
    fusionsolar_session: FusionSolarSession | None = None,
    min_gap: timedelta = _MIN_SYNC_GAP,
    device_role: DeviceRole | None = None,
    derive_plant: bool = True,
) -> SyncRunResult:
    """Login, load DB config, and incrementally sync a plant.

    Fetches history from each device's latest ``collected_at`` when that falls
    on today or yesterday (so midnight can close the overnight gap), otherwise
    from start of today, through now. When ``derive_plant`` is true, plant
    metrics are re-derived over a 1h lookback even if every device sync was
    skipped. Does not touch ``sync_windows`` checkpoints.

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
    device_role : DeviceRole or None, optional
        When set, sync only the device with this role.
    derive_plant : bool, optional
        When ``False``, skip plant metric derivation after device sync.

    Returns
    -------
    SyncRunResult
        Counters summarizing the run.
    """
    active_fusionsolar_session = fusionsolar_session or login_fusionsolar()

    with get_session(database_url) as session:
        plant, devices = load_plant_config(session, plant_code)

        if device_role is not None:
            logger.info(
                f"Intraday sync for plant {plant_code} "
                f"role={device_role.value} "
                f"(derive_plant={derive_plant})"
            )
        else:
            logger.info(
                f"Intraday sync for plant {plant_code} "
                f"across {len(devices)} device(s)"
            )

        device_results, derive_from, derive_to = sync_intraday_devices(
            active_fusionsolar_session,
            session,
            plant=plant,
            devices=devices,
            min_gap=min_gap,
            device_role=device_role,
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
        if derive_plant:
            plant_readings_upserted = sync_plant_intraday(
                session,
                plant=plant,
                devices=devices,
                collected_from=derive_from,
                collected_to=derive_to,
            )

        return SyncRunResult(
            synced=synced,
            skipped=skipped,
            failed=failed,
            readings_upserted=readings_upserted,
            plant_readings_upserted=plant_readings_upserted,
        )

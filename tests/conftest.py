"""Shared pytest fixtures for the darb-solar test suite.

Fixtures that depend on the optional ``viz`` extra (pandas) import it lazily, so tests
that do not request them still run when the extra is not installed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
import requests
from pytest_mock import MockerFixture, MockType
from sqlalchemy.orm import Session

from darb_solar.db import connection
from darb_solar.db.models import Device, Plant
from darb_solar.db.types import DeviceRole
from darb_solar.fusionsolar import FusionSolarClient
from darb_solar.history_sync.session import FusionSolarSession

if TYPE_CHECKING:
    import pandas as pd

PLANT_CODE = "NE=12345678"
PLANT_NAME = "Darb Test Plant"
TIMEZONE_NAME = "Africa/Casablanca"
INVERTER_DEV_ID = "1000000001"
METER_DEV_ID = "1000000002"
INVERTER_DEV_TYPE_ID = 1
METER_DEV_TYPE_ID = 47

ReadingsDfFactory = Callable[..., "pd.DataFrame"]
FakeResponseFactory = Callable[..., MockType]


@pytest.fixture
def casablanca_tz() -> ZoneInfo:
    """Return the plant-local ``Africa/Casablanca`` timezone.

    Returns
    -------
    zoneinfo.ZoneInfo
        Timezone used by the test plant.
    """
    return ZoneInfo(TIMEZONE_NAME)


@pytest.fixture
def plant() -> Plant:
    """Return a transient ``Plant`` ORM instance.

    Returns
    -------
    Plant
        Plant not attached to any session.
    """
    return Plant(
        plant_code=PLANT_CODE,
        plant_name=PLANT_NAME,
        timezone=TIMEZONE_NAME,
    )


@pytest.fixture
def inverter(plant: Plant) -> Device:
    """Return a transient inverter ``Device`` belonging to `plant`.

    Parameters
    ----------
    plant : Plant
        Owning plant fixture.

    Returns
    -------
    Device
        Inverter device not attached to any session.
    """
    return Device(
        dev_id=INVERTER_DEV_ID,
        plant_code=plant.plant_code,
        dev_dn=f"NE={INVERTER_DEV_ID}",
        dev_type_id=INVERTER_DEV_TYPE_ID,
        role=DeviceRole.INVERTER,
    )


@pytest.fixture
def meter(plant: Plant) -> Device:
    """Return a transient meter ``Device`` belonging to `plant`.

    Parameters
    ----------
    plant : Plant
        Owning plant fixture.

    Returns
    -------
    Device
        Meter device not attached to any session.
    """
    return Device(
        dev_id=METER_DEV_ID,
        plant_code=plant.plant_code,
        dev_dn=f"NE={METER_DEV_ID}",
        dev_type_id=METER_DEV_TYPE_ID,
        role=DeviceRole.METER,
    )


@pytest.fixture
def db_session(mocker: MockerFixture) -> MockType:
    """Return a mock SQLAlchemy session.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Mock constrained to the ``sqlalchemy.orm.Session`` interface.
    """
    return mocker.MagicMock(spec=Session)


@pytest.fixture
def fusionsolar_session(mocker: MockerFixture) -> MockType:
    """Return a mock FusionSolar session exposing a mock ``client``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Mock ``FusionSolarSession`` whose ``client`` is a mock
        ``FusionSolarClient``.
    """
    session = mocker.MagicMock(spec=FusionSolarSession)
    session.client = mocker.MagicMock(spec=FusionSolarClient)
    return session


@pytest.fixture
def readings_df(casablanca_tz: ZoneInfo) -> ReadingsDfFactory:
    """Return a factory building plant-local five-minute readings DataFrames.

    Parameters
    ----------
    casablanca_tz : zoneinfo.ZoneInfo
        Plant-local timezone applied to ``collected_at``.

    Returns
    -------
    collections.abc.Callable
        Factory taking `pv_production_kw`, `grid_export_kw` and
        `consumption_kw` sequences of equal length, plus an optional `start`
        datetime, and returning a DataFrame passed through
        ``with_derived_columns``.
    """
    pandas = pytest.importorskip("pandas")
    from darb_solar.power.constants import READING_INTERVAL_MINUTES
    from darb_solar.power.derived import with_derived_columns

    def _build(
        pv_production_kw: Sequence[float],
        grid_export_kw: Sequence[float],
        consumption_kw: Sequence[float],
        start: datetime | None = None,
    ) -> pd.DataFrame:
        if not len(pv_production_kw) == len(grid_export_kw) == len(consumption_kw):
            raise ValueError("reading sequences must have the same length")

        if start is None:
            start = datetime(2026, 6, 1, tzinfo=casablanca_tz)
        collected_at = pandas.date_range(
            start=start,
            periods=len(pv_production_kw),
            freq=f"{READING_INTERVAL_MINUTES}min",
        ).tz_convert(casablanca_tz)
        df = pandas.DataFrame(
            {
                "plant_code": PLANT_CODE,
                "collected_at": collected_at,
                "pv_production_kw": list(pv_production_kw),
                "grid_export_kw": list(grid_export_kw),
                "consumption_kw": list(consumption_kw),
                "synced_at": datetime(2026, 6, 2, tzinfo=timezone.utc),
            }
        )
        return with_derived_columns(df)

    return _build


@pytest.fixture
def fake_response(mocker: MockerFixture) -> FakeResponseFactory:
    """Return a factory building mock ``requests.Response`` objects.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    collections.abc.Callable
        Factory taking a JSON `payload`, optional response `headers` and an
        optional `http_error` raised by ``raise_for_status()``.
    """

    def _build(
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        http_error: requests.HTTPError | None = None,
    ) -> MockType:
        response = mocker.MagicMock(spec=requests.Response)
        response.json.return_value = dict(payload or {})
        response.headers = dict(headers or {})
        response.raise_for_status.side_effect = http_error
        return response

    return _build


@pytest.fixture(autouse=True)
def _clear_connection_caches() -> Iterator[None]:
    """Clear cached engines and session factories around every test.

    Yields
    ------
    None
        Control returns to the test between the two cache clears.
    """
    connection._engines.clear()
    connection._session_factories.clear()
    yield
    connection._engines.clear()
    connection._session_factories.clear()

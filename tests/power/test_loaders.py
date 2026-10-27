"""Tests for ``darb_solar.power.loaders``."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pytest_mock import MockerFixture, MockType
from sqlalchemy.dialects import postgresql

pd = pytest.importorskip("pandas")

from darb_solar.power import loaders  # noqa: E402
from darb_solar.power.columns import READING_COLUMNS  # noqa: E402

PLANT_CODE = "NE=12345678"


@pytest.fixture
def read_sql_mock(mocker: MockerFixture) -> MockType:
    """Patch ``pd.read_sql`` as used by the loaders module.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched ``read_sql`` returning an empty frame by default.
    """
    return mocker.patch.object(
        loaders.pd,
        "read_sql",
        return_value=pd.DataFrame(),
    )


@pytest.fixture
def utc_rows() -> pd.DataFrame:
    """Return two raw plant readings as stored in the database (UTC).

    Returns
    -------
    pandas.DataFrame
        Raw readings without derived columns.
    """
    return pd.DataFrame(
        {
            "plant_code": [PLANT_CODE, PLANT_CODE],
            "collected_at": pd.to_datetime(
                ["2026-06-01 22:55:00", "2026-06-01 23:00:00"],
                utc=True,
            ),
            "pv_production_kw": [6.0, 0.0],
            "grid_export_kw": [1.0, 0.0],
            "consumption_kw": [3.0, 2.0],
            "synced_at": pd.to_datetime(["2026-06-02", "2026-06-02"], utc=True),
        }
    )


def test_load_power_readings_df_returns_empty_schema_without_rows(
    db_session: MockType,
    read_sql_mock: MockType,
    casablanca_tz: ZoneInfo,
) -> None:
    """With no rows, an empty frame with ``READING_COLUMNS`` is returned."""
    start = datetime(2026, 6, 1, tzinfo=casablanca_tz)

    df = loaders.load_power_readings_df(
        db_session,
        PLANT_CODE,
        start,
        start + timedelta(days=1),
        casablanca_tz,
    )

    assert df.empty
    assert list(df.columns) == READING_COLUMNS


def test_load_power_readings_df_queries_half_open_range(
    db_session: MockType,
    read_sql_mock: MockType,
    casablanca_tz: ZoneInfo,
) -> None:
    """The statement filters the plant and the half-open time range in order."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 2, tzinfo=timezone.utc)

    loaders.load_power_readings_df(db_session, PLANT_CODE, start, end, casablanca_tz)

    (statement, connection), _ = read_sql_mock.call_args
    assert connection is db_session.connection.return_value
    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    assert "FROM plant_power_readings" in sql
    assert f"plant_power_readings.plant_code = '{PLANT_CODE}'" in sql
    assert "plant_power_readings.collected_at >= '2026-06-01 00:00:00+00:00'" in sql
    assert "plant_power_readings.collected_at < '2026-06-02 00:00:00+00:00'" in sql
    assert sql.endswith("ORDER BY plant_power_readings.collected_at")


def test_load_power_readings_df_converts_to_plant_timezone_and_derives(
    db_session: MockType,
    read_sql_mock: MockType,
    utc_rows: pd.DataFrame,
    casablanca_tz: ZoneInfo,
) -> None:
    """Timestamps become plant-local and derived columns are added."""
    read_sql_mock.return_value = utc_rows
    start = datetime(2026, 6, 1, tzinfo=casablanca_tz)

    df = loaders.load_power_readings_df(
        db_session,
        PLANT_CODE,
        start,
        start + timedelta(days=1),
        casablanca_tz,
    )

    assert df["collected_at"].dt.tz == casablanca_tz
    assert df["collected_at"].dt.hour.tolist() == [23, 0]
    assert df["self_consumed_kw"].tolist() == [5.0, 0.0]
    assert df["grid_import_kw"].tolist() == [0.0, 2.0]
    assert set(READING_COLUMNS) <= set(df.columns)


def test_load_day_data_uses_local_day_bounds(
    db_session: MockType,
    mocker: MockerFixture,
    casablanca_tz: ZoneInfo,
) -> None:
    """The day is loaded from local midnight to the next local midnight."""
    load_mock = mocker.patch.object(loaders, "load_power_readings_df")

    result = loaders.load_day_data(
        db_session,
        PLANT_CODE,
        date(2026, 6, 1),
        casablanca_tz,
    )

    assert result is load_mock.return_value
    load_mock.assert_called_once_with(
        db_session,
        PLANT_CODE,
        datetime(2026, 6, 1, tzinfo=casablanca_tz),
        datetime(2026, 6, 2, tzinfo=casablanca_tz),
        casablanca_tz,
    )


@pytest.mark.parametrize(
    ("year", "month", "expected_end"),
    [
        (2026, 6, (2026, 7)),
        (2026, 12, (2027, 1)),
    ],
)
def test_load_month_data_uses_local_month_bounds(
    db_session: MockType,
    mocker: MockerFixture,
    casablanca_tz: ZoneInfo,
    year: int,
    month: int,
    expected_end: tuple[int, int],
) -> None:
    """The month ends at the next month start, rolling over in December."""
    load_mock = mocker.patch.object(loaders, "load_power_readings_df")

    result = loaders.load_month_data(
        db_session,
        PLANT_CODE,
        year,
        month,
        casablanca_tz,
    )

    assert result is load_mock.return_value
    load_mock.assert_called_once_with(
        db_session,
        PLANT_CODE,
        datetime(year, month, 1, tzinfo=casablanca_tz),
        datetime(*expected_end, 1, tzinfo=casablanca_tz),
        casablanca_tz,
    )


def test_load_year_data_uses_local_year_bounds(
    db_session: MockType,
    mocker: MockerFixture,
    casablanca_tz: ZoneInfo,
) -> None:
    """The year is loaded from January 1 to the next January 1."""
    load_mock = mocker.patch.object(loaders, "load_power_readings_df")

    result = loaders.load_year_data(db_session, PLANT_CODE, 2026, casablanca_tz)

    assert result is load_mock.return_value
    load_mock.assert_called_once_with(
        db_session,
        PLANT_CODE,
        datetime(2026, 1, 1, tzinfo=casablanca_tz),
        datetime(2027, 1, 1, tzinfo=casablanca_tz),
        casablanca_tz,
    )

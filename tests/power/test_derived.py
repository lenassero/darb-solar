"""Tests for ``darb_solar.power.derived``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from darb_solar.power.columns import READING_COLUMNS  # noqa: E402
from darb_solar.power.derived import with_derived_columns  # noqa: E402

ReadingsDfFactory = Callable[..., Any]


def test_derived_power_flows(readings_df: ReadingsDfFactory) -> None:
    """Self-consumption is production minus export; import never goes negative."""
    df = readings_df(
        pv_production_kw=[4.0, 1.0, 0.0],
        grid_export_kw=[1.0, 0.0, 0.0],
        consumption_kw=[3.0, 3.0, 2.0],
    )

    assert df["self_consumed_kw"].tolist() == [3.0, 1.0, 0.0]
    assert df["grid_import_kw"].tolist() == [0.0, 2.0, 2.0]


def test_import_is_clipped_at_zero_when_production_exceeds_consumption(
    readings_df: ReadingsDfFactory,
) -> None:
    """A surplus of production over consumption yields zero grid import."""
    df = readings_df([10.0], [7.0], [3.0])

    assert df["grid_import_kw"].tolist() == [0.0]


def test_energy_columns_are_power_over_twelve(readings_df: ReadingsDfFactory) -> None:
    """Five-minute readings convert to kWh by dividing kW by twelve."""
    df = readings_df([6.0], [1.2], [9.0])

    assert df["self_consumed_kwh"].iloc[0] == pytest.approx(4.8 / 12)
    assert df["grid_export_kwh"].iloc[0] == pytest.approx(1.2 / 12)
    assert df["grid_import_kwh"].iloc[0] == pytest.approx(3.0 / 12)
    assert df["consumption_kwh"].iloc[0] == pytest.approx(9.0 / 12)


def test_output_has_every_reading_column(readings_df: ReadingsDfFactory) -> None:
    """Derived output exposes the full ``READING_COLUMNS`` schema."""
    df = readings_df([1.0], [0.0], [1.0])

    assert set(READING_COLUMNS) <= set(df.columns)


def test_input_is_not_mutated() -> None:
    """The function returns a copy and leaves its argument untouched."""
    raw = pd.DataFrame(
        {
            "pv_production_kw": [2.0],
            "grid_export_kw": [0.5],
            "consumption_kw": [1.0],
        }
    )

    derived = with_derived_columns(raw)

    assert list(raw.columns) == [
        "pv_production_kw",
        "grid_export_kw",
        "consumption_kw",
    ]
    assert "self_consumed_kw" in derived.columns

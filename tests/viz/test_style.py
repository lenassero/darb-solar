"""Tests for ``darb_solar.viz.style``."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

pytest.importorskip("plotly")

from darb_solar.viz import style  # noqa: E402


def test_home_consumption_icon_source_encodes_icon_file(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """The icon file content is returned as a base64 PNG data URL."""
    icon_path = tmp_path / "icon.png"
    icon_path.write_bytes(b"\x89PNG fake bytes")
    mocker.patch.object(style, "HOME_CONSUMPTION_ICON", icon_path)

    source = style.home_consumption_icon_source()

    assert (
        source
        == "data:image/png;base64," + base64.b64encode(b"\x89PNG fake bytes").decode()
    )


def test_home_consumption_icon_exists_in_repository() -> None:
    """The packaged icon resolves to a real PNG so the default path works."""
    source = style.home_consumption_icon_source()

    prefix = "data:image/png;base64,"
    assert source.startswith(prefix)
    assert base64.b64decode(source[len(prefix) :]).startswith(b"\x89PNG")


def test_donut_center_layout_formats_total_and_places_icon(
    mocker: MockerFixture,
) -> None:
    """The center shows the icon above the total formatted to one decimal."""
    mocker.patch.object(style, "home_consumption_icon_source", return_value="data:x")

    images, annotations = style.donut_center_layout(12.345)

    assert len(images) == 1
    assert images[0]["source"] == "data:x"
    assert images[0]["y"] == style.CENTER_ICON_Y
    assert images[0]["sizex"] == style.CENTER_ICON_SIZE
    assert len(annotations) == 1
    assert annotations[0]["text"] == "12.3kWh"
    assert annotations[0]["y"] == style.CENTER_TEXT_Y
    assert annotations[0]["showarrow"] is False


@pytest.mark.parametrize(
    ("total_kwh", "expected_text"),
    [(0.0, "0.0kWh"), (7, "7.0kWh"), (1234.56, "1234.6kWh")],
)
def test_donut_center_layout_text_precision(
    mocker: MockerFixture,
    total_kwh: float,
    expected_text: str,
) -> None:
    """The total is always rendered with one decimal and a ``kWh`` suffix."""
    mocker.patch.object(style, "home_consumption_icon_source", return_value="data:x")

    _, annotations = style.donut_center_layout(total_kwh)

    assert annotations[0]["text"] == expected_text

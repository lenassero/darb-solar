"""Shared chart styling constants and layout helpers."""

from __future__ import annotations

import base64
from pathlib import Path

DONUT_HEIGHT = 360
DONUT_HOLE = 0.4
DONUT_TEXT_SIZE = 22
HOME_CONSUMPTION_ICON = (
    Path(__file__).resolve().parents[3] / "images" / "home_consumption.png"
)
CENTER_ICON_Y = 0.58
CENTER_TEXT_Y = 0.42
CENTER_ICON_SIZE = 0.12


def home_consumption_icon_source() -> str:
    """Return a data URL for the home-consumption center icon.

    Returns
    -------
    str
        Base64-encoded PNG data URL for Plotly image overlays.
    """
    encoded = base64.b64encode(HOME_CONSUMPTION_ICON.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


def donut_center_layout(total_kwh: float) -> tuple[list[dict], list[dict]]:
    """Build Plotly image and annotation layouts for the donut center.

    Parameters
    ----------
    total_kwh : float
        Total consumption shown under the center icon.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(images, annotations)`` ready for ``Figure.update_layout``.
    """
    images = [
        {
            "source": home_consumption_icon_source(),
            "xref": "paper",
            "yref": "paper",
            "x": 0.5,
            "y": CENTER_ICON_Y,
            "sizex": CENTER_ICON_SIZE,
            "sizey": CENTER_ICON_SIZE,
            "xanchor": "center",
            "yanchor": "middle",
            "layer": "above",
        }
    ]
    annotations = [
        {
            "text": f"{total_kwh:.1f}kWh",
            "x": 0.5,
            "y": CENTER_TEXT_Y,
            "xref": "paper",
            "yref": "paper",
            "xanchor": "center",
            "yanchor": "middle",
            "showarrow": False,
            "font": {"size": 20},
        }
    ]
    return images, annotations

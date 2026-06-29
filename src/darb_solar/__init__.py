"""darb-solar."""

from __future__ import annotations

from darb_solar.env import load_env
from darb_solar.fusionsolar import FusionSolarClient

__all__ = ["FusionSolarClient", "load_env", "__version__"]

__version__ = "0.1.0"

"""Cloud Run HTTP entrypoint for the FusionSolar intraday sync.

This is a thin wrapper around the existing sync logic in ``darb_solar``. It is deployed
as a Cloud Run function (functions-framework) and is intended to be triggered on a
schedule by Cloud Scheduler.

The handler keeps request parsing minimal and contains no business logic: it resolves
configuration from the environment and delegates to ``sync_intraday``.

Optional JSON body (Cloud Scheduler ``--message-body``)::

    {"role": "inverter", "derive_plant": false}
    {"role": "meter", "derive_plant": true}

When ``role`` is set and ``derive_plant`` is omitted, ``derive_plant`` defaults to
``false``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# The package uses a src/ layout. When deployed from source, the tree is copied
# verbatim, so make ``src`` importable before importing ``darb_solar``.
_SRC_DIR = str(Path(__file__).resolve().parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import functions_framework  # noqa: E402
from loguru import logger  # noqa: E402

from darb_solar.db import (  # noqa: E402
    DeviceRole,
    redact_database_url,
    resolve_database_url,
)
from darb_solar.intraday_sync import sync_intraday  # noqa: E402

_VALID_ROLES = {role.value for role in DeviceRole}


def _parse_sync_options(request: Any) -> tuple[DeviceRole | None, bool]:
    """Parse optional ``role`` / ``derive_plant`` from the request JSON body.

    Parameters
    ----------
    request : flask.Request
        Incoming HTTP request. Body may be empty or JSON with ``role`` and
        ``derive_plant``.

    Returns
    -------
    tuple[DeviceRole or None, bool]
        Device role filter (``None`` = all devices) and whether to derive
        plant metrics.

    Raises
    ------
    ValueError
        If ``role`` is present but not ``inverter`` or ``meter``, or if
        ``derive_plant`` is present but not a boolean.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, True

    role_raw = body.get("role")
    device_role: DeviceRole | None = None
    if role_raw is not None:
        if not isinstance(role_raw, str) or role_raw not in _VALID_ROLES:
            raise ValueError(
                f"role must be one of {sorted(_VALID_ROLES)}, got {role_raw!r}."
            )
        device_role = DeviceRole(role_raw)

    if "derive_plant" in body:
        derive_plant = body["derive_plant"]
        if not isinstance(derive_plant, bool):
            raise ValueError(f"derive_plant must be a boolean, got {derive_plant!r}.")
    elif device_role is not None:
        derive_plant = False
    else:
        derive_plant = True

    return device_role, derive_plant


@functions_framework.http
def sync(request: Any):
    """HTTP entrypoint that runs the intraday sync and returns a summary.

    Parameters
    ----------
    request : flask.Request
        Incoming HTTP request. The plant code is read from
        ``DARB_SOLAR_PLANT_CODE`` and the database URL from
        ``DARB_SOLAR_DATABASE_URL``. Optional JSON body may include
        ``role`` (``inverter`` or ``meter``) and ``derive_plant``.

    Returns
    -------
    tuple[dict, int]
        JSON-serializable summary and an HTTP status code.
    """
    plant_code = os.environ.get("DARB_SOLAR_PLANT_CODE")
    if not plant_code:
        return {
            "status": "error",
            "error": "plant_code is required (set DARB_SOLAR_PLANT_CODE).",
        }, 400

    try:
        device_role, derive_plant = _parse_sync_options(request)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}, 400

    database_url = resolve_database_url()
    role_label = device_role.value if device_role is not None else "all"
    logger.info(
        f"Cloud Run intraday sync plant={plant_code} "
        f"role={role_label} derive_plant={derive_plant} "
        f"db={redact_database_url(database_url)}"
    )

    try:
        result = sync_intraday(
            plant_code=plant_code,
            database_url=database_url,
            device_role=device_role,
            derive_plant=derive_plant,
        )
    except ValueError as exc:
        logger.error(f"Sync failed: {exc}")
        return {"status": "error", "error": str(exc)}, 400
    except Exception as exc:  # noqa: BLE001 - surface any failure as HTTP 500
        logger.exception("Unexpected sync failure")
        return {"status": "error", "error": str(exc)}, 500

    summary = {
        "status": "ok" if not result.failed else "partial",
        "plant_code": plant_code,
        "role": role_label,
        "derive_plant": derive_plant,
        "result": asdict(result),
    }
    logger.info(f"Cloud Run intraday sync complete: {summary}")
    status_code = 200 if not result.failed else 207
    return summary, status_code

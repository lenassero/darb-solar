"""Cloud Run HTTP entrypoint for the FusionSolar intraday sync.

This is a thin wrapper around the existing sync logic in ``darb_solar``. It is deployed
as a Cloud Run function (functions-framework) and is intended to be triggered on a
schedule by Cloud Scheduler.

The handler keeps request parsing minimal and contains no business logic: it resolves
configuration from the environment and delegates to ``sync_intraday``.
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

from darb_solar.db import redact_database_url, resolve_database_url  # noqa: E402
from darb_solar.intraday_sync import sync_intraday  # noqa: E402


@functions_framework.http
def sync(request: Any):
    """HTTP entrypoint that runs the intraday sync and returns a summary.

    Parameters
    ----------
    request : flask.Request
        Incoming HTTP request. The plant code is read from
        ``DARB_SOLAR_PLANT_CODE`` and the database URL from
        ``DARB_SOLAR_DATABASE_URL``.

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

    database_url = resolve_database_url()
    logger.info(
        f"Cloud Run intraday sync plant={plant_code} "
        f"db={redact_database_url(database_url)}"
    )

    try:
        result = sync_intraday(plant_code=plant_code, database_url=database_url)
    except ValueError as exc:
        logger.error(f"Sync failed: {exc}")
        return {"status": "error", "error": str(exc)}, 400
    except Exception as exc:  # noqa: BLE001 - surface any failure as HTTP 500
        logger.exception("Unexpected sync failure")
        return {"status": "error", "error": str(exc)}, 500

    summary = {
        "status": "ok" if not result.failed else "partial",
        "plant_code": plant_code,
        "result": asdict(result),
    }
    logger.info(f"Cloud Run intraday sync complete: {summary}")
    status_code = 200 if not result.failed else 207
    return summary, status_code

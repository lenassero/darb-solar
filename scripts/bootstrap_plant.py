"""CLI to seed FusionSolar plant and device reference data into SQLite."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from darb_solar.db import DEFAULT_TIMEZONE_NAME, PROJECT_ROOT, resolve_db_path
from darb_solar.history_sync import bootstrap_plant


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap FusionSolar plant and device metadata into SQLite."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--plant-code",
        default=os.environ.get("DARB_SOLAR_PLANT_CODE"),
        required=not os.environ.get("DARB_SOLAR_PLANT_CODE"),
        help="FusionSolar plant code to register.",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE_NAME,
        help="IANA timezone stored on the plant row.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLite database URL (sqlite:///...).",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to the SQLite database file (overrides --database-url).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the FusionSolar bootstrap CLI.

    Parameters
    ----------
    argv : list[str] or None, optional
        Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)

    try:
        db_path = resolve_db_path(
            args.db_path,
            database_url=args.database_url,
        )
    except ValueError as exc:
        logger.error(f"{exc}")
        return 1

    logger.info(f"Using database at {db_path}")

    try:
        result = bootstrap_plant(
            plant_code=args.plant_code,
            timezone=args.timezone,
            db_path=db_path,
        )
    except ValueError as exc:
        logger.error(f"{exc}")
        return 1

    for device in result.devices:
        logger.info(
            f"Registered {device['role']}: dev_id={device['dev_id']}, "
            f"dev_dn={device['dev_dn']}, dev_type_id={device['dev_type_id']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

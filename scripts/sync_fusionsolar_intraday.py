"""CLI to incrementally sync today's FusionSolar history into Postgres."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

from dotenv import load_dotenv
from loguru import logger

from darb_solar.db import PROJECT_ROOT, redact_database_url, resolve_database_url
from darb_solar.intraday_sync import sync_intraday


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally sync today's FusionSolar device history "
            "into a Postgres database."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--plant-code",
        default=os.environ.get("DARB_SOLAR_PLANT_CODE"),
        required=not os.environ.get("DARB_SOLAR_PLANT_CODE"),
        help="FusionSolar plant code stored in the database.",
    )
    parser.add_argument(
        "--min-gap-minutes",
        type=int,
        default=5,
        help=(
            "Skip a device when the fetch range is shorter than this many " "minutes."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Override DARB_SOLAR_DATABASE_URL for this run "
            "(postgresql+psycopg://...)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the FusionSolar intraday sync CLI.

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

    if args.min_gap_minutes < 1:
        logger.error("--min-gap-minutes must be at least 1.")
        return 1

    database_url = resolve_database_url(args.database_url)

    logger.info(f"Using database at {redact_database_url(database_url)}")

    try:
        result = sync_intraday(
            plant_code=args.plant_code,
            database_url=database_url,
            min_gap=timedelta(minutes=args.min_gap_minutes),
        )
    except ValueError as exc:
        logger.error(f"{exc}")
        return 1

    logger.info(
        "Intraday sync complete: "
        f"{result.synced} device(s) synced, "
        f"{result.skipped} skipped, "
        f"{result.failed} failed, "
        f"{result.readings_upserted} device reading(s), "
        f"{result.plant_readings_upserted} plant reading(s)."
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())

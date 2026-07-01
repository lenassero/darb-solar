"""CLI to backfill FusionSolar device history into Postgres."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from loguru import logger

from darb_solar.db import PROJECT_ROOT, resolve_database_url
from darb_solar.time import DEFAULT_TIMEZONE
from darb_solar.history_sync import sync_history


def parse_sync_date(
    value: str | None,
    *,
    tz=DEFAULT_TIMEZONE,
) -> date | None:
    """Parse a CLI date value or return ``None`` when omitted.

    Parameters
    ----------
    value : str or None
        ISO calendar date (``YYYY-MM-DD``), ``today``, or ``yesterday``.
    tz : ZoneInfo, optional
        Timezone used for relative keywords.

    Returns
    -------
    date or None
        Parsed calendar date, or ``None`` when ``value`` is omitted.

    Raises
    ------
    argparse.ArgumentTypeError
        If ``value`` is not a recognized date format.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    now = datetime.now(tz)
    if normalized == "today":
        return now.date()
    if normalized == "yesterday":
        return (now - timedelta(days=1)).date()

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; use YYYY-MM-DD, today, or yesterday."
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Sync FusionSolar device history into a Postgres database."
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
        "--from-date",
        type=parse_sync_date,
        default=None,
        help="First calendar day to sync (YYYY-MM-DD, today, or yesterday).",
    )
    parser.add_argument(
        "--to-date",
        type=parse_sync_date,
        default=None,
        help="Last calendar day to sync (YYYY-MM-DD, today, or yesterday).",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip device-day windows already marked done in sync_windows.",
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
    """Run the FusionSolar history sync CLI.

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

    database_url = resolve_database_url(args.database_url)

    if args.from_date is not None and args.to_date is not None:
        if args.from_date > args.to_date:
            logger.error(
                f"--from-date {args.from_date} is after "
                f"--to-date {args.to_date}."
            )
            return 1

    logger.info(f"Using database at {database_url}")

    try:
        result = sync_history(
            plant_code=args.plant_code,
            from_date=args.from_date,
            to_date=args.to_date,
            resume=args.resume,
            database_url=database_url,
        )
    except ValueError as exc:
        logger.error(f"{exc}")
        return 1

    logger.info(
        "Sync complete: "
        f"{result.synced} window(s) synced, "
        f"{result.skipped} skipped, "
        f"{result.failed} failed, "
        f"{result.readings_upserted} device reading(s), "
        f"{result.plant_readings_upserted} plant reading(s), "
        f"{result.plant_skipped} plant day(s) skipped."
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())

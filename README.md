# darb-solar

Python package for syncing FusionSolar plant history into a Postgres database.

## Setup

Create a virtual environment and install dependencies:

```bash
cd darb-solar
uv venv
source .venv/bin/activate
uv sync
```

Add/update dependencies with:

```bash
uv add <package>
uv add --dev <package>
```

## Local database

This project uses the **Postgres 16** instance already installed on your Mac
(`/Library/PostgreSQL/16`). Create the application role, database, and tables
once:

```bash
# Prompts for the postgres superuser password from install
./scripts/setup_native_postgres.sh

# Or non-interactive:
PGPASSWORD='your-postgres-password' ./scripts/setup_native_postgres.sh
```

The setup script runs `scripts/setup_native_postgres.sql` (role and database)
and `scripts/setup_schema.sql` (application tables). Re-run only on a fresh
database; there is no automatic schema migration at runtime.

### Database access

The database layer uses [SQLAlchemy](https://www.sqlalchemy.org/) 2.0 ORM with
the psycopg3 driver. Row types such as `Plant` and `Device` are ORM model
classes exported from `darb_solar.db`; open a session with `get_session()`.

Use the psycopg3 driver in `DARB_SOLAR_DATABASE_URL`
(`postgresql+psycopg://...`).

### Docker alternative

`docker compose up -d` is available if you prefer a containerized database.
Use a different host port when native Postgres already listens on 5432 (for
example `5433:5432` in `docker-compose.yml` and update
`DARB_SOLAR_DATABASE_URL` accordingly). Apply `scripts/setup_schema.sql` to
the container database once after it starts.

## Configuration

Create a `.env` file in the project root (never commit it):

```bash
FUSIONSOLAR_USERNAME=your@email.com
FUSIONSOLAR_SYSTEM_CODE=your-system-code
DARB_SOLAR_PLANT_CODE=NE=182468888
DARB_SOLAR_DATABASE_URL=postgresql+psycopg://darb_solar:darb_solar@localhost:5432/darb_solar
```

`DARB_SOLAR_DATABASE_URL` points the application at your local Postgres instance
(default: `postgresql+psycopg://darb_solar:darb_solar@localhost:5432/darb_solar`). The
same URL format works for hosted Postgres providers (Neon, Supabase, and
similar) when you deploy later.

## Data directory

Runtime artifacts live under `data/`:

| path | purpose |
|------|---------|
| `data/logs/` | optional sync job stdout/stderr from scheduled runs |

The `data/` directory is listed in `.gitignore` so logs stay local. The
directory is created automatically on first bootstrap or sync.

## One-time bootstrap

Register the plant and devices from the FusionSolar API:

```bash
uv run python scripts/bootstrap_plant.py
```

## Manual sync

Backfill or refresh history for a date range (plant timezone,
`Africa/Casablanca` by default):

```bash
# Full backfill from 2026-01-01 through yesterday (default range)
uv run python scripts/sync_fusionsolar_history.py

# Sync the previous complete calendar day (daily steady-state)
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date yesterday

# Optional: also refresh today for near-real-time dashboard data
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date today
```

`--resume` is on by default: completed device-day windows in `sync_windows`
are skipped. Re-running the same day is safe because upserts are idempotent.

### Checkpoint status vs run outcome

Two enums describe overlapping but distinct concepts:

| | `SyncWindowCheckpointStatus` (DB) | `SyncWindowRunOutcome` (per run) |
|---|---|---|
| Stored in | `sync_windows.status` | returned in memory only |
| Values | `pending`, `done`, `failed` | `skipped`, `done`, `failed` |
| Role | resume checkpoints across runs | aggregate counters for this run |

`pending` is written when a fetch starts; `done` or `failed` when it finishes.
`skipped` is reported only for this run when resume finds an existing `done`
row and does not call the API again. See docstrings in
`darb_solar.db.types.SyncWindowCheckpointStatus` and
`darb_solar.history_sync.types.SyncWindowRunOutcome`.

Expect roughly five minutes of wall-clock time per device-day because the
FusionSolar API enforces spacing between history calls.

## Daily automation

Run the sync once per day to ingest the previous complete calendar day only
(`yesterday` through `yesterday`). Pick a time after local midnight so that
day is finished (for example 03:00 in `Africa/Casablanca`).

Set `PROJECT_ROOT` to the absolute path of this repository before installing
either scheduler below.

### macOS (launchd)

Create `~/Library/LaunchAgents/com.darb-solar.sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.darb-solar.sync</string>
  <key>WorkingDirectory</key>
  <string>PROJECT_ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>PROJECT_ROOT/.venv/bin/python</string>
    <string>PROJECT_ROOT/scripts/sync_fusionsolar_history.py</string>
    <string>--from-date</string>
    <string>yesterday</string>
    <string>--to-date</string>
    <string>yesterday</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>PROJECT_ROOT/data/logs/sync.log</string>
  <key>StandardErrorPath</key>
  <string>PROJECT_ROOT/data/logs/sync.err.log</string>
</dict>
</plist>
```

Replace both `PROJECT_ROOT` occurrences with the real path, then load the job:

```bash
mkdir -p PROJECT_ROOT/data/logs
launchctl load ~/Library/LaunchAgents/com.darb-solar.sync.plist
```

Useful commands:

```bash
# Run immediately without waiting for the schedule
launchctl start com.darb-solar.sync

# Disable
launchctl unload ~/Library/LaunchAgents/com.darb-solar.sync.plist
```

`launchd` does not rotate log files. Trim or archive `data/logs/sync.log`
periodically, or add a separate `log rotate` entry if the logs grow large.

### Linux / VPS (cron)

Edit the crontab (`crontab -e`) and add:

```cron
0 3 * * * cd PROJECT_ROOT && .venv/bin/python scripts/sync_fusionsolar_history.py --from-date yesterday --to-date yesterday >> data/logs/sync.log 2>&1
```

Create the log directory once:

```bash
mkdir -p PROJECT_ROOT/data/logs
```

Cron also does not rotate logs; use `logrotate` or manual cleanup on the VPS.

### Steady-state vs backfill

The daily job above syncs one complete day (yesterday). For an initial
historical backfill, run the sync manually without date flags (defaults to
`2026-01-01` through yesterday) and allow many hours to complete. After that,
the scheduled job keeps the database current one day at a time.

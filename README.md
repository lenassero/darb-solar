# darb-solar

Python package for syncing FusionSolar plant history into a Postgres database.

## Setup

Create a virtual environment and install dependencies:

```bash
cd darb-solar
uv venv
source .venv/bin/activate
uv sync --extra viz --group dev
```

Core runtime deps install with `uv sync` alone. Add `--extra viz` for the
dashboard stack (streamlit, pandas, plotly, matplotlib) and `--group dev` for
local tooling (jupyter, pre-commit, ipdb).

Add/update dependencies with:

```bash
uv add <package>              # core runtime dep
uv add --optional viz <package>  # dashboard / viz extra
uv add --group dev <package>     # dev tooling
uv add --group cloudrun <package>  # Cloud Run-only dep
```

After changing deployment dependencies, regenerate the exported requirement
files:

```bash
uv lock
./scripts/export_cloudrun_requirements.sh
./scripts/export_streamlit_requirements.sh
```

`requirements.txt` at the repository root is for the Cloud Run deployment.
`app/requirements.txt` is for Streamlit Community Cloud because the app
entrypoint lives in `app/streamlit_app.py`, and Streamlit checks that
directory first when resolving app dependencies. The Streamlit app imports
the local `darb_solar` package from `src/` directly.

## Database (Supabase)

Production data lives in Supabase Postgres. Apply `scripts/setup_schema.sql`
once to a fresh project; there is no automatic schema migration at runtime.

The database layer uses [SQLAlchemy](https://www.sqlalchemy.org/) 2.0 ORM with
the psycopg3 driver. Row types such as `Plant` and `Device` are ORM model
classes exported from `darb_solar.db`; open a session with `get_session()`.

Use the psycopg3 driver in connection URLs (`postgresql+psycopg://...`).

## Configuration

Create a `.env` file in the project root (never commit it):

```bash
FUSIONSOLAR_USERNAME=your@email.com
FUSIONSOLAR_SYSTEM_CODE=your-system-code
DARB_SOLAR_PLANT_CODE=NE=182468888
DARB_SOLAR_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
```v

`DARB_SOLAR_DATABASE_URL` is used by the sync CLI, bootstrap scripts, and the
Cloud Run sync deployment. In Supabase, take it from `Connect to your project`
-> `Direct connection string` -> `Direct connection`.

### Streamlit SQL secret

The Streamlit dashboard uses its own SQL connection secret and does not read
`DARB_SOLAR_DATABASE_URL` by default. That lets the dashboard use the Supabase
IPv4 shared pooler while sync keeps the direct connection.

By default, `app/streamlit_app.py` opens `st.connection("supabase", type="sql")`.
Set the secret in Streamlit Community Cloud under `Secrets`, or locally in
`.streamlit/secrets.toml`:

```toml
[connections.supabase]
url = "postgresql+psycopg://USER:PASSWORD@HOST:6543/postgres?sslmode=require"
```

Point `url` at the Supabase IPv4-compatible session pooler
(`Connect to your project` -> `Direct connection string` -> `Session pooler`).

If you need a different Streamlit connection name, set
`DARB_SOLAR_STREAMLIT_SQL_CONNECTION` in the app environment and create the
matching `[connections.<name>]` secret instead.

## One-time bootstrap

Register the plant and devices from the FusionSolar API:

```bash
uv run python scripts/bootstrap_plant.py
```

## Manual sync (backfill)

Steady-state ingestion is automated on Cloud Run (see below). Use the history
CLI for an initial backfill or ad-hoc date-range refresh (plant timezone,
`Africa/Casablanca` by default):

```bash
# Full backfill from 2026-01-01 through yesterday (default range)
uv run python scripts/sync_fusionsolar_history.py

# Sync the previous complete calendar day
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date yesterday

# Optional: also refresh today for near-real-time dashboard data
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date today
```

`--resume` is on by default: completed device-day windows in `sync_windows`
are skipped. Re-running the same day is safe because upserts are idempotent.
A full backfill can take many hours; expect roughly five minutes of wall-clock
time per device-day because the FusionSolar API enforces spacing between
history calls.

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

## Automation (Cloud Run)

Near-real-time device readings run on Cloud Run, triggered by Cloud Scheduler
every 30 minutes. The HTTP entrypoint is `main.py` at the repository root
(functions-framework handler `sync`). Deploy packages that file with the
source tree via `./scripts/deploy_cloudrun_intraday.sh`.

FusionSolar enforces ~300s between history calls; sleeping inside a single
request would bill several minutes of Cloud Run CPU every tick. The deploy
script attaches **two staggered jobs** that each sync one device instead. The
6-minute gap keeps those waits outside Cloud Run, so each invocation is only a
few seconds of billed compute.

Deploy or refresh with:

```bash
./scripts/deploy_cloudrun_intraday.sh
```

### Scheduler jobs

Both jobs POST to the same Cloud Run service (`darb-solar-intraday`) with
`Content-Type: application/json` and OIDC auth. Timezone is
`Africa/Casablanca`.

| Job | Cron | Body |
|-----|------|------|
| `darb-solar-intraday-inverter` | `0,30 * * * *` | `{"role":"inverter","derive_plant":false}` |
| `darb-solar-intraday-meter` | `6,36 * * * *` | `{"role":"meter","derive_plant":true}` |

Job A writes inverter readings only. Job B writes meter readings, then
re-derives plant metrics over a **1-hour lookback** from rows already in the
DB. That window lets staggered `:00`/`:30` holes self-heal when a reading was
missing at that clock time but landed in a later sync.

The older single job `darb-solar-intraday-sync` is deleted on deploy if it
still exists.

### Request body

`main.py` accepts an optional JSON body:

| Field | Values | Default |
|-------|--------|---------|
| `role` | `inverter` or `meter` | omitted = sync all devices |
| `derive_plant` | `true` or `false` | `false` when `role` is set; `true` when the body is empty / has no `role` |

### Manual intraday (debug)

For a one-off local run (for example after a failed Cloud Run tick), use the
CLI. It calls the same `sync_intraday` logic as `main.py`, syncs all devices
in one process, and loads `.env`:

```bash
uv run python scripts/sync_fusionsolar_intraday.py
```

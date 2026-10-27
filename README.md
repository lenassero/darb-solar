# darb-solar

Sync FusionSolar plant and device readings into Supabase Postgres (Cloud Run sync automation), and explore the data in a Streamlit dashboard.

## Architecture

| Piece | Role |
|-------|------|
| **FusionSolar API** | Source of plant and device history (Huawei Northbound API). |
| **Database** | [Supabase Postgres](#database-supabase) stores plants, devices, readings, and history-sync checkpoints. |
| **Cloud Run sync** | [Scheduled intraday sync](#sync-automation-cloud-run) pulls recent readings into the database. |
| **Dashboard** | [Streamlit app](#dashboard) (`app/streamlit_app.py`) on Community Cloud (or locally) reads the database and charts energy. |

Data flow: FusionSolar API → Cloud Run (and optional manual sync CLIs) → Supabase → Streamlit.

## Setup

Create a virtual environment and install dependencies:

```bash
cd darb-solar
uv venv
source .venv/bin/activate
uv sync --extra viz --group dev
```

Core runtime deps install with `uv sync` alone.
Add `--extra viz` for the dashboard stack (streamlit, pandas, plotly, matplotlib) and `--group dev` for local tooling (jupyter, pre-commit, ipdb).

Add/update dependencies with:

```bash
uv add <package>              # core runtime dep
uv add --optional viz <package>  # dashboard / viz extra
uv add --group dev <package>     # dev tooling
uv add --group cloudrun <package>  # Cloud Run-only dep
```

After changing dependencies, run `uv lock`.

`./scripts/deploy_cloudrun_intraday.sh` regenerates the root `requirements.txt` before each Cloud Run deploy, so you do not need to export it by hand for that path.
For Streamlit Community Cloud, regenerate and commit `app/requirements.txt` when dashboard deps change:

```bash
./scripts/export_streamlit_requirements.sh
```

Streamlit resolves deps next to `app/streamlit_app.py`, which is why that file lives under `app/`.
The Streamlit app imports the local `darb_solar` package from `src/` directly.

## Database (Supabase)

Production data lives in Supabase Postgres.
Apply `scripts/setup_schema.sql` once to a fresh project (there is no migration runner): open the Supabase dashboard → **SQL Editor** → paste the file contents → **Run**.

The database layer uses [SQLAlchemy](https://www.sqlalchemy.org/) 2.0 ORM with the psycopg3 driver.
Row types such as `Plant` and `Device` are ORM model classes exported from `darb_solar.db`; open a session with `get_session()`.

Use the psycopg3 driver in connection URLs (`postgresql+psycopg://...`).

### Checkpoint status vs run outcome

History backfill records progress in `sync_windows`.
Two enums describe overlapping but distinct concepts:

| | `SyncWindowCheckpointStatus` (DB) | `SyncWindowRunOutcome` (per run) |
|---|---|---|
| Stored in | `sync_windows.status` | returned in memory only |
| Values | `pending`, `done`, `failed` | `skipped`, `done`, `failed` |
| Role | resume checkpoints across runs | aggregate counters for this run |

`pending` is written when a fetch starts; `done` or `failed` when it finishes.
`skipped` is reported only for this run when resume finds an existing `done` row and does not call the API again.
Intraday sync does not read or write these checkpoints.
See docstrings in `darb_solar.db.types.SyncWindowCheckpointStatus` and `darb_solar.history_sync.types.SyncWindowRunOutcome`.

## Configuration

Create a `.env` file in the project root (never commit it):

```bash
FUSIONSOLAR_USERNAME=your@email.com
FUSIONSOLAR_SYSTEM_CODE=your-system-code
DARB_SOLAR_PLANT_CODE=NE=182468888
DARB_SOLAR_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
```

These variables are used by [bootstrap](#one-time-bootstrap), the [sync CLI](#manual-sync), and the [Cloud Run sync deployment](#sync-automation-cloud-run) (`FUSIONSOLAR_*` for the API login, `DARB_SOLAR_PLANT_CODE` for which plant to sync, `DARB_SOLAR_DATABASE_URL` for Postgres).
For `DARB_SOLAR_DATABASE_URL` in Supabase, take it from `Connect to your project` -> `Direct connection string` -> `Direct connection`.

### Streamlit SQL secret

The Streamlit dashboard uses its own SQL connection secret and does not read `DARB_SOLAR_DATABASE_URL` by default.
That lets the dashboard use the Supabase IPv4 shared pooler while sync keeps the direct connection.

By default, `app/streamlit_app.py` opens `st.connection("supabase", type="sql")`.
Set the secret in Streamlit Community Cloud under `Secrets` (see [Secrets management for Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)), or locally in `.streamlit/secrets.toml`:

```toml
[connections.supabase]
url = "postgresql+psycopg://USER:PASSWORD@HOST:6543/postgres?sslmode=require"
```

Point `url` at the Supabase IPv4-compatible session pooler (`Connect to your project` -> `Direct connection string` -> `Session pooler`).

If you need a different Streamlit connection name, set `DARB_SOLAR_STREAMLIT_SQL_CONNECTION` in the app environment and create the matching `[connections.<name>]` secret instead.

## Dashboard

### Local

Install the viz extra (`uv sync --extra viz`), configure [Streamlit SQL secret](#streamlit-sql-secret), and set `DARB_SOLAR_PLANT_CODE` in `.env` (cf. [Configuration](#configuration)).
Then from the repository root:

```bash
uv run streamlit run app/streamlit_app.py
```

The app opens at `http://localhost:8501` by default.

### Streamlit Community Cloud

Deploy from this repository with the main file `app/streamlit_app.py` (Streamlit Community Cloud UI; there is no deploy script in this repo).
Configure the app manually once under `Secrets` (see [Secrets management for Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)): paste the [Streamlit SQL secret](#streamlit-sql-secret) as above, and in addition a root-level `DARB_SOLAR_PLANT_CODE` so it is available via `os.environ` (the dashboard does not read it from `st.secrets`):

```toml
DARB_SOLAR_PLANT_CODE = "NE=182468888"
```

Commit an up-to-date `app/requirements.txt` when dashboard dependencies change (`./scripts/export_streamlit_requirements.sh`).

## One-time bootstrap

Run this once after applying the schema (and again only if plant or device metadata changes).
It is not part of Cloud Run automation: production sync expects `plants` and `devices` rows to already exist.

```bash
uv run python scripts/bootstrap_plant.py
```

## Sync automation (Cloud Run)

Near-real-time device readings run on Cloud Run, triggered by Cloud Scheduler every 30 minutes.
The HTTP entrypoint is `main.py` at the repository root (functions-framework handler `sync`).
Deploy packages that file with the source tree via `./scripts/deploy_cloudrun_intraday.sh`.

FusionSolar enforces ~300s between history calls; sleeping inside a single request would bill several minutes of Cloud Run CPU every tick.
The deploy script attaches **two staggered jobs** that each sync one device instead.
The 6-minute gap keeps those waits outside Cloud Run, so each invocation is only a few seconds of billed compute.

Deploy or refresh with:

```bash
./scripts/deploy_cloudrun_intraday.sh
```

### Scheduler jobs

Both jobs POST to the same Cloud Run service (`darb-solar-intraday`) with `Content-Type: application/json` and OIDC auth.
Timezone is `Africa/Casablanca`.

| Job | Cron | Body |
|-----|------|------|
| `darb-solar-intraday-inverter` | `0,30 * * * *` | `{"role":"inverter","derive_plant":false}` |
| `darb-solar-intraday-meter` | `6,36 * * * *` | `{"role":"meter","derive_plant":true}` |

Job A writes inverter readings only.
Job B writes meter readings, then re-derives plant metrics over a **1-hour lookback** from rows already in the DB.
That window lets staggered `:00`/`:30` holes self-heal when a reading was missing at that clock time but landed in a later sync.

The older single job `darb-solar-intraday-sync` is deleted on deploy if it still exists.

### Manual sync

For one-off local runs (initial backfill or debugging a failed Cloud Run tick).
Both CLIs load `.env`.

History backfill or date-range refresh (plant timezone `Africa/Casablanca` by default):

```bash
# Full backfill from 2026-01-01 through yesterday (default range)
uv run python scripts/sync_fusionsolar_history.py

# Sync the previous complete calendar day
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date yesterday

# Optional: also refresh today
uv run python scripts/sync_fusionsolar_history.py \
  --from-date yesterday --to-date today
```

`--resume` is on by default: completed device-day windows in `sync_windows` are skipped.
Re-running the same day is safe because upserts are idempotent.

A full backfill can take many hours; expect roughly five minutes of wall-clock time per device-day because the FusionSolar API enforces spacing between history calls.

Intraday (same `sync_intraday` logic as `main.py`, all devices in one process):

```bash
uv run python scripts/sync_fusionsolar_intraday.py
```

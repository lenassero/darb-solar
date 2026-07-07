#!/usr/bin/env bash
# Deploy the intraday sync to Cloud Run and attach a Cloud Scheduler job.
#
# Prerequisites:
#   - gcloud CLI authenticated with deploy permissions
#   - uv (exports Cloud Run requirements.txt from pyproject.toml)
#   - .env in the project root with FusionSolar creds, plant code, and DB URL
#
# Usage:
#   ./scripts/deploy_cloudrun_intraday.sh
#
# Optional overrides:
#   GCP_PROJECT=darb-solar GCP_REGION=europe-west1 ./scripts/deploy_cloudrun_intraday.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GCP_PROJECT="${GCP_PROJECT:-darb-solar}"
GCP_REGION="${GCP_REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-darb-solar-intraday}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-darb-solar-intraday-sync}"
SCHEDULER_SA_NAME="${SCHEDULER_SA_NAME:-darb-solar-scheduler}"
SCHEDULE_CRON="${SCHEDULE_CRON:-*/30 * * * *}"
# The sync can take several minutes because FusionSolar enforces rate-limit
# spacing between history calls, so give Scheduler a deadline that matches the
# Cloud Run request timeout to avoid premature retries mid-run.
SCHEDULER_ATTEMPT_DEADLINE="${SCHEDULER_ATTEMPT_DEADLINE:-900s}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
MEMORY="${MEMORY:-256Mi}"
CONCURRENCY="${CONCURRENCY:-1}"

ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"

log() { printf '==> %s\n' "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "error: env file not found: ${ENV_FILE}" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a

  : "${FUSIONSOLAR_USERNAME:?FUSIONSOLAR_USERNAME must be set in ${ENV_FILE}}"
  : "${FUSIONSOLAR_SYSTEM_CODE:?FUSIONSOLAR_SYSTEM_CODE must be set in ${ENV_FILE}}"
  : "${DARB_SOLAR_PLANT_CODE:?DARB_SOLAR_PLANT_CODE must be set in ${ENV_FILE}}"
  : "${DARB_SOLAR_DATABASE_URL:?DARB_SOLAR_DATABASE_URL must be set in ${ENV_FILE}}"
}

upsert_secret() {
  local name="$1"
  local value="$2"
  if gcloud secrets describe "${name}" --project="${GCP_PROJECT}" >/dev/null 2>&1; then
    local current
    current="$(gcloud secrets versions access latest --secret="${name}" \
      --project="${GCP_PROJECT}" 2>/dev/null || true)"
    if [[ "${current}" == "${value}" ]]; then
      log "Secret ${name} unchanged, skipping new version"
      return
    fi
    log "Updating secret ${name}"
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --project="${GCP_PROJECT}" \
      --data-file=-
  else
    log "Creating secret ${name}"
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --project="${GCP_PROJECT}" \
      --replication-policy=automatic \
      --data-file=-
  fi
}

grant_secret_accessor() {
  local secret_name="$1"
  local member="$2"
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --project="${GCP_PROJECT}" \
    --member="${member}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
}

enable_apis() {
  log "Enabling required APIs"
  gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    cloudscheduler.googleapis.com \
    --project="${GCP_PROJECT}" \
    --quiet
}

ensure_scheduler_service_account() {
  SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${GCP_PROJECT}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${SCHEDULER_SA_EMAIL}" \
    --project="${GCP_PROJECT}" >/dev/null 2>&1; then
    log "Creating scheduler service account ${SCHEDULER_SA_EMAIL}"
    gcloud iam service-accounts create "${SCHEDULER_SA_NAME}" \
      --project="${GCP_PROJECT}" \
      --display-name="Darb Solar Cloud Scheduler"
  else
    log "Scheduler service account already exists: ${SCHEDULER_SA_EMAIL}"
  fi
}

sync_secrets() {
  log "Syncing secrets from ${ENV_FILE}"
  upsert_secret "fusionsolar-username" "${FUSIONSOLAR_USERNAME}"
  upsert_secret "fusionsolar-system-code" "${FUSIONSOLAR_SYSTEM_CODE}"
  upsert_secret "darb-solar-database-url" "${DARB_SOLAR_DATABASE_URL}"

  local project_number compute_sa
  project_number="$(gcloud projects describe "${GCP_PROJECT}" --format='value(projectNumber)')"
  compute_sa="serviceAccount:${project_number}-compute@developer.gserviceaccount.com"

  for secret in fusionsolar-username fusionsolar-system-code darb-solar-database-url; do
    grant_secret_accessor "${secret}" "${compute_sa}"
  done
}

deploy_service() {
  log "Exporting Cloud Run requirements.txt"
  "${SCRIPT_DIR}/export_cloudrun_requirements.sh"

  log "Deploying Cloud Run service ${SERVICE_NAME}"
  gcloud run deploy "${SERVICE_NAME}" \
    --project="${GCP_PROJECT}" \
    --region="${GCP_REGION}" \
    --source="${PROJECT_ROOT}" \
    --function=sync \
    --base-image=python313 \
    --no-allow-unauthenticated \
    --concurrency="${CONCURRENCY}" \
    --timeout="${TIMEOUT_SECONDS}" \
    --memory="${MEMORY}" \
    --set-env-vars="DARB_SOLAR_PLANT_CODE=${DARB_SOLAR_PLANT_CODE}" \
    --set-secrets="DARB_SOLAR_DATABASE_URL=darb-solar-database-url:latest,FUSIONSOLAR_USERNAME=fusionsolar-username:latest,FUSIONSOLAR_SYSTEM_CODE=fusionsolar-system-code:latest" \
    --quiet
}

grant_invoker() {
  log "Granting run.invoker to ${SCHEDULER_SA_EMAIL}"
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project="${GCP_PROJECT}" \
    --region="${GCP_REGION}" \
    --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
}

ensure_scheduler_job() {
  local service_url
  service_url="$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${GCP_PROJECT}" \
    --region="${GCP_REGION}" \
    --format='value(status.url)')"

  log "Ensuring Cloud Scheduler job ${SCHEDULER_JOB_NAME} -> ${service_url}"

  if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --project="${GCP_PROJECT}" \
    --location="${GCP_REGION}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
      --project="${GCP_PROJECT}" \
      --location="${GCP_REGION}" \
      --schedule="${SCHEDULE_CRON}" \
      --uri="${service_url}" \
      --http-method=POST \
      --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${service_url}" \
      --attempt-deadline="${SCHEDULER_ATTEMPT_DEADLINE}" \
      --time-zone="Africa/Casablanca" \
      --quiet
  else
    gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
      --project="${GCP_PROJECT}" \
      --location="${GCP_REGION}" \
      --schedule="${SCHEDULE_CRON}" \
      --uri="${service_url}" \
      --http-method=POST \
      --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
      --oidc-token-audience="${service_url}" \
      --attempt-deadline="${SCHEDULER_ATTEMPT_DEADLINE}" \
      --time-zone="Africa/Casablanca" \
      --quiet
  fi
}

main() {
  require_cmd gcloud
  require_cmd uv
  load_env
  enable_apis
  ensure_scheduler_service_account
  sync_secrets
  deploy_service
  grant_invoker
  ensure_scheduler_job

  local service_url
  service_url="$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${GCP_PROJECT}" \
    --region="${GCP_REGION}" \
    --format='value(status.url)')"

  log "Deployment complete"
  echo "Service URL: ${service_url}"
  echo "Scheduler: ${SCHEDULER_JOB_NAME} (${SCHEDULE_CRON}, Africa/Casablanca)"
  echo ""
  echo "Manual test:"
  echo "  curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${service_url}"
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${project_dir}"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and fill in the values first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

required=(GCP_PROJECT_ID GCP_REGION CLOUD_RUN_SERVICE OPENAI_API_KEY OPENAI_BASE_URL LLM_MODEL TAVILY_API_KEY)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]] || [[ "${!name}" == *"your-"* ]]; then
    echo "Missing or placeholder value for ${name} in .env" >&2
    exit 1
  fi
done

image="gcr.io/${GCP_PROJECT_ID}/${CLOUD_RUN_SERVICE}"

gcloud config set project "${GCP_PROJECT_ID}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
gcloud builds submit --tag "${image}"
gcloud run deploy "${CLOUD_RUN_SERVICE}" \
  --image "${image}" \
  --platform managed \
  --region "${GCP_REGION}" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 8 \
  --timeout 120 \
  --min-instances 0 \
  --max-instances 1 \
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY},OPENAI_BASE_URL=${OPENAI_BASE_URL},LLM_MODEL=${LLM_MODEL},TAVILY_API_KEY=${TAVILY_API_KEY},MCP_FILES_ROOT=/app/workspace,AGENT_TIMEOUT_SECONDS=90"

service_url="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
  --platform managed \
  --region "${GCP_REGION}" \
  --format='value(status.url)')"

echo "Deployment complete: ${service_url}"
echo "Run: .venv/bin/python scripts/smoke_test.py ${service_url}"

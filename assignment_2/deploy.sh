#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${project_dir}"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and fill in the values first." >&2
  exit 1
fi
if [[ ! -d chroma_index ]]; then
  echo "Missing chroma_index/. Run: python -m scripts.ingest --from-jsonl" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

required=(GCP_PROJECT_ID GCP_REGION CLOUD_RUN_SERVICE OPENAI_API_KEY OPENAI_MODEL GOOGLE_API_KEY GEMINI_MODEL
          DEEPSEEK_API_KEY DEEPSEEK_MODEL DEEPSEEK_BASE_URL KIMI_API_KEY TAVILY_API_KEY)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]] || [[ "${!name}" == *"your-"* ]]; then
    echo "Missing or placeholder value for ${name} in .env" >&2
    exit 1
  fi
done

image="gcr.io/${GCP_PROJECT_ID}/${CLOUD_RUN_SERVICE}"

gcloud config set project "${GCP_PROJECT_ID}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud builds submit --tag "${image}"
gcloud run deploy "${CLOUD_RUN_SERVICE}" \
  --image "${image}" \
  --platform managed \
  --region "${GCP_REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --concurrency 10 \
  --timeout 300 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY},OPENAI_MODEL=${OPENAI_MODEL},OPENAI_EMBEDDING_MODEL=${OPENAI_EMBEDDING_MODEL:-text-embedding-3-small},GOOGLE_API_KEY=${GOOGLE_API_KEY},GEMINI_MODEL=${GEMINI_MODEL},DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY},DEEPSEEK_MODEL=${DEEPSEEK_MODEL},DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL},KIMI_API_KEY=${KIMI_API_KEY},KIMI_MODEL=${KIMI_MODEL:-kimi-k3},KIMI_BASE_URL=${KIMI_BASE_URL:-https://api.moonshot.cn/v1},TAVILY_API_KEY=${TAVILY_API_KEY},WEB_ENABLED=true"

service_url="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" \
  --platform managed --region "${GCP_REGION}" --format='value(status.url)')"

echo "Deployment complete: ${service_url}"
echo "Run: .venv/bin/python -m scripts.smoke_test ${service_url}"

#!/usr/bin/env bash
set -euo pipefail

output="${1:-csci599-assignment-1.zip}"
if [[ "${output}" != *.zip ]]; then
  echo "Output filename must end in .zip" >&2
  exit 1
fi

tracked_and_source=(
  .dockerignore .env.example .gitignore Dockerfile LICENSE PROCESS_LOG.md README.md
  app deploy.sh main.py mcp_servers package-lock.json package.json pytest.ini
  requirements-dev.txt requirements.txt scripts tests workspace/.gitkeep
)

zip -r "${output}" "${tracked_and_source[@]}" \
  -x '*/__pycache__/*' '*.pyc' '.env' 'node_modules/*' '.venv/*'
echo "Created ${output}"

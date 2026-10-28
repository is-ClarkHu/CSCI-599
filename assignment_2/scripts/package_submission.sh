#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"
out="${project_dir}/../csci599-assignment-2.zip"
rm -f "${out}"

zip -r "${out}" . \
  -x ".env" ".env.*" ".venv/*" "*/__pycache__/*" "*.pyc" ".pytest_cache/*" \
     "corpus/raw/*" "data/raw_tables/*" "data/medals.sqlite" \
     "description/*" "*.DS_Store" "*.zip"
zip "${out}" .env.example

echo "Created ${out}"
unzip -l "${out}" | grep -E "\.env$" && { echo "ERROR: .env leaked into zip" >&2; exit 1; } || true

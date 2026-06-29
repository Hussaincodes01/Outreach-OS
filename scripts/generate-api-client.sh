#!/usr/bin/env bash
# Generate TypeScript types for the web client from the FastAPI OpenAPI schema.
# Requires: the API running on $API_URL (default http://localhost:8000) and
# `npx openapi-typescript` installed.
#
# Usage:
#   API_URL=http://localhost:8000 bash scripts/generate-api-client.sh
#
# Output: apps/web/src/openapi.d.ts (overwritten)

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
OUT_DIR="apps/web/src"
OUT_FILE="${OUT_DIR}/openapi.d.ts"

mkdir -p "${OUT_DIR}"

echo "Fetching OpenAPI schema from ${API_URL}/openapi.json ..."
curl -fsS "${API_URL}/openapi.json" -o "${OUT_DIR}/openapi.json"

echo "Generating types with openapi-typescript ..."
npx --yes openapi-typescript "${OUT_DIR}/openapi.json" --output "${OUT_FILE}"

echo "Done. Wrote ${OUT_FILE}"

#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
E2E_STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/yobi-e2e.XXXXXX")"
E2E_DB="$E2E_STATE_DIR/yobi_e2e.db"
BACKEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  rm -rf "$E2E_STATE_DIR"
}

trap cleanup EXIT INT TERM

"$PROJECT_ROOT/backend/.venv/bin/python" "$SCRIPT_DIR/prepare_local_e2e_db.py" \
  --source "$PROJECT_ROOT/backend/data/yobi_demo.db" \
  --destination "$E2E_DB"

APP_ENV=test \
DEMO_DB_BACKEND=sqlite \
SQLITE_PATH="$E2E_DB" \
ADDRESS_OCR_PROVIDER=fixture \
OCI_GENAI_API_KEY= \
OCI_COMPARTMENT_ID= \
"$PROJECT_ROOT/backend/.venv/bin/uvicorn" app.main:app \
  --app-dir "$PROJECT_ROOT/backend" --host 127.0.0.1 --port 18000 &
BACKEND_PID=$!
wait "$BACKEND_PID"

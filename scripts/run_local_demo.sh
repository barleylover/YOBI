#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_STATE_DIR="$PROJECT_ROOT/.local-demo"
BACKEND_LOG="$LOCAL_STATE_DIR/backend.log"
FRONTEND_LOG="$LOCAL_STATE_DIR/frontend.log"
BACKEND_PID_FILE="$LOCAL_STATE_DIR/backend.pid"
FRONTEND_PID_FILE="$LOCAL_STATE_DIR/frontend.pid"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  [[ -n "$FRONTEND_PID" ]] && wait "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && wait "$BACKEND_PID" 2>/dev/null || true
  rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
}

fail() {
  printf 'Local demo could not start: %s\n' "$1" >&2
  exit 1
}

choose_port() {
  local preferred="$1"
  local maximum="$2"
  local candidate="$preferred"
  while [[ "$candidate" -le "$maximum" ]]; do
    if ! lsof -nP -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
    candidate=$((candidate + 1))
  done
  fail "no free local port was found between $preferred and $maximum."
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local pid="$3"
  local attempt=0
  while ! curl -fsS --max-time 1 -o /dev/null "$url"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '%s exited before it became ready. Recent log output:\n' "$label" >&2
      if [[ "$label" == "Backend" ]]; then
        tail -n 30 "$BACKEND_LOG" >&2 || true
      else
        tail -n 30 "$FRONTEND_LOG" >&2 || true
      fi
      exit 1
    fi
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge 60 ]]; then
      fail "$label did not become ready within 30 seconds. Check $LOCAL_STATE_DIR."
    fi
    sleep 0.5
  done
}

trap cleanup EXIT INT TERM

[[ -x "$PROJECT_ROOT/.venv/bin/uvicorn" ]] || fail "Python dependencies are missing. Run 'make setup' first."
[[ -f "$PROJECT_ROOT/frontend/node_modules/vite/bin/vite.js" ]] || fail "Frontend dependencies are missing. Run 'make setup' first."

NODE_BIN="$(command -v node || true)"
if [[ -n "$NODE_BIN" ]]; then
  NODE_MAJOR="$("$NODE_BIN" -p "process.versions.node.split('.')[0]" 2>/dev/null || printf '0')"
else
  NODE_MAJOR=0
fi
if [[ "$NODE_MAJOR" -lt 20 ]]; then
  PNPM_BIN="$(command -v pnpm || true)"
  PNPM_NODE_CANDIDATE="$(dirname "$PNPM_BIN")/../../node/bin/node"
  if [[ -n "$PNPM_BIN" ]] && [[ -x "$PNPM_NODE_CANDIDATE" ]]; then
    NODE_BIN="$PNPM_NODE_CANDIDATE"
  else
    fail "Node.js 20 or newer is required."
  fi
fi

BACKEND_PORT="$(choose_port 8000 8010)"
FRONTEND_PORT="$(choose_port 5173 5183)"
if [[ "$BACKEND_PORT" != "8000" ]]; then
  printf 'Port 8000 is already in use; using backend port %s without stopping the existing process.\n' "$BACKEND_PORT"
fi
if [[ "$FRONTEND_PORT" != "5173" ]]; then
  printf 'Port 5173 is already in use; using frontend port %s without stopping the existing process.\n' "$FRONTEND_PORT"
fi
mkdir -p "$LOCAL_STATE_DIR"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

cd "$PROJECT_ROOT"
APP_ENV=development \
APP_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
DEMO_DB_BACKEND=sqlite \
SQLITE_PATH="$PROJECT_ROOT/backend/data/yobi_demo.db" \
DEMO_FALLBACK_ENABLED=true \
ADDRESS_OCR_PROVIDER=fixture \
OCI_GENAI_API_KEY= \
OCI_COMPARTMENT_ID= \
"$PROJECT_ROOT/.venv/bin/uvicorn" app.main:app --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT" \
  > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" > "$BACKEND_PID_FILE"

cd "$PROJECT_ROOT/frontend"
YOBI_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" \
"$NODE_BIN" node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort \
  > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
printf '%s\n' "$FRONTEND_PID" > "$FRONTEND_PID_FILE"

wait_for_url "http://127.0.0.1:$BACKEND_PORT/readyz" Backend "$BACKEND_PID"
wait_for_url "http://127.0.0.1:$FRONTEND_PORT" Frontend "$FRONTEND_PID"

printf '\nYOBI local demo is ready.\n'
printf '  Web:             http://127.0.0.1:%s\n' "$FRONTEND_PORT"
printf '  Backend health:  http://127.0.0.1:%s/healthz\n' "$BACKEND_PORT"
printf '  Backend ready:   http://127.0.0.1:%s/readyz\n' "$BACKEND_PORT"
printf '  Logs:            %s\n' "$LOCAL_STATE_DIR"
printf '\nThis local run uses SQLite, fixture address extraction, and deterministic agent continuity.\n'
printf 'It does not call Oracle, OCI GenAI, a real restaurant, courier, or payment service.\n'
printf 'Press Ctrl-C to stop both servers.\n\n'

if [[ "${YOBI_NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1 || true
fi

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

printf 'One of the local demo processes stopped unexpectedly.\n' >&2
printf 'Backend log: %s\nFrontend log: %s\n' "$BACKEND_LOG" "$FRONTEND_LOG" >&2
exit 1

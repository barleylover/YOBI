#!/usr/bin/env bash
set -euo pipefail

# Read only the bounded provider-attempt rows and terminal LLM events associated
# with one public QA session. Run this through a guarded SSH transport wrapper.

readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly KNOWN_HOSTS="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"

[[ $# == 2 ]] || { printf 'Usage: %s SESSION_ID REQUEST_ID\n' "$0" >&2; exit 2; }
readonly SESSION_ID="$1"
readonly REQUEST_ID="$2"

[[ "$SESSION_ID" =~ ^session_[a-f0-9]{32}$ ]] \
  || { printf 'Session ID is invalid.\n' >&2; exit 2; }
[[ "$REQUEST_ID" =~ ^recommendation-[A-Za-z0-9-]{8,120}$ ]] \
  || { printf 'Request ID is invalid.\n' >&2; exit 2; }
[[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
  && -n "$HOST" && "$PORT" == "443" \
  && -f "$KNOWN_HOSTS" && -S "$CONTROL_PATH" ]] \
  || { printf 'A guarded SSH transport is required.\n' >&2; exit 1; }

ssh_options=(
  -T -q -p "$PORT" -i "$SSH_KEY"
  -o BatchMode=yes -o ControlMaster=no -o ControlPersist=no
  -o "UserKnownHostsFile=${KNOWN_HOSTS}"
  -o "ControlPath=${CONTROL_PATH}"
  -o StrictHostKeyChecking=yes
)

ssh "${ssh_options[@]}" "$SSH_USER@$HOST" \
  "sudo -n bash -s -- '$SESSION_ID' '$REQUEST_ID'" <<'REMOTE'
set -euo pipefail
session_id="$1"
request_id="$2"
release_path="$(readlink -f /opt/yobi/current)"
case "$release_path" in
  /opt/yobi/releases/*) ;;
  *) printf 'Active release path is invalid.\n' >&2; exit 1 ;;
esac

sudo -n env PYTHONPATH="$release_path/backend:$release_path" \
  "$release_path/venv/bin/python" \
  "$release_path/deploy/run_with_runtime_env.py" /etc/yobi/yobi.env \
  "$release_path/venv/bin/python" - "$session_id" "$request_id" <<'PY'
from __future__ import annotations

import json
import sys

from app.dependencies import get_repository

session_id, request_id = sys.argv[1:3]
repository = get_repository()
with repository.pool.connection() as connection:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT attempt_no, attempt_role, provider, model_id, status, error_code,
               latency_ms, input_tokens, output_tokens, created_at, completed_at
        FROM recommendation_provider_attempt
        WHERE session_id=:session_id AND request_id=:request_id
        ORDER BY attempt_no
        """,
        session_id=session_id,
        request_id=request_id,
    )
    columns = [str(value[0]).lower() for value in cursor.description]
    attempts = [dict(zip(columns, row)) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT status, failure_code, dispatch_count, created_at, completed_at
        FROM structured_recommendation_request
        WHERE session_id=:session_id AND request_id=:request_id
        """,
        session_id=session_id,
        request_id=request_id,
    )
    request_row = cursor.fetchone()
    request_columns = [str(value[0]).lower() for value in cursor.description]
    request = dict(zip(request_columns, request_row)) if request_row else None

    cursor.execute(
        """
        SELECT status, error_code, attempt_count, updated_at
        FROM menu_presentation_generation_lease
        WHERE status='FAILED'
          AND updated_at >= SYSTIMESTAMP - INTERVAL '30' MINUTE
        ORDER BY updated_at DESC
        FETCH FIRST 12 ROWS ONLY
        """
    )
    lease_columns = [str(value[0]).lower() for value in cursor.description]
    recent_failed_presentation_leases = [
        dict(zip(lease_columns, row)) for row in cursor.fetchall()
    ]

def safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)

print(
    json.dumps(
        {
            "request": request,
            "attempts": attempts,
            "recent_failed_presentation_leases": recent_failed_presentation_leases,
        },
        default=safe,
    )
)
PY

sudo -n journalctl -u yobi-api \
  --since '30 minutes ago' --no-pager -o cat \
  | grep -E 'option_localization_terminal|structured_recommendation_terminal' \
  | tail -n 40 || true
REMOTE

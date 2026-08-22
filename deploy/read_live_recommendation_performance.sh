#!/usr/bin/env bash
set -euo pipefail

# Read bounded recommendation/provider timing evidence for one to five public
# QA sessions. Run this through the guarded SSH transport wrapper.

readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly KNOWN_HOSTS="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"

[[ $# -ge 1 && $# -le 5 ]] \
  || { printf 'Usage: %s SESSION_ID [SESSION_ID ...]\n' "$0" >&2; exit 2; }
for session_id in "$@"; do
  [[ "$session_id" =~ ^session_[a-f0-9]{32}$ ]] \
    || { printf 'Session ID is invalid.\n' >&2; exit 2; }
done
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
  "sudo -n bash -s -- $*" <<'REMOTE'
set -euo pipefail
release_path="$(readlink -f /opt/yobi/current)"
case "$release_path" in
  /opt/yobi/releases/*) ;;
  *) printf 'Active release path is invalid.\n' >&2; exit 1 ;;
esac

sudo -n env PYTHONPATH="$release_path/backend:$release_path" \
  "$release_path/venv/bin/python" \
  "$release_path/deploy/run_with_runtime_env.py" /etc/yobi/yobi.env \
  "$release_path/venv/bin/python" - "$@" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from typing import Any

from app.dependencies import get_repository


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    reader = getattr(value, "read", None)
    if callable(reader):
        value = reader()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(str(value))


def milliseconds(start: Any, end: Any) -> int | None:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


session_ids = sys.argv[1:]
repository = get_repository()
output: list[dict[str, Any]] = []
with repository.pool.connection() as connection:
    cursor = connection.cursor()
    for session_id in session_ids:
        cursor.execute(
            """
            SELECT request_id,status,dispatch_count,failure_code,
                   created_at,dispatched_at,completed_at,result_json,evidence_pool_json
            FROM structured_recommendation_request
            WHERE session_id=:session_id
            ORDER BY created_at DESC
            FETCH FIRST 3 ROWS ONLY
            """,
            session_id=session_id,
        )
        request_columns = [str(value[0]).lower() for value in cursor.description]
        requests: list[dict[str, Any]] = []
        for raw_row in cursor.fetchall():
            row = dict(zip(request_columns, raw_row))
            result = json_value(row.pop("result_json")) or {}
            evidence_pool = json_value(row.pop("evidence_pool_json")) or []
            server_rank_by_menu = {
                str((item.get("menu") or {}).get("menu_id") or item.get("menu_id") or ""):
                item.get("server_rank")
                for item in evidence_pool
                if isinstance(item, dict)
            }
            recommendations = result.get("recommendations", [])
            row["total_ms"] = milliseconds(row.get("created_at"), row.get("completed_at"))
            row["dispatch_to_complete_ms"] = milliseconds(
                row.get("dispatched_at"), row.get("completed_at")
            )
            row["recommendations"] = [
                {
                    "menu_id": item.get("menu_id"),
                    "merchant_id": (item.get("menu") or {}).get("merchant_id"),
                    "rank": item.get("rank"),
                    "server_rank": server_rank_by_menu.get(str(item.get("menu_id") or "")),
                    "generation_model": item.get("generation_model"),
                }
                for item in recommendations
                if isinstance(item, dict)
            ]
            cursor.execute(
                """
                SELECT attempt_no,attempt_role,provider,model_id,status,error_code,
                       latency_ms,input_tokens,output_tokens,created_at,completed_at
                FROM recommendation_provider_attempt
                WHERE session_id=:session_id AND request_id=:request_id
                ORDER BY attempt_no
                """,
                session_id=session_id,
                request_id=row["request_id"],
            )
            attempt_columns = [str(value[0]).lower() for value in cursor.description]
            row["attempts"] = [
                dict(zip(attempt_columns, attempt)) for attempt in cursor.fetchall()
            ]
            requests.append(row)
        output.append(
            {
                "session_id": session_id,
                "session_id_hash": hashlib.sha256(session_id.encode()).hexdigest(),
                "requests": requests,
            }
        )

print(json.dumps(output, default=safe, ensure_ascii=False))
PY

for session_id in "$@"; do
  session_hash="$(printf '%s' "$session_id" | sha256sum | cut -d' ' -f1)"
  sudo -n journalctl -u yobi-api --since '3 hours ago' --no-pager -o cat \
    | grep 'structured_recommendation_terminal' \
    | grep "$session_hash" \
    | tail -n 3 || true
done
REMOTE

#!/usr/bin/env bash
set -euo pipefail

readonly RELEASE_ID="${1:-}"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly KNOWN_HOSTS="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RUN_ID="postdeploy-${RELEASE_ID}"
readonly REMOTE_OUTPUT_DIR="/opt/yobi/shared/evidence/recommendation-v2"
readonly REMOTE_ARTIFACT="${REMOTE_OUTPUT_DIR}/postdeploy-${RUN_ID}.json"
readonly LOCAL_ARTIFACT="${TMPDIR:-/tmp}/yobi-${RUN_ID}.json"
readonly LOCAL_SIDECAR="${LOCAL_ARTIFACT}.sha256"

[[ "$RELEASE_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]] \
  || { printf 'Release ID is invalid.\n' >&2; exit 1; }
[[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_NLB_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_LB_WINDOW:-}" == "1" \
  && "$PORT" == "443" && -n "$HOST" \
  && -f "$KNOWN_HOSTS" && ! -L "$KNOWN_HOSTS" \
  && -S "$CONTROL_PATH" && ! -L "$CONTROL_PATH" ]] \
  || { printf 'Postdeploy gate requires the guarded LB SSH transport.\n' >&2; exit 1; }
[[ ! -e "$LOCAL_ARTIFACT" && ! -e "$LOCAL_SIDECAR" ]] \
  || { printf 'Local postdeploy evidence target already exists.\n' >&2; exit 1; }

ssh_options=(
  -T -q -p "$PORT" -i "$SSH_KEY"
  -o LogLevel=ERROR -o ConnectTimeout=20
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6
  -o "UserKnownHostsFile=${KNOWN_HOSTS}" -o StrictHostKeyChecking=yes
  -o ControlMaster=no -o "ControlPath=${CONTROL_PATH}" -o ControlPersist=no
)

release_path="/opt/yobi/releases/${RELEASE_ID}"
set +e
ssh "${ssh_options[@]}" "$SSH_USER@$HOST" \
  "sudo -n env PYTHONPATH='${release_path}/backend:${release_path}' \
    '${release_path}/venv/bin/python' \
    '${release_path}/deploy/run_with_runtime_env.py' /etc/yobi/yobi.env \
    '${release_path}/venv/bin/python' \
    '${release_path}/scripts/recommendation_v2_live_harness.py' postdeploy \
    --run-id '${RUN_ID}' --output-dir '${REMOTE_OUTPUT_DIR}' \
    --base-url http://127.0.0.1"
harness_status=$?
set -e

ssh "${ssh_options[@]}" "$SSH_USER@$HOST" \
  "sudo -n cat '${REMOTE_ARTIFACT}'" >"$LOCAL_ARTIFACT"
ssh "${ssh_options[@]}" "$SSH_USER@$HOST" \
  "sudo -n cat '${REMOTE_ARTIFACT}.sha256'" >"$LOCAL_SIDECAR"
expected_sidecar="$(shasum -a 256 "$LOCAL_ARTIFACT" | awk -v name="$(basename "$REMOTE_ARTIFACT")" '{print $1 "  " name}')"
[[ "$(cat "$LOCAL_SIDECAR")" == "$expected_sidecar" ]] \
  || { printf 'Postdeploy evidence checksum does not match the remote sidecar.\n' >&2; exit 1; }

if [[ "$harness_status" -ne 0 ]]; then
  printf 'Postdeploy five-call gate failed; active release remains PROVISIONAL. evidence=%s\n' \
    "$LOCAL_ARTIFACT" >&2
  exit "$harness_status"
fi

"$ROOT_DIR/deploy/finalize_recommendation_v2_release.sh" \
  "$RELEASE_ID" "$LOCAL_ARTIFACT"
printf 'Postdeploy five-call gate passed and zero-call finalization completed. evidence=%s\n' \
  "$LOCAL_ARTIFACT"

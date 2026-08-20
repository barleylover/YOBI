#!/usr/bin/env bash
set -euo pipefail

readonly RELEASES_ROOT="/opt/yobi/releases"
readonly CURRENT_LINK="/opt/yobi/current"
readonly SHARED_ROOT="/opt/yobi/shared"
readonly CONTROL_ROOT="$SHARED_ROOT/control"
readonly READY_MARKER=".yobi-release-ready"
readonly PREVIOUS_RECORD="$CONTROL_ROOT/previous_release"
readonly LEGACY_PREVIOUS_RECORD="$SHARED_ROOT/previous_release"
readonly DEPLOY_LOCK="/run/lock/yobi-deploy.lock"

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run on the VM with sudo.\n' >&2
  exit 1
fi
if (( $# > 1 )); then
  printf 'Usage: %s [verified-release-id]\n' "$0" >&2
  exit 1
fi

command -v flock >/dev/null \
  || { printf 'flock is required for rollback.\n' >&2; exit 1; }
[[ ! -L "$DEPLOY_LOCK" ]] \
  || { printf 'Deployment lock path must not be a symlink.\n' >&2; exit 1; }
if [[ ! -e "$DEPLOY_LOCK" ]]; then
  (umask 077; set -o noclobber; : > "$DEPLOY_LOCK") 2>/dev/null || true
fi
[[ -f "$DEPLOY_LOCK" && ! -L "$DEPLOY_LOCK" ]] \
  || { printf 'Deployment lock is not a regular file.\n' >&2; exit 1; }
chown root:root "$DEPLOY_LOCK"
chmod 0600 "$DEPLOY_LOCK"
exec {deployment_lock_fd}<>"$DEPLOY_LOCK"
flock -n "$deployment_lock_fd" \
  || { printf 'Another YOBI deploy or rollback is already running.\n' >&2; exit 75; }

[[ ! -L /opt/yobi && -d /opt/yobi ]] \
  || { printf 'YOBI root must be a real directory.\n' >&2; exit 1; }
[[ ! -L "$RELEASES_ROOT" && -d "$RELEASES_ROOT" ]] \
  || { printf 'Release root must be a real directory.\n' >&2; exit 1; }
id yobi >/dev/null 2>&1 \
  || { printf 'The yobi service account is missing.\n' >&2; exit 1; }
chown root:root /opt/yobi
chmod 0755 /opt/yobi
chown root:yobi "$RELEASES_ROOT"
chmod 0755 "$RELEASES_ROOT"

validate_release_path() {
  local release_path="$1"
  local release_name="${release_path##*/}"
  [[ "$release_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ \
    && "$release_path" == "$RELEASES_ROOT/$release_name" \
    && ! -L "$release_path" && -d "$release_path" ]]
}

harden_release_tree() {
  local release_path="$1"
  local writable_path
  validate_release_path "$release_path" || return 1
  chown -R --no-dereference root:yobi "$release_path" || return 1
  find -P "$release_path" -xdev -type d -exec chmod go-w {} + || return 1
  find -P "$release_path" -xdev -type f -exec chmod go-w {} + || return 1
  [[ "$(stat -c '%U:%G' "$release_path")" == "root:yobi" ]] || return 1
  writable_path="$(find -P "$release_path" -xdev \
    \( -type d -o -type f \) -perm /022 -print -quit)"
  [[ -z "$writable_path" ]]
}

current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
validate_release_path "$current" \
  || { printf 'Current release link is missing or untrusted.\n' >&2; exit 1; }
harden_release_tree "$current" \
  || { printf 'Current release permissions could not be hardened.\n' >&2; exit 1; }
state_manager="$current/deploy/release_state.py"
knowledge_manager="$current/scripts/manage_knowledge_release.py"
recommendation_manager="$current/scripts/manage_recommendation_release.py"
runtime_env_runner=(
  "$current/venv/bin/python"
  "$current/deploy/run_with_runtime_env.py"
  /etc/yobi/yobi.env
)
[[ -x "$current/venv/bin/python" && -f "$state_manager" \
  && -f "$knowledge_manager" && -f "$recommendation_manager" \
  && -f "$current/deploy/run_with_runtime_env.py" ]] \
  || { printf 'Current release lacks trusted rollback helpers.\n' >&2; exit 1; }

run_knowledge_manager() {
  env PYTHONPATH="$current" "${runtime_env_runner[@]}" \
    "$current/venv/bin/python" "$knowledge_manager" "$@"
}

run_recommendation_manager() {
  env PYTHONPATH="$current" "${runtime_env_runner[@]}" \
    "$current/venv/bin/python" "$recommendation_manager" "$@"
}

original_knowledge_release_id=""
knowledge_restore_required=false
original_recommendation_release_family_id=""
recommendation_restore_required=false
rollback_activation_started=false

restore_original_knowledge() {
  local active_now
  [[ "$knowledge_restore_required" == true ]] || return 0
  active_now="$(run_knowledge_manager get-active)" || return 1
  if [[ -n "$original_knowledge_release_id" ]]; then
    if [[ "$active_now" == "$original_knowledge_release_id" ]]; then
      knowledge_restore_required=false
      return 0
    fi
    if [[ -n "$active_now" ]]; then
      run_knowledge_manager activate-ready "$original_knowledge_release_id" \
        --expected-current "$active_now" >/dev/null || return 1
    else
      run_knowledge_manager activate-ready "$original_knowledge_release_id" \
        --expect-no-active >/dev/null || return 1
    fi
  elif [[ -n "$active_now" ]]; then
    run_knowledge_manager clear-active --expected-current "$active_now" \
      >/dev/null || return 1
  fi
  knowledge_restore_required=false
}

restore_original_recommendation() {
  local active_now
  [[ "$recommendation_restore_required" == true ]] || return 0
  active_now="$(run_recommendation_manager get-active)" || return 1
  if [[ -n "$original_recommendation_release_family_id" ]]; then
    if [[ "$active_now" == "$original_recommendation_release_family_id" ]]; then
      recommendation_restore_required=false
      return 0
    fi
    if [[ -n "$active_now" ]]; then
      run_recommendation_manager activate-ready \
        "$original_recommendation_release_family_id" \
        --expected-current "$active_now" >/dev/null || return 1
    else
      run_recommendation_manager activate-ready \
        "$original_recommendation_release_family_id" \
        --expect-no-active >/dev/null || return 1
    fi
  elif [[ -n "$active_now" ]]; then
    run_recommendation_manager clear-active --expected-current "$active_now" \
      >/dev/null || return 1
  fi
  recommendation_restore_required=false
}

check_local_services() {
  curl --fail --silent --retry 8 --retry-delay 2 --retry-connrefused \
    --max-time 10 http://127.0.0.1/healthz >/dev/null \
    && curl --fail --silent --retry 8 --retry-delay 2 --retry-connrefused \
      --max-time 30 http://127.0.0.1/readyz >/dev/null
}

restore_original_release() {
  local restored
  restore_original_knowledge || return 1
  restore_original_recommendation || return 1
  ln -sfn "$current" "$CURRENT_LINK" || return 1
  systemctl daemon-reload || return 1
  systemctl restart yobi-api nginx || return 1
  check_local_services || return 1
  restored="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
  [[ "$restored" == "$current" ]] || return 1
  rollback_activation_started=false
  printf 'Restored release_id=%s and reverified health/ready.\n' "${current##*/}"
}

rollback_complete=false
restore_on_failure() {
  local status="$?"
  trap - EXIT
  if [[ "$rollback_complete" != true && "$rollback_activation_started" == true ]]; then
    if ! restore_original_release; then
      printf 'CRITICAL: failed rollback could not restore original app and release pointers.\n' >&2
    fi
  fi
  exit "$status"
}
trap restore_on_failure EXIT

if (( $# == 1 )); then
  target_id="$1"
else
  target_id="$("$current/venv/bin/python" "$state_manager" \
    read-previous --allow-legacy)" \
    || { printf 'No trusted last-known-good rollback target is available.\n' >&2; exit 1; }
fi
[[ "$target_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || { printf 'Rollback release id is invalid.\n' >&2; exit 1; }

target="$(readlink -f "$RELEASES_ROOT/$target_id" 2>/dev/null || true)"
validate_release_path "$target" \
  || { printf 'Rollback target does not resolve to a trusted direct release.\n' >&2; exit 1; }
[[ "$target" != "$current" ]] || { printf 'Rollback target is already current.\n' >&2; exit 1; }
harden_release_tree "$target" \
  || { printf 'Rollback target permissions could not be hardened.\n' >&2; exit 1; }
[[ -f "$target/$READY_MARKER" && ! -L "$target/$READY_MARKER" \
  && "$(stat -c '%U:%G:%a' "$target/$READY_MARKER")" == "root:yobi:644" ]] \
  || { printf 'Rollback target was never health-verified; refusing activation.\n' >&2; exit 1; }
[[ -x "$target/venv/bin/python" && -f "$target/frontend/dist/index.html" ]] \
  || { printf 'Rollback target is incomplete; refusing activation.\n' >&2; exit 1; }

target_knowledge_release_id="$("$current/venv/bin/python" "$state_manager" \
  read-field "$target_id" knowledge_release_id --allow-missing)" \
  || { printf 'Rollback target release state is invalid.\n' >&2; exit 1; }
if [[ -z "$target_knowledge_release_id" \
  && -f "$target/scripts/manage_knowledge_release.py" ]]; then
  printf 'Rollback target uses the knowledge-release contract but lacks trusted state.\n' >&2
  exit 1
fi
target_recommendation_release_family_id="$("$current/venv/bin/python" "$state_manager" \
  read-field "$target_id" recommendation_release_family_id --allow-missing)" \
  || { printf 'Rollback target recommendation release state is invalid.\n' >&2; exit 1; }
if [[ -n "$target_knowledge_release_id" ]]; then
  original_knowledge_release_id="$(run_knowledge_manager get-active)"
  rollback_activation_started=true
  knowledge_restore_required=true
  if [[ -n "$original_knowledge_release_id" ]]; then
    run_knowledge_manager activate-ready "$target_knowledge_release_id" \
      --expected-current "$original_knowledge_release_id" >/dev/null
  else
    run_knowledge_manager activate-ready "$target_knowledge_release_id" \
      --expect-no-active >/dev/null
  fi
else
  rollback_activation_started=true
fi

original_recommendation_release_family_id="$(run_recommendation_manager get-active)"
if [[ -n "$target_recommendation_release_family_id" ]]; then
  recommendation_restore_required=true
  if [[ -n "$original_recommendation_release_family_id" ]]; then
    run_recommendation_manager activate-ready \
      "$target_recommendation_release_family_id" \
      --expected-current "$original_recommendation_release_family_id" >/dev/null
  else
    run_recommendation_manager activate-ready \
      "$target_recommendation_release_family_id" \
      --expect-no-active >/dev/null
  fi
elif [[ -n "$original_recommendation_release_family_id" ]]; then
  recommendation_restore_required=true
  run_recommendation_manager clear-active \
    --expected-current "$original_recommendation_release_family_id" >/dev/null
fi

ln -sfn "$target" "$CURRENT_LINK"
if ! systemctl daemon-reload \
  || ! systemctl restart yobi-api nginx \
  || ! check_local_services \
  || [[ "$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)" != "$target" ]]; then
  if ! restore_original_release; then
    printf 'CRITICAL: rollback activation failed and original release did not pass health/ready.\n' >&2
    exit 1
  fi
  printf 'Rollback activation failed; original release restoration was verified.\n' >&2
  exit 1
fi

current_id="${current##*/}"
if ! "$current/venv/bin/python" "$state_manager" write-previous "$current_id"; then
  if ! restore_original_release; then
    printf 'CRITICAL: rollback metadata update failed and original release did not pass health/ready.\n' >&2
    exit 1
  fi
  printf 'Rollback metadata update failed; original release restoration was verified.\n' >&2
  exit 1
fi
rollback_complete=true
knowledge_restore_required=false
recommendation_restore_required=false
rollback_activation_started=false
printf 'Activated rollback release_id=%s and passed local health/ready checks.\n' "$target_id"

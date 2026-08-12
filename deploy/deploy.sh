#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RECOVERY_ALLOW_UNREADY_CURRENT="${YOBI_RECOVERY_ALLOW_UNREADY_CURRENT:-false}"

[[ "$RECOVERY_ALLOW_UNREADY_CURRENT" == "true" \
  || "$RECOVERY_ALLOW_UNREADY_CURRENT" == "false" ]] \
  || { printf 'YOBI_RECOVERY_ALLOW_UNREADY_CURRENT must be true or false.\n' >&2; exit 1; }

for command in oci ssh scp tar shasum; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || { printf 'SSH user is invalid.\n' >&2; exit 1; }
[[ -f "$SSH_KEY" ]] || { printf 'SSH key not found: %s\n' "$SSH_KEY" >&2; exit 1; }
[[ -d "$ROOT_DIR/frontend/dist" ]] || { printf 'Run make build before deployment.\n' >&2; exit 1; }
[[ -d "$ROOT_DIR/knowledge" ]] || { printf 'Knowledge authoring sources are missing.\n' >&2; exit 1; }
readonly EXPECTED_MIGRATIONS=(
  001_core_schema.sql
  002_knowledge_and_cache.sql
  003_normalized_catalog_safety.sql
  004_three_level_spice.sql
  005_conversation_state.sql
  006_knowledge_graph.sql
  007_service_area_and_mutation_idempotency.sql
  008_checkout_cart_version.sql
  009_cart_confirmation_fingerprint.sql
  010_structured_hybrid_rag_recommendation.sql
)
for migration in "${EXPECTED_MIGRATIONS[@]}"; do
  [[ -f "$ROOT_DIR/database/migrations/$migration" ]] \
    || { printf 'Required migration is missing: %s\n' "$migration" >&2; exit 1; }
done
expected_migration_list="$(printf '%s\n' "${EXPECTED_MIGRATIONS[@]}")"
actual_migration_list="$(
  for migration_path in "$ROOT_DIR"/database/migrations/[0-9][0-9][0-9]_*.sql; do
    basename "$migration_path"
  done | LC_ALL=C sort
)"
[[ "$actual_migration_list" == "$expected_migration_list" ]] \
  || { printf 'Migration directory must contain exactly 001-010.\n' >&2; exit 1; }

compartment_id="$(oci iam compartment list --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
[[ -n "$compartment_id" && "$compartment_id" != "null" ]] || { printf 'Target compartment not found.\n' >&2; exit 1; }
instance_id="$(oci compute instance list --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$INSTANCE_NAME" \
  --lifecycle-state RUNNING --query 'data[0].id' --raw-output)"
[[ -n "$instance_id" && "$instance_id" != "null" ]] || { printf 'Running target VM not found.\n' >&2; exit 1; }
host="$(oci compute instance list-vnics --profile "$PROFILE" --region "$REGION" \
  --instance-id "$instance_id" --query 'data[0]."public-ip"' --raw-output)"
[[ -n "$host" && "$host" != "null" ]] || { printf 'VM public IP is unavailable.\n' >&2; exit 1; }

archive="$(mktemp -t yobi-release.XXXXXX.tar.gz)"
trap 'rm -f "$archive"' EXIT
COPYFILE_DISABLE=1 tar -C "$ROOT_DIR" -czf "$archive" \
  --exclude='._*' --exclude='.DS_Store' \
  --exclude='.venv' --exclude='frontend/node_modules' --exclude='frontend/test-results' \
  --exclude='frontend/playwright-report' --exclude='backend/data' --exclude='tmp' \
  backend frontend/dist database deploy scripts knowledge README.md Makefile .env.example
if tar -tzf "$archive" | grep -Eq '(^|/)\._|(^|/)\.DS_Store$'; then
  printf 'Release archive contains macOS metadata sidecars.\n' >&2
  exit 1
fi
readonly ARCHIVE_SHA256="$(shasum -a 256 "$archive" | awk '{print $1}')"
[[ "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { printf 'Release archive checksum could not be computed.\n' >&2; exit 1; }
readonly RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-${ARCHIVE_SHA256:0:12}"
readonly ARCHIVE_NONCE="$(printf '%s' "$archive" | shasum -a 256 | awk '{print substr($1,1,16)}')"
readonly REMOTE_ARCHIVE="/home/${SSH_USER}/.yobi-release-${RELEASE_ID}-${ARCHIVE_NONCE}.tar.gz"

scp -q -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
  "$archive" "$SSH_USER@$host:$REMOTE_ARCHIVE"
ssh -t -i "$SSH_KEY" "$SSH_USER@$host" \
  "sudo -n bash -s -- '$RELEASE_ID' '$ARCHIVE_SHA256' '$REMOTE_ARCHIVE' '$SSH_USER' '$ARCHIVE_NONCE' '$RECOVERY_ALLOW_UNREADY_CURRENT'" <<'REMOTE'
set -euo pipefail
[[ "${EUID}" -eq 0 ]] || { printf 'Remote deployment requires root.\n' >&2; exit 1; }
release_id="$1"
archive_sha256="$2"
remote_archive="$3"
upload_user="$4"
archive_nonce="$5"
recovery_allow_unready_current="$6"
[[ "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ \
  && "$archive_sha256" =~ ^[0-9a-f]{64}$ \
  && "$upload_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ \
  && "$archive_nonce" =~ ^[0-9a-f]{16}$ \
  && ( "$recovery_allow_unready_current" == "true" \
    || "$recovery_allow_unready_current" == "false" ) \
  && "$remote_archive" == "/home/${upload_user}/.yobi-release-${release_id}-${archive_nonce}.tar.gz" ]] \
  || { printf 'Remote release identity is invalid.\n' >&2; exit 1; }

cleanup_remote_archive() {
  if [[ -n "$remote_archive" ]]; then
    rm -f -- "$remote_archive" \
      || printf 'WARNING: remote release archive cleanup failed.\n' >&2
    remote_archive=""
  fi
}
trap cleanup_remote_archive EXIT

readonly DEPLOY_LOCK="/run/lock/yobi-deploy.lock"
command -v flock >/dev/null \
  || { printf 'Remote flock command is unavailable.\n' >&2; exit 1; }
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

readonly RELEASES_ROOT="/opt/yobi/releases"
[[ ! -L /opt/yobi && -d /opt/yobi ]] \
  || { printf 'YOBI root must be a real directory.\n' >&2; exit 1; }
[[ ! -L "$RELEASES_ROOT" && -d "$RELEASES_ROOT" ]] \
  || { printf 'Release root must be a real directory.\n' >&2; exit 1; }
id yobi >/dev/null 2>&1 \
  || { printf 'The existing yobi service account is missing.\n' >&2; exit 1; }
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

write_ready_marker() {
  local release_path="$1"
  local marker_path="$release_path/$ready_marker"
  validate_release_path "$release_path" || return 1
  rm -f -- "$marker_path" || return 1
  install -o root -g yobi -m 0644 /dev/null "$marker_path" || return 1
  [[ -f "$marker_path" && ! -L "$marker_path" \
    && "$(stat -c '%U:%G:%a' "$marker_path")" == "root:yobi:644" ]]
}

new_release="/opt/yobi/releases/$release_id"
old_release="$(readlink -f /opt/yobi/current 2>/dev/null || true)"
ready_marker=".yobi-release-ready"
old_release_verified=false
old_knowledge_release_id=""
new_knowledge_release_id=""
knowledge_restore_required=false
old_recommendation_release_family_id=""
new_recommendation_release_family_id=""
recommendation_restore_required=false

check_local_services() {
  curl --fail --silent --retry 8 --retry-delay 2 --retry-connrefused \
    --max-time 10 http://127.0.0.1/healthz >/dev/null \
    && curl --fail --silent --retry 8 --retry-delay 2 --retry-connrefused \
      --max-time 30 http://127.0.0.1/readyz >/dev/null
}

check_local_health() {
  curl --fail --silent --retry 8 --retry-delay 2 --retry-connrefused \
    --max-time 10 http://127.0.0.1/healthz >/dev/null
}

run_knowledge_manager() {
  sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" "$new_release/scripts/manage_knowledge_release.py" "$@"
}

run_recommendation_manager() {
  sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" \
    "$new_release/scripts/manage_recommendation_release.py" "$@"
}

restore_knowledge_release() {
  local active_now
  [[ "$knowledge_restore_required" == true ]] || return 0
  active_now="$(run_knowledge_manager get-active)" || return 1
  if [[ -n "$old_knowledge_release_id" ]]; then
    if [[ "$active_now" == "$old_knowledge_release_id" ]]; then
      knowledge_restore_required=false
      return 0
    fi
    if [[ -n "$active_now" ]]; then
      run_knowledge_manager activate-ready "$old_knowledge_release_id" \
        --expected-current "$active_now" >/dev/null || return 1
    else
      run_knowledge_manager activate-ready "$old_knowledge_release_id" \
        --expect-no-active >/dev/null || return 1
    fi
  elif [[ -n "$active_now" ]]; then
    run_knowledge_manager clear-active --expected-current "$active_now" \
      >/dev/null || return 1
  fi
  knowledge_restore_required=false
}

restore_recommendation_release() {
  local active_now
  [[ "$recommendation_restore_required" == true ]] || return 0
  active_now="$(run_recommendation_manager get-active)" || return 1
  if [[ -n "$old_recommendation_release_family_id" ]]; then
    if [[ "$active_now" == "$old_recommendation_release_family_id" ]]; then
      recommendation_restore_required=false
      return 0
    fi
    if [[ -n "$active_now" ]]; then
      run_recommendation_manager activate-ready \
        "$old_recommendation_release_family_id" \
        --expected-current "$active_now" >/dev/null || return 1
    else
      run_recommendation_manager activate-ready \
        "$old_recommendation_release_family_id" \
        --expect-no-active >/dev/null || return 1
    fi
  elif [[ -n "$active_now" ]]; then
    run_recommendation_manager clear-active --expected-current "$active_now" \
      >/dev/null || return 1
  fi
  recommendation_restore_required=false
}

restore_old_release() {
  local restored
  case "$old_release" in
    /opt/yobi/releases/*) ;;
    *) return 1 ;;
  esac
  [[ -n "$old_release" && -d "$old_release" ]] || return 1
  restore_knowledge_release || return 1
  restore_recommendation_release || return 1
  sudo ln -sfn "$old_release" /opt/yobi/current || return 1
  sudo systemctl daemon-reload || return 1
  sudo systemctl restart yobi-api nginx || return 1
  check_local_services || return 1
  restored="$(readlink -f /opt/yobi/current 2>/dev/null || true)"
  [[ "$restored" == "$old_release" ]] || return 1
  printf 'Restored release_id=%s and reverified health/ready.\n' "${old_release##*/}"
}

deployment_complete=false
verify_old_release_on_failure() {
  local status="$?"
  local current_after_failure
  trap - EXIT
  cleanup_remote_archive
  if [[ "$deployment_complete" != true && "$old_release_verified" == true \
    && -n "$old_release" && -d "$old_release" ]]; then
    current_after_failure="$(readlink -f /opt/yobi/current 2>/dev/null || true)"
    if [[ "$knowledge_restore_required" != true \
      && "$recommendation_restore_required" != true \
      && "$current_after_failure" == "$old_release" ]] && check_local_services; then
      printf 'Failed deployment retained release_id=%s; health/ready reverified.\n' \
        "${old_release##*/}" >&2
    elif ! restore_old_release; then
      printf 'CRITICAL: failed deployment left no health/ready verified release.\n' >&2
    fi
  elif [[ "$deployment_complete" != true \
    && "$recovery_allow_unready_current" == "true" ]]; then
    printf 'CRITICAL: recovery deployment failed; no rollback-safe prior release was registered.\n' >&2
  elif [[ "$deployment_complete" != true \
    && ( "$knowledge_restore_required" == true \
      || "$recommendation_restore_required" == true ) ]]; then
    if ! restore_knowledge_release || ! restore_recommendation_release; then
      printf 'CRITICAL: failed deployment could not restore prior release pointers.\n' >&2
    fi
  fi
  exit "$status"
}
trap verify_old_release_on_failure EXIT

printf 'Preparing release_id=%s archive_sha256=%s.\n' "$release_id" "$archive_sha256"
[[ -f "$remote_archive" && ! -L "$remote_archive" ]] \
  || { printf 'Uploaded release archive is missing or invalid.\n' >&2; exit 1; }
archive_owner="$(stat -c '%U' "$remote_archive")"
archive_mode="$(stat -c '%a' "$remote_archive")"
[[ "$archive_owner" == "$upload_user" ]] \
  || { printf 'Uploaded release archive owner is invalid.\n' >&2; exit 1; }
[[ "$archive_mode" =~ ^[0-7]{3,4}$ ]] \
  || { printf 'Uploaded release archive mode is invalid.\n' >&2; exit 1; }
(( (8#$archive_mode & 022) == 0 )) \
  || { printf 'Uploaded release archive is group/world writable.\n' >&2; exit 1; }
remote_archive_sha256="$(sha256sum "$remote_archive" | awk '{print $1}')"
[[ "$remote_archive_sha256" == "$archive_sha256" ]] \
  || { printf 'Uploaded release archive checksum mismatch.\n' >&2; exit 1; }
if [[ -n "$old_release" ]]; then
  validate_release_path "$old_release" \
    || { printf 'Current release is not a trusted direct release path.\n' >&2; exit 1; }
  harden_release_tree "$old_release" \
    || { printf 'Current release permissions could not be hardened.\n' >&2; exit 1; }
  if check_local_services; then
    old_release_verified=true
    write_ready_marker "$old_release" \
      || { printf 'Current release marker could not be trusted.\n' >&2; exit 1; }
  elif [[ "$recovery_allow_unready_current" == "true" ]] && check_local_health; then
    printf 'RECOVERY: current release is health-only and will not be registered as a rollback target.\n' >&2
  else
    printf 'Current release is not healthy enough to register as rollback target.\n' >&2
    exit 1
  fi
fi

[[ ! -e "$new_release" ]] \
  || { printf 'Release directory already exists: %s\n' "$release_id" >&2; exit 1; }
install -d -o root -g root -m 0755 "$new_release"
tar -xzf "$remote_archive" -C "$new_release"
printf 'release_id=%s\narchive_sha256=%s\n' "$release_id" "$archive_sha256" \
  | sudo tee "$new_release/.yobi-release-manifest" >/dev/null
sudo env YOBI_RELEASE_ROOT="$new_release" "$new_release/deploy/install_vm.sh"
harden_release_tree "$new_release" \
  || { printf 'New release permissions could not be hardened.\n' >&2; exit 1; }

sudo env PYTHONPATH="$new_release" "$new_release/venv/bin/python" -c \
  "from deploy.secure_bootstrap import persist_runtime_release_policy; persist_runtime_release_policy()"
# The protected dotenv file is data, not shell code. Keep every secret out of `source`/eval.
runtime_env_runner=(
  "$new_release/venv/bin/python"
  "$new_release/deploy/run_with_runtime_env.py"
  /etc/yobi/yobi.env
)
sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
  "$new_release/venv/bin/python" -c \
  'import app.main; print("Verified Python 3.9 application imports.")'
sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
  "$new_release/venv/bin/python" "$new_release/scripts/migrate.py"
sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
  "$new_release/venv/bin/python" -c \
  'from deploy.secure_bootstrap import Settings, verify_database
status = verify_database(Settings())
if not (
    status["expected_migration_count"] == status["applied_migration_count"] == 10
    and status["latest_expected_migration"]
    == status["latest_applied_migration"]
    == "010"
):
    raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")
print("Verified exact migrations=001-010 runtime_user=YOBI_APP")'
old_knowledge_release_id="$(run_knowledge_manager get-active)"
old_recommendation_release_family_id="$(run_recommendation_manager get-active)"
knowledge_restore_required=true
recommendation_restore_required=true
sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
  "$new_release/venv/bin/python" "$new_release/scripts/seed_demo.py" --upsert
sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
  "$new_release/venv/bin/python" "$new_release/scripts/seed_demo.py" --verify-only
new_knowledge_release_id="$(run_knowledge_manager get-active)"
[[ -n "$new_knowledge_release_id" ]] \
  || { printf 'Seed completed without an active knowledge release.\n' >&2; exit 1; }
new_recommendation_release_family_id="$(run_recommendation_manager get-active)"
[[ -n "$new_recommendation_release_family_id" ]] \
  || { printf 'Seed completed without an active recommendation release family.\n' >&2; exit 1; }
recorded_previous_knowledge_release_id="none"
recorded_previous_recommendation_release_family_id="none"
release_state_command=(
  sudo "$new_release/venv/bin/python" "$new_release/deploy/release_state.py"
  write-state "$release_id" "$archive_sha256" "$new_knowledge_release_id"
  --recommendation-release-family-id "$new_recommendation_release_family_id"
)
if [[ "$old_release_verified" == true && -n "$old_knowledge_release_id" ]]; then
  release_state_command+=(--previous-knowledge-release-id "$old_knowledge_release_id")
  recorded_previous_knowledge_release_id="$old_knowledge_release_id"
fi
if [[ "$old_release_verified" == true \
  && -n "$old_recommendation_release_family_id" ]]; then
  release_state_command+=(
    --previous-recommendation-release-family-id
    "$old_recommendation_release_family_id"
  )
  recorded_previous_recommendation_release_family_id="$old_recommendation_release_family_id"
fi
"${release_state_command[@]}"
printf 'knowledge_release_id=%s\nprevious_knowledge_release_id=%s\nrecommendation_release_family_id=%s\nprevious_recommendation_release_family_id=%s\n' \
  "$new_knowledge_release_id" "$recorded_previous_knowledge_release_id" \
  "$new_recommendation_release_family_id" \
  "$recorded_previous_recommendation_release_family_id" \
  | sudo tee -a "$new_release/.yobi-release-manifest" >/dev/null

harden_release_tree "$new_release" \
  || { printf 'Activated release permissions are not trusted.\n' >&2; exit 1; }
sudo ln -sfn "$new_release" /opt/yobi/current
if ! sudo systemctl daemon-reload \
  || ! sudo systemctl restart yobi-api nginx \
  || ! check_local_services \
  || [[ "$(readlink -f /opt/yobi/current 2>/dev/null || true)" != "$new_release" ]] \
  || ! sudo env PYTHONPATH="$new_release/backend:$new_release" \
    "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
    "$new_release/scripts/structured_recommendation_smoke.py" \
    --base-url http://127.0.0.1 \
  || ! write_ready_marker "$new_release"; then
  if [[ "$old_release_verified" == true && -n "$old_release" ]]; then
    if ! restore_old_release; then
      printf 'CRITICAL: release activation failed and restored release did not pass health/ready.\n' >&2
      exit 1
    fi
  elif [[ "$recovery_allow_unready_current" == "true" ]]; then
    printf 'CRITICAL: recovery activation failed and no rollback-safe prior release exists.\n' >&2
    exit 1
  fi
  printf 'Release activation failed; previous release restoration was verified.\n' >&2
  exit 1
fi
if [[ "$old_release_verified" == true && -n "$old_release" ]]; then
  old_release_id="${old_release##*/}"
  if ! sudo "$new_release/venv/bin/python" "$new_release/deploy/release_state.py" \
    write-previous "$old_release_id"; then
    if ! restore_old_release; then
      printf 'CRITICAL: rollback-target recording failed and restored release did not pass health/ready.\n' >&2
      exit 1
    fi
    printf 'Rollback-target recording failed; previous release restoration was verified.\n' >&2
    exit 1
  fi
fi
deployment_complete=true
knowledge_restore_required=false
recommendation_restore_required=false
cleanup_remote_archive
printf 'Activated release_id=%s archive_sha256=%s and verified health/ready.\n' \
  "$release_id" "$archive_sha256"
REMOTE

printf 'Release %s migrated, seeded, activated, and passed local health/ready checks.\n' "$RELEASE_ID"

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
readonly PROVISIONAL_DEPLOY="${YOBI_PROVISIONAL_DEPLOY:-false}"
readonly ZERO_PROVIDER_PROVISIONAL="${YOBI_ZERO_PROVIDER_PROVISIONAL:-false}"
readonly CODE_ONLY_PROVISIONAL="${YOBI_CODE_ONLY_PROVISIONAL:-false}"
readonly QUALITY_FIVE_ONLY="${YOBI_QUALITY_FIVE_ONLY:-false}"
readonly POST_QUALITY_REVIEW_DEPLOY="${YOBI_POST_QUALITY_REVIEW_DEPLOY:-false}"
readonly MENU_SEMANTIC_BACKFILL="${YOBI_MENU_SEMANTIC_BACKFILL:-false}"
readonly SYNTHETIC_ENRICHMENT_DEPLOY="${YOBI_SYNTHETIC_ENRICHMENT_DEPLOY:-false}"
readonly GUARDED_SSH_HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly GUARDED_SSH_PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly GUARDED_SSH_KNOWN_HOSTS_FILE="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly GUARDED_SSH_CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"

[[ "$RECOVERY_ALLOW_UNREADY_CURRENT" == "true" \
  || "$RECOVERY_ALLOW_UNREADY_CURRENT" == "false" ]] \
  || { printf 'YOBI_RECOVERY_ALLOW_UNREADY_CURRENT must be true or false.\n' >&2; exit 1; }
[[ "$PROVISIONAL_DEPLOY" == "true" || "$PROVISIONAL_DEPLOY" == "false" ]] \
  || { printf 'YOBI_PROVISIONAL_DEPLOY must be true or false.\n' >&2; exit 1; }
[[ "$ZERO_PROVIDER_PROVISIONAL" == "true" \
  || "$ZERO_PROVIDER_PROVISIONAL" == "false" ]] \
  || { printf 'YOBI_ZERO_PROVIDER_PROVISIONAL must be true or false.\n' >&2; exit 1; }
[[ "$CODE_ONLY_PROVISIONAL" == "true" \
  || "$CODE_ONLY_PROVISIONAL" == "false" ]] \
  || { printf 'YOBI_CODE_ONLY_PROVISIONAL must be true or false.\n' >&2; exit 1; }
[[ "$QUALITY_FIVE_ONLY" == "true" || "$QUALITY_FIVE_ONLY" == "false" ]] \
  || { printf 'YOBI_QUALITY_FIVE_ONLY must be true or false.\n' >&2; exit 1; }
[[ "$POST_QUALITY_REVIEW_DEPLOY" == "true" \
  || "$POST_QUALITY_REVIEW_DEPLOY" == "false" ]] \
  || { printf 'YOBI_POST_QUALITY_REVIEW_DEPLOY must be true or false.\n' >&2; exit 1; }
[[ "$MENU_SEMANTIC_BACKFILL" == "true" \
  || "$MENU_SEMANTIC_BACKFILL" == "false" ]] \
  || { printf 'YOBI_MENU_SEMANTIC_BACKFILL must be true or false.\n' >&2; exit 1; }
[[ "$SYNTHETIC_ENRICHMENT_DEPLOY" == "true" \
  || "$SYNTHETIC_ENRICHMENT_DEPLOY" == "false" ]] \
  || { printf 'YOBI_SYNTHETIC_ENRICHMENT_DEPLOY must be true or false.\n' >&2; exit 1; }
[[ "$QUALITY_FIVE_ONLY" != "true" || "$PROVISIONAL_DEPLOY" != "true" ]] \
  && [[ "$POST_QUALITY_REVIEW_DEPLOY" != "true" \
    || "$PROVISIONAL_DEPLOY" != "true" ]] \
  && [[ "$POST_QUALITY_REVIEW_DEPLOY" != "true" \
    || "$QUALITY_FIVE_ONLY" != "true" ]] \
  || { printf 'Quality-five deployment modes are mutually exclusive.\n' >&2; exit 1; }
[[ "$ZERO_PROVIDER_PROVISIONAL" != "true" \
  || ( "$PROVISIONAL_DEPLOY" == "true" \
    && "$QUALITY_FIVE_ONLY" == "false" \
    && "$POST_QUALITY_REVIEW_DEPLOY" == "false" ) ]] \
  || { printf 'Zero-provider mode requires the exclusive provisional deployment mode.\n' >&2; exit 1; }
[[ "$CODE_ONLY_PROVISIONAL" != "true" \
  || ( "$PROVISIONAL_DEPLOY" == "true" \
    && "$ZERO_PROVIDER_PROVISIONAL" == "false" \
    && "$QUALITY_FIVE_ONLY" == "false" \
    && "$POST_QUALITY_REVIEW_DEPLOY" == "false" ) ]] \
  || { printf 'Code-only mode requires exclusive provisional deployment.\n' >&2; exit 1; }
[[ "$MENU_SEMANTIC_BACKFILL" != "true" \
  || ( "$PROVISIONAL_DEPLOY" == "true" \
    && "$ZERO_PROVIDER_PROVISIONAL" == "true" \
    && "$CODE_ONLY_PROVISIONAL" == "false" ) ]] \
  || { printf 'Menu semantic backfill requires the approved zero-provider provisional mode.\n' >&2; exit 1; }
[[ "$SYNTHETIC_ENRICHMENT_DEPLOY" != "true" \
  || ( "$PROVISIONAL_DEPLOY" == "true" \
    && "$CODE_ONLY_PROVISIONAL" == "true" ) ]] \
  || { printf 'Synthetic enrichment deploy requires code-only provisional mode.\n' >&2; exit 1; }

for command in git oci ssh tar shasum python3; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || { printf 'SSH user is invalid.\n' >&2; exit 1; }
[[ -f "$SSH_KEY" ]] || { printf 'SSH key not found: %s\n' "$SSH_KEY" >&2; exit 1; }
validate_ipv4() {
  local value="$1"
  local first second third fourth
  [[ "$value" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || return 1
  IFS=. read -r first second third fourth <<<"$value"
  for octet in "$first" "$second" "$third" "$fourth"; do
    (( 10#$octet >= 0 && 10#$octet <= 255 )) || return 1
  done
}
ssh_host_key_options=(-o StrictHostKeyChecking=accept-new)
# macOS Bash 3.2 treats an empty-array expansion as unbound under `set -u`.
# One harmless explicit option keeps guarded and default transports portable.
ssh_connection_options=(-o ControlMaster=no)
if [[ -n "$GUARDED_SSH_HOST" || -n "$GUARDED_SSH_PORT" \
  || -n "$GUARDED_SSH_KNOWN_HOSTS_FILE" \
  || -n "$GUARDED_SSH_CONTROL_PATH" \
  || "${YOBI_GUARDED_BASTION_WINDOW:-}" == "1" ]]; then
  guarded_tcp443=false
  guarded_bastion=false
  if [[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
    && "${YOBI_GUARDED_NLB_WINDOW:-}" == "1" \
    && "${YOBI_GUARDED_BASTION_WINDOW:-}" != "1" \
    && -n "$GUARDED_SSH_HOST" && "$GUARDED_SSH_PORT" == "443" \
    && ( ( -z "$GUARDED_SSH_KNOWN_HOSTS_FILE" \
          && -z "$GUARDED_SSH_CONTROL_PATH" ) \
      || ( -f "$GUARDED_SSH_KNOWN_HOSTS_FILE" \
          && ! -L "$GUARDED_SSH_KNOWN_HOSTS_FILE" \
          && -S "$GUARDED_SSH_CONTROL_PATH" \
          && ! -L "$GUARDED_SSH_CONTROL_PATH" ) ) ]]; then
    guarded_tcp443=true
  fi
  if [[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
    && "${YOBI_GUARDED_BASTION_WINDOW:-}" == "1" \
    && "${YOBI_GUARDED_NLB_WINDOW:-}" != "1" \
    && "$GUARDED_SSH_HOST" == "127.0.0.1" \
    && "$GUARDED_SSH_PORT" =~ ^[0-9]{4,5}$ \
    && "$GUARDED_SSH_PORT" -ge 1024 && "$GUARDED_SSH_PORT" -le 65535 \
    && -f "$GUARDED_SSH_KNOWN_HOSTS_FILE" \
    && ! -L "$GUARDED_SSH_KNOWN_HOSTS_FILE" ]]; then
    guarded_bastion=true
  fi
  [[ "$guarded_tcp443" == "true" || "$guarded_bastion" == "true" ]] \
    || { printf 'Guarded SSH override is not an approved temporary transport.\n' >&2; exit 1; }
  if [[ "$guarded_tcp443" == "true" ]]; then
    validate_ipv4 "$GUARDED_SSH_HOST" \
      || { printf 'Guarded SSH host is not a valid IPv4 address.\n' >&2; exit 1; }
    if [[ -n "$GUARDED_SSH_CONTROL_PATH" ]]; then
      ssh_host_key_options=(
        -o "UserKnownHostsFile=${GUARDED_SSH_KNOWN_HOSTS_FILE}"
        -o StrictHostKeyChecking=yes
      )
      ssh_connection_options=(
        -o ControlMaster=no
        -o "ControlPath=${GUARDED_SSH_CONTROL_PATH}"
        -o ControlPersist=no
      )
    fi
  else
    ssh_host_key_options=(
      -o "UserKnownHostsFile=${GUARDED_SSH_KNOWN_HOSTS_FILE}"
      -o StrictHostKeyChecking=yes
    )
  fi
  unset guarded_tcp443 guarded_bastion
fi
[[ -d "$ROOT_DIR/frontend/dist" ]] || { printf 'Run make build before deployment.\n' >&2; exit 1; }
[[ -d "$ROOT_DIR/knowledge" ]] || { printf 'Knowledge authoring sources are missing.\n' >&2; exit 1; }
readonly REQUIRED_RELEASE_TOOLS=(
  scripts/backfill_menu_semantic_embeddings.py
  scripts/build_external_knowledge_release.py
  scripts/build_synthetic_enrichment_release.py
  scripts/catalog_mode.py
  scripts/manage_demo_address.py
  scripts/recommendation_http.py
  scripts/recommendation_query_plan.py
  scripts/structured_recommendation_smoke.py
  scripts/structured_fallback_smoke.py
  scripts/recommendation_performance_smoke.py
  scripts/recommendation_quality_smoke.py
  scripts/recommendation_v2_live_harness.py
  deploy/release_gate_contract.py
)
for release_tool in "${REQUIRED_RELEASE_TOOLS[@]}"; do
  [[ -f "$ROOT_DIR/$release_tool" ]] \
    || { printf 'Required release gate tool is missing: %s\n' "$release_tool" >&2; exit 1; }
done
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
  011_external_catalog_import.sql
  012_concept_preference_support_and_server_ranking.sql
  013_menu_preference_features_and_hybrid_rank.sql
  014_wiki_eligibility_indexes.sql
  015_synthetic_demo_enrichment.sql
  016_recommendation_v3_runtime.sql
  017_grounded_menu_presentation.sql
  018_llm_runtime_resilience.sql
  019_option_localization_runtime.sql
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
  || { printf 'Migration directory must contain exactly 001-019.\n' >&2; exit 1; }

source_git_commit="$(git -C "$ROOT_DIR" rev-parse --verify HEAD)"
source_git_branch="$(git -C "$ROOT_DIR" branch --show-current)"
[[ "$source_git_commit" =~ ^[0-9a-f]{40}$ \
  && "$source_git_branch" =~ ^[A-Za-z0-9._/-]+$ ]] \
  || { printf 'Source Git identity is invalid.\n' >&2; exit 1; }
[[ -z "$(git -C "$ROOT_DIR" status --porcelain=v1 --untracked-files=all)" ]] \
  || { printf 'Deployment requires a clean Git worktree.\n' >&2; exit 1; }
remote_source_git_commit="$(git -C "$ROOT_DIR" ls-remote --exit-code origin \
  "refs/heads/$source_git_branch" | awk 'NR == 1 {print $1}')"
[[ "$remote_source_git_commit" == "$source_git_commit" ]] \
  || { printf 'Deployment requires HEAD to match the pushed origin branch.\n' >&2; exit 1; }
readonly source_git_commit source_git_branch
unset remote_source_git_commit

compartment_id="$(oci iam compartment list --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
[[ -n "$compartment_id" && "$compartment_id" != "null" ]] || { printf 'Target compartment not found.\n' >&2; exit 1; }
instance_id="$(oci compute instance list --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$INSTANCE_NAME" \
  --lifecycle-state RUNNING --query 'data[0].id' --raw-output)"
[[ -n "$instance_id" && "$instance_id" != "null" ]] || { printf 'Running target VM not found.\n' >&2; exit 1; }
ssh_port=22
if [[ -n "$GUARDED_SSH_HOST" ]]; then
  host="$GUARDED_SSH_HOST"
  ssh_port="$GUARDED_SSH_PORT"
else
  host="$(oci compute instance list-vnics --profile "$PROFILE" --region "$REGION" \
    --instance-id "$instance_id" --query 'data[0]."public-ip"' --raw-output)"
  [[ -n "$host" && "$host" != "null" ]] \
    || { printf 'VM public IP is unavailable.\n' >&2; exit 1; }
fi
readonly host ssh_port

archive="$(mktemp -t yobi-release.XXXXXX.tar.gz)"
trap 'rm -f "$archive"' EXIT
COPYFILE_DISABLE=1 tar -C "$ROOT_DIR" -czf "$archive" \
  --exclude='._*' --exclude='.DS_Store' \
  --exclude='.env' --exclude='*/.env' \
  --exclude='keys' --exclude='*/keys' \
  --exclude='wallet' --exclude='*/wallet' \
  --exclude='*.db' --exclude='*.db-*' --exclude='*.sqlite' --exclude='*.sqlite3' \
  --exclude='.venv' --exclude='frontend/node_modules' --exclude='frontend/test-results' \
  --exclude='frontend/playwright-report' --exclude='backend/data' \
  --exclude='backend/backend' --exclude='*/backend/backend' \
  --exclude='tmp' --exclude='*/tmp' \
  --exclude='cache' --exclude='*/cache' \
  --exclude='.cache' --exclude='*/.cache' \
  --exclude='__pycache__' --exclude='*/__pycache__' \
  --exclude='.pytest_cache' --exclude='*/.pytest_cache' \
  --exclude='.mypy_cache' --exclude='*/.mypy_cache' \
  --exclude='.ruff_cache' --exclude='*/.ruff_cache' \
  backend frontend/dist database deploy scripts knowledge README.md Makefile .env.example
archive_listing="$(tar -tzf "$archive")"
printf '%s\n' "$archive_listing" \
  | python3 "$ROOT_DIR/deploy/release_gate_contract.py" validate-archive
if grep -Eq '(^|/)\._|(^|/)\.DS_Store$' <<<"$archive_listing"; then
  printf 'Release archive contains macOS metadata sidecars.\n' >&2
  exit 1
fi
if grep -Eq '(^|/)(\.env|keys|wallet)(/|$)|\.(db($|-)|sqlite3?$)|(^|/)(backend/backend|tmp|cache|\.cache|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)(/|$)' \
  <<<"$archive_listing"; then
  printf 'Release archive contains a forbidden secret, database, nested backend, temporary, or cache path.\n' >&2
  exit 1
fi
readonly ARCHIVE_SHA256="$(shasum -a 256 "$archive" | awk '{print $1}')"
[[ "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { printf 'Release archive checksum could not be computed.\n' >&2; exit 1; }
readonly RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-${ARCHIVE_SHA256:0:12}"
readonly ARCHIVE_NONCE="$(printf '%s' "$archive" | shasum -a 256 | awk '{print substr($1,1,16)}')"
readonly REMOTE_ARCHIVE="/home/${SSH_USER}/.yobi-release-${RELEASE_ID}-${ARCHIVE_NONCE}.tar.gz"

[[ "$REMOTE_ARCHIVE" =~ ^/home/[a-z_][a-z0-9_-]{0,31}/\.yobi-release-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}-[0-9a-f]{16}\.tar\.gz$ ]] \
  || { printf 'Remote archive path is invalid.\n' >&2; exit 1; }
# Stream the release archive in bounded chunks over the already-authenticated
# SSH command channel. This avoids a separate SFTP/SCP subsystem and prevents a
# guarded transport from having to carry the whole archive in one exec channel.
archive_bytes="$(wc -c <"$archive")"
archive_bytes="${archive_bytes//[[:space:]]/}"
[[ "$archive_bytes" =~ ^[1-9][0-9]*$ ]] \
  || { printf 'Release archive size is invalid.\n' >&2; exit 1; }
readonly ARCHIVE_CHUNK_BYTES=131072
readonly ARCHIVE_CHUNK_COUNT=$(( (archive_bytes + ARCHIVE_CHUNK_BYTES - 1) / ARCHIVE_CHUNK_BYTES ))
archive_ssh() {
  ssh -T -p "$ssh_port" -i "$SSH_KEY" \
    -o ConnectTimeout=20 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
    "${ssh_host_key_options[@]}" \
    "${ssh_connection_options[@]}" \
    "$SSH_USER@$host" "$@"
}
archive_ssh \
  "set -eu; umask 077; : > '$REMOTE_ARCHIVE'; chmod 600 '$REMOTE_ARCHIVE'"
for (( chunk_index=0; chunk_index<ARCHIVE_CHUNK_COUNT; chunk_index++ )); do
  if ! dd if="$archive" bs="$ARCHIVE_CHUNK_BYTES" skip="$chunk_index" count=1 2>/dev/null \
    | archive_ssh "cat >> '$REMOTE_ARCHIVE'"; then
    archive_ssh "rm -f '$REMOTE_ARCHIVE'" >/dev/null 2>&1 || true
    printf 'Release archive chunk transfer failed.\n' >&2
    exit 1
  fi
done
if ! archive_ssh \
  "actual=\$(wc -c < '$REMOTE_ARCHIVE'); [ \"\$actual\" -eq '$archive_bytes' ]"; then
  archive_ssh "rm -f '$REMOTE_ARCHIVE'" >/dev/null 2>&1 || true
  printf 'Release archive byte count verification failed.\n' >&2
  exit 1
fi
unset chunk_index
ssh -t -p "$ssh_port" -i "$SSH_KEY" \
  -o ConnectTimeout=20 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
  "${ssh_host_key_options[@]}" \
  "${ssh_connection_options[@]}" \
  "$SSH_USER@$host" \
  "sudo -n bash -s -- '$RELEASE_ID' '$ARCHIVE_SHA256' '$REMOTE_ARCHIVE' '$SSH_USER' '$ARCHIVE_NONCE' '$RECOVERY_ALLOW_UNREADY_CURRENT' '$PROVISIONAL_DEPLOY' '$ZERO_PROVIDER_PROVISIONAL' '$CODE_ONLY_PROVISIONAL' '$QUALITY_FIVE_ONLY' '$POST_QUALITY_REVIEW_DEPLOY' '$MENU_SEMANTIC_BACKFILL' '$compartment_id' '$source_git_commit' '$SYNTHETIC_ENRICHMENT_DEPLOY'" <<'REMOTE'
set -euo pipefail
[[ "${EUID}" -eq 0 ]] || { printf 'Remote deployment requires root.\n' >&2; exit 1; }
release_id="$1"
archive_sha256="$2"
remote_archive="$3"
upload_user="$4"
archive_nonce="$5"
recovery_allow_unready_current="$6"
provisional_deploy="$7"
zero_provider_provisional="$8"
code_only_provisional="$9"
quality_five_only="${10}"
post_quality_review_deploy="${11}"
menu_semantic_backfill="${12}"
oci_compartment_id="${13}"
source_git_commit="${14}"
synthetic_enrichment_deploy="${15}"
[[ "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ \
  && "$archive_sha256" =~ ^[0-9a-f]{64}$ \
  && "$source_git_commit" =~ ^[0-9a-f]{40}$ \
  && "$upload_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ \
  && "$archive_nonce" =~ ^[0-9a-f]{16}$ \
  && ( "$recovery_allow_unready_current" == "true" \
    || "$recovery_allow_unready_current" == "false" ) \
  && ( "$provisional_deploy" == "true" \
    || "$provisional_deploy" == "false" ) \
  && ( "$zero_provider_provisional" == "true" \
    || "$zero_provider_provisional" == "false" ) \
  && ( "$code_only_provisional" == "true" \
    || "$code_only_provisional" == "false" ) \
  && ( "$quality_five_only" == "true" \
    || "$quality_five_only" == "false" ) \
  && ( "$post_quality_review_deploy" == "true" \
    || "$post_quality_review_deploy" == "false" ) \
  && ( "$menu_semantic_backfill" == "true" \
    || "$menu_semantic_backfill" == "false" ) \
  && ( "$synthetic_enrichment_deploy" == "true" \
    || "$synthetic_enrichment_deploy" == "false" ) \
  && "$oci_compartment_id" =~ ^ocid1\.compartment\.[A-Za-z0-9._-]+$ \
  && "$remote_archive" == "/home/${upload_user}/.yobi-release-${release_id}-${archive_nonce}.tar.gz" ]] \
  || { printf 'Remote release identity is invalid.\n' >&2; exit 1; }
[[ "$quality_five_only" != "true" || "$provisional_deploy" != "true" ]] \
  && [[ "$post_quality_review_deploy" != "true" \
    || "$provisional_deploy" != "true" ]] \
  && [[ "$post_quality_review_deploy" != "true" \
    || "$quality_five_only" != "true" ]] \
  || { printf 'Remote quality-five deployment modes are mutually exclusive.\n' >&2; exit 1; }
[[ "$zero_provider_provisional" != "true" \
  || ( "$provisional_deploy" == "true" \
    && "$quality_five_only" == "false" \
    && "$post_quality_review_deploy" == "false" ) ]] \
  || { printf 'Remote zero-provider mode requires exclusive provisional deployment.\n' >&2; exit 1; }
[[ "$code_only_provisional" != "true" \
  || ( "$provisional_deploy" == "true" \
    && "$zero_provider_provisional" == "false" \
    && "$quality_five_only" == "false" \
    && "$post_quality_review_deploy" == "false" ) ]] \
  || { printf 'Remote code-only mode requires exclusive provisional deployment.\n' >&2; exit 1; }
[[ "$menu_semantic_backfill" != "true" \
  || ( "$provisional_deploy" == "true" \
    && "$zero_provider_provisional" == "true" \
    && "$code_only_provisional" == "false" ) ]] \
  || { printf 'Remote menu semantic backfill requires zero-provider provisional mode.\n' >&2; exit 1; }
[[ "$synthetic_enrichment_deploy" != "true" \
  || ( "$provisional_deploy" == "true" \
    && "$code_only_provisional" == "true" ) ]] \
  || { printf 'Remote synthetic enrichment deploy requires code-only provisional mode.\n' >&2; exit 1; }

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

write_provisional_marker() {
  local release_path="$1"
  local marker_path="$release_path/.yobi-release-provisional"
  validate_release_path "$release_path" || return 1
  install -o root -g yobi -m 0644 /dev/null "$marker_path" || return 1
  if [[ "$zero_provider_provisional" == "true" \
    || "$code_only_provisional" == "true" ]]; then
    printf '%s\n' 'recommendation-v2-five=pending' \
      | tee "$marker_path" >/dev/null || return 1
  else
    printf '%s\n' 'quality-five-gate=pending' \
      | tee "$marker_path" >/dev/null || return 1
  fi
  [[ -f "$marker_path" && ! -L "$marker_path" \
    && "$(stat -c '%U:%G:%a' "$marker_path")" == "root:yobi:644" \
    && ( "$(cat "$marker_path")" == "quality-five-gate=pending" \
      || "$(cat "$marker_path")" == "recommendation-v2-five=pending" ) ]]
}

write_reviewed_quality_marker() {
  local release_path="$1"
  local marker_path="$release_path/.yobi-release-quality-five"
  local evidence_path="$release_path/deploy/evidence/recommendation_quality_expansion_five_20260817.json"
  local evidence_sha256
  validate_release_path "$release_path" || return 1
  [[ -f "$evidence_path" && ! -L "$evidence_path" ]] || return 1
  evidence_sha256="$(sha256sum "$evidence_path" | awk '{print $1}')" || return 1
  [[ "$evidence_sha256" =~ ^[0-9a-f]{64}$ ]] || return 1
  install -o root -g yobi -m 0644 /dev/null "$marker_path" || return 1
  printf 'release-status=FINAL\nquality-gate=recommendation-quality-five-reviewed\nsamples=5\nnormal-recommended=4\nsafe-fallback=1\nadditional-provider-dispatches=0\nevidence-sha256=%s\nfull30=operator-superseded\n' \
    "$evidence_sha256" | tee "$marker_path" >/dev/null || return 1
  [[ -f "$marker_path" && ! -L "$marker_path" \
    && "$(stat -c '%U:%G:%a' "$marker_path")" == "root:yobi:644" \
    && "$(grep -c '^samples=5$' "$marker_path")" == "1" \
    && "$(grep -c '^additional-provider-dispatches=0$' "$marker_path")" == "1" ]]
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
      :
    elif [[ -n "$active_now" ]]; then
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
  sudo env PYTHONPATH="$new_release/backend:$new_release" \
    "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
    "$new_release/scripts/build_synthetic_enrichment_release.py" \
    --backend oracle --sync-runtime-to-active-family >/dev/null || return 1
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
cleanup_failed_candidate_release() {
  local current_release
  [[ "$deployment_complete" != true ]] || return 0
  [[ -d "$new_release" && ! -L "$new_release" ]] || return 0
  validate_release_path "$new_release" || return 1
  current_release="$(readlink -f /opt/yobi/current 2>/dev/null || true)"
  [[ "$current_release" != "$new_release" ]] || return 1
  sudo rm -rf --one-file-system -- "$new_release" || return 1
  [[ ! -e "$new_release" ]] || return 1
  printf 'Removed failed candidate release_id=%s.\n' "$release_id" >&2
}

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
  if ! cleanup_failed_candidate_release; then
    printf 'WARNING: failed candidate release cleanup could not be verified.\n' >&2
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
printf 'release_id=%s\narchive_sha256=%s\nsource_git_commit=%s\n' \
  "$release_id" "$archive_sha256" "$source_git_commit" \
  | sudo tee "$new_release/.yobi-release-manifest" >/dev/null
sudo env YOBI_RELEASE_ROOT="$new_release" "$new_release/deploy/install_vm.sh"
harden_release_tree "$new_release" \
  || { printf 'New release permissions could not be hardened.\n' >&2; exit 1; }

sudo env PYTHONPATH="$new_release" "$new_release/venv/bin/python" -c \
  'import sys
from deploy.secure_bootstrap import (
    persist_runtime_compartment_identity,
    persist_runtime_release_policy,
)
persist_runtime_compartment_identity(sys.argv[1])
persist_runtime_release_policy()' "$oci_compartment_id"
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
    status["expected_migration_count"] == status["applied_migration_count"] == 19
    and status["latest_expected_migration"]
    == status["latest_applied_migration"]
    == "019"
):
    raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")
print("Verified exact migrations=001-019 runtime_user=YOBI_APP")'
old_knowledge_release_id="$(run_knowledge_manager get-active)"
old_recommendation_release_family_id="$(run_recommendation_manager get-active)"
knowledge_restore_required=true
recommendation_restore_required=true
reuse_active_data_releases=false
catalog_mode="$(sudo env PYTHONPATH="$new_release/backend:$new_release" \
  "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
  "$new_release/scripts/catalog_mode.py" get-mode)"
if [[ "$catalog_mode" == "external" ]]; then
  # A normal application release is code-only with respect to the externally
  # managed catalog/knowledge/recommendation data. Preserve the active family
  # (including its additive synthetic enrichment pointer) unless an explicit
  # semantic backfill workflow was authorized.
  if [[ "$code_only_provisional" == "true" \
    || "$menu_semantic_backfill" != "true" ]]; then
    reuse_active_data_releases=true
    [[ -n "$old_knowledge_release_id" \
      && -n "$old_recommendation_release_family_id" ]] \
      || { printf 'Code-only deployment requires active data release pointers.\n' >&2; exit 1; }
    new_knowledge_release_id="$old_knowledge_release_id"
    new_recommendation_release_family_id="$old_recommendation_release_family_id"
    sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
      "$new_release/venv/bin/python" \
      "$new_release/scripts/recommendation_query_plan.py" \
      --backend oracle --scope active --verify
    sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
      "$new_release/venv/bin/python" "$new_release/scripts/manage_demo_address.py" \
      --verify-only
    if [[ "$synthetic_enrichment_deploy" == "true" ]]; then
      # The additive enrichment release starts with no runtime-generated option
      # or presentation cache. Those rows are populated lazily after selection.
      synthetic_release_id="synthetic-enrichment-${release_id}"
      enrichment_activation_json="$(sudo env \
        PYTHONPATH="$new_release/backend:$new_release" \
        "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
        "$new_release/scripts/build_synthetic_enrichment_release.py" \
        --backend oracle --release-id "$synthetic_release_id" --apply --activate)"
      new_recommendation_release_family_id="$(printf '%s' \
        "$enrichment_activation_json" | "$new_release/venv/bin/python" -c \
        'import json,re,sys
data=json.load(sys.stdin)
family=str(data.get("recommendation_release_family_id", ""))
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", family):
    raise SystemExit("SYNTHETIC_RECOMMENDATION_FAMILY_ID_INVALID")
print(family)')"
      printf '%s\n' "$enrichment_activation_json"
      unset enrichment_activation_json synthetic_release_id
      printf 'CODE-ONLY+ENRICHMENT: activated additive synthetic enrichment release.\n'
    else
      printf 'CODE-ONLY: reusing active knowledge and recommendation family without data rebuilds.\n'
    fi
  else
    # The default remains verification-only. A full provider backfill can run
    # only through the explicit, guarded, zero-provider provisional mode.
    if [[ "$menu_semantic_backfill" == "true" ]]; then
      sudo env PYTHONPATH="$new_release/backend:$new_release" \
        "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
        "$new_release/scripts/backfill_menu_semantic_embeddings.py" \
        --embedding-provider oci --dispatch-interval-seconds 1 --apply
    fi
    sudo env PYTHONPATH="$new_release/backend:$new_release" \
      "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
      "$new_release/scripts/backfill_menu_semantic_embeddings.py" \
      --embedding-provider oci --verify-only
    staged_release_json="$(sudo env PYTHONPATH="$new_release/backend:$new_release" \
    "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" \
    "$new_release/scripts/build_external_knowledge_release.py" \
    --backend oracle --stage-only)"
  mapfile -t staged_release_ids < <(
    printf '%s' "$staged_release_json" | "$new_release/venv/bin/python" -c \
      'import json,re,sys
data=json.load(sys.stdin)
knowledge=str(data.get("knowledge_release_id", ""))
family=str(data.get("release_family_id", ""))
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", knowledge):
    raise SystemExit("STAGED_KNOWLEDGE_ID_INVALID")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", family):
    raise SystemExit("STAGED_FAMILY_ID_INVALID")
print(knowledge)
print(family)'
  )
  [[ "${#staged_release_ids[@]}" -eq 2 ]] \
    || { printf 'Staged release identity could not be verified.\n' >&2; exit 1; }
  new_knowledge_release_id="${staged_release_ids[0]}"
  new_recommendation_release_family_id="${staged_release_ids[1]}"
  printf '%s\n' "$staged_release_json"
  unset staged_release_json staged_release_ids
  sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" \
    "$new_release/scripts/recommendation_query_plan.py" \
    --backend oracle --scope staged --verify
  sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" "$new_release/scripts/manage_demo_address.py" --apply
  sudo env PYTHONPATH="$new_release/backend:$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" "$new_release/scripts/manage_demo_address.py" --verify-only
  if [[ "$zero_provider_provisional" == "true" ]]; then
    # The one allowed staged-family Grok probe happens before either the app or
    # recommendation-family active pointer changes. A failure exits here and
    # leaves the existing live release active.
    predeploy_base_run_id="predeploy-$(printf '%s' "$new_recommendation_release_family_id" \
      | sha256sum | awk '{print substr($1,1,32)}')"
    predeploy_run_id=""
    for recovery_number in {0..9}; do
      candidate_run_id="$predeploy_base_run_id"
      if (( recovery_number > 0 )); then
        candidate_run_id="${predeploy_base_run_id}-r${recovery_number}"
      fi
      predeploy_artifact="/opt/yobi/shared/evidence/recommendation-v2/predeploy-${candidate_run_id}.json"
      predeploy_started="/opt/yobi/shared/evidence/recommendation-v2/predeploy-${candidate_run_id}.started.json"
      if [[ ! -e "$predeploy_artifact" && ! -e "$predeploy_started" ]]; then
        predeploy_run_id="$candidate_run_id"
        break
      fi
      [[ -f "$predeploy_artifact" ]] \
        || { printf 'Existing predeploy run is incomplete.\n' >&2; exit 1; }
      if ! predeploy_artifact_status="$(sudo "$new_release/venv/bin/python" - \
        "$predeploy_artifact" "$new_recommendation_release_family_id" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
family_id = sys.argv[2]
sidecar = path.with_suffix(path.suffix + ".sha256")
encoded = path.read_bytes()
digest = hashlib.sha256(encoded).hexdigest()
payload = json.loads(encoded)
common = (
    sidecar.read_text(encoding="utf-8") == f"{digest}  {path.name}\n"
    and payload.get("gate") == "recommendation-v2-predeploy-one"
    and payload.get("release_family_id") == family_id
    and payload.get("provider_retry_count") == 0
)
if common and payload.get("status") == "FAIL" and payload.get("provider_call_count") == 0:
    print("FAIL_ZERO")
elif common and payload.get("status") == "PASS" and payload.get("provider_call_count") == 1:
    print("PASS_ONE")
else:
    raise SystemExit(1)
PY
      )"; then
        printf 'Existing predeploy run cannot be recovered without a provider retry.\n' >&2
        exit 1
      fi
      if [[ "$predeploy_artifact_status" == "PASS_ONE" ]]; then
        predeploy_run_id="$candidate_run_id"
        break
      fi
      [[ "$predeploy_artifact_status" == "FAIL_ZERO" ]] \
        || { printf 'Existing predeploy artifact status is invalid.\n' >&2; exit 1; }
    done
    [[ -n "$predeploy_run_id" ]] \
      || { printf 'Provider-free predeploy recovery ledger is exhausted.\n' >&2; exit 1; }
    sudo env PYTHONPATH="$new_release/backend:$new_release" \
      "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
      "$new_release/scripts/recommendation_v2_live_harness.py" predeploy \
      --run-id "$predeploy_run_id" \
      --output-dir /opt/yobi/shared/evidence/recommendation-v2 \
      --release-family-id "$new_recommendation_release_family_id"
    unset candidate_run_id predeploy_artifact predeploy_artifact_status \
      predeploy_base_run_id predeploy_run_id predeploy_started recovery_number
    fi
  fi
elif [[ "$catalog_mode" == "synthetic" ]]; then
  sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" "$new_release/scripts/seed_demo.py" --upsert
  sudo env PYTHONPATH="$new_release" "${runtime_env_runner[@]}" \
    "$new_release/venv/bin/python" "$new_release/scripts/seed_demo.py" --verify-only
  new_knowledge_release_id="$(run_knowledge_manager get-active)"
  new_recommendation_release_family_id="$(run_recommendation_manager get-active)"
else
  printf 'Unsupported catalog mode: %s\n' "$catalog_mode" >&2
  exit 1
fi
[[ -n "$new_knowledge_release_id" ]] \
  || { printf 'Seed completed without an active knowledge release.\n' >&2; exit 1; }
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
if [[ "$catalog_mode" == "external" \
  && "$reuse_active_data_releases" != "true" ]]; then
  sudo env PYTHONPATH="$new_release/backend:$new_release" \
    "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
    "$new_release/scripts/build_external_knowledge_release.py" \
    --backend oracle --activate-staged
  [[ "$(run_knowledge_manager get-active)" == "$new_knowledge_release_id" \
    && "$(run_recommendation_manager get-active)" \
      == "$new_recommendation_release_family_id" ]] \
    || { printf 'Activated staged release pointers did not match.\n' >&2; exit 1; }
elif [[ "$catalog_mode" == "external" ]]; then
  [[ "$(run_knowledge_manager get-active)" == "$new_knowledge_release_id" \
    && "$(run_recommendation_manager get-active)" \
      == "$new_recommendation_release_family_id" ]] \
    || { printf 'Code-only deployment changed active data pointers.\n' >&2; exit 1; }
fi
run_release_smokes() {
  local completed_release_gates=()
  if [[ "$catalog_mode" == "external" ]]; then
    sudo env PYTHONPATH="$new_release/backend:$new_release" \
      "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
      "$new_release/scripts/recommendation_query_plan.py" \
      --backend oracle --scope active --verify \
      || return 1
    completed_release_gates+=(query-plan)
    sudo env PYTHONPATH="$new_release/backend:$new_release" \
      "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
      "$new_release/scripts/catalog_mode.py" verify-external \
      || return 1
    completed_release_gates+=(source-integrity)
  fi
  if [[ "$zero_provider_provisional" == "true" \
    || "$code_only_provisional" == "true" ]]; then
    if [[ "$catalog_mode" != "external" \
      || "${#completed_release_gates[@]}" -ne 2 \
      || "${completed_release_gates[0]}" != "query-plan" \
      || "${completed_release_gates[1]}" != "source-integrity" ]]; then
      printf 'Zero-provider provisional gates are incomplete.\n' >&2
      return 1
    fi
    printf 'PROVISIONAL-V2: activated with zero post-activation provider calls; fixed five-call gate remains pending.\n'
    return 0
  fi
  if [[ "$quality_five_only" != "true" \
    && "$post_quality_review_deploy" != "true" ]]; then
    sudo env PYTHONPATH="$new_release/backend:$new_release" \
      "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
      "$new_release/scripts/structured_recommendation_smoke.py" \
      --base-url http://127.0.0.1 \
      || return 1
  elif [[ "$catalog_mode" != "external" ]]; then
    printf 'Quality-five deployment modes require the external catalog.\n' >&2
    return 1
  elif [[ "$post_quality_review_deploy" == "true" ]]; then
    printf 'POST-QUALITY-REVIEW: exactly five provider calls were already observed; final deploy performs zero provider calls.\n'
  else
    printf 'QUALITY-FIVE-ONLY: live normal generation is covered by exactly five expanded-cuisine cases.\n'
  fi
  if [[ "$catalog_mode" == "external" ]]; then
    if [[ "$post_quality_review_deploy" == "true" ]]; then
      sudo env PYTHONPATH="$new_release/backend:$new_release" \
        "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
        "$new_release/scripts/structured_fallback_smoke.py" \
        --category-code cuisine_origins --option-code ITALIAN \
        || return 1
    else
      sudo env PYTHONPATH="$new_release/backend:$new_release" \
        "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
        "$new_release/scripts/structured_fallback_smoke.py" \
        || return 1
    fi
    completed_release_gates+=(structured)
    if [[ "$provisional_deploy" == "true" ]]; then
      printf '%s\n' "${completed_release_gates[@]}" \
        | "$new_release/venv/bin/python" \
          "$new_release/deploy/release_gate_contract.py" \
          verify-provisional-external-gates \
        || return 1
      printf 'PROVISIONAL: quality-five release gate deferred by explicit operator choice.\n'
    elif [[ "$post_quality_review_deploy" == "true" ]]; then
      "$new_release/venv/bin/python" \
        "$new_release/deploy/release_gate_contract.py" \
        verify-reviewed-quality-five \
        "$new_release/deploy/evidence/recommendation_quality_expansion_five_20260817.json" \
        --fix-source-path \
        "$new_release/backend/app/services/structured_recommendation.py" \
        --knowledge-release-id "$new_knowledge_release_id" \
        --recommendation-release-family-id \
        "$new_recommendation_release_family_id" \
        || return 1
      completed_release_gates+=(quality-five-reviewed)
      printf '%s\n' "${completed_release_gates[@]}" \
        | "$new_release/venv/bin/python" \
          "$new_release/deploy/release_gate_contract.py" \
          verify-post-review-external-gates \
        || return 1
      printf 'POST-QUALITY-REVIEW: five observations accepted after zero-call deterministic remediation verification.\n'
    else
      sudo env PYTHONPATH="$new_release/backend:$new_release" \
        "${runtime_env_runner[@]}" "$new_release/venv/bin/python" \
        "$new_release/scripts/recommendation_quality_smoke.py" \
        --base-url http://127.0.0.1 \
        || return 1
      completed_release_gates+=(quality-five)
      printf '%s\n' "${completed_release_gates[@]}" \
        | "$new_release/venv/bin/python" \
          "$new_release/deploy/release_gate_contract.py" verify-external-gates \
        || return 1
    fi
  fi
}
if ! sudo systemctl daemon-reload \
  || ! sudo systemctl restart yobi-api nginx \
  || ! check_local_services \
  || [[ "$(readlink -f /opt/yobi/current 2>/dev/null || true)" != "$new_release" ]] \
  || ! run_release_smokes \
  || ! { [[ "$provisional_deploy" != "true" ]] \
    || write_provisional_marker "$new_release"; } \
  || ! { [[ "$post_quality_review_deploy" != "true" ]] \
    || write_reviewed_quality_marker "$new_release"; } \
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
printf 'Activated release_id=%s archive_sha256=%s source_git_commit=%s and verified health/ready.\n' \
  "$release_id" "$archive_sha256" "$source_git_commit"
REMOTE

printf 'Release %s from source_git_commit=%s migrated, seeded, activated, and passed local health/ready checks.\n' \
  "$RELEASE_ID" "$source_git_commit"

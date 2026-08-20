#!/usr/bin/env bash
set -euo pipefail

# One guarded-window release gate:
# deploy -> public verify -> rollback -> public verify -> redeploy -> public verify.
# Run only through a guarded SSH wrapper so its EXIT trap removes temporary access.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" ]] \
  || { printf 'Release rehearsal must run inside the guarded SSH wrapper.\n' >&2; exit 1; }
for command in oci curl jq; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for release rehearsal.\n' >&2; exit 1; }
done

public_base_url="${YOBI_PUBLIC_BASE_URL:-}"
if [[ -n "$public_base_url" ]]; then
  [[ "$public_base_url" =~ ^https?://[^/]+/?$ ]] \
    || { printf 'YOBI_PUBLIC_BASE_URL must be an HTTP(S) origin without a path.\n' >&2; exit 1; }
  public_base_url="${public_base_url%/}"
else
  compartment_id="$(oci iam compartment list \
    --profile "$PROFILE" --region "$REGION" --all \
    --compartment-id-in-subtree true \
    --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" \
    --raw-output 2>/dev/null)" \
    || { printf 'Target compartment lookup failed.\n' >&2; exit 1; }
  [[ -n "$compartment_id" && "$compartment_id" != "null" ]] \
    || { printf 'Target compartment was not found.\n' >&2; exit 1; }
  instance_id="$(oci compute instance list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --display-name "$INSTANCE_NAME" \
    --lifecycle-state RUNNING --query 'data[0].id' --raw-output 2>/dev/null)" \
    || { printf 'Target instance lookup failed.\n' >&2; exit 1; }
  [[ -n "$instance_id" && "$instance_id" != "null" ]] \
    || { printf 'Running target instance was not found.\n' >&2; exit 1; }
  host="$(oci compute instance list-vnics \
    --profile "$PROFILE" --region "$REGION" --instance-id "$instance_id" \
    --query 'data[0]."public-ip"' --raw-output 2>/dev/null)" \
    || { printf 'Target network lookup failed.\n' >&2; exit 1; }
  [[ -n "$host" && "$host" != "null" ]] \
    || { printf 'Target address was unavailable.\n' >&2; exit 1; }
  public_base_url="http://${host}"
  unset host instance_id compartment_id
fi

public_verify() {
  local contract="$1"
  local health ready page protected_status
  health="$(curl --fail --silent --max-time 30 \
    "$public_base_url/healthz" 2>/dev/null)" \
    || { printf 'Public health verification failed.\n' >&2; return 1; }
  ready="$(curl --fail --silent --max-time 30 \
    "$public_base_url/readyz" 2>/dev/null)" \
    || { printf 'Public readiness verification failed.\n' >&2; return 1; }
  page="$(curl --fail --silent --max-time 30 \
    "$public_base_url/" 2>/dev/null)" \
    || { printf 'Public application shell verification failed.\n' >&2; return 1; }
  protected_status="$(curl --silent --max-time 30 --output /dev/null \
    --write-out '%{http_code}' "$public_base_url/api/v1/demo/status" 2>/dev/null)" \
    || { printf 'Protected route verification failed.\n' >&2; return 1; }
  jq -e '.status == "ok" or .status == "healthy"' <<<"$health" >/dev/null \
    || { printf 'Public health payload was invalid.\n' >&2; return 1; }
  jq -e '.status == "ready"' <<<"$ready" >/dev/null \
    || { printf 'Public readiness payload was invalid.\n' >&2; return 1; }
  if [[ "$contract" == "new" ]]; then
    jq -e \
      '.database.source_integrity_ready == true and .database.recommendation_ready == true' \
      <<<"$ready" >/dev/null \
      || { printf 'New release recommendation readiness was not satisfied.\n' >&2; return 1; }
  fi
  [[ "$page" == *'id="root"'* && "$protected_status" == "403" ]] \
    || { printf 'Public application/protected-route contract failed.\n' >&2; return 1; }
}

stage="initial"
recover_on_failure() {
  local command_status="$?"
  trap - EXIT INT TERM
  if (( command_status != 0 )) \
    && [[ "$stage" == "first_deployed" || "$stage" == "final_deployed" ]]; then
    printf 'Release rehearsal failed after activation; restoring the verified predecessor.\n' >&2
    if ! "$ROOT_DIR/deploy/run_remote_rollback.sh"; then
      printf 'CRITICAL: automatic rehearsal rollback failed.\n' >&2
    fi
  fi
  exit "$command_status"
}
trap recover_on_failure EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Release rehearsal: deploying candidate.\n'
"$ROOT_DIR/deploy/deploy.sh"
stage="first_deployed"
public_verify new

printf 'Release rehearsal: rolling back to verified predecessor.\n'
"$ROOT_DIR/deploy/run_remote_rollback.sh"
stage="rolled_back"
public_verify previous

# Release IDs include second precision; keep the final deployment distinct.
sleep 2
printf 'Release rehearsal: redeploying identical source as the final release.\n'
"$ROOT_DIR/deploy/deploy.sh"
stage="final_deployed"
public_verify new
stage="complete"

printf 'Release rehearsal passed deploy, public verify, rollback, and final redeploy.\n'

#!/usr/bin/env bash
set -euo pipefail

# Run the standard deploy command inside one exact current-source /32 SSH window.
# No IP address, OCID, or rule ID is printed. The exact created rule is removed on
# every normal/error/signal exit and the final NSG state is independently counted.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly NSG_NAME="yobi-app-nsg"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in oci curl jq; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for guarded deployment.\n' >&2; exit 1; }
done

validate_ipv4() {
  local value="$1"
  local first second third fourth
  [[ "$value" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || return 1
  IFS=. read -r first second third fourth <<<"$value"
  for octet in "$first" "$second" "$third" "$fourth"; do
    (( 10#$octet >= 0 && 10#$octet <= 255 )) || return 1
  done
}

source_cidr="${YOBI_DEPLOY_SOURCE_CIDR:-}"
if [[ -n "$source_cidr" ]]; then
  [[ "$source_cidr" =~ ^(.+)/32$ ]] \
    || { printf 'YOBI_DEPLOY_SOURCE_CIDR must be one IPv4 /32.\n' >&2; exit 1; }
  validate_ipv4 "${BASH_REMATCH[1]}" \
    || { printf 'YOBI_DEPLOY_SOURCE_CIDR is invalid.\n' >&2; exit 1; }
else
  source_ip="$(curl --fail --silent --show-error --max-time 10 \
    https://api.ipify.org 2>/dev/null)" \
    || { printf 'Current source address could not be resolved.\n' >&2; exit 1; }
  validate_ipv4 "$source_ip" \
    || { printf 'Resolved source address was not IPv4.\n' >&2; exit 1; }
  source_cidr="${source_ip}/32"
  unset source_ip
fi

compartment_id="$(oci iam compartment list \
  --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true \
  --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" \
  --raw-output 2>/dev/null)" \
  || { printf 'Target compartment lookup failed.\n' >&2; exit 1; }
[[ -n "$compartment_id" && "$compartment_id" != "null" ]] \
  || { printf 'Target compartment was not found.\n' >&2; exit 1; }
nsg_id="$(oci network nsg list \
  --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$NSG_NAME" \
  --query 'data[0].id' --raw-output 2>/dev/null)" \
  || { printf 'Target NSG lookup failed.\n' >&2; exit 1; }
[[ -n "$nsg_id" && "$nsg_id" != "null" ]] \
  || { printf 'Target NSG was not found.\n' >&2; exit 1; }

tcp_rule_count() {
  local port="$1"
  oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$nsg_id" \
    --direction INGRESS \
    --query "length(data[?protocol==\`\"6\"\` && \"tcp-options\".\"destination-port-range\".min==\`${port}\` && \"tcp-options\".\"destination-port-range\".max==\`${port}\`])" \
    --raw-output 2>/dev/null
}

baseline_ssh_count="$(tcp_rule_count 22)" \
  || { printf 'Initial SSH ingress verification failed.\n' >&2; exit 1; }
baseline_http_count="$(tcp_rule_count 80)" \
  || { printf 'Initial HTTP ingress verification failed.\n' >&2; exit 1; }
[[ "$baseline_ssh_count" == "0" ]] \
  || { printf 'Guarded deployment requires initial TCP 22 ingress count zero.\n' >&2; exit 1; }
[[ "$baseline_http_count" == "1" ]] \
  || { printf 'Guarded deployment requires the existing single TCP 80 rule.\n' >&2; exit 1; }

security_rules="$(jq -cn --arg source "$source_cidr" \
  '[{"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"CIDR_BLOCK","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]')"
rule_id=""
rule_created=false
cleanup_failed=false

cleanup() {
  local command_status="$?"
  trap - EXIT INT TERM
  if [[ "$rule_created" == "true" && -n "$rule_id" ]]; then
    rule_ids="$(jq -cn --arg id "$rule_id" '[$id]')"
    if ! oci network nsg rules remove \
      --profile "$PROFILE" --region "$REGION" --nsg-id "$nsg_id" \
      --security-rule-ids "$rule_ids" >/dev/null 2>&1; then
      cleanup_failed=true
    fi
  elif [[ "$rule_created" == "true" ]]; then
    cleanup_failed=true
  fi
  final_ssh_count="$(tcp_rule_count 22 2>/dev/null || true)"
  final_http_count="$(tcp_rule_count 80 2>/dev/null || true)"
  if [[ "$final_ssh_count" != "0" || "$final_http_count" != "$baseline_http_count" ]]; then
    cleanup_failed=true
  fi
  if [[ "$cleanup_failed" == "true" ]]; then
    printf 'CRITICAL: temporary SSH cleanup or final NSG verification failed.\n' >&2
    exit 1
  fi
  printf 'Temporary SSH rule removed; independently verified TCP 22=0 and TCP 80 unchanged.\n'
  exit "$command_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

add_result="$(oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$nsg_id" \
  --security-rules "$security_rules" 2>/dev/null)" \
  || { printf 'Temporary SSH rule could not be added.\n' >&2; exit 1; }
rule_created=true
rule_id="$(jq -r '.data."security-rules"[0].id // empty' <<<"$add_result")"
unset add_result security_rules source_cidr compartment_id
[[ -n "$rule_id" ]] \
  || { printf 'Created SSH rule identity could not be resolved for exact cleanup.\n' >&2; exit 1; }

active_ssh_count="$(tcp_rule_count 22)" \
  || { printf 'Temporary SSH ingress verification failed.\n' >&2; exit 1; }
[[ "$active_ssh_count" == "1" ]] \
  || { printf 'Temporary SSH window is not exactly one rule.\n' >&2; exit 1; }

printf 'Opened one guarded current-source /32 SSH window; starting standard deploy.\n'
export YOBI_GUARDED_SSH_WINDOW=1
if (( $# > 0 )); then
  (cd "$ROOT_DIR" && "$@")
else
  (cd "$ROOT_DIR" && make deploy)
fi

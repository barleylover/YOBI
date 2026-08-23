#!/usr/bin/env bash
set -euo pipefail

# Run the standard release workflow through one temporary OCI Bastion SSH
# port-forwarding session. The VM's public SSH path stays closed. The only
# target ingress is the Bastion private endpoint /32 to TCP 22, tracked by the
# exact NSG rule ID and removed with the session, bastion, and ephemeral keys
# on every exit. Resolved addresses, OCIDs, rule IDs, and key material are
# never printed.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly APP_NSG_NAME="yobi-app-nsg"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BASTION_SESSION_TTL=10800
readonly BASTION_PUBLIC_HOST="host.bastion.${REGION}.oci.oraclecloud.com"

for command in oci curl jq ssh ssh-keygen shasum python3 mktemp chmod rm rmdir; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for guarded Bastion deployment.\n' >&2; exit 1; }
done
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || { printf 'SSH user is invalid.\n' >&2; exit 1; }
[[ -f "$SSH_KEY" ]] \
  || { printf 'SSH key file was not found.\n' >&2; exit 1; }

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
instance_id="$(oci compute instance list \
  --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$INSTANCE_NAME" \
  --lifecycle-state RUNNING --query 'data[0].id' --raw-output 2>/dev/null)" \
  || { printf 'Target instance lookup failed.\n' >&2; exit 1; }
[[ -n "$instance_id" && "$instance_id" != "null" ]] \
  || { printf 'Running target instance was not found.\n' >&2; exit 1; }

vnic_id="$(oci compute instance list-vnics \
  --profile "$PROFILE" --region "$REGION" --instance-id "$instance_id" \
  --query 'data[0].id' --raw-output 2>/dev/null)" \
  || { printf 'Target VNIC lookup failed.\n' >&2; exit 1; }
[[ -n "$vnic_id" && "$vnic_id" != "null" ]] \
  || { printf 'Target VNIC was not found.\n' >&2; exit 1; }
vnic_json="$(oci network vnic get \
  --profile "$PROFILE" --region "$REGION" --vnic-id "$vnic_id" 2>/dev/null)" \
  || { printf 'Target VNIC verification failed.\n' >&2; exit 1; }
instance_private_ip="$(jq -r '.data."private-ip" // empty' <<<"$vnic_json")"
target_subnet_id="$(jq -r '.data."subnet-id" // empty' <<<"$vnic_json")"
validate_ipv4 "$instance_private_ip" \
  || { printf 'Target VNIC does not have a valid private IPv4 address.\n' >&2; exit 1; }
[[ -n "$target_subnet_id" ]] \
  || { printf 'Target subnet identity was unavailable.\n' >&2; exit 1; }

subnet_json="$(oci network subnet get \
  --profile "$PROFILE" --region "$REGION" \
  --subnet-id "$target_subnet_id" 2>/dev/null)" \
  || { printf 'Target subnet verification failed.\n' >&2; exit 1; }
vcn_id="$(jq -r '.data."vcn-id" // empty' <<<"$subnet_json")"
security_list_ids="$(jq -c '.data."security-list-ids" // []' <<<"$subnet_json")"
[[ -n "$vcn_id" ]] \
  || { printf 'Target VCN identity was unavailable.\n' >&2; exit 1; }

app_nsg_json="$(oci network nsg list \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --display-name "$APP_NSG_NAME" --all 2>/dev/null)" \
  || { printf 'Application NSG lookup failed.\n' >&2; exit 1; }
[[ "$(jq '[.data[] | select(."lifecycle-state" == "AVAILABLE")] | length' \
  <<<"$app_nsg_json")" == "1" ]] \
  || { printf 'Exactly one available application NSG is required.\n' >&2; exit 1; }
app_nsg_id="$(jq -r '.data[] | select(."lifecycle-state" == "AVAILABLE") | .id' \
  <<<"$app_nsg_json")"
app_nsg_vcn_id="$(jq -r '.data[] | select(."lifecycle-state" == "AVAILABLE") | ."vcn-id"' \
  <<<"$app_nsg_json")"
[[ "$app_nsg_vcn_id" == "$vcn_id" ]] \
  || { printf 'Target subnet and application NSG are not in the same VCN.\n' >&2; exit 1; }
jq -e --arg id "$app_nsg_id" '.data."nsg-ids" | index($id) != null' \
  <<<"$vnic_json" >/dev/null \
  || { printf 'Target VNIC is not attached to the application NSG.\n' >&2; exit 1; }
unset app_nsg_json app_nsg_vcn_id subnet_json vnic_json vnic_id instance_id

# Security lists and NSGs are a union. Refuse to proceed if a subnet security
# list would leave any direct public/private TCP 22 ingress path open.
security_list_ssh_bypass_count=0
while IFS= read -r security_list_id; do
  [[ -n "$security_list_id" ]] || continue
  security_list_json="$(oci network security-list get \
    --profile "$PROFILE" --region "$REGION" \
    --security-list-id "$security_list_id" 2>/dev/null)" \
    || { printf 'Target subnet security-list lookup failed.\n' >&2; exit 1; }
  bypass_count="$(jq -r '
    def matches_port($port):
      (.protocol == "all") or
      (.protocol == "6" and
        ((."tcp-options"."destination-port-range" // null) == null or
          (."tcp-options"."destination-port-range".min <= $port and
           ."tcp-options"."destination-port-range".max >= $port)));
    [.data."ingress-security-rules"[]? | select(matches_port(22))] | length' \
    <<<"$security_list_json")"
  security_list_ssh_bypass_count=$((security_list_ssh_bypass_count + bypass_count))
done < <(jq -r '.[]?' <<<"$security_list_ids")
unset security_list_json security_list_id security_list_ids bypass_count
[[ "$security_list_ssh_bypass_count" == "0" ]] \
  || { printf 'Target subnet security lists would bypass the exact Bastion SSH path.\n' >&2; exit 1; }
unset security_list_ssh_bypass_count

tcp_rule_count() {
  local port="$1"
  local payload
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
    --direction INGRESS --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r --argjson port "$port" \
    '[.data[]? | select((.protocol == "all") or (.protocol == "6" and ((."tcp-options"."destination-port-range" // null) == null or (."tcp-options"."destination-port-range".min <= $port and ."tcp-options"."destination-port-range".max >= $port))))] | length' \
    <<<"$payload"
}

bastion_count() {
  local payload
  payload="$(oci bastion bastion list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

lb_count() {
  local payload
  payload="$(oci lb load-balancer list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

nlb_count() {
  local payload
  payload="$(oci nlb network-load-balancer list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":{"items":[]}}'
  jq -r '[
    (if (.data | type) == "object" then (.data.items // [])[]?
     else .data[]? end) |
    select(."lifecycle-state" != "DELETED" and
      ."lifecycle-state" != "TERMINATED")
  ] | length' <<<"$payload"
}

baseline_ssh_count="$(tcp_rule_count 22)" \
  || { printf 'Initial SSH ingress verification failed.\n' >&2; exit 1; }
baseline_http_count="$(tcp_rule_count 80)" \
  || { printf 'Initial HTTP ingress verification failed.\n' >&2; exit 1; }
baseline_bastion_count="$(bastion_count)" \
  || { printf 'Initial Bastion verification failed.\n' >&2; exit 1; }
baseline_lb_count="$(lb_count)" \
  || { printf 'Initial LB verification failed.\n' >&2; exit 1; }
baseline_nlb_count="$(nlb_count)" \
  || { printf 'Initial NLB verification failed.\n' >&2; exit 1; }
[[ "$baseline_ssh_count" == "0" ]] \
  || { printf 'Guarded deployment requires initial TCP 22 ingress count zero.\n' >&2; exit 1; }
[[ "$baseline_http_count" == "1" ]] \
  || { printf 'Guarded deployment requires the existing single TCP 80 rule.\n' >&2; exit 1; }
[[ "$baseline_bastion_count" == "0" ]] \
  || { printf 'Guarded deployment requires no pre-existing Bastion.\n' >&2; exit 1; }
[[ "$baseline_lb_count" == "0" && "$baseline_nlb_count" == "0" ]] \
  || { printf 'Guarded Bastion deployment requires no load balancer transport.\n' >&2; exit 1; }

resource_nonce="$(printf '%s:%s:%s' "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "$RANDOM" \
  | shasum -a 256 | awk '{print substr($1,1,12)}')"
readonly temp_bastion_name="yobibastion${resource_nonce}"
readonly temp_session_name="yobi-bastion-session-${resource_nonce}"

temp_bastion_id=""
temp_session_id=""
bastion_private_cidr=""
app_rule_id=""
temp_dir=""
session_key=""
session_public_key=""
known_hosts_file=""
tunnel_pid=""
local_port=""
bastion_create_started=false
session_create_started=false
app_rule_create_started=false
tunnel_started=false
session_absent_verified=false
readonly local_temp_root="${TMPDIR:-/tmp}"
[[ "$local_temp_root" == /* && "$local_temp_root" != *$'\n'* ]] \
  || { printf 'Temporary directory root is invalid.\n' >&2; exit 1; }

bastion_name_count() {
  local payload
  payload="$(oci bastion bastion list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --name "$temp_bastion_name" \
    --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

resolve_temp_bastion_id() {
  local payload
  payload="$(oci bastion bastion list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --name "$temp_bastion_name" \
    --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")][0].id // empty' \
    <<<"$payload"
}

session_name_count() {
  local payload
  [[ -n "$temp_bastion_id" ]] || return 1
  payload="$(oci bastion session list \
    --profile "$PROFILE" --region "$REGION" --bastion-id "$temp_bastion_id" \
    --display-name "$temp_session_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

resolve_temp_session_id() {
  local payload
  [[ -n "$temp_bastion_id" ]] || return 1
  payload="$(oci bastion session list \
    --profile "$PROFILE" --region "$REGION" --bastion-id "$temp_bastion_id" \
    --display-name "$temp_session_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")][0].id // empty' \
    <<<"$payload"
}

matching_app_rule_ids() {
  local payload
  [[ -n "$bastion_private_cidr" ]] || { printf '[]\n'; return 0; }
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
    --direction INGRESS --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -c --arg source "$bastion_private_cidr" \
    '[.data[]? | select(.protocol == "6" and ."source-type" == "CIDR_BLOCK" and .source == $source and ."tcp-options"."destination-port-range".min == 22 and ."tcp-options"."destination-port-range".max == 22) | .id]' \
    <<<"$payload"
}

wait_for_temp_bastion_id() {
  local candidate=""
  local attempt
  for attempt in {1..12}; do
    candidate="$(resolve_temp_bastion_id 2>/dev/null || true)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    (( attempt < 12 )) && sleep 5
  done
}

wait_for_temp_session_id() {
  local candidate=""
  local attempt
  [[ -n "$temp_bastion_id" ]] || return 1
  for attempt in {1..12}; do
    candidate="$(resolve_temp_session_id 2>/dev/null || true)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    (( attempt < 12 )) && sleep 5
  done
}

remove_exact_app_rule() {
  local rule_ids=""
  local matching_count="0"
  local attempt
  if [[ -z "$app_rule_id" ]]; then
    for attempt in {1..12}; do
      rule_ids="$(matching_app_rule_ids 2>/dev/null || true)"
      [[ -n "$rule_ids" ]] || { sleep 5; continue; }
      matching_count="$(jq 'length' <<<"$rule_ids")"
      if [[ "$matching_count" == "1" ]]; then
        app_rule_id="$(jq -r '.[0]' <<<"$rule_ids")"
        break
      fi
      [[ "$matching_count" == "0" ]] || return 1
      (( attempt < 12 )) && sleep 5
    done
  fi
  if [[ -n "$app_rule_id" ]]; then
    rule_ids="$(jq -cn --arg id "$app_rule_id" '[$id]')"
    for attempt in {1..2}; do
      oci network nsg rules remove \
        --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
        --security-rule-ids "$rule_ids" >/dev/null 2>&1 || true
      rule_ids="$(matching_app_rule_ids 2>/dev/null || true)"
      [[ -n "$rule_ids" && "$(jq 'length' <<<"$rule_ids")" == "0" ]] \
        && return 0
      sleep 3
    done
    return 1
  fi
  rule_ids="$(matching_app_rule_ids 2>/dev/null || true)"
  [[ -n "$rule_ids" && "$(jq 'length' <<<"$rule_ids")" == "0" ]]
}

stop_local_tunnel() {
  local attempt
  if [[ "$tunnel_started" == "true" && "$tunnel_pid" =~ ^[0-9]+$ ]]; then
    kill "$tunnel_pid" >/dev/null 2>&1 || true
    for attempt in {1..10}; do
      kill -0 "$tunnel_pid" >/dev/null 2>&1 || break
      sleep 1
    done
    if kill -0 "$tunnel_pid" >/dev/null 2>&1; then
      kill -9 "$tunnel_pid" >/dev/null 2>&1 || true
    fi
    wait "$tunnel_pid" >/dev/null 2>&1 || true
  fi
  tunnel_started=false
  tunnel_pid=""
}

remove_local_key_material() {
  local candidate
  [[ -n "$temp_dir" ]] || return 0
  case "$temp_dir" in
    "${local_temp_root%/}"/yobi-bastion.*) ;;
    *) return 1 ;;
  esac
  for candidate in "$known_hosts_file" "$session_public_key" "$session_key"; do
    [[ -n "$candidate" ]] || continue
    rm -f -- "$candidate" || return 1
  done
  rmdir -- "$temp_dir"
}

cleanup() {
  local command_status="$?"
  local cleanup_operation_warning=false
  local cleanup_verified=false
  local final_ssh_count final_http_count final_bastion_count
  local final_lb_count final_nlb_count temp_bastion_remaining
  local matching_rule_ids session_remaining verification_attempt
  trap - EXIT INT TERM

  stop_local_tunnel

  if [[ "$bastion_create_started" == "true" && -z "$temp_bastion_id" ]]; then
    temp_bastion_id="$(wait_for_temp_bastion_id 2>/dev/null || true)"
  fi
  if [[ "$session_create_started" == "true" && -z "$temp_session_id" \
    && -n "$temp_bastion_id" ]]; then
    temp_session_id="$(wait_for_temp_session_id 2>/dev/null || true)"
  fi

  # Teardown order matters: stop local use, delete the session, close the only
  # target ingress rule, then delete the Bastion control-plane resource.
  if [[ "$session_create_started" == "true" && -n "$temp_session_id" ]]; then
    if ! oci bastion session delete \
      --profile "$PROFILE" --region "$REGION" --session-id "$temp_session_id" \
      --force --wait-for-state SUCCEEDED --max-wait-seconds 600 \
      --wait-interval-seconds 5 >/dev/null 2>&1; then
      cleanup_operation_warning=true
    fi
  fi
  if [[ "$session_create_started" != "true" ]]; then
    session_absent_verified=true
  elif [[ -n "$temp_bastion_id" ]]; then
    for verification_attempt in {1..12}; do
      session_remaining="$(session_name_count 2>/dev/null || true)"
      if [[ "$session_remaining" == "0" ]]; then
        session_absent_verified=true
        break
      fi
      (( verification_attempt < 12 )) && sleep 5
    done
  fi

  if [[ "$app_rule_create_started" == "true" ]]; then
    if ! remove_exact_app_rule; then
      cleanup_operation_warning=true
    fi
  fi

  if [[ "$bastion_create_started" == "true" && -n "$temp_bastion_id" ]]; then
    if ! oci bastion bastion delete \
      --profile "$PROFILE" --region "$REGION" --bastion-id "$temp_bastion_id" \
      --force --wait-for-state SUCCEEDED --max-wait-seconds 1200 \
      --wait-interval-seconds 10 >/dev/null 2>&1; then
      cleanup_operation_warning=true
    fi
  fi

  # OCI list APIs can lag successful deletes. Require the entire safe state in
  # one read: no TCP 22, HTTP unchanged, no Bastion/session, and no LB/NLB.
  for verification_attempt in {1..60}; do
    final_ssh_count="$(tcp_rule_count 22 2>/dev/null || true)"
    final_http_count="$(tcp_rule_count 80 2>/dev/null || true)"
    final_bastion_count="$(bastion_count 2>/dev/null || true)"
    final_lb_count="$(lb_count 2>/dev/null || true)"
    final_nlb_count="$(nlb_count 2>/dev/null || true)"
    temp_bastion_remaining="$(bastion_name_count 2>/dev/null || true)"
    matching_rule_ids="$(matching_app_rule_ids 2>/dev/null || true)"
    if [[ "$temp_bastion_remaining" == "0" ]]; then
      session_absent_verified=true
    fi
    if [[ "$final_ssh_count" == "0" \
      && "$final_http_count" == "$baseline_http_count" \
      && "$final_bastion_count" == "$baseline_bastion_count" \
      && "$final_lb_count" == "$baseline_lb_count" \
      && "$final_nlb_count" == "$baseline_nlb_count" \
      && "$temp_bastion_remaining" == "0" \
      && "$session_absent_verified" == "true" \
      && -n "$matching_rule_ids" \
      && "$(jq 'length' <<<"$matching_rule_ids")" == "0" ]]; then
      cleanup_verified=true
      break
    fi
    (( verification_attempt < 60 )) && sleep 5
  done

  if ! remove_local_key_material; then
    cleanup_operation_warning=true
    cleanup_verified=false
  fi

  if [[ "$cleanup_verified" != "true" ]]; then
    printf 'CRITICAL: temporary Bastion cleanup or final network verification failed.\n' >&2
    exit 1
  fi
  if [[ "$cleanup_operation_warning" == "true" ]]; then
    printf 'Cleanup commands reported a transient error; exact final state was independently verified.\n' >&2
  fi
  printf 'Temporary Bastion path removed; TCP 22=0, TCP 80 unchanged, and Bastion/LB absence verified.\n'
  exit "$command_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

umask 077
temp_dir="$(mktemp -d "${local_temp_root%/}/yobi-bastion.XXXXXX")" \
  || { printf 'Ephemeral Bastion key directory could not be created.\n' >&2; exit 1; }
chmod 0700 "$temp_dir"
session_key="${temp_dir}/session_ed25519"
session_public_key="${session_key}.pub"
known_hosts_file="${temp_dir}/known_hosts"
if ! ssh-keygen -q -t ed25519 -N '' -C yobi-ephemeral-bastion \
  -f "$session_key" >/dev/null 2>&1; then
  printf 'Ephemeral Bastion session key could not be generated.\n' >&2
  exit 1
fi
chmod 0600 "$session_key" "$session_public_key"
: >"$known_hosts_file"
chmod 0600 "$known_hosts_file"

client_cidr_list="$(jq -cn --arg cidr "$source_cidr" '[$cidr]')"
bastion_create_started=true
if ! oci bastion bastion create \
  --profile "$PROFILE" --region "$REGION" --bastion-type STANDARD \
  --compartment-id "$compartment_id" --target-subnet-id "$target_subnet_id" \
  --name "$temp_bastion_name" --client-cidr-list "$client_cidr_list" \
  --max-session-ttl "$BASTION_SESSION_TTL" \
  --wait-for-state SUCCEEDED --max-wait-seconds 1200 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary Bastion could not be created.\n' >&2
  exit 1
fi
unset client_cidr_list source_cidr
# The create --wait response is a work-request envelope in some CLI versions.
# Resolve the resource only from the exact unique display name instead of
# treating response data.id as a Bastion identity.
temp_bastion_id="$(wait_for_temp_bastion_id)"
[[ -n "$temp_bastion_id" && "$(bastion_name_count)" == "1" ]] \
  || { printf 'Temporary Bastion identity was not unique.\n' >&2; exit 1; }

bastion_details="$(oci bastion bastion get \
  --profile "$PROFILE" --region "$REGION" \
  --bastion-id "$temp_bastion_id" 2>/dev/null)" \
  || { printf 'Temporary Bastion verification failed.\n' >&2; exit 1; }
[[ "$(jq -r '.data."lifecycle-state" // empty' <<<"$bastion_details")" == "ACTIVE" ]] \
  || { printf 'Temporary Bastion did not become active.\n' >&2; exit 1; }
bastion_private_ip="$(jq -r '.data."private-endpoint-ip-address" // empty' \
  <<<"$bastion_details")"
unset bastion_details
validate_ipv4 "$bastion_private_ip" \
  || { printf 'Temporary Bastion private endpoint was invalid.\n' >&2; exit 1; }
bastion_private_cidr="${bastion_private_ip}/32"
unset bastion_private_ip

[[ "$(jq 'length' <<<"$(matching_app_rule_ids)")" == "0" ]] \
  || { printf 'A Bastion endpoint SSH rule already exists unexpectedly.\n' >&2; exit 1; }
app_rule="$(jq -cn --arg source "$bastion_private_cidr" \
  '[{"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]')"
app_rule_create_started=true
app_rule_result="$(oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
  --security-rules "$app_rule" 2>/dev/null)" \
  || { printf 'Application NSG Bastion rule could not be added.\n' >&2; exit 1; }
app_rule_id="$(jq -r '.data."security-rules"[0].id // empty' <<<"$app_rule_result")"
unset app_rule_result app_rule
if [[ -z "$app_rule_id" ]]; then
  matching_rule_ids="$(matching_app_rule_ids)"
  [[ "$(jq 'length' <<<"$matching_rule_ids")" == "1" ]] \
    || { printf 'Application NSG Bastion rule identity was ambiguous.\n' >&2; exit 1; }
  app_rule_id="$(jq -r '.[0]' <<<"$matching_rule_ids")"
  unset matching_rule_ids
fi
[[ "$(tcp_rule_count 22)" == "1" \
  && "$(tcp_rule_count 80)" == "$baseline_http_count" \
  && "$(jq 'length' <<<"$(matching_app_rule_ids)")" == "1" ]] \
  || { printf 'Temporary Bastion SSH ingress was not exactly one rule.\n' >&2; exit 1; }

session_create_started=true
if ! oci bastion session create-port-forwarding \
  --profile "$PROFILE" --region "$REGION" --bastion-id "$temp_bastion_id" \
  --display-name "$temp_session_name" --key-type PUB \
  --ssh-public-key-file "$session_public_key" \
  --session-ttl "$BASTION_SESSION_TTL" \
  --target-private-ip "$instance_private_ip" --target-port 22 \
  --wait-for-state SUCCEEDED --max-wait-seconds 1200 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary Bastion port-forwarding session could not be created.\n' >&2
  exit 1
fi
temp_session_id="$(wait_for_temp_session_id)"
[[ -n "$temp_session_id" && "$(session_name_count)" == "1" ]] \
  || { printf 'Temporary Bastion session identity was not unique.\n' >&2; exit 1; }
session_state="$(oci bastion session get \
  --profile "$PROFILE" --region "$REGION" --session-id "$temp_session_id" \
  --query 'data."lifecycle-state"' --raw-output 2>/dev/null)" \
  || { printf 'Temporary Bastion session verification failed.\n' >&2; exit 1; }
[[ "$session_state" == "ACTIVE" ]] \
  || { printf 'Temporary Bastion session did not become active.\n' >&2; exit 1; }
unset session_state target_subnet_id vcn_id

local_port="$(python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
[[ "$local_port" =~ ^[0-9]{4,5}$ \
  && "$local_port" -ge 1024 && "$local_port" -le 65535 ]] \
  || { printf 'A safe local forwarding port could not be selected.\n' >&2; exit 1; }

# A newly ACTIVE Bastion session can take a few seconds to become available on
# the SSH data plane. Retry only the local tunnel process against the same
# already-verified session; never create a wider rule or another session.
for tunnel_attempt in {1..3}; do
  ssh -N -T -L "127.0.0.1:${local_port}:${instance_private_ip}:22" \
    -i "$session_key" -p 22 \
    -o BatchMode=yes -o ConnectionAttempts=1 -o ConnectTimeout=20 \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=120 \
    -o ServerAliveCountMax=3 -o TCPKeepAlive=yes \
    -o "UserKnownHostsFile=${known_hosts_file}" \
    -o StrictHostKeyChecking=accept-new \
    "${temp_session_id}@${BASTION_PUBLIC_HOST}" \
    </dev/null >/dev/null 2>&1 &
  tunnel_pid=$!
  tunnel_started=true
  sleep 5
  if kill -0 "$tunnel_pid" >/dev/null 2>&1; then
    break
  fi
  wait "$tunnel_pid" 2>/dev/null || true
  tunnel_pid=""
  (( tunnel_attempt < 3 )) && sleep 5
done
[[ -n "$tunnel_pid" ]] \
  || { printf 'Temporary Bastion tunnel did not become available.\n' >&2; exit 1; }

classify_ssh_failure() {
  local diagnostic="$1"
  case "$diagnostic" in
    *"REMOTE HOST IDENTIFICATION HAS CHANGED"*) printf 'HOST_KEY_MISMATCH\n' ;;
    *"Permission denied"*) printf 'AUTHENTICATION\n' ;;
    *"Connection timed out"*|*"Operation timed out"*) printf 'TIMEOUT\n' ;;
    *"Connection refused"*) printf 'REFUSED\n' ;;
    *"No route to host"*) printf 'NO_ROUTE\n' ;;
    *"kex_exchange_identification"*|*"banner exchange"*) printf 'KEY_EXCHANGE\n' ;;
    *"Connection reset"*) printf 'RESET\n' ;;
    *"Connection closed"*|*"closed by remote host"*) printf 'CLOSED\n' ;;
    *) printf 'OTHER\n' ;;
  esac
}

ssh_preflight_ok=false
ssh_failure_category="NOT_ATTEMPTED"
ssh_preflight_output=""
for preflight_attempt in {1..12}; do
  if ! kill -0 "$tunnel_pid" >/dev/null 2>&1; then
    ssh_failure_category="TUNNEL_EXITED"
    break
  fi
  if ssh_preflight_output="$(LC_ALL=C ssh -p "$local_port" -i "$SSH_KEY" \
    -o BatchMode=yes -o ConnectionAttempts=1 -o ConnectTimeout=10 \
    -o "UserKnownHostsFile=${known_hosts_file}" \
    -o StrictHostKeyChecking=accept-new \
    "$SSH_USER@127.0.0.1" true 2>&1)"; then
    ssh_preflight_ok=true
    ssh_failure_category="NONE"
    break
  fi
  ssh_failure_category="$(classify_ssh_failure "$ssh_preflight_output")"
  (( preflight_attempt < 12 )) && sleep 5
done
unset ssh_preflight_output
if [[ "$ssh_preflight_ok" != "true" ]]; then
  printf 'Temporary Bastion SSH preflight failed (category=%s).\n' \
    "$ssh_failure_category" >&2
  exit 1
fi
chmod 0600 "$known_hosts_file"

printf 'Temporary source-restricted Bastion tunnel is healthy; starting standard release workflow.\n'
export YOBI_GUARDED_SSH_WINDOW=1
export YOBI_GUARDED_BASTION_WINDOW=1
unset YOBI_GUARDED_NLB_WINDOW YOBI_GUARDED_LB_WINDOW
export YOBI_GUARDED_SSH_HOST=127.0.0.1
export YOBI_GUARDED_SSH_PORT="$local_port"
export YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE="$known_hosts_file"
workflow_status=0
if (( $# > 0 )); then
  (cd "$ROOT_DIR" && "$@") || workflow_status=$?
else
  (cd "$ROOT_DIR" && make deploy) || workflow_status=$?
fi
exit "$workflow_status"

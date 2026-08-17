#!/usr/bin/env bash
set -euo pipefail

# Run the unchanged SSH deployment path through one temporary public Flexible
# Load Balancer. OCI Load Balancing is a full proxy, so the only permitted path
# is current source /32:443 -> temporary LB NSG -> yobi-app-01 private IP:22.
# The LB, its dedicated NSG, and the exact app-NSG rule are removed on every
# exit. No IP, OCID, rule ID, or SSH material is printed.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly PUBLIC_SUBNET_NAME="yobi-public-subnet"
readonly APP_NSG_NAME="yobi-app-nsg"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly FLOW_SOURCE_PROBE="${ROOT_DIR}/deploy/derive_source_cidr_with_temporary_flow_log.sh"
readonly BACKEND_SET_NAME="yobi_ssh_backend_set"
readonly LISTENER_NAME="yobi_ssh_listener"

for command in oci curl jq ssh shasum mktemp chmod rm rmdir; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for guarded LB deployment.\n' >&2; exit 1; }
done
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || { printf 'SSH user is invalid.\n' >&2; exit 1; }
[[ -f "$SSH_KEY" ]] \
  || { printf 'SSH key file was not found.\n' >&2; exit 1; }
[[ -f "$FLOW_SOURCE_PROBE" ]] \
  || { printf 'Bounded flow-log source probe was not found.\n' >&2; exit 1; }

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

subnets_json="$(oci network subnet list \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --display-name "$PUBLIC_SUBNET_NAME" --all 2>/dev/null)" \
  || { printf 'Public subnet lookup failed.\n' >&2; exit 1; }
[[ "$(jq '[.data[] | select(."lifecycle-state" == "AVAILABLE" and ."prohibit-public-ip-on-vnic" == false)] | length' \
  <<<"$subnets_json")" == "1" ]] \
  || { printf 'Exactly one available public subnet is required.\n' >&2; exit 1; }
public_subnet_id="$(jq -r '.data[] | select(."lifecycle-state" == "AVAILABLE" and ."prohibit-public-ip-on-vnic" == false) | .id' \
  <<<"$subnets_json")"
vcn_id="$(jq -r '.data[] | select(."lifecycle-state" == "AVAILABLE" and ."prohibit-public-ip-on-vnic" == false) | ."vcn-id"' \
  <<<"$subnets_json")"
security_list_ids="$(jq -c '.data[] | select(."lifecycle-state" == "AVAILABLE" and ."prohibit-public-ip-on-vnic" == false) | ."security-list-ids"' \
  <<<"$subnets_json")"
unset subnets_json

security_list_bypass_count=0
while IFS= read -r security_list_id; do
  [[ -n "$security_list_id" ]] || continue
  security_list_json="$(oci network security-list get \
    --profile "$PROFILE" --region "$REGION" \
    --security-list-id "$security_list_id" 2>/dev/null)" \
    || { printf 'Public subnet security-list lookup failed.\n' >&2; exit 1; }
  bypass_count="$(jq -r --arg allowed_source "$source_cidr" '
    def matches_port($port):
      (.protocol == "all") or
      (.protocol == "6" and
        ((."tcp-options"."destination-port-range" // null) == null or
          (."tcp-options"."destination-port-range".min <= $port and
           ."tcp-options"."destination-port-range".max >= $port)));
    [.data."ingress-security-rules"[]? |
      select(matches_port(22) or
        (matches_port(443) and
          ((."source-type" != "CIDR_BLOCK") or .source != $allowed_source)))] |
    length' <<<"$security_list_json")"
  security_list_bypass_count=$((security_list_bypass_count + bypass_count))
done < <(jq -r '.[]?' <<<"$security_list_ids")
unset security_list_json security_list_id security_list_ids bypass_count
[[ "$security_list_bypass_count" == "0" ]] \
  || { printf 'Public subnet security lists would bypass the exact SSH path.\n' >&2; exit 1; }
unset security_list_bypass_count

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
unset app_nsg_json
[[ "$app_nsg_vcn_id" == "$vcn_id" ]] \
  || { printf 'Public subnet and application NSG are not in the same VCN.\n' >&2; exit 1; }

vnic_id="$(oci compute instance list-vnics \
  --profile "$PROFILE" --region "$REGION" --instance-id "$instance_id" \
  --query 'data[0].id' --raw-output 2>/dev/null)" \
  || { printf 'Target VNIC lookup failed.\n' >&2; exit 1; }
[[ -n "$vnic_id" && "$vnic_id" != "null" ]] \
  || { printf 'Target VNIC was not found.\n' >&2; exit 1; }
vnic_json="$(oci network vnic get \
  --profile "$PROFILE" --region "$REGION" --vnic-id "$vnic_id" 2>/dev/null)" \
  || { printf 'Target VNIC verification failed.\n' >&2; exit 1; }
jq -e --arg id "$app_nsg_id" '.data."nsg-ids" | index($id) != null' \
  <<<"$vnic_json" >/dev/null \
  || { printf 'Target VNIC is not attached to the application NSG.\n' >&2; exit 1; }
instance_private_ip="$(jq -r '.data."private-ip" // empty' <<<"$vnic_json")"
validate_ipv4 "$instance_private_ip" \
  || { printf 'Target VNIC does not have a valid private IPv4 address.\n' >&2; exit 1; }
unset vnic_json vnic_id app_nsg_vcn_id instance_id

tcp_rule_count() {
  local port="$1"
  local payload
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
    --direction INGRESS --all 2>/dev/null)" || return 1
  jq -r --argjson port "$port" \
    '[.data[] | select((.protocol == "all") or (.protocol == "6" and ((."tcp-options"."destination-port-range" // null) == null or (."tcp-options"."destination-port-range".min <= $port and ."tcp-options"."destination-port-range".max >= $port))))] | length' \
    <<<"$payload"
}

lb_count() {
  local payload
  payload="$(oci lb load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

lb_name_count() {
  local payload
  payload="$(oci lb load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_lb_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

resolve_temp_nsg_id() {
  local payload
  payload="$(oci network nsg list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_nsg_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[] | select(."lifecycle-state" != "TERMINATED")][0].id // empty' \
    <<<"$payload"
}

temp_nsg_name_count() {
  local payload
  payload="$(oci network nsg list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_nsg_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[] | select(."lifecycle-state" != "TERMINATED")] | length' \
    <<<"$payload"
}

temp_nsg_rule_count() {
  local direction="$1"
  local peer_type="$2"
  local peer="$3"
  local port="$4"
  local payload
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
    --direction "$direction" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  if [[ "$direction" == "INGRESS" ]]; then
    jq -r --arg type "$peer_type" --arg peer "$peer" --argjson port "$port" \
      '[.data[] | select(.protocol == "6" and ."source-type" == $type and .source == $peer and ."tcp-options"."destination-port-range".min == $port and ."tcp-options"."destination-port-range".max == $port)] | length' \
      <<<"$payload"
  else
    jq -r --arg type "$peer_type" --arg peer "$peer" --argjson port "$port" \
      '[.data[] | select(.protocol == "6" and ."destination-type" == $type and .destination == $peer and ."tcp-options"."destination-port-range".min == $port and ."tcp-options"."destination-port-range".max == $port)] | length' \
      <<<"$payload"
  fi
}

temp_nsg_total_rule_count() {
  local payload
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
    --all 2>/dev/null)" || return 1
  jq -r '.data | length' <<<"$payload"
}

replace_frontend_source_cidr() {
  local replacement_source="$1"
  local payload old_rule_ids old_rule_count replacement_rule
  local replacement_rule_count attempt

  [[ "$replacement_source" =~ ^(.+)/32$ ]] \
    && validate_ipv4 "${BASH_REMATCH[1]}" \
    && [[ "$replacement_source" != "$source_cidr" ]] \
    || return 1

  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
    --direction INGRESS --all 2>/dev/null)" || return 1
  old_rule_ids="$(jq -c --arg source "$source_cidr" '
    [.data[] | select(
      .protocol == "6" and ."source-type" == "CIDR_BLOCK" and
      .source == $source and ."is-stateless" == false and
      ."tcp-options"."destination-port-range".min == 443 and
      ."tcp-options"."destination-port-range".max == 443
    ) | .id]' <<<"$payload")"
  old_rule_count="$(jq 'length' <<<"$old_rule_ids")"
  [[ "$old_rule_count" == "1" ]] || return 1

  oci network nsg rules remove \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
    --security-rule-ids "$old_rule_ids" >/dev/null 2>&1 || return 1

  # Do not add the corrected rule until the old /32 is independently absent.
  # This keeps the transition fail closed even when OCI reads converge slowly.
  for attempt in {1..12}; do
    old_rule_count="$(temp_nsg_rule_count \
      INGRESS CIDR_BLOCK "$source_cidr" 443 2>/dev/null || true)"
    if [[ "$old_rule_count" == "0" \
      && "$(temp_nsg_total_rule_count 2>/dev/null || true)" == "1" ]]; then
      break
    fi
    (( attempt < 12 )) && sleep 5
  done
  [[ "$old_rule_count" == "0" \
    && "$(temp_nsg_total_rule_count)" == "1" ]] || return 1

  replacement_rule="$(jq -cn --arg source "$replacement_source" \
    '[{"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}}]')"
  oci network nsg rules add \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
    --security-rules "$replacement_rule" >/dev/null 2>&1 || return 1

  source_cidr="$replacement_source"
  for attempt in {1..12}; do
    replacement_rule_count="$(temp_nsg_rule_count \
      INGRESS CIDR_BLOCK "$source_cidr" 443 2>/dev/null || true)"
    if [[ "$replacement_rule_count" == "1" \
      && "$(temp_nsg_rule_count EGRESS NETWORK_SECURITY_GROUP "$app_nsg_id" 22 2>/dev/null || true)" == "1" \
      && "$(temp_nsg_total_rule_count 2>/dev/null || true)" == "2" ]]; then
      return 0
    fi
    (( attempt < 12 )) && sleep 5
  done
  return 1
}

resolve_temp_lb_id() {
  local payload
  payload="$(oci lb load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_lb_name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '[.data[]? | select(."lifecycle-state" != "DELETED")][0].id // empty' \
    <<<"$payload"
}

matching_app_rule_ids() {
  local payload
  payload="$(oci network nsg rules list \
    --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
    --direction INGRESS --all 2>/dev/null)" || return 1
  jq -c --arg source "$temp_nsg_id" \
    '[.data[] | select(.protocol == "6" and ."source-type" == "NETWORK_SECURITY_GROUP" and .source == $source and ."tcp-options"."destination-port-range".min == 22 and ."tcp-options"."destination-port-range".max == 22) | .id]' \
    <<<"$payload"
}

wait_for_temp_nsg_id() {
  local candidate=""
  local _
  for _ in {1..12}; do
    candidate="$(resolve_temp_nsg_id 2>/dev/null || true)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    (( _ < 12 )) && sleep 5
  done
}

wait_for_temp_lb_id() {
  local candidate=""
  local _
  for _ in {1..12}; do
    candidate="$(resolve_temp_lb_id 2>/dev/null || true)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    (( _ < 12 )) && sleep 5
  done
}

remove_exact_app_rule() {
  local rule_ids=""
  local matching_count="0"
  local _
  if [[ -z "$app_rule_id" ]]; then
    for _ in {1..12}; do
      rule_ids="$(matching_app_rule_ids 2>/dev/null || true)"
      [[ -n "$rule_ids" ]] || { sleep 5; continue; }
      matching_count="$(jq 'length' <<<"$rule_ids")"
      if [[ "$matching_count" == "1" ]]; then
        app_rule_id="$(jq -r '.[0]' <<<"$rule_ids")"
        break
      fi
      if [[ "$matching_count" != "0" ]]; then
        return 1
      fi
      (( _ < 12 )) && sleep 5
    done
  fi
  if [[ -n "$app_rule_id" ]]; then
    rule_ids="$(jq -cn --arg id "$app_rule_id" '[$id]')"
    for _ in {1..2}; do
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

baseline_ssh_count="$(tcp_rule_count 22)" \
  || { printf 'Initial SSH ingress verification failed.\n' >&2; exit 1; }
baseline_http_count="$(tcp_rule_count 80)" \
  || { printf 'Initial HTTP ingress verification failed.\n' >&2; exit 1; }
baseline_lb_count="$(lb_count)" \
  || { printf 'Initial LB verification failed.\n' >&2; exit 1; }
[[ "$baseline_ssh_count" == "0" ]] \
  || { printf 'Guarded deployment requires initial TCP 22 ingress count zero.\n' >&2; exit 1; }
[[ "$baseline_http_count" == "1" ]] \
  || { printf 'Guarded deployment requires the existing single TCP 80 rule.\n' >&2; exit 1; }
[[ "$baseline_lb_count" == "0" ]] \
  || { printf 'Guarded deployment requires no pre-existing load balancer.\n' >&2; exit 1; }

resource_nonce="$(printf '%s:%s:%s' "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "$RANDOM" \
  | shasum -a 256 | awk '{print substr($1,1,12)}')"
readonly temp_nsg_name="yobi-ssh-lb-nsg-${resource_nonce}"
readonly temp_lb_name="yobi-ssh-lb-${resource_nonce}"
temp_nsg_id=""
temp_lb_id=""
app_rule_id=""
transport_temp_dir=""
known_hosts_file=""
control_path=""
master_started=false
temp_nsg_create_started=false
app_rule_create_started=false
lb_create_started=false

cleanup() {
  local command_status="$?"
  local final_ssh_count final_http_count final_lb_count
  local temp_nsg_remaining temp_lb_remaining
  local verification_attempt
  local cleanup_operation_warning=false
  local cleanup_verified=false
  trap - EXIT INT TERM

  if [[ "$master_started" == "true" && -n "$control_path" \
    && -n "${lb_host:-}" ]]; then
    ssh -S "$control_path" -O exit -p 443 \
      -o "UserKnownHostsFile=${known_hosts_file}" \
      -o StrictHostKeyChecking=yes \
      "$SSH_USER@$lb_host" >/dev/null 2>&1 || cleanup_operation_warning=true
    master_started=false
  fi

  if [[ "$temp_nsg_create_started" == "true" && -z "$temp_nsg_id" ]]; then
    temp_nsg_id="$(wait_for_temp_nsg_id 2>/dev/null || true)"
  fi
  if [[ "$lb_create_started" == "true" && -z "$temp_lb_id" ]]; then
    temp_lb_id="$(wait_for_temp_lb_id 2>/dev/null || true)"
  fi

  # Keep this order: remove the frontend first, then its only backend ingress,
  # then the temporary NSG which owns the frontend ingress/egress rules.
  if [[ "$lb_create_started" == "true" && -n "$temp_lb_id" ]]; then
    if ! oci lb load-balancer delete \
      --profile "$PROFILE" --region "$REGION" \
      --load-balancer-id "$temp_lb_id" --force \
      --wait-for-state SUCCEEDED --max-wait-seconds 1200 \
      --wait-interval-seconds 10 >/dev/null 2>&1; then
      cleanup_operation_warning=true
    fi
  fi

  if [[ "$app_rule_create_started" == "true" && -n "$temp_nsg_id" ]]; then
    if ! remove_exact_app_rule; then
      cleanup_operation_warning=true
    fi
  fi

  if [[ "$temp_nsg_create_started" == "true" && -n "$temp_nsg_id" ]]; then
    if ! oci network nsg delete \
      --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
      --force --wait-for-state TERMINATED --max-wait-seconds 600 \
      --wait-interval-seconds 10 >/dev/null 2>&1; then
      cleanup_operation_warning=true
    fi
  fi

  if [[ -n "$transport_temp_dir" ]]; then
    case "$transport_temp_dir" in
      "${TMPDIR:-/tmp}"/yobi-lb-master.*) ;;
      *) cleanup_operation_warning=true ;;
    esac
    if [[ "$transport_temp_dir" == "${TMPDIR:-/tmp}"/yobi-lb-master.* ]]; then
      rm -f -- "$control_path" "$known_hosts_file" \
        || cleanup_operation_warning=true
      rmdir -- "$transport_temp_dir" 2>/dev/null \
        || cleanup_operation_warning=true
    fi
  fi

  # OCI list/read APIs can lag a successful delete. Require the complete safe
  # state in one observation, but allow bounded convergence before declaring a
  # cleanup failure. Individual command errors are non-authoritative if the
  # independently queried final state is exact.
  # LB and NSG list APIs have taken longer than 55 seconds to converge after a
  # confirmed delete in this tenancy.  Keep polling the authoritative complete
  # state for up to five minutes before treating cleanup as failed.
  for verification_attempt in {1..60}; do
    final_ssh_count="$(tcp_rule_count 22 2>/dev/null || true)"
    final_http_count="$(tcp_rule_count 80 2>/dev/null || true)"
    final_lb_count="$(lb_count 2>/dev/null || true)"
    temp_lb_remaining="$(lb_name_count 2>/dev/null || true)"
    temp_nsg_remaining="$(temp_nsg_name_count 2>/dev/null || true)"
    if [[ "$final_ssh_count" == "0" \
      && "$final_http_count" == "$baseline_http_count" \
      && "$final_lb_count" == "$baseline_lb_count" \
      && "$temp_lb_remaining" == "0" \
      && "$temp_nsg_remaining" == "0" ]]; then
      cleanup_verified=true
      break
    fi
    (( verification_attempt < 60 )) && sleep 5
  done
  if [[ "$cleanup_verified" != "true" ]]; then
    printf 'CRITICAL: temporary LB cleanup or final network verification failed.\n' >&2
    exit 1
  fi
  if [[ "$cleanup_operation_warning" == "true" ]]; then
    printf 'Cleanup commands reported a transient error; exact final network state was independently verified.\n' >&2
  fi
  printf 'Temporary LB path removed; independently verified TCP 22=0, TCP 80 unchanged, and LB count restored.\n'
  exit "$command_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

umask 077
transport_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/yobi-lb-master.XXXXXX")" \
  || { printf 'Temporary SSH master directory could not be created.\n' >&2; exit 1; }
chmod 0700 "$transport_temp_dir"
known_hosts_file="${transport_temp_dir}/known_hosts"
control_path="${transport_temp_dir}/control"
: >"$known_hosts_file"
chmod 0600 "$known_hosts_file"

temp_nsg_create_started=true
if ! oci network nsg create \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --vcn-id "$vcn_id" --display-name "$temp_nsg_name" \
  --wait-for-state AVAILABLE --max-wait-seconds 300 \
  --wait-interval-seconds 5 >/dev/null 2>&1; then
  printf 'Temporary LB NSG could not be created.\n' >&2
  exit 1
fi
temp_nsg_id="$(resolve_temp_nsg_id)" \
  || { printf 'Temporary LB NSG lookup failed.\n' >&2; exit 1; }
[[ -n "$temp_nsg_id" ]] \
  || { printf 'Temporary LB NSG identity could not be resolved.\n' >&2; exit 1; }

temp_nsg_rules="$(jq -cn --arg source "$source_cidr" --arg destination "$app_nsg_id" \
  '[
    {"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}},
    {"direction":"EGRESS","protocol":"6","destination":$destination,"destinationType":"NETWORK_SECURITY_GROUP","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}
  ]')"
if ! oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
  --security-rules "$temp_nsg_rules" >/dev/null 2>&1; then
  printf 'Temporary LB NSG rules could not be added.\n' >&2
  exit 1
fi
[[ "$(temp_nsg_total_rule_count)" == "2" \
  && "$(temp_nsg_rule_count INGRESS CIDR_BLOCK "$source_cidr" 443)" == "1" \
  && "$(temp_nsg_rule_count EGRESS NETWORK_SECURITY_GROUP "$app_nsg_id" 22)" == "1" ]] \
  || { printf 'Temporary LB NSG does not contain the exact two-path rules.\n' >&2; exit 1; }

app_rule="$(jq -cn --arg source "$temp_nsg_id" \
  '[{"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"NETWORK_SECURITY_GROUP","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]')"
app_rule_create_started=true
app_rule_result="$(oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
  --security-rules "$app_rule" 2>/dev/null)" \
  || { printf 'Application NSG backend rule could not be added.\n' >&2; exit 1; }
app_rule_id="$(jq -r '.data."security-rules"[0].id // empty' <<<"$app_rule_result")"
unset app_rule_result app_rule temp_nsg_rules
[[ -n "$app_rule_id" ]] \
  || { printf 'Application NSG rule identity could not be resolved.\n' >&2; exit 1; }
[[ "$(tcp_rule_count 22)" == "1" ]] \
  || { printf 'Temporary backend SSH rule is not exactly one rule.\n' >&2; exit 1; }
[[ "$(tcp_rule_count 80)" == "$baseline_http_count" ]] \
  || { printf 'Existing HTTP ingress changed during setup.\n' >&2; exit 1; }

lb_nsg_ids="$(jq -cn --arg id "$temp_nsg_id" '[$id]')"
subnet_ids="$(jq -cn --arg id "$public_subnet_id" '[$id]')"
shape_details='{"minimumBandwidthInMbps":10,"maximumBandwidthInMbps":10}'
lb_create_started=true
if ! oci lb load-balancer create \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --display-name "$temp_lb_name" --shape-name flexible \
  --shape-details "$shape_details" --subnet-ids "$subnet_ids" \
  --is-private false --ip-mode IPV4 --nsg-ids "$lb_nsg_ids" \
  --wait-for-state SUCCEEDED --max-wait-seconds 1200 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary public Flexible LB could not be created.\n' >&2
  exit 1
fi
temp_lb_id="$(resolve_temp_lb_id)" \
  || { printf 'Temporary LB lookup failed.\n' >&2; exit 1; }
[[ -n "$temp_lb_id" && "$(lb_name_count)" == "1" ]] \
  || { printf 'Temporary LB identity was not unique.\n' >&2; exit 1; }

if ! oci lb backend-set create \
  --profile "$PROFILE" --region "$REGION" \
  --load-balancer-id "$temp_lb_id" --name "$BACKEND_SET_NAME" \
  --policy LEAST_CONNECTIONS --health-checker-protocol TCP \
  --health-checker-port 22 --health-checker-interval-in-ms 10000 \
  --health-checker-timeout-in-ms 3000 --health-checker-retries 3 \
  --wait-for-state SUCCEEDED --max-wait-seconds 600 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary LB backend set could not be created.\n' >&2
  exit 1
fi
if ! oci lb backend create \
  --profile "$PROFILE" --region "$REGION" \
  --load-balancer-id "$temp_lb_id" \
  --backend-set-name "$BACKEND_SET_NAME" \
  --ip-address "$instance_private_ip" --port 22 --backup false \
  --drain false --offline false --wait-for-state SUCCEEDED \
  --max-wait-seconds 600 --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary LB backend could not be created.\n' >&2
  exit 1
fi
if ! oci lb listener create \
  --profile "$PROFILE" --region "$REGION" \
  --load-balancer-id "$temp_lb_id" --name "$LISTENER_NAME" \
  --default-backend-set-name "$BACKEND_SET_NAME" --protocol TCP --port 443 \
  --wait-for-state SUCCEEDED --max-wait-seconds 600 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary LB listener could not be created.\n' >&2
  exit 1
fi

lb_details="$(oci lb load-balancer get \
  --profile "$PROFILE" --region "$REGION" \
  --load-balancer-id "$temp_lb_id" 2>/dev/null)" \
  || { printf 'Temporary LB address lookup failed.\n' >&2; exit 1; }
lb_host="$(jq -r '[.data."ip-addresses"[]? | select(."is-public" == true)][0]."ip-address" // empty' \
  <<<"$lb_details")"
unset lb_details lb_nsg_ids subnet_ids shape_details public_subnet_id vcn_id
validate_ipv4 "$lb_host" \
  || { printf 'Temporary LB did not receive a public IPv4 address.\n' >&2; exit 1; }

backend_healthy=false
readonly backend_name="${instance_private_ip}:22"
unset instance_private_ip
for _ in {1..60}; do
  backend_status="$(oci lb backend-health get \
    --profile "$PROFILE" --region "$REGION" \
    --load-balancer-id "$temp_lb_id" \
    --backend-set-name "$BACKEND_SET_NAME" --backend-name "$backend_name" \
    --query 'data.status' --raw-output 2>/dev/null || true)"
  if [[ "$backend_status" == "OK" ]]; then
    backend_healthy=true
    break
  fi
  sleep 5
done
[[ "$backend_healthy" == "true" ]] \
  || { printf 'Temporary LB backend did not become healthy.\n' >&2; exit 1; }

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

run_ssh_preflight() {
  local preflight_attempt
  ssh_preflight_ok=false
  ssh_failure_category="NOT_ATTEMPTED"
  ssh_preflight_output=""
  for preflight_attempt in {1..12}; do
    if ssh_preflight_output="$(LC_ALL=C ssh -p 443 -i "$SSH_KEY" \
      -o BatchMode=yes -o ConnectionAttempts=1 -o ConnectTimeout=10 \
      -o StrictHostKeyChecking=accept-new "$SSH_USER@$lb_host" true 2>&1)"; then
      ssh_preflight_ok=true
      ssh_failure_category="NONE"
      break
    fi
    ssh_failure_category="$(classify_ssh_failure "$ssh_preflight_output")"
    (( preflight_attempt < 12 )) && sleep 5
  done
  unset ssh_preflight_output
  [[ "$ssh_preflight_ok" == "true" ]]
}

if ! run_ssh_preflight; then
  if [[ "$ssh_failure_category" != "TIMEOUT" ]]; then
    printf 'Temporary LB SSH preflight failed (category=%s).\n' \
      "$ssh_failure_category" >&2
    exit 1
  fi
  derived_source_cidr=""
  if ! derived_source_cidr="$(bash "$FLOW_SOURCE_PROBE" \
    --transport lb --frontend-nsg-id "$temp_nsg_id" \
    --frontend-host "$lb_host" --configured-source-cidr "$source_cidr" \
    --result-fd 3 3>&1 1>&2)"; then
    printf 'Bounded flow-log source diagnosis failed; frontend rule was not widened.\n' >&2
    exit 1
  fi
  if ! replace_frontend_source_cidr "$derived_source_cidr"; then
    printf 'Exact frontend source replacement failed.\n' >&2
    exit 1
  fi
  unset derived_source_cidr
  if ! run_ssh_preflight; then
    printf 'Temporary LB SSH retry failed after exact source correction (category=%s).\n' \
      "$ssh_failure_category" >&2
    exit 1
  fi
fi
unset source_cidr

master_output=""
if ! master_output="$(LC_ALL=C ssh -MNf -S "$control_path" \
  -p 443 -i "$SSH_KEY" -o BatchMode=yes -o ConnectionAttempts=1 \
  -o ConnectTimeout=20 -o ControlMaster=yes -o ControlPersist=no \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
  -o "UserKnownHostsFile=${known_hosts_file}" \
  -o StrictHostKeyChecking=accept-new "$SSH_USER@$lb_host" 2>&1)"; then
  master_failure_category="$(classify_ssh_failure "$master_output")"
  unset master_output
  printf 'Persistent guarded SSH connection failed (category=%s).\n' \
    "$master_failure_category" >&2
  exit 1
fi
unset master_output
master_started=true
if [[ ! -S "$control_path" ]] \
  || ! ssh -S "$control_path" -O check -p 443 \
    -o "UserKnownHostsFile=${known_hosts_file}" \
    -o StrictHostKeyChecking=yes "$SSH_USER@$lb_host" >/dev/null 2>&1 \
  || ! ssh -S "$control_path" -p 443 -i "$SSH_KEY" \
    -o BatchMode=yes -o ControlMaster=no -o ControlPersist=no \
    -o "UserKnownHostsFile=${known_hosts_file}" \
    -o StrictHostKeyChecking=yes "$SSH_USER@$lb_host" true >/dev/null 2>&1; then
  printf 'Persistent guarded SSH connection verification failed.\n' >&2
  exit 1
fi

printf 'Temporary source-restricted TCP 443 SSH path is healthy; starting unchanged release workflow.\n'
export YOBI_GUARDED_SSH_WINDOW=1
# deploy.sh and run_remote_rollback.sh intentionally remain unchanged. Their
# existing generic TCP-443 override gate uses this compatibility marker.
export YOBI_GUARDED_NLB_WINDOW=1
export YOBI_GUARDED_LB_WINDOW=1
export YOBI_GUARDED_SSH_HOST="$lb_host"
export YOBI_GUARDED_SSH_PORT=443
export YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE="$known_hosts_file"
export YOBI_GUARDED_SSH_CONTROL_PATH="$control_path"
if (( $# > 0 )); then
  (cd "$ROOT_DIR" && "$@")
else
  (cd "$ROOT_DIR" && make deploy)
fi

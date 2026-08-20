#!/usr/bin/env bash
set -euo pipefail

# Run the unchanged SSH deployment path through one temporary public NLB:
# current source /32:443 -> full-NAT NLB -> yobi-app-01:22. The NLB, its
# dedicated NSG, and the exact app-NSG rule are removed on every exit. No IP,
# OCID, rule ID, or SSH material is printed.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly PUBLIC_SUBNET_NAME="yobi-public-subnet"
readonly APP_NSG_NAME="yobi-app-nsg"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKEND_SET_NAME="yobi_ssh_backend_set"
readonly BACKEND_NAME="yobi_ssh_backend"
readonly LISTENER_NAME="yobi_ssh_listener"

for command in oci curl jq ssh shasum; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for guarded NLB deployment.\n' >&2; exit 1; }
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
vnic_nsg_ids="$(oci network vnic get \
  --profile "$PROFILE" --region "$REGION" --vnic-id "$vnic_id" \
  --query 'data."nsg-ids"' 2>/dev/null)" \
  || { printf 'Target VNIC NSG verification failed.\n' >&2; exit 1; }
jq -e --arg id "$app_nsg_id" 'index($id) != null' <<<"$vnic_nsg_ids" >/dev/null \
  || { printf 'Target VNIC is not attached to the application NSG.\n' >&2; exit 1; }
unset vnic_nsg_ids vnic_id app_nsg_vcn_id

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

nlb_count() {
  local payload
  payload="$(oci nlb network-load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --all 2>/dev/null)" || return 1
  jq -r '[.data.items[]? | select(."lifecycle-state" != "DELETED")] | length' \
    <<<"$payload"
}

nlb_name_count() {
  local payload
  payload="$(oci nlb network-load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_nlb_name" --all 2>/dev/null)" || return 1
  jq -r '[.data.items[]? | select(."lifecycle-state" != "DELETED")] | length' \
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

resolve_temp_nlb_id() {
  local payload
  payload="$(oci nlb network-load-balancer list \
    --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
    --display-name "$temp_nlb_name" --all 2>/dev/null)" || return 1
  jq -r '[.data.items[]? | select(."lifecycle-state" != "DELETED")][0].id // empty' \
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

wait_for_temp_nlb_id() {
  local candidate=""
  local _
  for _ in {1..12}; do
    candidate="$(resolve_temp_nlb_id 2>/dev/null || true)"
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
baseline_nlb_count="$(nlb_count)" \
  || { printf 'Initial NLB verification failed.\n' >&2; exit 1; }
[[ "$baseline_ssh_count" == "0" ]] \
  || { printf 'Guarded deployment requires initial TCP 22 ingress count zero.\n' >&2; exit 1; }
[[ "$baseline_http_count" == "1" ]] \
  || { printf 'Guarded deployment requires the existing single TCP 80 rule.\n' >&2; exit 1; }
[[ "$baseline_nlb_count" == "0" ]] \
  || { printf 'Guarded deployment requires no pre-existing network load balancer.\n' >&2; exit 1; }

resource_nonce="$(printf '%s:%s:%s' "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "$RANDOM" \
  | shasum -a 256 | awk '{print substr($1,1,12)}')"
readonly temp_nsg_name="yobi-ssh-nsg-${resource_nonce}"
readonly temp_nlb_name="yobi-ssh-nlb-${resource_nonce}"
temp_nsg_id=""
temp_nlb_id=""
app_rule_id=""
temp_nsg_create_started=false
app_rule_create_started=false
nlb_create_started=false

cleanup() {
  local command_status="$?"
  local final_ssh_count final_http_count final_nlb_count
  local temp_nsg_remaining temp_nlb_remaining
  local verification_attempt
  local cleanup_operation_warning=false
  local cleanup_verified=false
  trap - EXIT INT TERM

  if [[ "$temp_nsg_create_started" == "true" && -z "$temp_nsg_id" ]]; then
    temp_nsg_id="$(wait_for_temp_nsg_id 2>/dev/null || true)"
  fi
  if [[ "$nlb_create_started" == "true" && -z "$temp_nlb_id" ]]; then
    temp_nlb_id="$(wait_for_temp_nlb_id 2>/dev/null || true)"
  fi

  # Keep this order: remove the frontend first, then its only backend ingress,
  # then the temporary NSG which owns the frontend ingress/egress rules.
  if [[ "$nlb_create_started" == "true" && -n "$temp_nlb_id" ]]; then
    if ! oci nlb network-load-balancer delete \
      --profile "$PROFILE" --region "$REGION" \
      --network-load-balancer-id "$temp_nlb_id" --force \
      --wait-for-state SUCCEEDED --max-wait-seconds 900 \
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

  # OCI list/read APIs can lag a successful delete. Require the complete safe
  # state in one observation, but allow bounded convergence before declaring a
  # cleanup failure. Individual command errors are non-authoritative if the
  # independently queried final state is exact.
  # NLB and NSG list APIs can lag a successful delete for more than 55
  # seconds.  Require the same exact final state, but allow up to five minutes
  # for the read side to converge before declaring cleanup failure.
  for verification_attempt in {1..60}; do
    final_ssh_count="$(tcp_rule_count 22 2>/dev/null || true)"
    final_http_count="$(tcp_rule_count 80 2>/dev/null || true)"
    final_nlb_count="$(nlb_count 2>/dev/null || true)"
    temp_nlb_remaining="$(nlb_name_count 2>/dev/null || true)"
    temp_nsg_remaining="$(temp_nsg_name_count 2>/dev/null || true)"
    if [[ "$final_ssh_count" == "0" \
      && "$final_http_count" == "$baseline_http_count" \
      && "$final_nlb_count" == "$baseline_nlb_count" \
      && "$temp_nlb_remaining" == "0" \
      && "$temp_nsg_remaining" == "0" ]]; then
      cleanup_verified=true
      break
    fi
    (( verification_attempt < 60 )) && sleep 5
  done
  if [[ "$cleanup_verified" != "true" ]]; then
    printf 'CRITICAL: temporary NLB cleanup or final network verification failed.\n' >&2
    exit 1
  fi
  if [[ "$cleanup_operation_warning" == "true" ]]; then
    printf 'Cleanup commands reported a transient error; exact final network state was independently verified.\n' >&2
  fi
  printf 'Temporary NLB path removed; independently verified TCP 22=0, TCP 80 unchanged, and NLB count restored.\n'
  exit "$command_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

temp_nsg_create_started=true
if ! oci network nsg create \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --vcn-id "$vcn_id" --display-name "$temp_nsg_name" \
  --wait-for-state AVAILABLE --max-wait-seconds 300 \
  --wait-interval-seconds 5 >/dev/null 2>&1; then
  printf 'Temporary NLB NSG could not be created.\n' >&2
  exit 1
fi
temp_nsg_id="$(resolve_temp_nsg_id)" \
  || { printf 'Temporary NLB NSG lookup failed.\n' >&2; exit 1; }
[[ -n "$temp_nsg_id" ]] \
  || { printf 'Temporary NLB NSG identity could not be resolved.\n' >&2; exit 1; }

temp_nsg_rules="$(jq -cn --arg source "$source_cidr" --arg destination "$app_nsg_id" \
  '[
    {"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}},
    {"direction":"EGRESS","protocol":"6","destination":$destination,"destinationType":"NETWORK_SECURITY_GROUP","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}
  ]')"
if ! oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$temp_nsg_id" \
  --security-rules "$temp_nsg_rules" >/dev/null 2>&1; then
  printf 'Temporary NLB NSG rules could not be added.\n' >&2
  exit 1
fi
[[ "$(temp_nsg_total_rule_count)" == "2" \
  && "$(temp_nsg_rule_count INGRESS CIDR_BLOCK "$source_cidr" 443)" == "1" \
  && "$(temp_nsg_rule_count EGRESS NETWORK_SECURITY_GROUP "$app_nsg_id" 22)" == "1" ]] \
  || { printf 'Temporary NLB NSG does not contain the exact two-path rules.\n' >&2; exit 1; }

app_rule="$(jq -cn --arg source "$temp_nsg_id" \
  '[{"direction":"INGRESS","protocol":"6","source":$source,"sourceType":"NETWORK_SECURITY_GROUP","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]')"
app_rule_create_started=true
app_rule_result="$(oci network nsg rules add \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$app_nsg_id" \
  --security-rules "$app_rule" 2>/dev/null)" \
  || { printf 'Application NSG backend rule could not be added.\n' >&2; exit 1; }
app_rule_id="$(jq -r '.data."security-rules"[0].id // empty' <<<"$app_rule_result")"
unset app_rule_result app_rule temp_nsg_rules source_cidr
[[ -n "$app_rule_id" ]] \
  || { printf 'Application NSG rule identity could not be resolved.\n' >&2; exit 1; }
[[ "$(tcp_rule_count 22)" == "1" ]] \
  || { printf 'Temporary backend SSH rule is not exactly one rule.\n' >&2; exit 1; }
[[ "$(tcp_rule_count 80)" == "$baseline_http_count" ]] \
  || { printf 'Existing HTTP ingress changed during setup.\n' >&2; exit 1; }

nlb_nsg_ids="$(jq -cn --arg id "$temp_nsg_id" '[$id]')"
nlb_create_started=true
if ! oci nlb network-load-balancer create \
  --profile "$PROFILE" --region "$REGION" --compartment-id "$compartment_id" \
  --display-name "$temp_nlb_name" --subnet-id "$public_subnet_id" \
  --is-private false --is-preserve-source-destination false \
  --network-security-group-ids "$nlb_nsg_ids" \
  --wait-for-state SUCCEEDED --max-wait-seconds 900 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary public NLB could not be created.\n' >&2
  exit 1
fi
temp_nlb_id="$(resolve_temp_nlb_id)" \
  || { printf 'Temporary NLB lookup failed.\n' >&2; exit 1; }
[[ -n "$temp_nlb_id" && "$(nlb_name_count)" == "1" ]] \
  || { printf 'Temporary NLB identity was not unique.\n' >&2; exit 1; }

health_checker='{"protocol":"TCP","port":22,"intervalInMillis":10000,"timeoutInMillis":3000,"retries":3}'
if ! oci nlb backend-set create \
  --profile "$PROFILE" --region "$REGION" \
  --network-load-balancer-id "$temp_nlb_id" --name "$BACKEND_SET_NAME" \
  --policy FIVE_TUPLE --health-checker "$health_checker" \
  --is-preserve-source false --wait-for-state SUCCEEDED \
  --max-wait-seconds 600 --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary NLB backend set could not be created.\n' >&2
  exit 1
fi
if ! oci nlb backend create \
  --profile "$PROFILE" --region "$REGION" \
  --network-load-balancer-id "$temp_nlb_id" \
  --backend-set-name "$BACKEND_SET_NAME" --name "$BACKEND_NAME" \
  --target-id "$instance_id" --port 22 --is-backup false --is-drain false \
  --is-offline false --wait-for-state SUCCEEDED --max-wait-seconds 600 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary NLB backend could not be created.\n' >&2
  exit 1
fi
if ! oci nlb listener create \
  --profile "$PROFILE" --region "$REGION" \
  --network-load-balancer-id "$temp_nlb_id" --name "$LISTENER_NAME" \
  --default-backend-set-name "$BACKEND_SET_NAME" --protocol TCP --port 443 \
  --wait-for-state SUCCEEDED --max-wait-seconds 600 \
  --wait-interval-seconds 10 >/dev/null 2>&1; then
  printf 'Temporary NLB listener could not be created.\n' >&2
  exit 1
fi

nlb_details="$(oci nlb network-load-balancer get \
  --profile "$PROFILE" --region "$REGION" \
  --network-load-balancer-id "$temp_nlb_id" 2>/dev/null)" \
  || { printf 'Temporary NLB address lookup failed.\n' >&2; exit 1; }
nlb_host="$(jq -r '[.data."ip-addresses"[]? | select(."is-public" == true)][0]."ip-address" // empty' \
  <<<"$nlb_details")"
unset nlb_details nlb_nsg_ids health_checker public_subnet_id vcn_id
validate_ipv4 "$nlb_host" \
  || { printf 'Temporary NLB did not receive a public IPv4 address.\n' >&2; exit 1; }

backend_healthy=false
for _ in {1..60}; do
  backend_status="$(oci nlb backend-health get \
    --profile "$PROFILE" --region "$REGION" \
    --network-load-balancer-id "$temp_nlb_id" \
    --backend-set-name "$BACKEND_SET_NAME" --backend-name "$BACKEND_NAME" \
    --query 'data.status' --raw-output 2>/dev/null || true)"
  if [[ "$backend_status" == "OK" ]]; then
    backend_healthy=true
    break
  fi
  sleep 5
done
[[ "$backend_healthy" == "true" ]] \
  || { printf 'Temporary NLB backend did not become healthy.\n' >&2; exit 1; }

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
  if ssh_preflight_output="$(LC_ALL=C ssh -p 443 -i "$SSH_KEY" \
    -o BatchMode=yes -o ConnectionAttempts=1 -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new "$SSH_USER@$nlb_host" true 2>&1)"; then
    ssh_preflight_ok=true
    ssh_failure_category="NONE"
    break
  fi
  ssh_failure_category="$(classify_ssh_failure "$ssh_preflight_output")"
  (( preflight_attempt < 12 )) && sleep 5
done
unset ssh_preflight_output
if [[ "$ssh_preflight_ok" != "true" ]]; then
  printf 'Temporary NLB SSH preflight failed (category=%s).\n' \
    "$ssh_failure_category" >&2
  exit 1
fi

printf 'Temporary source-restricted TCP 443 SSH path is healthy; starting unchanged release workflow.\n'
export YOBI_GUARDED_SSH_WINDOW=1
export YOBI_GUARDED_NLB_WINDOW=1
export YOBI_GUARDED_SSH_HOST="$nlb_host"
export YOBI_GUARDED_SSH_PORT=443
if (( $# > 0 )); then
  (cd "$ROOT_DIR" && "$@")
else
  (cd "$ROOT_DIR" && make deploy)
fi

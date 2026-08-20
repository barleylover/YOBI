#!/usr/bin/env bash
set -euo pipefail

# Diagnose only the source-address mismatch for an already-created guarded
# LB/NLB TCP-443 frontend. The caller owns the frontend and its NSG. This
# helper only creates one short-lived FLOWLOG capture filter, log group, and
# VNIC service log per frontend VNIC. It never changes an NSG, LB, NLB, VNIC,
# route, subnet, instance, or SSH credential.
#
# The derived /32 is written only to an inherited file descriptor, and only
# after all helper-owned OCI resources have been independently verified gone.
# stdout/stderr contain sanitized state only; source addresses, other log
# fields, IPs, OCIDs, and request IDs are never printed.
#
# Contract for the guarded transport wrapper after a successful return:
#   1. read exactly one IPv4 /32 from --result-fd;
#   2. remove the old frontend ingress rule by its exact rule ID;
#   3. add exactly one stateful CIDR_BLOCK ingress rule for the returned /32
#      and TCP destination port 443;
#   4. prove the NSG still has only that ingress rule plus its existing exact
#      backend egress rule before retrying SSH.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"

transport=""
frontend_nsg_id=""
frontend_host=""
configured_source_cidr=""
result_fd=""

usage() {
  printf '%s\n' \
    'Usage: derive_source_cidr_with_temporary_flow_log.sh --transport lb|nlb --frontend-nsg-id OCID --frontend-host IPv4 --configured-source-cidr IPv4/32 --result-fd FD' >&2
}

while (( $# > 0 )); do
  case "$1" in
    --transport)
      (( $# >= 2 )) || { usage; exit 2; }
      transport="$2"
      shift 2
      ;;
    --frontend-nsg-id)
      (( $# >= 2 )) || { usage; exit 2; }
      frontend_nsg_id="$2"
      shift 2
      ;;
    --frontend-host)
      (( $# >= 2 )) || { usage; exit 2; }
      frontend_host="$2"
      shift 2
      ;;
    --configured-source-cidr)
      (( $# >= 2 )) || { usage; exit 2; }
      configured_source_cidr="$2"
      shift 2
      ;;
    --result-fd)
      (( $# >= 2 )) || { usage; exit 2; }
      result_fd="$2"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

for command in oci jq ssh shasum date; do
  command -v "$command" >/dev/null \
    || { printf 'A command required for the bounded flow-log probe is missing.\n' >&2; exit 1; }
done

validate_ipv4() {
  local value="$1"
  local first second third fourth octet
  [[ "$value" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || return 1
  IFS=. read -r first second third fourth <<<"$value"
  for octet in "$first" "$second" "$third" "$fourth"; do
    (( 10#$octet >= 0 && 10#$octet <= 255 )) || return 1
  done
}

[[ "$transport" == "lb" || "$transport" == "nlb" ]] \
  || { printf 'Flow-log probe transport must be lb or nlb.\n' >&2; exit 2; }
[[ "$frontend_nsg_id" =~ ^ocid1\.networksecuritygroup\.[A-Za-z0-9._-]+$ ]] \
  || { printf 'Flow-log probe frontend NSG identity is invalid.\n' >&2; exit 2; }
validate_ipv4 "$frontend_host" \
  || { printf 'Flow-log probe frontend address is not IPv4.\n' >&2; exit 2; }
[[ "$configured_source_cidr" =~ ^(.+)/32$ ]] \
  || { printf 'Configured source must be exactly one IPv4 /32.\n' >&2; exit 2; }
validate_ipv4 "${BASH_REMATCH[1]}" \
  || { printf 'Configured source /32 is invalid.\n' >&2; exit 2; }
[[ "$result_fd" =~ ^[3-9][0-9]*$ ]] \
  || { printf 'Result descriptor must be an inherited writable descriptor.\n' >&2; exit 2; }
if ! { true >&"$result_fd"; } 2>/dev/null; then
  printf 'Result descriptor is not writable.\n' >&2
  exit 2
fi

nsg_json="$(oci network nsg get \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$frontend_nsg_id" \
  2>/dev/null)" \
  || { printf 'Temporary frontend NSG verification failed.\n' >&2; exit 1; }
compartment_id="$(jq -r '.data."compartment-id" // empty' <<<"$nsg_json")"
frontend_nsg_name="$(jq -r '.data."display-name" // empty' <<<"$nsg_json")"
frontend_nsg_state="$(jq -r '.data."lifecycle-state" // empty' <<<"$nsg_json")"
unset nsg_json
[[ "$compartment_id" =~ ^ocid1\.compartment\.[A-Za-z0-9._-]+$ \
  && "$frontend_nsg_state" == "AVAILABLE" ]] \
  || { printf 'Temporary frontend NSG is not an available compartment resource.\n' >&2; exit 1; }
case "$transport:$frontend_nsg_name" in
  lb:yobi-ssh-lb-nsg-*) ;;
  nlb:yobi-ssh-nsg-*) ;;
  *)
    printf 'Frontend NSG does not match the guarded transport identity.\n' >&2
    exit 1
    ;;
esac
unset frontend_nsg_name frontend_nsg_state

nsg_rules_json="$(oci network nsg rules list \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$frontend_nsg_id" \
  --all 2>/dev/null)" \
  || { printf 'Temporary frontend NSG rule verification failed.\n' >&2; exit 1; }
ingress_match_count="$(jq -r --arg source "$configured_source_cidr" '
  [.data[]? | select(
    .direction == "INGRESS" and .protocol == "6" and
    ."source-type" == "CIDR_BLOCK" and .source == $source and
    ."is-stateless" == false and
    ."tcp-options"."destination-port-range".min == 443 and
    ."tcp-options"."destination-port-range".max == 443
  )] | length' <<<"$nsg_rules_json")"
egress_match_count="$(jq -r '
  [.data[]? | select(
    .direction == "EGRESS" and .protocol == "6" and
    ."destination-type" == "NETWORK_SECURITY_GROUP" and
    ."is-stateless" == false and
    ."tcp-options"."destination-port-range".min == 22 and
    ."tcp-options"."destination-port-range".max == 22
  )] | length' <<<"$nsg_rules_json")"
total_rule_count="$(jq -r '.data | length' <<<"$nsg_rules_json")"
unset nsg_rules_json
[[ "$total_rule_count" == "2" && "$ingress_match_count" == "1" \
  && "$egress_match_count" == "1" ]] \
  || { printf 'Temporary frontend NSG is not the exact guarded two-rule path.\n' >&2; exit 1; }
unset total_rule_count ingress_match_count egress_match_count

frontend_vnics_json="$(oci network nsg vnics list \
  --profile "$PROFILE" --region "$REGION" --nsg-id "$frontend_nsg_id" \
  --all 2>/dev/null)" \
  || { printf 'Temporary frontend VNIC lookup failed.\n' >&2; exit 1; }
frontend_vnic_ids=()
while IFS= read -r candidate_vnic_id; do
  [[ -n "$candidate_vnic_id" ]] || continue
  [[ "$candidate_vnic_id" =~ ^ocid1\.vnic\.[A-Za-z0-9._-]+$ ]] \
    || { printf 'Temporary frontend VNIC identity is invalid.\n' >&2; exit 1; }
  vnic_json="$(oci network vnic get \
    --profile "$PROFILE" --region "$REGION" --vnic-id "$candidate_vnic_id" \
    2>/dev/null)" \
    || { printf 'Temporary frontend VNIC verification failed.\n' >&2; exit 1; }
  jq -e --arg nsg "$frontend_nsg_id" '
    .data."lifecycle-state" == "AVAILABLE" and
    (.data."nsg-ids" | index($nsg) != null)' \
    <<<"$vnic_json" >/dev/null \
    || { printf 'Temporary frontend VNIC is not attached to the guarded NSG.\n' >&2; exit 1; }
  unset vnic_json
  frontend_vnic_ids+=("$candidate_vnic_id")
done < <(jq -r '[.data[]?."vnic-id"] | unique[]?' <<<"$frontend_vnics_json")
unset frontend_vnics_json candidate_vnic_id
(( ${#frontend_vnic_ids[@]} >= 1 && ${#frontend_vnic_ids[@]} <= 4 )) \
  || { printf 'Guarded frontend must resolve to between one and four exact VNICs.\n' >&2; exit 1; }

resource_nonce="$(printf '%s:%s:%s' "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "$RANDOM" \
  | shasum -a 256 | awk '{print substr($1,1,12)}')"
readonly capture_filter_name="yobi-flow-source-filter-${resource_nonce}"
readonly log_group_name="yobi-flow-source-group-${resource_nonce}"
readonly log_name_prefix="yobi-flow-source-log-${resource_nonce}"

capture_filter_id=""
log_group_id=""
log_ids=()
log_names=()
capture_filter_create_started=false
log_group_create_started=false
log_create_started=false
cleanup_completed=false
cleanup_in_progress=false

capture_filter_name_count() {
  local payload
  payload="$(oci network capture-filter list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --display-name "$capture_filter_name" \
    --filter-type FLOWLOG --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '.data | length' <<<"$payload"
}

resolve_capture_filter_id() {
  local payload count
  payload="$(oci network capture-filter list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --display-name "$capture_filter_name" \
    --filter-type FLOWLOG --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  count="$(jq '[.data[]? | select(."lifecycle-state" != "TERMINATED")] | length' \
    <<<"$payload")"
  [[ "$count" == "1" ]] || return 1
  jq -r '[.data[] | select(."lifecycle-state" != "TERMINATED")][0].id' \
    <<<"$payload"
}

log_group_name_count() {
  local payload
  payload="$(oci logging log-group list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --display-name "$log_group_name" \
    --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '.data | length' <<<"$payload"
}

resolve_log_group_id() {
  local payload count
  payload="$(oci logging log-group list \
    --profile "$PROFILE" --region "$REGION" \
    --compartment-id "$compartment_id" --display-name "$log_group_name" \
    --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  count="$(jq '[.data[]? | select(."lifecycle-state" != "DELETING")] | length' \
    <<<"$payload")"
  [[ "$count" == "1" ]] || return 1
  jq -r '[.data[] | select(."lifecycle-state" != "DELETING")][0].id' \
    <<<"$payload"
}

log_name_count() {
  local name="$1"
  local payload
  [[ -n "$log_group_id" ]] || return 1
  payload="$(oci logging log list \
    --profile "$PROFILE" --region "$REGION" --log-group-id "$log_group_id" \
    --display-name "$name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  jq -r '.data | length' <<<"$payload"
}

resolve_log_id() {
  local name="$1"
  local payload count
  [[ -n "$log_group_id" ]] || return 1
  payload="$(oci logging log list \
    --profile "$PROFILE" --region "$REGION" --log-group-id "$log_group_id" \
    --display-name "$name" --all 2>/dev/null)" || return 1
  [[ -n "$payload" ]] || payload='{"data":[]}'
  count="$(jq '[.data[]? | select(."lifecycle-state" != "DELETING")] | length' \
    <<<"$payload")"
  [[ "$count" == "1" ]] || return 1
  jq -r '[.data[] | select(."lifecycle-state" != "DELETING")][0].id' \
    <<<"$payload"
}

cleanup_resources() {
  local operation_warning=false
  local cleanup_verified=false
  local attempt name log_id remaining_logs
  cleanup_in_progress=true
  # Once teardown starts, defer ordinary interrupts until helper-owned
  # resources have reached an independently proven absent state.
  trap '' INT TERM
  set +e

  if [[ "$log_group_create_started" == "true" && -z "$log_group_id" ]]; then
    for attempt in {1..60}; do
      log_group_id="$(resolve_log_group_id 2>/dev/null || true)"
      [[ -n "$log_group_id" ]] && break
      (( attempt < 60 )) && sleep 5
    done
  fi
  if [[ "$capture_filter_create_started" == "true" && -z "$capture_filter_id" ]]; then
    for attempt in {1..60}; do
      capture_filter_id="$(resolve_capture_filter_id 2>/dev/null || true)"
      [[ -n "$capture_filter_id" ]] && break
      (( attempt < 60 )) && sleep 5
    done
  fi

  if [[ "$log_create_started" == "true" && -n "$log_group_id" ]]; then
    for name in "${log_names[@]}"; do
      log_id="$(resolve_log_id "$name" 2>/dev/null || true)"
      if [[ -n "$log_id" ]]; then
        oci logging log delete \
          --profile "$PROFILE" --region "$REGION" \
          --log-group-id "$log_group_id" --log-id "$log_id" --force \
          --wait-for-state SUCCEEDED --max-wait-seconds 300 \
          --wait-interval-seconds 5 >/dev/null 2>&1 \
          || operation_warning=true
      fi
    done

    for attempt in {1..60}; do
      remaining_logs=0
      for name in "${log_names[@]}"; do
        name_count="$(log_name_count "$name" 2>/dev/null || true)"
        [[ "$name_count" =~ ^[0-9]+$ ]] \
          || { remaining_logs=-1; break; }
        remaining_logs=$((remaining_logs + name_count))
      done
      [[ "$remaining_logs" == "0" ]] && break
      (( attempt < 60 )) && sleep 5
    done
    [[ "$remaining_logs" == "0" ]] || operation_warning=true
  fi

  if [[ "$log_group_create_started" == "true" && -n "$log_group_id" ]]; then
    oci logging log-group delete \
      --profile "$PROFILE" --region "$REGION" \
      --log-group-id "$log_group_id" --force \
      --wait-for-state SUCCEEDED --max-wait-seconds 300 \
      --wait-interval-seconds 5 >/dev/null 2>&1 \
      || operation_warning=true
  fi
  if [[ "$capture_filter_create_started" == "true" && -n "$capture_filter_id" ]]; then
    oci network capture-filter delete \
      --profile "$PROFILE" --region "$REGION" \
      --capture-filter-id "$capture_filter_id" --force \
      --wait-for-state TERMINATED --max-wait-seconds 300 \
      --wait-interval-seconds 5 >/dev/null 2>&1 \
      || operation_warning=true
  fi

  for attempt in {1..60}; do
    final_group_count="$(log_group_name_count 2>/dev/null || true)"
    final_filter_count="$(capture_filter_name_count 2>/dev/null || true)"
    if [[ "$final_group_count" == "0" && "$final_filter_count" == "0" ]]; then
      cleanup_verified=true
      break
    fi
    (( attempt < 60 )) && sleep 5
  done

  set -e
  cleanup_in_progress=false
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [[ "$cleanup_verified" != "true" ]]; then
    printf 'CRITICAL: temporary flow-log diagnostic cleanup could not be proven.\n' >&2
    return 1
  fi
  cleanup_completed=true
  if [[ "$operation_warning" == "true" ]]; then
    printf 'Flow-log cleanup commands reported a transient error; exact absence was independently verified.\n' >&2
  fi
  printf 'Temporary flow-log diagnostic resources were removed and independently verified absent.\n'
}

on_exit() {
  local command_status="$?"
  trap - EXIT INT TERM
  if [[ "$cleanup_completed" != "true" && "$cleanup_in_progress" != "true" ]]; then
    if ! cleanup_resources; then
      exit 96
    fi
  fi
  exit "$command_status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$(capture_filter_name_count)" == "0" ]] \
  || { printf 'Flow-log diagnostic capture-filter name is not unique.\n' >&2; exit 1; }
[[ "$(log_group_name_count)" == "0" ]] \
  || { printf 'Flow-log diagnostic log-group name is not unique.\n' >&2; exit 1; }

capture_rules='[{"flowLogType":"REJECT","isEnabled":true,"priority":0,"protocol":"6","ruleAction":"INCLUDE","samplingRate":1,"sourceCidr":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":443,"max":443}}}]'
capture_filter_create_started=true
if ! oci network capture-filter create \
  --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --filter-type FLOWLOG \
  --display-name "$capture_filter_name" \
  --flow-log-capture-filter-rules "$capture_rules" \
  --wait-for-state AVAILABLE --max-wait-seconds 300 \
  --wait-interval-seconds 5 >/dev/null 2>&1; then
  printf 'Temporary flow-log capture filter could not be created.\n' >&2
  exit 1
fi
unset capture_rules
capture_filter_id="$(resolve_capture_filter_id)" \
  || { printf 'Temporary flow-log capture-filter identity was not unique.\n' >&2; exit 1; }
[[ -n "$capture_filter_id" ]] \
  || { printf 'Temporary flow-log capture-filter identity was unavailable.\n' >&2; exit 1; }

log_group_create_started=true
if ! oci logging log-group create \
  --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$log_group_name" \
  --description 'Short-lived guarded SSH source diagnosis' \
  --wait-for-state SUCCEEDED --max-wait-seconds 300 \
  --wait-interval-seconds 5 >/dev/null 2>&1; then
  printf 'Temporary flow-log group could not be created.\n' >&2
  exit 1
fi
log_group_id="$(resolve_log_group_id)" \
  || { printf 'Temporary flow-log group identity was not unique.\n' >&2; exit 1; }
[[ -n "$log_group_id" ]] \
  || { printf 'Temporary flow-log group identity was unavailable.\n' >&2; exit 1; }

log_create_started=true
vnic_index=0
for frontend_vnic_id in "${frontend_vnic_ids[@]}"; do
  vnic_index=$((vnic_index + 1))
  log_name="${log_name_prefix}-${vnic_index}"
  log_names+=("$log_name")
  log_configuration="$(jq -cn \
    --arg compartment "$compartment_id" \
    --arg resource "$frontend_vnic_id" \
    --arg capture_filter "$capture_filter_id" \
    '{compartmentId:$compartment,source:{sourceType:"OCISERVICE",service:"flowlogs",resource:$resource,category:"vnic",parameters:{capture_filter:$capture_filter}}}')"
  if ! oci logging log create \
    --profile "$PROFILE" --region "$REGION" \
    --log-group-id "$log_group_id" --display-name "$log_name" \
    --log-type SERVICE --is-enabled true --retention-duration 30 \
    --configuration "$log_configuration" \
    --wait-for-state SUCCEEDED --max-wait-seconds 300 \
    --wait-interval-seconds 5 >/dev/null 2>&1; then
    printf 'Temporary VNIC flow log could not be created.\n' >&2
    exit 1
  fi
  log_id="$(resolve_log_id "$log_name")" \
    || { printf 'Temporary VNIC flow-log identity was not unique.\n' >&2; exit 1; }
  [[ -n "$log_id" ]] \
    || { printf 'Temporary VNIC flow-log identity was unavailable.\n' >&2; exit 1; }
  log_ids+=("$log_id")
  unset log_configuration log_id
done
unset frontend_vnic_id frontend_vnic_ids vnic_index log_name

search_start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
search_streams=""
for log_id in "${log_ids[@]}"; do
  if [[ -n "$search_streams" ]]; then
    search_streams+=", "
  fi
  search_streams+="\"${compartment_id}/${log_group_id}/${log_id}\""
done
search_query="search ${search_streams} | where data.status = 'OK' and data.action = 'REJECT' and data.protocol = 6 and data.destinationPort = 443 | sort by datetime desc"
derived_source_ip=""
for probe_attempt in {1..18}; do
  for _ in {1..2}; do
    LC_ALL=C ssh -p 443 \
      -o BatchMode=yes -o PreferredAuthentications=none \
      -o ConnectionAttempts=1 -o ConnectTimeout=7 \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o LogLevel=QUIET "yobi-flow-probe@${frontend_host}" true \
      >/dev/null 2>&1 || true
  done
  sleep 20
  search_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  search_payload="$(oci logging-search search-logs \
    --profile "$PROFILE" --region "$REGION" \
    --time-start "$search_start" --time-end "$search_end" \
    --search-query "$search_query" --is-return-field-info false --limit 100 \
    2>/dev/null || true)"
  [[ -n "$search_payload" ]] || search_payload='{"data":{"results":[]}}'
  unique_sources="$(jq -c '
    [.data.results[]?.data.logContent.data? |
      select(.status == "OK" and .action == "REJECT" and
        .protocol == 6 and .destinationPort == 443) |
      .sourceAddress |
      select(type == "string")] |
    unique' <<<"$search_payload" 2>/dev/null || printf '[]')"
  unset search_payload
  source_count="$(jq 'length' <<<"$unique_sources")"
  if (( source_count > 1 )); then
    printf 'Flow-log probe observed more than one candidate source; refusing an ambiguous rule.\n' >&2
    exit 1
  fi
  if [[ "$source_count" == "1" ]]; then
    derived_source_ip="$(jq -r '.[0]' <<<"$unique_sources")"
    break
  fi
done
unset search_start search_end search_query search_streams unique_sources source_count probe_attempt

validate_ipv4 "$derived_source_ip" \
  || { printf 'Flow-log probe did not resolve exactly one valid IPv4 source.\n' >&2; exit 1; }
derived_source_cidr="${derived_source_ip}/32"
[[ "$derived_source_cidr" != "$configured_source_cidr" ]] \
  || { printf 'Flow-log source matches the configured /32; source mismatch is not proven.\n' >&2; exit 1; }

# Cleanup is deliberately completed before the only sensitive result leaves
# this process. A cleanup failure exits nonzero and writes nothing to the FD.
cleanup_resources \
  || { printf 'Flow-log probe result withheld because cleanup was not proven.\n' >&2; exit 96; }
printf '%s\n' "$derived_source_cidr" >&"$result_fd"
unset derived_source_ip derived_source_cidr configured_source_cidr frontend_host
printf 'Exactly one different rejected TCP-443 source was derived for guarded retry.\n'

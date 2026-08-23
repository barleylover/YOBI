#!/usr/bin/env bash
set -euo pipefail

# Invoke the installed rollback through the same read-only OCI target discovery as
# deploy.sh. Keep the resolved public address and OCI identifiers out of output.

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly GUARDED_SSH_HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly GUARDED_SSH_PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly GUARDED_SSH_KNOWN_HOSTS_FILE="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly GUARDED_SSH_CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"

for command in oci ssh; do
  command -v "$command" >/dev/null \
    || { printf 'Missing command required for rollback.\n' >&2; exit 1; }
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
ssh_host_key_options=(-o StrictHostKeyChecking=accept-new)
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
ssh_port=22
if [[ -n "$GUARDED_SSH_HOST" ]]; then
  host="$GUARDED_SSH_HOST"
  ssh_port="$GUARDED_SSH_PORT"
else
  host="$(oci compute instance list-vnics \
    --profile "$PROFILE" --region "$REGION" --instance-id "$instance_id" \
    --query 'data[0]."public-ip"' --raw-output 2>/dev/null)" \
    || { printf 'Target network lookup failed.\n' >&2; exit 1; }
  [[ -n "$host" && "$host" != "null" ]] \
    || { printf 'Target address was unavailable.\n' >&2; exit 1; }
fi
readonly host ssh_port

if ! ssh -t -q -p "$ssh_port" -i "$SSH_KEY" -o LogLevel=ERROR \
  -o ConnectTimeout=20 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
  "${ssh_host_key_options[@]}" "${ssh_connection_options[@]}" \
  "$SSH_USER@$host" \
  "sudo -n /opt/yobi/current/deploy/rollback.sh" 2>/dev/null; then
  printf 'Remote rollback failed; inspect the guarded operator session.\n' >&2
  exit 1
fi
printf 'Remote rollback completed and its built-in health/readiness verification passed.\n'

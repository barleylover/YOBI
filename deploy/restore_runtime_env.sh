#!/usr/bin/env bash
set +x
set -euo pipefail

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"

adb_tls_dsn=''
yobi_app_password=''
oci_genai_api_key=''
demo_control_token=''

clear_secrets() {
  adb_tls_dsn=''
  yobi_app_password=''
  oci_genai_api_key=''
  demo_control_token=''
  unset adb_tls_dsn yobi_app_password oci_genai_api_key demo_control_token
}

abort_on_signal() {
  clear_secrets
  exit 130
}

trap clear_secrets EXIT
trap abort_on_signal HUP INT TERM

for command_name in oci ssh; do
  command -v "$command_name" >/dev/null || {
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  }
done
[[ -f "$SSH_KEY" ]] || {
  printf 'SSH key file was not found.\n' >&2
  exit 1
}
[[ -r /dev/tty && -w /dev/tty ]] || {
  printf 'A local interactive terminal is required.\n' >&2
  exit 1
}

read_secret() {
  local target_name="$1"
  local prompt="$2"
  local value=''
  IFS= read -r -s -p "$prompt" value </dev/tty
  printf '\n' >/dev/tty
  if [[ -z "$value" ]]; then
    printf 'A required value was empty; no file was written.\n' >&2
    exit 1
  fi
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    printf 'A required value contained an unsupported control character.\n' >&2
    exit 1
  fi
  printf -v "$target_name" '%s' "$value"
  value=''
}

read_secret adb_tls_dsn 'ADB TLS DSN: '
read_secret yobi_app_password 'YOBI_APP password: '
read_secret oci_genai_api_key 'OCI Generative AI API Key Secret: '
read_secret demo_control_token 'Demo control token: '

quote_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

emit_runtime_env() {
  # This file is data for systemd/python-dotenv. Never shell-source or eval its values;
  # deployment subprocesses must use deploy/run_with_runtime_env.py.
  printf 'APP_ENV="production"\n'
  printf 'APP_BASE_URL="http://127.0.0.1"\n'
  printf 'DEMO_MODE="true"\n'
  printf 'DEMO_FALLBACK_ENABLED="true"\n'
  printf 'DEMO_DB_BACKEND="oracle"\n'
  printf '%s\n' \
    'OCI_GENAI_BASE_URL="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1"'
  printf 'OCI_GENAI_API_KEY='; quote_env_value "$oci_genai_api_key"; printf '\n'
  printf 'OCI_GENAI_MODEL="xai.grok-4.3"\n'
  printf 'OCI_GENAI_FALLBACK_MODEL="openai.gpt-oss-120b"\n'
  printf 'OCI_GENAI_STRUCTURED_OUTPUT_ENABLED="false"\n'
  printf 'OCI_GENAI_STREAMING_ENABLED="false"\n'
  printf 'OCI_GENAI_ADMISSION_CONTROL_ENABLED="true"\n'
  printf 'OCI_GENAI_MAX_CONCURRENT_REQUESTS_PER_MODEL="1"\n'
  printf 'OCI_GENAI_MIN_INTERVAL_SECONDS="2"\n'
  printf 'OCI_GENAI_RATE_LIMIT_COOLDOWN_SECONDS="65"\n'
  printf 'RESTAURANT_NOTE_MODEL="openai.gpt-oss-20b"\n'
  printf '%s\n' \
    'RESTAURANT_NOTE_MODEL_CHAIN="google.gemini-2.5-flash-lite,google.gemini-2.5-flash,openai.gpt-oss-20b,openai.gpt-oss-120b"'
  printf 'STRUCTURED_RECOMMENDATION_MODEL="xai.grok-4.3"\n'
  printf 'STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS="2048"\n'
  printf 'STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS="2"\n'
  printf 'RECOMMENDATION_CANDIDATE_LIMIT="100"\n'
  printf 'RECOMMENDATION_LLM_SHORTLIST_LIMIT="15"\n'
  printf 'RECOMMENDATION_LLM_PASSAGES_PER_MENU="2"\n'
  printf 'RECOMMENDATION_LLM_SELECTION_ENABLED="true"\n'
  printf 'OCI_GENAI_MAX_INPUT_TOKENS="131072"\n'
  printf 'OCI_GENAI_MAX_OUTPUT_TOKENS="8192"\n'
  printf 'OCI_EMBED_MODEL="cohere.embed-v4.0"\n'
  printf 'OCI_EMBED_DIMENSION="1536"\n'
  printf 'OCI_EMBED_AUTH="instance_principal"\n'
  printf 'OCI_COMPARTMENT_ID='; quote_env_value "$compartment_id"; printf '\n'
  printf 'EMBEDDING_PROVIDER="oci"\n'
  printf 'ADB_DSN='; quote_env_value "$adb_tls_dsn"; printf '\n'
  printf 'DB_USERNAME="YOBI_APP"\n'
  printf 'DB_PASSWORD='; quote_env_value "$yobi_app_password"; printf '\n'
  printf 'LLM_TIMEOUT_SECONDS="120"\n'
  printf 'LLM_MAX_RETRIES="0"\n'
  printf 'LLM_MAX_INPUT_TOKENS="131072"\n'
  printf 'LLM_MAX_OUTPUT_TOKENS="4096"\n'
  printf 'TOOL_CALL_MAX_STEPS="6"\n'
  printf 'MAX_UPLOAD_MB="8"\n'
  printf 'ADDRESS_OCR_PROVIDER="fixture"\n'
  printf 'LOG_LEVEL="INFO"\n'
  printf 'DEMO_CONTROL_TOKEN='; quote_env_value "$demo_control_token"; printf '\n'
}

compartment_id="$(oci iam compartment list \
  --profile "$PROFILE" \
  --region "$REGION" \
  --all \
  --compartment-id-in-subtree true \
  --query "data[?name=='HACK-TEAM-05' && \"lifecycle-state\"=='ACTIVE'].id | [0]" \
  --raw-output)"
[[ -n "$compartment_id" && "$compartment_id" != 'null' ]] || {
  printf 'Target compartment was not resolved.\n' >&2
  exit 1
}

instance_id="$(oci compute instance list \
  --profile "$PROFILE" \
  --region "$REGION" \
  --compartment-id "$compartment_id" \
  --display-name yobi-app-01 \
  --lifecycle-state RUNNING \
  --query 'data[0].id' \
  --raw-output)"
[[ -n "$instance_id" && "$instance_id" != 'null' ]] || {
  printf 'Running YOBI VM was not resolved.\n' >&2
  exit 1
}

host="$(oci compute instance list-vnics \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-id "$instance_id" \
  --query 'data[0]."public-ip"' \
  --raw-output)"
[[ -n "$host" && "$host" != 'null' ]] || {
  printf 'YOBI VM network endpoint was not resolved.\n' >&2
  exit 1
}

remote_script=''
read -r -d '' remote_script <<'REMOTE_SCRIPT' || true
set -euo pipefail

target=/etc/yobi/yobi.env
temporary=''

cleanup_temporary() {
  if [[ -n "$temporary" && -e "$temporary" ]]; then
    rm -f -- "$temporary"
  fi
}

abort_on_signal() {
  cleanup_temporary
  exit 130
}

trap cleanup_temporary EXIT
trap abort_on_signal HUP INT TERM

install -d -o root -g root -m 0755 /etc/yobi
umask 077
temporary="$(mktemp /etc/yobi/.yobi.env.restore.XXXXXX)"
chown root:root "$temporary"
chmod 0600 "$temporary"
cat >"$temporary"

required=(
  APP_ENV APP_BASE_URL DEMO_MODE DEMO_FALLBACK_ENABLED DEMO_DB_BACKEND
  OCI_GENAI_BASE_URL OCI_GENAI_API_KEY OCI_GENAI_MODEL OCI_GENAI_FALLBACK_MODEL
  OCI_GENAI_ADMISSION_CONTROL_ENABLED OCI_GENAI_MAX_CONCURRENT_REQUESTS_PER_MODEL
  OCI_GENAI_MIN_INTERVAL_SECONDS OCI_GENAI_RATE_LIMIT_COOLDOWN_SECONDS
  RESTAURANT_NOTE_MODEL RESTAURANT_NOTE_MODEL_CHAIN
  STRUCTURED_RECOMMENDATION_MODEL STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS
  STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS
  RECOMMENDATION_LLM_PASSAGES_PER_MENU
  OCI_GENAI_MAX_INPUT_TOKENS OCI_GENAI_MAX_OUTPUT_TOKENS
  OCI_EMBED_MODEL OCI_EMBED_DIMENSION OCI_EMBED_AUTH OCI_COMPARTMENT_ID
  EMBEDDING_PROVIDER ADB_DSN DB_USERNAME DB_PASSWORD
  LLM_TIMEOUT_SECONDS LLM_MAX_RETRIES LLM_MAX_INPUT_TOKENS LLM_MAX_OUTPUT_TOKENS
  TOOL_CALL_MAX_STEPS MAX_UPLOAD_MB
  ADDRESS_OCR_PROVIDER LOG_LEVEL DEMO_CONTROL_TOKEN
)
missing=()
empty=()
duplicate=()
for key in "${required[@]}"; do
  count="$(grep -c "^${key}=" "$temporary" || true)"
  if [[ "$count" -eq 0 ]]; then
    missing+=("$key")
    continue
  fi
  if [[ "$count" -ne 1 ]]; then
    duplicate+=("$key")
    continue
  fi
  line="$(grep -m 1 "^${key}=" "$temporary")"
  encoded_value="${line#*=}"
  if [[ -z "$encoded_value" || "$encoded_value" == '""' ]]; then
    empty+=("$key")
  fi
done

if [[ "${#missing[@]}" -ne 0 || "${#empty[@]}" -ne 0 || "${#duplicate[@]}" -ne 0 ]]; then
  printf 'runtime_env=not_written\n'
  printf 'missing_required_variables=%s\n' "$(IFS=,; printf '%s' "${missing[*]:-none}")"
  printf 'empty_required_variables=%s\n' "$(IFS=,; printf '%s' "${empty[*]:-none}")"
  printf 'duplicate_required_variables=%s\n' "$(IFS=,; printf '%s' "${duplicate[*]:-none}")"
  exit 1
fi

grep -qx 'DB_USERNAME="YOBI_APP"' "$temporary" || {
  printf 'runtime_env=not_written\n'
  printf 'DB_USERNAME=invalid\n'
  exit 1
}

sync "$temporary"
mv -f -- "$temporary" "$target"
temporary=''

owner="$(stat -c '%U' "$target")"
group="$(stat -c '%G' "$target")"
mode="$(stat -c '%a' "$target")"
[[ "$owner" == root && "$group" == root && "$mode" == 600 ]] || {
  printf 'runtime_env=present_but_metadata_invalid\n'
  printf 'owner=%s\n' "$owner"
  printf 'group=%s\n' "$group"
  printf 'mode=%s\n' "$mode"
  exit 1
}

printf 'runtime_env=present\n'
printf 'owner=%s\n' "$owner"
printf 'group=%s\n' "$group"
printf 'mode=%s\n' "$mode"
for key in "${required[@]}"; do
  printf 'variable_%s=present\n' "$key"
done
printf 'empty_required_variables=none\n'
REMOTE_SCRIPT

printf -v quoted_remote_script '%q' "$remote_script"
if ! emit_runtime_env | ssh \
  -i "$SSH_KEY" \
  -o BatchMode=yes \
  -o LogLevel=ERROR \
  -o StrictHostKeyChecking=accept-new \
  "$SSH_USER@$host" \
  "sudo -n bash -c $quoted_remote_script"; then
  printf 'Runtime environment restoration failed; secret values were not printed.\n' >&2
  exit 1
fi

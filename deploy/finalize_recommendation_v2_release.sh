#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_RELEASE_ID="${1:-}"
readonly EVIDENCE_PATH="${2:-}"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly HOST="${YOBI_GUARDED_SSH_HOST:-}"
readonly PORT="${YOBI_GUARDED_SSH_PORT:-}"
readonly KNOWN_HOSTS="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"
readonly CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"

for command in ssh shasum python3; do
  command -v "$command" >/dev/null \
    || { printf 'Missing finalization command.\n' >&2; exit 1; }
done
[[ "$EXPECTED_RELEASE_ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]] \
  || { printf 'Expected release ID is invalid.\n' >&2; exit 1; }
[[ -f "$EVIDENCE_PATH" && ! -L "$EVIDENCE_PATH" ]] \
  || { printf 'Recommendation-v2 evidence is unavailable.\n' >&2; exit 1; }
[[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_NLB_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_LB_WINDOW:-}" == "1" \
  && "$PORT" == "443" && -n "$HOST" \
  && -f "$KNOWN_HOSTS" && ! -L "$KNOWN_HOSTS" \
  && -S "$CONTROL_PATH" && ! -L "$CONTROL_PATH" ]] \
  || { printf 'Finalization requires the guarded LB SSH transport.\n' >&2; exit 1; }

evidence_identity="$({
python3 - "$EVIDENCE_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_names = [
    "postdeploy_spicy_noodles_ko",
    "postdeploy_crispy_chicken_fried_en",
    "postdeploy_clean_mild_soup_hot_ko",
    "postdeploy_italian_noodles_10k_19k_en",
    "postdeploy_sweet_frozen_dessert_ko",
]
cases = payload.get("cases")
latency = payload.get("latency")
release = payload.get("release")
database = release.get("database") if isinstance(release, dict) else None
application = release.get("application") if isinstance(release, dict) else None
family_id = (
    database.get("recommendation_release_family_id")
    if isinstance(database, dict)
    else None
)
valid = (
    payload.get("schema_version") == "1"
    and payload.get("gate") == "recommendation-v2-postdeploy-five"
    and payload.get("status") == "PASS"
    and payload.get("requested") == 5
    and payload.get("executed") == 5
    and payload.get("provider_call_count") == 5
    and payload.get("provider_retry_count") == 0
    and payload.get("dispatch_interval_seconds") == 60
    and isinstance(application, dict)
    and application.get("release_id") is not None
    and payload.get("run_id") == f"postdeploy-{application.get('release_id')}"
    and payload.get("preflight_error_codes") == []
    and payload.get("failure_action") == "FINALIZE_ZERO_CALL"
    and isinstance(latency, dict)
    and latency.get("percentile_claim") == "not_made_for_five_samples"
    and isinstance(latency.get("median_ms"), (int, float))
    and float(latency["median_ms"]) <= 8000
    and isinstance(latency.get("max_ms"), (int, float))
    and float(latency["max_ms"]) <= 10000
    and isinstance(cases, list)
    and [case.get("name") for case in cases] == expected_names
    and all(
        case.get("status") == "PASS"
        and case.get("error_codes") == []
        and case.get("dispatch_count") == 1
        and case.get("ledger_status") == "COMPLETED"
        and case.get("selection_status") == "GROK_SELECTED"
        and case.get("fallback_reason") is None
        and case.get("shortlist_count") == 15
        and case.get("result_count") == 3
        and case.get("merchant_count") == 3
        and case.get("matched_group_count_min") == case.get("required_group_count")
        for case in cases
    )
    and isinstance(family_id, str)
    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", family_id)
)
if not valid:
    raise SystemExit("RECOMMENDATION_V2_FIVE_EVIDENCE_INVALID")
print(f"{family_id}\t{application.get('release_id')}")
PY
})"
IFS=$'\t' read -r expected_family_id evidence_release_id <<< "$evidence_identity"
readonly EXPECTED_FAMILY_ID="$expected_family_id"
readonly EVIDENCE_RELEASE_ID="$evidence_release_id"
unset evidence_identity expected_family_id evidence_release_id
[[ "$EVIDENCE_RELEASE_ID" == "$EXPECTED_RELEASE_ID" ]] \
  || { printf 'Recommendation-v2 evidence belongs to another release.\n' >&2; exit 1; }

readonly EVIDENCE_SHA256="$(shasum -a 256 "$EVIDENCE_PATH" | awk '{print $1}')"
[[ "$EVIDENCE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { printf 'Recommendation-v2 evidence checksum is invalid.\n' >&2; exit 1; }

# This remote finalizer performs health/readiness reads and marker writes only.
# It never invokes the recommendation API or any model provider.
ssh -T -q -p "$PORT" -i "$SSH_KEY" \
  -o LogLevel=ERROR -o ConnectTimeout=20 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
  -o "UserKnownHostsFile=${KNOWN_HOSTS}" -o StrictHostKeyChecking=yes \
  -o ControlMaster=no -o "ControlPath=${CONTROL_PATH}" -o ControlPersist=no \
  "$SSH_USER@$HOST" \
  "sudo -n bash -s -- '$EXPECTED_RELEASE_ID' '$EXPECTED_FAMILY_ID' '$EVIDENCE_SHA256'" <<'REMOTE'
set -euo pipefail
release_id="$1"
expected_family_id="$2"
evidence_sha256="$3"
release_path="/opt/yobi/releases/$release_id"
ready_marker="$release_path/.yobi-release-ready"
provisional_marker="$release_path/.yobi-release-provisional"
final_marker="$release_path/.yobi-release-recommendation-v2-final"
[[ "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ \
  && "$expected_family_id" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$ \
  && "$evidence_sha256" =~ ^[0-9a-f]{64}$ \
  && -d "$release_path" && ! -L "$release_path" \
  && "$(readlink -f /opt/yobi/current)" == "$release_path" \
  && -f "$ready_marker" && ! -L "$ready_marker" \
  && "$(stat -c '%U:%G:%a' "$ready_marker")" == "root:yobi:644" \
  && -f "$provisional_marker" && ! -L "$provisional_marker" \
  && "$(cat "$provisional_marker")" == "recommendation-v2-five=pending" ]] \
  || { printf 'Active recommendation-v2 provisional identity is invalid.\n' >&2; exit 1; }

runtime_env_runner=(
  "$release_path/venv/bin/python"
  "$release_path/deploy/run_with_runtime_env.py"
  /etc/yobi/yobi.env
)
active_family_id="$(sudo env PYTHONPATH="$release_path/backend:$release_path" \
  "${runtime_env_runner[@]}" "$release_path/venv/bin/python" \
  "$release_path/scripts/manage_recommendation_release.py" get-active)"
[[ "$active_family_id" == "$expected_family_id" ]] \
  || { printf 'Active recommendation family changed before finalization.\n' >&2; exit 1; }

curl --fail --silent --max-time 10 http://127.0.0.1/healthz >/dev/null
curl --fail --silent --max-time 30 http://127.0.0.1/readyz >/dev/null
install -o root -g yobi -m 0644 /dev/null "$final_marker"
printf 'release-status=FINAL\nquality-gate=recommendation-v2-postdeploy-five\nprovider-calls=5\nprovider-retries=0\nevidence-sha256=%s\n' \
  "$evidence_sha256" | tee "$final_marker" >/dev/null
rm -f -- "$provisional_marker"
[[ -f "$final_marker" && ! -L "$final_marker" \
  && "$(stat -c '%U:%G:%a' "$final_marker")" == "root:yobi:644" \
  && ! -e "$provisional_marker" \
  && "$(grep -c '^provider-calls=5$' "$final_marker")" == "1" \
  && "$(grep -c "^evidence-sha256=${evidence_sha256}$" "$final_marker")" == "1" ]]
printf 'Finalized release_id=%s with zero additional provider calls.\n' "$release_id"
REMOTE

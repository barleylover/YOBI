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
  || { printf 'Quality-five evidence is unavailable.\n' >&2; exit 1; }
[[ "${YOBI_GUARDED_SSH_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_NLB_WINDOW:-}" == "1" \
  && "${YOBI_GUARDED_LB_WINDOW:-}" == "1" \
  && "$PORT" == "443" && -n "$HOST" \
  && -f "$KNOWN_HOSTS" && ! -L "$KNOWN_HOSTS" \
  && -S "$CONTROL_PATH" && ! -L "$CONTROL_PATH" ]] \
  || { printf 'Finalization requires the guarded LB SSH transport.\n' >&2; exit 1; }

python3 - "$EVIDENCE_PATH" "$EXPECTED_RELEASE_ID" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
cases = payload.get("cases")
expected_cuisines = {
    "JAPANESE", "ITALIAN", "AMERICAN", "SOUTHEAST_ASIAN", "MEXICAN"
}
covered_cuisines = {
    code
    for case in cases or []
    for code in case.get("selected_cuisine_codes", [])
}
valid = (
    payload.get("status") == "PASS"
    and payload.get("gate") == "recommendation-quality-five"
    and payload.get("requested") == 5
    and payload.get("completed") == 5
    and payload.get("expansion_cuisine_coverage_complete") is True
    and set(payload.get("expansion_cuisine_codes", [])) == expected_cuisines
    and covered_cuisines == expected_cuisines
    and payload.get("release", {}).get("application_release_id") == sys.argv[2]
    and isinstance(cases, list)
    and len(cases) == 5
    and all(
        case.get("status") == "PASS"
        and case.get("error_codes") == []
        and case.get("result_count") == 3
        and case.get("merchant_count") == 3
        and case.get("evidence_count", 0) >= 3
        for case in cases
    )
)
if not valid:
    raise SystemExit("QUALITY_FIVE_EVIDENCE_INVALID")
PY

readonly EVIDENCE_SHA256="$(shasum -a 256 "$EVIDENCE_PATH" | awk '{print $1}')"
[[ "$EVIDENCE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { printf 'Quality-five evidence checksum is invalid.\n' >&2; exit 1; }

ssh -T -q -p "$PORT" -i "$SSH_KEY" \
  -o LogLevel=ERROR -o ConnectTimeout=20 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
  -o "UserKnownHostsFile=${KNOWN_HOSTS}" -o StrictHostKeyChecking=yes \
  -o ControlMaster=no -o "ControlPath=${CONTROL_PATH}" -o ControlPersist=no \
  "$SSH_USER@$HOST" \
  "sudo -n bash -s -- '$EXPECTED_RELEASE_ID' '$EVIDENCE_SHA256'" <<'REMOTE'
set -euo pipefail
release_id="$1"
evidence_sha256="$2"
release_path="/opt/yobi/releases/$release_id"
ready_marker="$release_path/.yobi-release-ready"
provisional_marker="$release_path/.yobi-release-provisional"
final_marker="$release_path/.yobi-release-quality-five"
[[ "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ \
  && "$evidence_sha256" =~ ^[0-9a-f]{64}$ \
  && -d "$release_path" && ! -L "$release_path" \
  && "$(readlink -f /opt/yobi/current)" == "$release_path" \
  && -f "$ready_marker" && ! -L "$ready_marker" \
  && "$(stat -c '%U:%G:%a' "$ready_marker")" == "root:yobi:644" \
  && -f "$provisional_marker" && ! -L "$provisional_marker" ]] \
  || { printf 'Active provisional release identity is invalid.\n' >&2; exit 1; }
case "$(cat "$provisional_marker")" in
  performance-gate=pending|quality-five-gate=pending) ;;
  *) printf 'Provisional marker content is invalid.\n' >&2; exit 1 ;;
esac
curl --fail --silent --max-time 10 http://127.0.0.1/healthz >/dev/null
curl --fail --silent --max-time 30 http://127.0.0.1/readyz >/dev/null
install -o root -g yobi -m 0644 /dev/null "$final_marker"
printf 'release-status=FINAL\nquality-gate=recommendation-quality-five\nquality-scope=expanded-cuisines\nsamples=5\nevidence-sha256=%s\nfull30=operator-superseded\n' \
  "$evidence_sha256" | tee "$final_marker" >/dev/null
rm -f -- "$provisional_marker"
[[ -f "$final_marker" && ! -L "$final_marker" \
  && "$(stat -c '%U:%G:%a' "$final_marker")" == "root:yobi:644" \
  && ! -e "$provisional_marker" \
  && "$(grep -c '^samples=5$' "$final_marker")" == "1" \
  && "$(grep -c "^evidence-sha256=${evidence_sha256}$" "$final_marker")" == "1" ]]
curl --fail --silent --max-time 10 http://127.0.0.1/healthz >/dev/null
curl --fail --silent --max-time 30 http://127.0.0.1/readyz >/dev/null
printf 'Finalized release_id=%s with quality-five evidence.\n' "$release_id"
REMOTE

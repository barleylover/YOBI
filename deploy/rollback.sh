#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run on the VM with sudo.\n' >&2
  exit 1
fi
current="$(readlink -f /opt/yobi/current)"
previous="$(find /opt/yobi/releases -mindepth 1 -maxdepth 1 -type d -print | sort -r | grep -Fvx "$current" | head -1)"
[[ -n "$previous" ]] || { printf 'No previous release is available.\n' >&2; exit 1; }
ln -sfn "$previous" /opt/yobi/current
/opt/yobi/venv/bin/python -m pip install -e /opt/yobi/current/backend
systemctl restart yobi-api nginx
curl --fail --silent http://127.0.0.1/healthz >/dev/null
printf 'Rolled back to %s and passed the local health check.\n' "$(basename "$previous")"


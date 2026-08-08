#!/usr/bin/env bash
set -euo pipefail

readonly RELEASES_ROOT="/opt/yobi/releases"
readonly CURRENT_LINK="/opt/yobi/current"
readonly SHARED_ROOT="/opt/yobi/shared"
readonly READY_MARKER=".yobi-release-ready"
readonly PREVIOUS_RECORD="$SHARED_ROOT/previous_release"

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run on the VM with sudo.\n' >&2
  exit 1
fi
if (( $# > 1 )); then
  printf 'Usage: %s [verified-release-id]\n' "$0" >&2
  exit 1
fi

current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
case "$current" in
  "$RELEASES_ROOT"/*) ;;
  *) printf 'Current release link is missing or outside the release root.\n' >&2; exit 1 ;;
esac

if (( $# == 1 )); then
  target_id="$1"
else
  [[ -f "$PREVIOUS_RECORD" ]] \
    || { printf 'No recorded last-known-good rollback target is available.\n' >&2; exit 1; }
  target_id="$(tr -d '\r\n' < "$PREVIOUS_RECORD")"
fi
[[ "$target_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || { printf 'Rollback release id is invalid.\n' >&2; exit 1; }

target="$(readlink -f "$RELEASES_ROOT/$target_id" 2>/dev/null || true)"
case "$target" in
  "$RELEASES_ROOT"/*) ;;
  *) printf 'Rollback target does not resolve inside the release root.\n' >&2; exit 1 ;;
esac
[[ "$target" != "$current" ]] || { printf 'Rollback target is already current.\n' >&2; exit 1; }
[[ -f "$target/$READY_MARKER" ]] \
  || { printf 'Rollback target was never health-verified; refusing activation.\n' >&2; exit 1; }
[[ -x "$target/venv/bin/python" && -f "$target/frontend/dist/index.html" ]] \
  || { printf 'Rollback target is incomplete; refusing activation.\n' >&2; exit 1; }

ln -sfn "$target" "$CURRENT_LINK"
if ! systemctl daemon-reload \
  || ! systemctl restart yobi-api nginx \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/healthz >/dev/null \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/readyz >/dev/null; then
  ln -sfn "$current" "$CURRENT_LINK"
  systemctl daemon-reload
  systemctl restart yobi-api nginx
  printf 'Rollback activation failed; original current release was restored.\n' >&2
  exit 1
fi

current_id="${current##*/}"
if ! { printf '%s\n' "$current_id" > "${PREVIOUS_RECORD}.tmp" \
  && chown root:root "${PREVIOUS_RECORD}.tmp" \
  && chmod 0644 "${PREVIOUS_RECORD}.tmp" \
  && mv "${PREVIOUS_RECORD}.tmp" "$PREVIOUS_RECORD"; }; then
  ln -sfn "$current" "$CURRENT_LINK"
  systemctl daemon-reload
  systemctl restart yobi-api nginx
  printf 'Rollback metadata update failed; original current release was restored.\n' >&2
  exit 1
fi
printf 'Rolled back to %s and passed local health/ready checks.\n' "$target_id"

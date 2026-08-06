#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly INSTANCE_NAME="yobi-app-01"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"

for command in oci ssh scp tar; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done
[[ -f "$SSH_KEY" ]] || { printf 'SSH key not found: %s\n' "$SSH_KEY" >&2; exit 1; }
[[ -d "$ROOT_DIR/frontend/dist" ]] || { printf 'Run make build before deployment.\n' >&2; exit 1; }

compartment_id="$(oci iam compartment list --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
[[ -n "$compartment_id" && "$compartment_id" != "null" ]] || { printf 'Target compartment not found.\n' >&2; exit 1; }
instance_id="$(oci compute instance list --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$INSTANCE_NAME" \
  --lifecycle-state RUNNING --query 'data[0].id' --raw-output)"
[[ -n "$instance_id" && "$instance_id" != "null" ]] || { printf 'Running target VM not found.\n' >&2; exit 1; }
host="$(oci compute instance list-vnics --profile "$PROFILE" --region "$REGION" \
  --instance-id "$instance_id" --query 'data[0]."public-ip"' --raw-output)"
[[ -n "$host" && "$host" != "null" ]] || { printf 'VM public IP is unavailable.\n' >&2; exit 1; }

archive="$(mktemp -t yobi-release.XXXXXX.tar.gz)"
trap 'rm -f "$archive"' EXIT
tar -C "$ROOT_DIR" -czf "$archive" \
  --exclude='.venv' --exclude='frontend/node_modules' --exclude='frontend/test-results' \
  --exclude='frontend/playwright-report' --exclude='backend/data' --exclude='tmp' \
  backend frontend/dist database deploy scripts README.md Makefile .env.example

scp -q -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$archive" "$SSH_USER@$host:/tmp/yobi-release.tar.gz"
ssh -t -i "$SSH_KEY" "$SSH_USER@$host" "bash -s -- '$RELEASE_ID'" <<'REMOTE'
set -euo pipefail
release_id="$1"
new_release="/opt/yobi/releases/$release_id"
old_release="$(readlink -f /opt/yobi/current 2>/dev/null || true)"

sudo install -d "$new_release"
sudo tar -xzf /tmp/yobi-release.tar.gz -C "$new_release"
sudo env YOBI_RELEASE_ROOT="$new_release" "$new_release/deploy/install_vm.sh"
sudo chown -R yobi:yobi "$new_release"

sudo bash -c "set -a; source /etc/yobi/yobi.env; set +a; '$new_release/venv/bin/python' '$new_release/scripts/migrate.py'"
sudo bash -c "set -a; source /etc/yobi/yobi.env; set +a; '$new_release/venv/bin/python' '$new_release/scripts/seed_demo.py' --upsert"

sudo ln -sfn "$new_release" /opt/yobi/current
if ! sudo systemctl daemon-reload \
  || ! sudo systemctl restart yobi-api nginx \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/healthz >/dev/null \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/readyz >/dev/null; then
  if [[ -n "$old_release" && -d "$old_release" ]]; then
    sudo ln -sfn "$old_release" /opt/yobi/current
    sudo systemctl daemon-reload
    sudo systemctl restart yobi-api nginx
  fi
  printf 'Release activation failed; previous current link was restored.\n' >&2
  exit 1
fi
rm -f /tmp/yobi-release.tar.gz
REMOTE

printf 'Release %s migrated, seeded, activated, and passed local health/ready checks.\n' "$RELEASE_ID"

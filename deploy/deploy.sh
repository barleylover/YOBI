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
ssh -t -i "$SSH_KEY" "$SSH_USER@$host" \
  "sudo install -d /opt/yobi/releases/$RELEASE_ID && \
   sudo tar -xzf /tmp/yobi-release.tar.gz -C /opt/yobi/releases/$RELEASE_ID && \
   sudo ln -sfn /opt/yobi/releases/$RELEASE_ID /opt/yobi/current && \
   sudo /opt/yobi/current/deploy/install_vm.sh && \
   sudo chown -R yobi:yobi /opt/yobi/releases/$RELEASE_ID && \
   rm -f /tmp/yobi-release.tar.gz"

printf 'Release %s uploaded and installed. Runtime secrets are still required before service start.\n' "$RELEASE_ID"

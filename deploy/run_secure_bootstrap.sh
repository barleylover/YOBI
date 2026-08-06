#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly SSH_KEY="${YOBI_SSH_KEY:-${HOME}/.ssh/yobi_oci_vm_ed25519}"
readonly SSH_USER="${YOBI_SSH_USER:-opc}"

compartment_id="$(oci iam compartment list --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true --query "data[?name=='HACK-TEAM-05' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
instance_id="$(oci compute instance list --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name yobi-app-01 --lifecycle-state RUNNING \
  --query 'data[0].id' --raw-output)"
host="$(oci compute instance list-vnics --profile "$PROFILE" --region "$REGION" \
  --instance-id "$instance_id" --query 'data[0]."public-ip"' --raw-output)"
[[ -n "$host" && "$host" != "null" ]] || { printf 'Running YOBI VM was not resolved.\n' >&2; exit 1; }

ssh -t -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$SSH_USER@$host" \
  "sudo /opt/yobi/venv/bin/python /opt/yobi/current/deploy/secure_bootstrap.py"


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
[[ -d "$ROOT_DIR/knowledge" ]] || { printf 'Knowledge authoring sources are missing.\n' >&2; exit 1; }
[[ -f "$ROOT_DIR/database/migrations/005_conversation_state.sql" ]] \
  || { printf 'Conversation-state migration is missing.\n' >&2; exit 1; }
[[ -f "$ROOT_DIR/database/migrations/006_knowledge_graph.sql" ]] \
  || { printf 'Knowledge-graph migration is missing.\n' >&2; exit 1; }
[[ -f "$ROOT_DIR/database/migrations/007_service_area_and_mutation_idempotency.sql" ]] \
  || { printf 'Service-area and mutation-idempotency migration is missing.\n' >&2; exit 1; }
[[ -f "$ROOT_DIR/database/migrations/008_checkout_cart_version.sql" ]] \
  || { printf 'Checkout cart-version migration is missing.\n' >&2; exit 1; }

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
  backend frontend/dist database deploy scripts knowledge README.md Makefile .env.example

scp -q -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$archive" "$SSH_USER@$host:/tmp/yobi-release.tar.gz"
ssh -t -i "$SSH_KEY" "$SSH_USER@$host" "bash -s -- '$RELEASE_ID'" <<'REMOTE'
set -euo pipefail
release_id="$1"
new_release="/opt/yobi/releases/$release_id"
old_release="$(readlink -f /opt/yobi/current 2>/dev/null || true)"
ready_marker=".yobi-release-ready"
previous_record="/opt/yobi/shared/previous_release"

if [[ -n "$old_release" ]]; then
  case "$old_release" in
    /opt/yobi/releases/*) ;;
    *) printf 'Current release points outside /opt/yobi/releases.\n' >&2; exit 1 ;;
  esac
  if ! curl --fail --silent http://127.0.0.1/healthz >/dev/null \
    || ! curl --fail --silent http://127.0.0.1/readyz >/dev/null; then
    printf 'Current release is not healthy enough to register as rollback target.\n' >&2
    exit 1
  fi
  sudo install -o root -g root -m 0644 /dev/null "$old_release/$ready_marker"
fi

sudo install -d "$new_release"
sudo tar -xzf /tmp/yobi-release.tar.gz -C "$new_release"
sudo env YOBI_RELEASE_ROOT="$new_release" "$new_release/deploy/install_vm.sh"
sudo chown -R yobi:yobi "$new_release"

sudo env PYTHONPATH="$new_release" "$new_release/venv/bin/python" -c \
  "from deploy.secure_bootstrap import persist_runtime_retry_policy; persist_runtime_retry_policy()"
sudo bash -c "set -a; source /etc/yobi/yobi.env; set +a; '$new_release/venv/bin/python' '$new_release/scripts/migrate.py'"
sudo bash -c "set -a; source /etc/yobi/yobi.env; set +a; '$new_release/venv/bin/python' '$new_release/scripts/seed_demo.py' --upsert"

sudo ln -sfn "$new_release" /opt/yobi/current
if ! sudo systemctl daemon-reload \
  || ! sudo systemctl restart yobi-api nginx \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/healthz >/dev/null \
  || ! curl --fail --silent --retry 8 --retry-delay 2 http://127.0.0.1/readyz >/dev/null \
  || ! sudo install -o root -g root -m 0644 /dev/null "$new_release/$ready_marker"; then
  if [[ -n "$old_release" && -d "$old_release" ]]; then
    sudo ln -sfn "$old_release" /opt/yobi/current
    sudo systemctl daemon-reload
    sudo systemctl restart yobi-api nginx
  fi
  printf 'Release activation failed; previous current link was restored.\n' >&2
  exit 1
fi
if [[ -n "$old_release" ]]; then
  old_release_id="${old_release##*/}"
  if ! { printf '%s\n' "$old_release_id" | sudo tee "${previous_record}.tmp" >/dev/null \
    && sudo chown root:root "${previous_record}.tmp" \
    && sudo chmod 0644 "${previous_record}.tmp" \
    && sudo mv "${previous_record}.tmp" "$previous_record"; }; then
    sudo ln -sfn "$old_release" /opt/yobi/current
    sudo systemctl daemon-reload
    sudo systemctl restart yobi-api nginx
    printf 'Rollback-target recording failed; previous current link was restored.\n' >&2
    exit 1
  fi
fi
rm -f /tmp/yobi-release.tar.gz
REMOTE

printf 'Release %s migrated, seeded, activated, and passed local health/ready checks.\n' "$RELEASE_ID"

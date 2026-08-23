#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE="${OCI_PROFILE:-rndmgr}"
readonly REGION="${OCI_REGION:-ap-seoul-1}"
readonly COMPARTMENT_NAME="HACK-TEAM-05"
readonly NSG_NAME="yobi-app-nsg"

compartment_id="$(oci iam compartment list --profile "$PROFILE" --region "$REGION" --all \
  --compartment-id-in-subtree true --query "data[?name=='${COMPARTMENT_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
[[ -n "$compartment_id" && "$compartment_id" != "null" ]] || { printf 'Target compartment not found.\n' >&2; exit 1; }
nsg_id="$(oci network nsg list --profile "$PROFILE" --region "$REGION" \
  --compartment-id "$compartment_id" --display-name "$NSG_NAME" \
  --query 'data[0].id' --raw-output)"
[[ -n "$nsg_id" && "$nsg_id" != "null" ]] || { printf 'Target NSG not found.\n' >&2; exit 1; }

existing="$(oci network nsg rules list --profile "$PROFILE" --region "$REGION" \
  --nsg-id "$nsg_id" --direction INGRESS \
  --query 'length(data[?protocol==`"6"` && source==`"0.0.0.0/0"` && "tcp-options"."destination-port-range".min==`80` && "tcp-options"."destination-port-range".max==`80`])' \
  --raw-output)"
if [[ "$existing" == "1" ]]; then
  printf 'HTTP ingress already matches the approved single TCP 80 rule.\n'
  exit 0
fi
[[ "$existing" == "0" ]] || { printf 'Unexpected duplicate HTTP ingress state: %s\n' "$existing" >&2; exit 1; }

oci network nsg rules add --profile "$PROFILE" --region "$REGION" \
  --nsg-id "$nsg_id" \
  --security-rules '[{"direction":"INGRESS","protocol":"6","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","tcpOptions":{"destinationPortRange":{"min":80,"max":80}}}]' \
  >/dev/null
verified="$(oci network nsg rules list --profile "$PROFILE" --region "$REGION" \
  --nsg-id "$nsg_id" --direction INGRESS \
  --query 'length(data[?protocol==`"6"` && source==`"0.0.0.0/0"` && "tcp-options"."destination-port-range".min==`80` && "tcp-options"."destination-port-range".max==`80`])' \
  --raw-output)"
[[ "$verified" == "1" ]] || { printf 'HTTP ingress verification failed after add.\n' >&2; exit 1; }
printf 'Added exactly one approved public ingress rule: TCP 80 to yobi-app-nsg.\n'

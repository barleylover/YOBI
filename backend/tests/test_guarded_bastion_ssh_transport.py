from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "with_temporary_bastion_ssh.sh"


def test_guarded_bastion_transport_shell_is_syntax_valid() -> None:
    for relative_path in (
        "deploy/with_temporary_bastion_ssh.sh",
        "deploy/deploy.sh",
        "deploy/run_remote_rollback.sh",
        "deploy/release_rehearsal.sh",
    ):
        subprocess.run(
            ["bash", "-n", str(ROOT / relative_path)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_wrapper_uses_agent_independent_port_forwarding_with_exact_ttl() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "oci bastion bastion create" in source
    assert "--bastion-type STANDARD" in source
    assert "--client-cidr-list" in source
    assert '"$source_cidr" =~ ^(.+)/32$' in source
    assert "readonly BASTION_SESSION_TTL=10800" in source
    assert '--max-session-ttl "$BASTION_SESSION_TTL"' in source
    assert "oci bastion session create-port-forwarding" in source
    assert "create-managed-ssh" not in source
    assert '--session-ttl "$BASTION_SESSION_TTL"' in source
    assert '--target-private-ip "$instance_private_ip" --target-port 22' in source
    assert "instance-agent" not in source
    assert "compute instance update" not in source
    assert 'data."public-ip"' not in source
    assert "bastion_create_result" not in source
    assert "session_create_result" not in source
    assert 'temp_bastion_id="$(wait_for_temp_bastion_id)"' in source
    assert 'temp_session_id="$(wait_for_temp_session_id)"' in source


def test_wrapper_opens_only_exact_bastion_endpoint_rule_on_app_nsg() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    rule_setup = source[
        source.index('bastion_private_cidr="${bastion_private_ip}/32"') : source.index(
            "session_create_started=true"
        )
    ]

    assert '"direction":"INGRESS"' in rule_setup
    assert '"protocol":"6"' in rule_setup
    assert '"sourceType":"CIDR_BLOCK"' in rule_setup
    assert '"destinationPortRange":{"min":22,"max":22}' in rule_setup
    assert 'app_rule_id="$(jq -r' in rule_setup
    assert '"$(tcp_rule_count 22)" == "1"' in rule_setup
    assert '"$(tcp_rule_count 80)" == "$baseline_http_count"' in rule_setup
    assert "oci network nsg create" not in source
    assert "oci lb load-balancer create" not in source
    assert "oci nlb network-load-balancer create" not in source


def test_wrapper_refuses_security_list_or_existing_transport_bypass() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert 'security_list_ids="$(jq -c' in source
    assert "oci network security-list get" in source
    assert "select(matches_port(22))" in source
    assert 'security_list_ssh_bypass_count" == "0"' in source
    assert 'baseline_ssh_count" == "0"' in source
    assert 'baseline_http_count" == "1"' in source
    assert 'baseline_bastion_count" == "0"' in source
    assert 'baseline_lb_count" == "0"' in source
    assert 'baseline_nlb_count" == "0"' in source


def test_nlb_baseline_accepts_the_cli_items_envelope() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    helper = source[
        source.index("nlb_count() {") : source.index(
            'baseline_ssh_count="$(tcp_rule_count 22)"'
        )
    ]

    assert '(.data | type) == "object"' in helper
    assert ".data.items // []" in helper
    assert "payload='{\"data\":{\"items\":[]}}'" in helper


def test_ephemeral_key_tunnel_and_known_hosts_are_local_and_bounded() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert 'mktemp -d "${local_temp_root%/}/yobi-bastion.XXXXXX"' in source
    assert "umask 077" in source
    assert "ssh-keygen -q -t ed25519 -N ''" in source
    assert 'chmod 0600 "$session_key" "$session_public_key"' in source
    assert '--ssh-public-key-file "$session_public_key"' in source
    assert '-L "127.0.0.1:${local_port}:${instance_private_ip}:22"' in source
    assert '-i "$session_key" -p 22' in source
    assert "ExitOnForwardFailure=yes" in source
    assert "for tunnel_attempt in {1..3}" in source
    assert "never create a wider rule or another session" in source
    assert "ServerAliveInterval=120" in source
    assert "ServerAliveCountMax=3" in source
    assert '"${temp_session_id}@${BASTION_PUBLIC_HOST}"' in source
    assert 'kill -0 "$tunnel_pid"' in source
    assert "for preflight_attempt in {1..12}" in source
    assert '-i "$SSH_KEY"' in source
    assert '"$SSH_USER@127.0.0.1" true' in source


def test_cleanup_is_trapped_and_uses_exact_order_and_identity() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    cleanup = source[source.index("cleanup() {") : source.index("trap cleanup EXIT")]
    exact_rule = source[
        source.index("remove_exact_app_rule() {") : source.index(
            "stop_local_tunnel() {"
        )
    ]

    assert 'jq -cn --arg id "$app_rule_id" \'[$id]\'' in exact_rule
    assert 'matching_count" == "1"' in exact_rule
    assert '"$matching_count" == "0"' in exact_rule
    assert cleanup.index("stop_local_tunnel") < cleanup.index(
        "bastion session delete"
    )
    assert cleanup.index("bastion session delete") < cleanup.index(
        "remove_exact_app_rule"
    )
    assert cleanup.index("remove_exact_app_rule") < cleanup.index(
        "bastion bastion delete"
    )
    assert cleanup.index("bastion bastion delete") < cleanup.index(
        "remove_local_key_material"
    )
    assert 'final_ssh_count" == "0"' in cleanup
    assert 'final_http_count" == "$baseline_http_count"' in cleanup
    assert 'final_bastion_count" == "$baseline_bastion_count"' in cleanup
    assert 'final_lb_count" == "$baseline_lb_count"' in cleanup
    assert 'final_nlb_count" == "$baseline_nlb_count"' in cleanup
    assert 'temp_bastion_remaining" == "0"' in cleanup
    assert 'session_absent_verified" == "true"' in cleanup
    assert "for verification_attempt in {1..60}" in cleanup
    assert 'rm -f -- "$candidate"' in source
    assert 'rmdir -- "$temp_dir"' in source


def test_partial_create_cleanup_reconciles_delayed_bastion_and_session() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    for function_name in (
        "wait_for_temp_bastion_id() {",
        "wait_for_temp_session_id() {",
    ):
        start = source.index(function_name)
        body = source[start : source.index("\n}\n", start) + 3]
        assert "for attempt in {1..12}" in body
        assert "sleep 5" in body
    cleanup = source[source.index("cleanup() {") : source.index("trap cleanup EXIT")]
    assert 'bastion_create_started" == "true"' in cleanup
    assert 'session_create_started" == "true"' in cleanup
    assert "wait_for_temp_bastion_id" in cleanup
    assert "wait_for_temp_session_id" in cleanup


def test_deploy_and_rollback_accept_only_strict_local_bastion_override() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "run_remote_rollback.sh").read_text(
        encoding="utf-8"
    )

    for source in (deploy_source, rollback_source):
        assert 'GUARDED_SSH_KNOWN_HOSTS_FILE="${YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE:-}"' in source
        assert '"${YOBI_GUARDED_BASTION_WINDOW:-}" == "1"' in source
        assert '"${YOBI_GUARDED_NLB_WINDOW:-}" != "1"' in source
        assert '"$GUARDED_SSH_HOST" == "127.0.0.1"' in source
        assert '"$GUARDED_SSH_PORT" =~ ^[0-9]{4,5}$' in source
        assert '"$GUARDED_SSH_PORT" -ge 1024' in source
        assert '"$GUARDED_SSH_PORT" -le 65535' in source
        assert '-f "$GUARDED_SSH_KNOWN_HOSTS_FILE"' in source
        assert '! -L "$GUARDED_SSH_KNOWN_HOSTS_FILE"' in source
        assert '-o "UserKnownHostsFile=${GUARDED_SSH_KNOWN_HOSTS_FILE}"' in source
        assert "-o StrictHostKeyChecking=yes" in source
        assert 'ssh_port="$GUARDED_SSH_PORT"' in source
    assert '"${ssh_host_key_options[@]}"' in deploy_source
    assert '"${ssh_host_key_options[@]}"' in rollback_source


def test_wrapper_passes_only_local_tunnel_override_to_standard_workflow() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "export YOBI_GUARDED_SSH_WINDOW=1" in source
    assert "export YOBI_GUARDED_BASTION_WINDOW=1" in source
    assert "unset YOBI_GUARDED_NLB_WINDOW YOBI_GUARDED_LB_WINDOW" in source
    assert "export YOBI_GUARDED_SSH_HOST=127.0.0.1" in source
    assert 'export YOBI_GUARDED_SSH_PORT="$local_port"' in source
    assert 'export YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE="$known_hosts_file"' in source
    assert '(cd "$ROOT_DIR" && "$@")' in source
    assert '(cd "$ROOT_DIR" && make deploy)' in source
    assert "workflow_status=0" in source
    assert "|| workflow_status=$?" in source
    assert 'exit "$workflow_status"' in source


def test_wrapper_stdout_never_interpolates_sensitive_values() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "set -x" not in source
    assert "ssh_preflight_output" in source
    assert 'printf \'%s\' "$ssh_preflight_output"' not in source
    for line in source.splitlines():
        if "printf" not in line:
            continue
        output_expression = line.split("printf", 1)[1]
        assert re.search(
            r"\$(?:[^ ]*_id|source_cidr|bastion_private_cidr|instance_private_ip|"
            r"temp_session_id|temp_bastion_id|session_key|known_hosts_file)",
            output_expression,
        ) is None

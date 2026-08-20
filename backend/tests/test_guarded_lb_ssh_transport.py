from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "with_temporary_lb_ssh.sh"


def test_guarded_lb_transport_shell_is_syntax_valid() -> None:
    subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_wrapper_builds_only_the_exact_flexible_lb_proxy_path() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "oci nlb" not in source
    assert '"$source_cidr" =~ ^(.+)/32$' in source
    assert '"sourceType":"CIDR_BLOCK"' in source
    assert '"destinationPortRange":{"min":443,"max":443}' in source
    assert '"direction":"EGRESS"' in source
    assert '"destinationType":"NETWORK_SECURITY_GROUP"' in source
    assert '"destinationPortRange":{"min":22,"max":22}' in source
    assert '"sourceType":"NETWORK_SECURITY_GROUP"' in source
    assert '"$(temp_nsg_total_rule_count)" == "2"' in source
    assert "oci lb load-balancer create" in source
    assert "--shape-name flexible" in source
    assert '"minimumBandwidthInMbps":10' in source
    assert '"maximumBandwidthInMbps":10' in source
    assert "--is-private false --ip-mode IPV4" in source
    assert '--nsg-ids "$lb_nsg_ids"' in source
    assert '--ip-address "$instance_private_ip" --port 22' in source
    assert "--health-checker-protocol TCP" in source
    assert "--health-checker-port 22" in source
    assert '--protocol TCP --port 443' in source
    assert 'backend_status" == "OK"' in source
    assert "is-preserve-source" not in source


def test_wrapper_uses_private_vnic_address_and_exact_backend_health_identity() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    private_backend = source[
        source.index('vnic_id="$(oci compute instance list-vnics') : source.index(
            "classify_ssh_failure() {"
        )
    ]

    assert "oci network vnic get" in private_backend
    assert '.data."nsg-ids" | index($id) != null' in private_backend
    assert '.data."private-ip" // empty' in private_backend
    assert 'validate_ipv4 "$instance_private_ip"' in private_backend
    assert 'readonly backend_name="${instance_private_ip}:22"' in private_backend
    assert '--backend-name "$backend_name"' in private_backend


def test_wrapper_checks_union_with_public_subnet_security_lists() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    security_list_gate = source[
        source.index('security_list_ids="$(jq') : source.index(
            'app_nsg_json="$(oci network nsg list'
        )
    ]

    assert "security-list-ids" in security_list_gate
    assert "oci network security-list get" in security_list_gate
    assert "matches_port(22)" in security_list_gate
    assert "matches_port(443)" in security_list_gate
    assert ".source != $allowed_source" in security_list_gate
    assert 'security_list_bypass_count" == "0"' in security_list_gate


def test_empty_successful_lb_list_output_is_authoritative_zero() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    helper_boundaries = (
        ("lb_count() {", "lb_name_count() {"),
        ("lb_name_count() {", "resolve_temp_nsg_id() {"),
        ("resolve_temp_lb_id() {", "matching_app_rule_ids() {"),
    )

    for start, end in helper_boundaries:
        helper = source[source.index(start) : source.index(end)]
        assert "oci lb load-balancer list" in helper
        assert '[[ -n "$payload" ]] || payload=\'{"data":[]}\'' in helper

    for start, end in (
        ("resolve_temp_nsg_id() {", "temp_nsg_name_count() {"),
        ("temp_nsg_name_count() {", "temp_nsg_rule_count() {"),
        ("temp_nsg_rule_count() {", "temp_nsg_total_rule_count() {"),
    ):
        helper = source[source.index(start) : source.index(end)]
        assert '[[ -n "$payload" ]] || payload=\'{"data":[]}\'' in helper


def test_cleanup_uses_exact_rule_identity_and_ordered_resource_teardown() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    exact_rule = source[
        source.index("remove_exact_app_rule() {") : source.index(
            'baseline_ssh_count="$(tcp_rule_count 22)"'
        )
    ]
    cleanup = source[
        source.index("cleanup() {") : source.index("trap cleanup EXIT")
    ]

    assert 'jq -cn --arg id "$app_rule_id" \'[$id]\'' in exact_rule
    assert 'matching_count" == "1"' in exact_rule
    assert 'matching_count" != "0"' in exact_rule
    assert "wait_for_temp_nsg_id" in cleanup
    assert "wait_for_temp_lb_id" in cleanup
    assert cleanup.index("lb load-balancer delete") < cleanup.index(
        "remove_exact_app_rule"
    )
    assert cleanup.index("remove_exact_app_rule") < cleanup.index(
        "network nsg delete"
    )
    assert 'final_ssh_count" == "0"' in cleanup
    assert 'final_http_count" == "$baseline_http_count"' in cleanup
    assert 'final_lb_count" == "$baseline_lb_count"' in cleanup
    assert 'temp_lb_remaining" == "0"' in cleanup
    assert 'temp_nsg_remaining" == "0"' in cleanup
    assert "for verification_attempt in {1..60}" in cleanup
    assert "cleanup_verified=true" in cleanup
    assert "cleanup_operation_warning" in cleanup


def test_partial_create_reconciliation_polls_for_delayed_visibility() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    nsg_wait = source[
        source.index("wait_for_temp_nsg_id() {") : source.index(
            "wait_for_temp_lb_id() {"
        )
    ]
    lb_wait = source[
        source.index("wait_for_temp_lb_id() {") : source.index(
            "remove_exact_app_rule() {"
        )
    ]

    for wait_body in (nsg_wait, lb_wait):
        assert "for _ in {1..12}" in wait_body
        assert "sleep 5" in wait_body
        assert "consecutive_absent" not in wait_body


def test_ssh_preflight_is_bounded_and_emits_only_sanitized_category() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    preflight = source[
        source.index("classify_ssh_failure() {") : source.index(
            "printf 'Temporary source-restricted TCP 443 SSH path is healthy"
        )
    ]

    assert "for preflight_attempt in {1..12}" in preflight
    assert "sleep 5" in preflight
    assert "ConnectionAttempts=1" in preflight
    assert "ConnectTimeout=10" in preflight
    assert "2>&1" in preflight
    assert "classify_ssh_failure" in preflight
    for category in (
        "HOST_KEY_MISMATCH",
        "AUTHENTICATION",
        "TIMEOUT",
        "REFUSED",
        "NO_ROUTE",
        "KEY_EXCHANGE",
        "RESET",
        "CLOSED",
        "OTHER",
    ):
        assert category in preflight
    assert "category=%s" in preflight
    assert "printf '%s' \"$ssh_preflight_output\"" not in preflight


def test_timeout_can_only_retry_after_bounded_exact_source_correction() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    replacement = source[
        source.index("replace_frontend_source_cidr() {") : source.index(
            "resolve_temp_lb_id() {"
        )
    ]
    retry = source[
        source.index("if ! run_ssh_preflight; then") : source.index(
            "unset source_cidr"
        )
    ]

    assert 'old_rule_count" == "1"' in replacement
    assert replacement.index("nsg rules remove") < replacement.index(
        "nsg rules add"
    )
    between_remove_and_add = replacement[
        replacement.index("nsg rules remove") : replacement.index(
            "nsg rules add"
        )
    ]
    assert 'old_rule_count" == "0"' in between_remove_and_add
    assert 'temp_nsg_total_rule_count 2>/dev/null || true)" == "1"' in (
        between_remove_and_add
    )
    assert 'for attempt in {1..12}' in replacement
    assert 'temp_nsg_total_rule_count 2>/dev/null || true)" == "2"' in replacement
    assert "NETWORK_SECURITY_GROUP \"$app_nsg_id\" 22" in replacement
    assert 'ssh_failure_category" != "TIMEOUT"' in retry
    assert 'bash "$FLOW_SOURCE_PROBE"' in retry
    assert "--result-fd 3 3>&1 1>&2" in retry
    assert 'replace_frontend_source_cidr "$derived_source_cidr"' in retry
    assert retry.count("run_ssh_preflight") == 2


def test_wrapper_reuses_existing_guarded_override_without_changing_workflow() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    cleanup = source[
        source.index("cleanup() {") : source.index("trap cleanup EXIT")
    ]

    assert "export YOBI_GUARDED_SSH_WINDOW=1" in source
    assert "export YOBI_GUARDED_NLB_WINDOW=1" in source
    assert "export YOBI_GUARDED_LB_WINDOW=1" in source
    assert 'export YOBI_GUARDED_SSH_HOST="$lb_host"' in source
    assert "export YOBI_GUARDED_SSH_PORT=443" in source
    assert 'export YOBI_GUARDED_SSH_KNOWN_HOSTS_FILE="$known_hosts_file"' in source
    assert 'export YOBI_GUARDED_SSH_CONTROL_PATH="$control_path"' in source
    assert "ControlMaster=yes" in source
    assert "ControlPersist=no" in source
    assert 'ssh -S "$control_path" -O check' in source
    assert cleanup.index('ssh -S "$control_path" -O exit') < cleanup.index(
        "lb load-balancer delete"
    )
    assert '(cd "$ROOT_DIR" && "$@")' in source
    assert '(cd "$ROOT_DIR" && make deploy)' in source


def test_wrapper_does_not_print_sensitive_resolved_values() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "set -x" not in source
    for line in source.splitlines():
        if "printf" not in line:
            continue
        assert re.search(
            r"\$(?:lb_host|[^ ]*_id|source_cidr|app_rule_id)", line
        ) is None


def test_deploy_and_rollback_can_only_reuse_a_real_guarded_master_socket() -> None:
    for relative_path in ("deploy/deploy.sh", "deploy/run_remote_rollback.sh"):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert 'GUARDED_SSH_CONTROL_PATH="${YOBI_GUARDED_SSH_CONTROL_PATH:-}"' in source
        assert '-S "$GUARDED_SSH_CONTROL_PATH"' in source
        assert '! -L "$GUARDED_SSH_CONTROL_PATH"' in source
        assert '-o "ControlPath=${GUARDED_SSH_CONTROL_PATH}"' in source
        assert "-o ControlMaster=no" in source
        assert '"${ssh_connection_options[@]}"' in source

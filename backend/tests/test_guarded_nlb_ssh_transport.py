from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "with_temporary_nlb_ssh.sh"


@pytest.mark.parametrize(
    "relative_path",
    (
        "deploy/with_temporary_nlb_ssh.sh",
        "deploy/deploy.sh",
        "deploy/run_remote_rollback.sh",
        "deploy/release_rehearsal.sh",
    ),
)
def test_guarded_transport_shell_is_syntax_valid(relative_path: str) -> None:
    subprocess.run(
        ["bash", "-n", str(ROOT / relative_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_deploy_and_rollback_accept_only_guarded_tcp443_override() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "run_remote_rollback.sh").read_text(
        encoding="utf-8"
    )

    for source in (deploy_source, rollback_source):
        assert 'GUARDED_SSH_HOST="${YOBI_GUARDED_SSH_HOST:-}"' in source
        assert 'GUARDED_SSH_PORT="${YOBI_GUARDED_SSH_PORT:-}"' in source
        assert '"${YOBI_GUARDED_SSH_WINDOW:-}" == "1"' in source
        assert '"${YOBI_GUARDED_NLB_WINDOW:-}" == "1"' in source
        assert '"$GUARDED_SSH_PORT" == "443"' in source
        assert 'ssh_port="$GUARDED_SSH_PORT"' in source
        assert '-p "$ssh_port"' in source
        assert "ConnectTimeout=20" in source
        assert "ServerAliveInterval=30" in source
        assert "ServerAliveCountMax=6" in source
    assert 'ssh -T -p "$ssh_port"' in deploy_source
    assert 'ARCHIVE_CHUNK_BYTES=131072' in deploy_source
    assert 'cat >> \'$REMOTE_ARCHIVE\'' in deploy_source
    assert 'wc -c < \'$REMOTE_ARCHIVE\'' in deploy_source
    assert "scp -q" not in deploy_source


def test_wrapper_builds_only_the_exact_full_nat_path() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert '"$source_cidr" =~ ^(.+)/32$' in source
    assert 'matches_port(443)' in source
    assert 'matches_port(22)' in source
    assert '"sourceType":"CIDR_BLOCK"' in source
    assert '"destinationPortRange":{"min":443,"max":443}' in source
    assert '"direction":"EGRESS"' in source
    assert '"destinationType":"NETWORK_SECURITY_GROUP"' in source
    assert '"destinationPortRange":{"min":22,"max":22}' in source
    assert '"sourceType":"NETWORK_SECURITY_GROUP"' in source
    assert '"$(temp_nsg_total_rule_count)" == "2"' in source
    assert "--is-private false --is-preserve-source-destination false" in source
    assert "--is-preserve-source false" in source
    assert '--target-id "$instance_id" --port 22' in source
    assert 'health_checker=\'{"protocol":"TCP","port":22' in source
    assert "--protocol TCP --port 443" in source
    assert 'backend_status" == "OK"' in source


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
    assert '.source != $allowed_source' in security_list_gate
    assert 'security_list_bypass_count" == "0"' in security_list_gate


def test_empty_successful_temp_nsg_list_output_is_authoritative_zero() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

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
    assert "wait_for_temp_nlb_id" in cleanup
    assert cleanup.index("network-load-balancer delete") < cleanup.index(
        "remove_exact_app_rule"
    )
    assert cleanup.index("remove_exact_app_rule") < cleanup.index(
        "network nsg delete"
    )
    assert 'final_ssh_count" == "0"' in cleanup
    assert 'final_http_count" == "$baseline_http_count"' in cleanup
    assert 'final_nlb_count" == "$baseline_nlb_count"' in cleanup
    assert 'temp_nlb_remaining" == "0"' in cleanup
    assert 'temp_nsg_remaining" == "0"' in cleanup
    assert "for verification_attempt in {1..60}" in cleanup
    assert "sleep 5" in cleanup
    assert "cleanup_verified=true" in cleanup
    assert "cleanup_operation_warning" in cleanup


def test_partial_create_reconciliation_polls_for_delayed_visibility() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    nsg_wait = source[
        source.index("wait_for_temp_nsg_id() {") : source.index(
            "wait_for_temp_nlb_id() {"
        )
    ]
    nlb_wait = source[
        source.index("wait_for_temp_nlb_id() {") : source.index(
            "remove_exact_app_rule() {"
        )
    ]

    for wait_body in (nsg_wait, nlb_wait):
        assert "for _ in {1..12}" in wait_body
        assert "sleep 5" in wait_body
        assert "consecutive_absent" not in wait_body


def test_ssh_preflight_retries_and_emits_only_sanitized_failure_category() -> None:
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


def test_wrapper_does_not_print_sensitive_resolved_values() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "set -x" not in source
    for line in source.splitlines():
        if "printf" not in line:
            continue
        assert re.search(
            r"\$(?:nlb_host|[^ ]*_id|source_cidr|app_rule_id)", line
        ) is None

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "deploy" / "derive_source_cidr_with_temporary_flow_log.sh"


def test_flow_log_source_probe_shell_is_syntax_valid() -> None:
    subprocess.run(
        ["bash", "-n", str(PROBE)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_probe_rejects_missing_contract_before_any_oci_call() -> None:
    result = subprocess.run(
        [str(PROBE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "transport must be lb or nlb" in result.stderr
    assert "ocid1." not in result.stderr
    assert re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", result.stderr) is None


def test_probe_accepts_only_the_guarded_frontend_identity_and_two_rule_path() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert '--transport)' in source
    assert '--frontend-nsg-id)' in source
    assert '--frontend-host)' in source
    assert '--configured-source-cidr)' in source
    assert '--result-fd)' in source
    assert 'lb:yobi-ssh-lb-nsg-*' in source
    assert 'nlb:yobi-ssh-nsg-*' in source
    assert '"$configured_source_cidr" =~ ^(.+)/32$' in source
    assert "oci network nsg get" in source
    assert "oci network nsg rules list" in source
    assert 'total_rule_count" == "2"' in source
    assert '.direction == "INGRESS"' in source
    assert '."source-type" == "CIDR_BLOCK"' in source
    assert '.source == $source' in source
    assert '.direction == "EGRESS"' in source
    assert '."destination-type" == "NETWORK_SECURITY_GROUP"' in source
    assert '."tcp-options"."destination-port-range".min == 443' in source
    assert '."tcp-options"."destination-port-range".min == 22' in source


def test_probe_targets_only_vnics_attached_to_the_exact_frontend_nsg() -> None:
    source = PROBE.read_text(encoding="utf-8")
    vnic_scope = source[
        source.index('frontend_vnics_json="$(oci network nsg vnics list') :
        source.index('resource_nonce="$(printf')
    ]

    assert '--nsg-id "$frontend_nsg_id"' in vnic_scope
    assert "oci network vnic get" in vnic_scope
    assert '.data."lifecycle-state" == "AVAILABLE"' in vnic_scope
    assert '(.data."nsg-ids" | index($nsg) != null)' in vnic_scope
    assert '${#frontend_vnic_ids[@]} >= 1' in vnic_scope
    assert '${#frontend_vnic_ids[@]} <= 4' in vnic_scope


def test_capture_filter_is_full_sampling_reject_only_tcp443() -> None:
    source = PROBE.read_text(encoding="utf-8")
    setup = source[
        source.index("capture_rules=") : source.index(
            'log_group_create_started=true'
        )
    ]

    assert '"flowLogType":"REJECT"' in setup
    assert '"ruleAction":"INCLUDE"' in setup
    assert '"samplingRate":1' in setup
    assert '"protocol":"6"' in setup
    assert '"sourceCidr":"0.0.0.0/0"' in setup
    assert '"destinationPortRange":{"min":443,"max":443}' in setup
    assert "--filter-type FLOWLOG" in setup
    assert "--flow-log-capture-filter-rules" in setup


def test_each_front_vnic_gets_one_minimum_retention_service_log() -> None:
    source = PROBE.read_text(encoding="utf-8")
    log_setup = source[
        source.index('log_create_started=true') : source.index(
            'search_start="$(date'
        )
    ]

    assert 'for frontend_vnic_id in "${frontend_vnic_ids[@]}"' in log_setup
    assert 'sourceType:"OCISERVICE"' in log_setup
    assert 'service:"flowlogs"' in log_setup
    assert 'category:"vnic"' in log_setup
    assert 'parameters:{capture_filter:$capture_filter}' in log_setup
    assert "--log-type SERVICE --is-enabled true --retention-duration 30" in log_setup
    assert "--wait-for-state SUCCEEDED" in log_setup


def test_search_is_scoped_to_exact_log_ids_and_one_rejected_source() -> None:
    source = PROBE.read_text(encoding="utf-8")
    search = source[
        source.index('search_start="$(date') : source.index(
            "# Cleanup is deliberately completed"
        )
    ]

    assert 'for log_id in "${log_ids[@]}"' in search
    assert '${compartment_id}/${log_group_id}/${log_id}' in search
    assert "data.status = 'OK'" in search
    assert "data.action = 'REJECT'" in search
    assert "data.protocol = 6" in search
    assert "data.destinationPort = 443" in search
    assert ".data.results[]?.data.logContent.data?" in search
    assert '.sourceAddress' in search
    assert 'source_count > 1' in search
    assert 'source_count" == "1"' in search
    assert 'validate_ipv4 "$derived_source_ip"' in search
    assert '"$derived_source_cidr" != "$configured_source_cidr"' in search


def test_probe_has_no_network_or_transport_mutation() -> None:
    source = PROBE.read_text(encoding="utf-8")

    forbidden = (
        "oci network nsg create",
        "oci network nsg update",
        "oci network nsg delete",
        "oci network nsg rules add",
        "oci network nsg rules remove",
        "oci lb ",
        "oci nlb ",
        "oci compute instance update",
        "oci network vnic update",
        "oci network subnet update",
    )
    for command in forbidden:
        assert command not in source


def test_cleanup_removes_exact_logs_group_filter_then_requires_raw_absence() -> None:
    source = PROBE.read_text(encoding="utf-8")
    cleanup = source[
        source.index("cleanup_resources() {") : source.index("on_exit() {")
    ]

    assert cleanup.index("oci logging log delete") < cleanup.index(
        "oci logging log-group delete"
    )
    assert cleanup.index("oci logging log-group delete") < cleanup.index(
        "oci network capture-filter delete"
    )
    assert 'for attempt in {1..60}' in cleanup
    assert "trap '' INT TERM" in cleanup
    assert 'final_group_count" == "0"' in cleanup
    assert 'final_filter_count" == "0"' in cleanup
    assert "cleanup_completed=true" in cleanup

    capture_count = source[
        source.index("capture_filter_name_count() {") : source.index(
            "resolve_capture_filter_id() {"
        )
    ]
    group_count = source[
        source.index("log_group_name_count() {") : source.index(
            "resolve_log_group_id() {"
        )
    ]
    log_count = source[
        source.index("log_name_count() {") : source.index("resolve_log_id() {")
    ]
    for counter in (capture_count, group_count, log_count):
        assert "jq -r '.data | length'" in counter
        assert '!= "DELETING"' not in counter
        assert '!= "TERMINATED"' not in counter


def test_sensitive_result_is_emitted_only_after_cleanup_over_inherited_fd() -> None:
    source = PROBE.read_text(encoding="utf-8")

    cleanup_call = source.rindex("cleanup_resources \\")
    result_write = source.index(
        'printf \'%s\\n\' "$derived_source_cidr" >&"$result_fd"'
    )
    assert cleanup_call < result_write
    assert "cleanup failure exits nonzero and writes nothing" in source
    assert '[[ "$result_fd" =~ ^[3-9][0-9]*$ ]]' in source
    assert 'true >&"$result_fd"' in source


def test_user_visible_output_never_interpolates_sensitive_values() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "set -x" not in source
    sensitive = (
        "frontend_host",
        "frontend_nsg_id",
        "configured_source_cidr",
        "derived_source_ip",
        "compartment_id",
        "capture_filter_id",
        "log_group_id",
        "log_id",
        "search_payload",
        "unique_sources",
    )
    for line in source.splitlines():
        if not line.lstrip().startswith("printf") or '>&"$result_fd"' in line:
            continue
        for variable in sensitive:
            assert f"${variable}" not in line
            assert f"${{{variable}}}" not in line

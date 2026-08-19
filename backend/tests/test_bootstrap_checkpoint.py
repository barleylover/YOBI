from __future__ import annotations

import importlib.util
import inspect
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_secure_bootstrap", ROOT / "deploy" / "secure_bootstrap.py"
)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def test_checkpoint_is_private_and_resumable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    checkpoint_path = tmp_path / "bootstrap_state.json"
    monkeypatch.setattr(bootstrap, "CHECKPOINT", checkpoint_path)
    monkeypatch.setattr(bootstrap.os, "chown", lambda path, uid, gid: None)

    bootstrap.checkpoint(
        "database",
        "complete",
        runtime_user="YOBI_APP",
        migration_records=["001_core_schema.sql", "002_knowledge_and_cache.sql"],
    )

    assert bootstrap.checkpoint_complete("database") is True
    assert stat.S_IMODE(checkpoint_path.stat().st_mode) == 0o600
    text = checkpoint_path.read_text(encoding="utf-8")
    assert "001_core_schema.sql" in text
    assert "002_knowledge_and_cache.sql" in text

    bootstrap.checkpoint("genai_smoke", "degraded", fallback_required=True)
    assert bootstrap.checkpoint_status("genai_smoke") == "degraded"
    assert bootstrap.checkpoint_complete("genai_smoke") is False


def test_runtime_environment_can_resume_and_upgrade_release_policy(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    runtime_env = tmp_path / "yobi.env"
    runtime_env.write_text(
        "\n".join(
            [
                'ADB_DSN="synthetic-dsn"',
                'DB_PASSWORD="synthetic-password"',
                'OCI_GENAI_API_KEY="synthetic-api-key"',
                'DEMO_CONTROL_TOKEN="synthetic-token"',
                'OCI_COMPARTMENT_ID="ocid1.compartment.synthetic"',
                'LLM_MAX_RETRIES="0"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "RUNTIME_ENV", runtime_env)
    for key in ("ADB_DSN", "DB_PASSWORD", "OCI_GENAI_API_KEY", "DEMO_CONTROL_TOKEN"):
        monkeypatch.delenv(key, raising=False)

    assert bootstrap.load_runtime_env() is True
    assert os.environ["ADB_DSN"] == "synthetic-dsn"
    persisted = runtime_env.read_text(encoding="utf-8")
    assert persisted.count('LLM_MAX_RETRIES="0"') == 1
    assert 'EMBEDDING_PROVIDER="oci"' in persisted
    assert 'OCI_EMBED_AUTH="instance_principal"' in persisted
    assert 'STRUCTURED_RECOMMENDATION_MODEL="xai.grok-4.3"' in persisted
    assert 'STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS="2048"' in persisted
    assert 'STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS="2"' in persisted
    assert 'RECOMMENDATION_CANDIDATE_LIMIT="100"' in persisted
    assert 'RECOMMENDATION_LLM_SHORTLIST_LIMIT="15"' in persisted
    assert 'RECOMMENDATION_LLM_PASSAGES_PER_MENU="2"' in persisted
    assert 'RECOMMENDATION_LLM_SELECTION_ENABLED="true"' in persisted
    assert 'DB_PASSWORD="synthetic-password"' in persisted
    assert stat.S_IMODE(runtime_env.stat().st_mode) == 0o600
    captured = capsys.readouterr()
    assert "synthetic-password" not in captured.out + captured.err
    # load_runtime_env mutates os.environ directly, outside monkeypatch's setter
    # tracking. Keep later Settings-based tests independent of this synthetic key.
    for key in (
        "ADB_DSN",
        "DB_PASSWORD",
        "OCI_GENAI_API_KEY",
        "DEMO_CONTROL_TOKEN",
        "LLM_MAX_RETRIES",
        "EMBEDDING_PROVIDER",
        "OCI_EMBED_AUTH",
        "OCI_COMPARTMENT_ID",
        "STRUCTURED_RECOMMENDATION_MODEL",
        "STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS",
        "STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS",
        "RECOMMENDATION_CANDIDATE_LIMIT",
        "RECOMMENDATION_LLM_SHORTLIST_LIMIT",
        "RECOMMENDATION_LLM_PASSAGES_PER_MENU",
        "RECOMMENDATION_LLM_SELECTION_ENABLED",
        "OCI_GENAI_STRUCTURED_OUTPUT_ENABLED",
        "OCI_GENAI_STREAMING_ENABLED",
    ):
        os.environ.pop(key, None)


def test_retry_policy_matches_settings_and_runtime_restore() -> None:
    assert bootstrap.Settings.model_fields["llm_max_retries"].default == 0
    assert "quote('0')" in inspect.getsource(bootstrap.write_env)
    assert '"LLM_MAX_RETRIES": "0"' in inspect.getsource(bootstrap.main)
    restore = (ROOT / "deploy" / "restore_runtime_env.sh").read_text(encoding="utf-8")
    assert "LLM_MAX_RETRIES=\"0\"" in restore
    assert "LLM_MAX_RETRIES=\"1\"" not in restore
    assert bootstrap.Settings.model_fields["embedding_provider"].default == "deterministic"
    assert "quote('oci')" in inspect.getsource(bootstrap.write_env)
    assert 'EMBEDDING_PROVIDER="oci"' in restore
    assert 'OCI_EMBED_AUTH="instance_principal"' in restore
    assert "OCI_COMPARTMENT_ID=" in restore
    assert 'OCI_GENAI_MAX_INPUT_TOKENS="131072"' in restore
    assert 'LLM_MAX_INPUT_TOKENS="131072"' in restore
    assert 'OCI_GENAI_MAX_OUTPUT_TOKENS="4096"' in restore
    assert 'LLM_MAX_OUTPUT_TOKENS="4096"' in restore
    assert (
        bootstrap.Settings.model_fields["structured_recommendation_model"].default
        == "xai.grok-4.3"
    )
    assert (
        bootstrap.Settings.model_fields[
            "structured_recommendation_max_output_tokens"
        ].default
        == 2048
    )
    assert (
        bootstrap.Settings.model_fields[
            "structured_recommendation_max_concurrent_requests"
        ].default
        == 2
    )
    write_source = inspect.getsource(bootstrap.write_env)
    main_source = inspect.getsource(bootstrap.main)
    assert "STRUCTURED_RECOMMENDATION_MODEL={quote('xai.grok-4.3')}" in write_source
    assert "STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS={quote('2048')}" in write_source
    assert "STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS={quote('2')}" in write_source
    assert '"STRUCTURED_RECOMMENDATION_MODEL": "xai.grok-4.3"' in main_source
    assert '"STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS": "2048"' in main_source
    assert '"STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS": "2"' in main_source
    assert 'STRUCTURED_RECOMMENDATION_MODEL="xai.grok-4.3"' in restore
    assert 'STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS="2048"' in restore
    assert 'STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS="2"' in restore
    assert 'RECOMMENDATION_CANDIDATE_LIMIT="100"' in restore
    assert 'RECOMMENDATION_LLM_SHORTLIST_LIMIT="15"' in restore
    assert 'RECOMMENDATION_LLM_PASSAGES_PER_MENU="2"' in restore
    assert 'RECOMMENDATION_LLM_SELECTION_ENABLED="true"' in restore
    assert 'OCI_GENAI_STRUCTURED_OUTPUT_ENABLED="false"' in restore
    assert 'OCI_GENAI_STREAMING_ENABLED="false"' in restore


def test_grok_43_release_envelope_is_persisted() -> None:
    assert bootstrap.Settings.model_fields["oci_genai_max_input_tokens"].default == 131072
    assert bootstrap.Settings.model_fields["llm_max_input_tokens"].default == 131072
    assert bootstrap.Settings.model_fields["oci_genai_max_output_tokens"].default == 4096
    assert bootstrap.Settings.model_fields["llm_max_output_tokens"].default == 4096
    source = inspect.getsource(bootstrap.persist_runtime_release_policy)
    for key in (
        "OCI_GENAI_MAX_INPUT_TOKENS",
        "LLM_MAX_INPUT_TOKENS",
        "OCI_GENAI_MAX_OUTPUT_TOKENS",
        "LLM_MAX_OUTPUT_TOKENS",
        "STRUCTURED_RECOMMENDATION_MODEL",
        "STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS",
        "STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS",
        "RECOMMENDATION_LLM_PASSAGES_PER_MENU",
        "OCI_GENAI_STRUCTURED_OUTPUT_ENABLED",
        "OCI_GENAI_STREAMING_ENABLED",
    ):
        assert key in source


def test_release_policy_rejects_duplicate_embedding_provider_without_writing(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "yobi.env"
    original = (
        'OCI_COMPARTMENT_ID="ocid1.compartment.synthetic"\n'
        'LLM_MAX_RETRIES="0"\n'
        'EMBEDDING_PROVIDER="auto"\n'
        'EMBEDDING_PROVIDER="oci"\n'
    )
    runtime_env.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit, match="duplicate EMBEDDING_PROVIDER"):
        bootstrap.persist_runtime_release_policy(runtime_env)

    assert runtime_env.read_text(encoding="utf-8") == original


def test_runtime_environment_load_disables_interpolation_and_execution(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    command_marker = tmp_path / "command-ran"
    backtick_marker = tmp_path / "backtick-ran"
    literal = (
        f"literal-${{HOME}}-$(touch {command_marker})"
        f"-`touch {backtick_marker}`-$HOME"
    )
    runtime_env = tmp_path / "yobi.env"
    runtime_env.write_text(
        "\n".join(
            (
                'ADB_DSN="synthetic-dsn"',
                f'DB_PASSWORD="{literal}"',
                'OCI_GENAI_API_KEY="synthetic-key"',
                'DEMO_CONTROL_TOKEN="synthetic-token"',
                'OCI_COMPARTMENT_ID="ocid1.compartment.synthetic"',
                'LLM_MAX_RETRIES="1"',
                'EMBEDDING_PROVIDER="deterministic"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "RUNTIME_ENV", runtime_env)
    monkeypatch.setenv("HOME", "expanded-home")

    try:
        assert bootstrap.load_runtime_env() is True
        assert os.environ["DB_PASSWORD"] == literal
        assert not command_marker.exists()
        assert not backtick_marker.exists()
    finally:
        for key in (
            "ADB_DSN",
            "DB_PASSWORD",
            "OCI_GENAI_API_KEY",
            "DEMO_CONTROL_TOKEN",
            "LLM_MAX_RETRIES",
            "EMBEDDING_PROVIDER",
            "OCI_EMBED_AUTH",
            "OCI_COMPARTMENT_ID",
            "STRUCTURED_RECOMMENDATION_MODEL",
            "STRUCTURED_RECOMMENDATION_MAX_OUTPUT_TOKENS",
            "STRUCTURED_RECOMMENDATION_MAX_CONCURRENT_REQUESTS",
            "RECOMMENDATION_CANDIDATE_LIMIT",
            "RECOMMENDATION_LLM_SHORTLIST_LIMIT",
            "RECOMMENDATION_LLM_SELECTION_ENABLED",
            "OCI_GENAI_STRUCTURED_OUTPUT_ENABLED",
            "OCI_GENAI_STREAMING_ENABLED",
        ):
            os.environ.pop(key, None)


def test_environment_is_persisted_before_genai_smoke() -> None:
    source = inspect.getsource(bootstrap.main)
    assert source.index("write_env(") < source.index('checkpoint_status("genai_smoke")')


def test_release_policy_requires_embedding_identity_before_writing(tmp_path: Path) -> None:
    runtime_env = tmp_path / "yobi.env"
    original = 'EMBEDDING_PROVIDER="deterministic"\n'
    runtime_env.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit, match="OCI_COMPARTMENT_ID"):
        bootstrap.persist_runtime_release_policy(runtime_env)

    assert runtime_env.read_text(encoding="utf-8") == original


def test_runtime_compartment_identity_is_added_without_rewriting_secrets(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "yobi.env"
    original = 'DB_PASSWORD="synthetic-secret"\nEMBEDDING_PROVIDER="deterministic"\n'
    runtime_env.write_text(original, encoding="utf-8")

    assert bootstrap.persist_runtime_compartment_identity(
        "ocid1.compartment.oc1..synthetic",
        runtime_env,
    ) is True
    persisted = runtime_env.read_text(encoding="utf-8")
    assert persisted.startswith(original)
    assert persisted.endswith(
        'OCI_COMPARTMENT_ID="ocid1.compartment.oc1..synthetic"\n'
    )
    assert stat.S_IMODE(runtime_env.stat().st_mode) == 0o600
    assert bootstrap.persist_runtime_compartment_identity(
        "ocid1.compartment.oc1..synthetic",
        runtime_env,
    ) is False


def test_runtime_compartment_identity_rejects_conflict_without_writing(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "yobi.env"
    original = 'OCI_COMPARTMENT_ID="ocid1.compartment.oc1..first"\n'
    runtime_env.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit, match="conflicts with deployment target"):
        bootstrap.persist_runtime_compartment_identity(
            "ocid1.compartment.oc1..second",
            runtime_env,
        )

    assert runtime_env.read_text(encoding="utf-8") == original


def test_bootstrap_requires_every_migration_shipped_in_the_release() -> None:
    records = bootstrap.expected_migration_records()

    assert records["005"][0] == "005_conversation_state.sql"
    assert records["006"][0] == "006_knowledge_graph.sql"
    assert records["007"][0] == "007_service_area_and_mutation_idempotency.sql"
    assert records["008"][0] == "008_checkout_cart_version.sql"
    assert records["009"][0] == "009_cart_confirmation_fingerprint.sql"
    assert records["010"][0] == "010_structured_hybrid_rag_recommendation.sql"
    assert records["011"][0] == "011_external_catalog_import.sql"
    assert records["012"][0] == "012_concept_preference_support_and_server_ranking.sql"
    assert records["013"][0] == "013_menu_preference_features_and_hybrid_rank.sql"
    assert records["014"][0] == "014_wiki_eligibility_indexes.sql"
    assert all(len(checksum) == 64 for _, checksum in records.values())


def test_prewarm_does_not_duplicate_genai_inference() -> None:
    source = (ROOT / "scripts" / "prewarm.py").read_text(encoding="utf-8")
    assert "responses.create" not in source


def test_degraded_primary_smoke_continues_to_fallback_checkpoints() -> None:
    source = inspect.getsource(bootstrap.main)
    degraded = source.index('"genai_smoke",\n                "degraded"')
    fallback = source.index('checkpoint_complete("fallback_model_smoke")')
    deterministic = source.index('checkpoint_complete("deterministic_fallback_smoke")')
    assert degraded < fallback < deterministic


def test_service_checkpoint_is_written_only_after_health_and_ready() -> None:
    source = inspect.getsource(bootstrap.main)
    health_ready = source.index('checkpoint("health_ready", "complete"')
    services_complete = source.index('checkpoint("services", "complete")')
    assert health_ready < services_complete


def test_external_bootstrap_restores_demo_address_before_catalog_verification() -> None:
    source = inspect.getsource(bootstrap.main)
    apply_address = source.index('"manage_demo_address.py"), "--apply"')
    verify_address = source.index('"manage_demo_address.py"),\n                "--verify-only"')
    verify_catalog = source.index('"catalog_mode.py"), "verify-external"')

    assert apply_address < verify_address < verify_catalog

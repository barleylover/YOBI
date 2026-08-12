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
    assert 'LLM_MAX_RETRIES="1"' in persisted
    assert 'LLM_MAX_RETRIES="0"' not in persisted
    assert 'EMBEDDING_PROVIDER="deterministic"' in persisted
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
    ):
        os.environ.pop(key, None)


def test_retry_policy_matches_settings_and_runtime_restore() -> None:
    assert bootstrap.Settings.model_fields["llm_max_retries"].default == 1
    assert "quote('1')" in inspect.getsource(bootstrap.write_env)
    assert '"LLM_MAX_RETRIES": "1"' in inspect.getsource(bootstrap.main)
    restore = (ROOT / "deploy" / "restore_runtime_env.sh").read_text(encoding="utf-8")
    assert "LLM_MAX_RETRIES=\"1\"" in restore
    assert "LLM_MAX_RETRIES=\"0\"" not in restore
    assert bootstrap.Settings.model_fields["embedding_provider"].default == "deterministic"
    assert "quote('deterministic')" in inspect.getsource(bootstrap.write_env)
    assert 'EMBEDDING_PROVIDER="deterministic"' in restore


def test_release_policy_rejects_duplicate_embedding_provider_without_writing(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "yobi.env"
    original = (
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
        ):
            os.environ.pop(key, None)


def test_environment_is_persisted_before_genai_smoke() -> None:
    source = inspect.getsource(bootstrap.main)
    assert source.index("write_env(") < source.index('checkpoint_status("genai_smoke")')


def test_bootstrap_requires_every_migration_shipped_in_the_release() -> None:
    records = bootstrap.expected_migration_records()

    assert records["005"][0] == "005_conversation_state.sql"
    assert records["006"][0] == "006_knowledge_graph.sql"
    assert records["007"][0] == "007_service_area_and_mutation_idempotency.sql"
    assert records["008"][0] == "008_checkout_cart_version.sql"
    assert records["009"][0] == "009_cart_confirmation_fingerprint.sql"
    assert records["010"][0] == "010_structured_hybrid_rag_recommendation.sql"
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

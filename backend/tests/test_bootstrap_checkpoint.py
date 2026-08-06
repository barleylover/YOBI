from __future__ import annotations

import importlib.util
import inspect
import os
import stat
from pathlib import Path

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


def test_runtime_environment_can_resume_without_prompting(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    runtime_env = tmp_path / "yobi.env"
    runtime_env.write_text(
        '\n'.join(
            [
                'ADB_DSN="synthetic-dsn"',
                'DB_PASSWORD="synthetic-password"',
                'OCI_GENAI_API_KEY="synthetic-api-key"',
                'DEMO_CONTROL_TOKEN="synthetic-token"',
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


def test_environment_is_persisted_before_genai_smoke() -> None:
    source = inspect.getsource(bootstrap.main)
    assert source.index("write_env(") < source.index('checkpoint_status("genai_smoke")')


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

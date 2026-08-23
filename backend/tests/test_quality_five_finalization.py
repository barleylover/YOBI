from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "finalize_quality_five_release.sh"


def test_quality_five_finalizer_is_syntax_valid_and_fail_closed() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"${YOBI_GUARDED_SSH_WINDOW:-}" == "1"' in source
    assert '"${YOBI_GUARDED_NLB_WINDOW:-}" == "1"' in source
    assert '"${YOBI_GUARDED_LB_WINDOW:-}" == "1"' in source
    assert '"$PORT" == "443"' in source
    assert '-S "$CONTROL_PATH"' in source
    assert "payload.get(\"requested\") == 5" in source
    assert "len(cases) == 5" in source
    assert '"SOUTHEAST_ASIAN", "MEXICAN"' in source
    assert 'payload.get("expansion_cuisine_coverage_complete") is True' in source
    assert '"$(readlink -f /opt/yobi/current)" == "$release_path"' in source
    assert "performance-gate=pending|quality-five-gate=pending" in source
    assert "full30=operator-superseded" in source
    assert 'rm -f -- "$provisional_marker"' in source
    assert source.index('tee "$final_marker"') < source.index(
        'rm -f -- "$provisional_marker"'
    )
    assert source.count("http://127.0.0.1/healthz") == 2
    assert source.count("http://127.0.0.1/readyz") == 2

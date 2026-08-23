from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "deploy" / "run_with_runtime_env.py"


def test_runtime_env_values_are_not_interpolated_or_executed(tmp_path: Path) -> None:
    command_substitution_marker = tmp_path / "command-substitution-ran"
    backtick_marker = tmp_path / "backtick-ran"
    literal = (
        f"prefix$(touch {command_substitution_marker})"
        f"`touch {backtick_marker}`"
        "-${YOBI_INTERPOLATION_SENTINEL}-$YOBI_INTERPOLATION_SENTINEL"
    )
    runtime_env = tmp_path / "yobi.env"
    runtime_env.write_text(f'YOBI_LITERAL="{literal}"\n', encoding="utf-8")
    child = "import json, os; print(json.dumps(os.environ['YOBI_LITERAL']))"

    result = subprocess.run(
        [sys.executable, str(RUNNER), str(runtime_env), sys.executable, "-c", child],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "YOBI_INTERPOLATION_SENTINEL": "expanded"},
    )

    assert json.loads(result.stdout) == literal
    assert not command_substitution_marker.exists()
    assert not backtick_marker.exists()

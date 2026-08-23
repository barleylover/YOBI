from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values


def load_environment(path: Path) -> dict[str, str]:
    """Load a dotenv file as data, never as shell source code."""

    if path.is_symlink() or not path.is_file():
        raise SystemExit("Runtime environment must be a regular file")
    values = dotenv_values(path, interpolate=False)
    invalid = sorted(key for key, value in values.items() if value is None)
    if invalid:
        raise SystemExit("Runtime environment contains a value without an assignment")
    return {key: value for key, value in values.items() if value is not None}


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: run_with_runtime_env.py ENV_FILE COMMAND [ARG ...]"
        )
    environment = os.environ.copy()
    environment.update(load_environment(Path(sys.argv[1])))
    command = sys.argv[2:]
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    main()

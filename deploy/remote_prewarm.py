#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path("/opt/yobi/current")
ENV_FILE = Path("/etc/yobi/yobi.env")


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo so the protected runtime environment can be read")
    if not ENV_FILE.is_file():
        raise SystemExit("Secure bootstrap has not created /etc/yobi/yobi.env")
    values = dotenv_values(ENV_FILE)
    runtime_env = {**os.environ}
    runtime_env.update({key: value for key, value in values.items() if value is not None})
    runtime_env["YOBI_PREWARM_BASE_URL"] = "http://127.0.0.1"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prewarm.py")],
        check=True,
        env=runtime_env,
    )


if __name__ == "__main__":
    main()

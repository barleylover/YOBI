#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    parser.add_argument("--base-url", default=os.getenv("YOBI_BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    response = httpx.post(
        f"{args.base_url.rstrip('/')}/api/v1/sessions/{args.session_id}/reset", timeout=20
    )
    response.raise_for_status()
    print("Demo session reset; deterministic catalog preserved.")


if __name__ == "__main__":
    main()


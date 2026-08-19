#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge.wiki_quality import audit_wiki_quality
from build_external_knowledge_release import (
    _authored_documents,
    build_support_rows,
    compile_external_release,
)


def main() -> None:
    documents = _authored_documents()
    compiled = compile_external_release("wiki-quality-audit-catalog")
    report = audit_wiki_quality(documents, compiled, build_support_rows(compiled))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()

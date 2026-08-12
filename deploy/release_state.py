#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

CONTROL_ROOT = Path("/opt/yobi/shared/control")
RELEASE_STATE_ROOT = CONTROL_ROOT / "release-state"
PREVIOUS_RELEASE_RECORD = CONTROL_ROOT / "previous_release"
LEGACY_PREVIOUS_RELEASE_RECORD = Path("/opt/yobi/shared/previous_release")
RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
KNOWLEDGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
RECOMMENDATION_FAMILY_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STATE_FIELDS = (
    "knowledge_release_id",
    "previous_knowledge_release_id",
    "recommendation_release_family_id",
    "previous_recommendation_release_family_id",
)


class ReleaseStateError(RuntimeError):
    """Stable error code for root-owned deployment provenance state."""


def _validate_release_id(value: str) -> str:
    if RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise ReleaseStateError("RELEASE_STATE_RELEASE_ID_INVALID")
    return value


def _validate_knowledge_id(value: str | None) -> str | None:
    if value is not None and KNOWLEDGE_ID_PATTERN.fullmatch(value) is None:
        raise ReleaseStateError("RELEASE_STATE_KNOWLEDGE_ID_INVALID")
    return value


def _validate_recommendation_family_id(value: str | None) -> str | None:
    if (
        value is not None
        and RECOMMENDATION_FAMILY_ID_PATTERN.fullmatch(value) is None
    ):
        raise ReleaseStateError("RELEASE_STATE_RECOMMENDATION_FAMILY_ID_INVALID")
    return value


def _validate_sha256(value: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ReleaseStateError("RELEASE_STATE_ARCHIVE_SHA256_INVALID")
    return value


def _require_trusted_directory(
    path: Path,
    *,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        raise ReleaseStateError("RELEASE_STATE_DIRECTORY_MISSING") from None
    if not stat.S_ISDIR(details.st_mode):
        raise ReleaseStateError("RELEASE_STATE_DIRECTORY_INVALID")
    if details.st_uid != trusted_uid or details.st_gid != trusted_gid:
        raise ReleaseStateError("RELEASE_STATE_DIRECTORY_OWNER_INVALID")
    if stat.S_IMODE(details.st_mode) & 0o022:
        raise ReleaseStateError("RELEASE_STATE_DIRECTORY_WRITABLE")


def _atomic_write(
    path: Path,
    payload: bytes,
    *,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
    mode: int = 0o640,
) -> None:
    _require_trusted_directory(
        path.parent,
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, trusted_uid, trusted_gid)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_trusted_bytes(
    path: Path,
    *,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
    validate_parent: bool = True,
) -> bytes:
    if validate_parent:
        _require_trusted_directory(
            path.parent,
            trusted_uid=trusted_uid,
            trusted_gid=trusted_gid,
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise ReleaseStateError("RELEASE_STATE_NOT_FOUND") from None
    except OSError:
        raise ReleaseStateError("RELEASE_STATE_FILE_INVALID") from None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ReleaseStateError("RELEASE_STATE_FILE_INVALID")
        if details.st_uid != trusted_uid or details.st_gid != trusted_gid:
            raise ReleaseStateError("RELEASE_STATE_FILE_OWNER_INVALID")
        if stat.S_IMODE(details.st_mode) & 0o022:
            raise ReleaseStateError("RELEASE_STATE_FILE_WRITABLE")
        payload = os.read(descriptor, 8193)
        if len(payload) > 8192:
            raise ReleaseStateError("RELEASE_STATE_FILE_TOO_LARGE")
        return payload
    finally:
        os.close(descriptor)


def atomic_write_control_file(
    path: Path,
    payload: bytes,
    *,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
    mode: int = 0o640,
) -> None:
    _atomic_write(
        path,
        payload,
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
        mode=mode,
    )


def read_control_file(
    path: Path,
    *,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
    validate_parent: bool = True,
) -> bytes:
    return _read_trusted_bytes(
        path,
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
        validate_parent=validate_parent,
    )


def write_release_state(
    release_id: str,
    archive_sha256: str,
    previous_knowledge_release_id: str | None,
    knowledge_release_id: str,
    *,
    previous_recommendation_release_family_id: str | None = None,
    recommendation_release_family_id: str | None = None,
    state_root: Path = RELEASE_STATE_ROOT,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
) -> Path:
    release_id = _validate_release_id(release_id)
    state = {
        "version": 2,
        "release_id": release_id,
        "archive_sha256": _validate_sha256(archive_sha256),
        "previous_knowledge_release_id": _validate_knowledge_id(
            previous_knowledge_release_id
        ),
        "knowledge_release_id": _validate_knowledge_id(knowledge_release_id),
        "previous_recommendation_release_family_id": (
            _validate_recommendation_family_id(
                previous_recommendation_release_family_id
            )
        ),
        "recommendation_release_family_id": _validate_recommendation_family_id(
            recommendation_release_family_id
        ),
    }
    path = state_root / f"{release_id}.json"
    payload = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _atomic_write(
        path,
        payload,
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
    )
    return path


def read_release_state(
    release_id: str,
    *,
    state_root: Path = RELEASE_STATE_ROOT,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
) -> dict[str, Any]:
    release_id = _validate_release_id(release_id)
    payload = _read_trusted_bytes(
        state_root / f"{release_id}.json",
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
    )
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReleaseStateError("RELEASE_STATE_JSON_INVALID") from None
    if not isinstance(parsed, dict):
        raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
    version = parsed.get("version")
    v1_fields = {
        "version",
        "release_id",
        "archive_sha256",
        "previous_knowledge_release_id",
        "knowledge_release_id",
    }
    v2_fields = {
        *v1_fields,
        "previous_recommendation_release_family_id",
        "recommendation_release_family_id",
    }
    if (
        version not in {1, 2}
        or set(parsed) != (v1_fields if version == 1 else v2_fields)
        or parsed["release_id"] != release_id
    ):
        raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
    _validate_sha256(str(parsed["archive_sha256"]))
    previous = parsed["previous_knowledge_release_id"]
    current = parsed["knowledge_release_id"]
    if previous is not None and not isinstance(previous, str):
        raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
    if not isinstance(current, str):
        raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
    _validate_knowledge_id(previous)
    _validate_knowledge_id(current)
    if version == 1:
        parsed["previous_recommendation_release_family_id"] = None
        parsed["recommendation_release_family_id"] = None
    else:
        previous_family = parsed["previous_recommendation_release_family_id"]
        current_family = parsed["recommendation_release_family_id"]
        if previous_family is not None and not isinstance(previous_family, str):
            raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
        if current_family is not None and not isinstance(current_family, str):
            raise ReleaseStateError("RELEASE_STATE_SCHEMA_INVALID")
        _validate_recommendation_family_id(previous_family)
        _validate_recommendation_family_id(current_family)
    return parsed


def write_previous_release(
    release_id: str,
    *,
    path: Path = PREVIOUS_RELEASE_RECORD,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
) -> None:
    release_id = _validate_release_id(release_id)
    _atomic_write(
        path,
        f"{release_id}\n".encode(),
        trusted_uid=trusted_uid,
        trusted_gid=trusted_gid,
    )


def read_previous_release(
    *,
    path: Path = PREVIOUS_RELEASE_RECORD,
    legacy_path: Path | None = None,
    trusted_uid: int = 0,
    trusted_gid: int = 0,
) -> str:
    try:
        payload = _read_trusted_bytes(
            path,
            trusted_uid=trusted_uid,
            trusted_gid=trusted_gid,
        )
    except ReleaseStateError as exc:
        if str(exc) != "RELEASE_STATE_NOT_FOUND" or legacy_path is None:
            raise
        payload = _read_trusted_bytes(
            legacy_path,
            trusted_uid=trusted_uid,
            trusted_gid=trusted_gid,
            validate_parent=False,
        )
    try:
        value = payload.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ReleaseStateError("RELEASE_STATE_PREVIOUS_INVALID") from None
    return _validate_release_id(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage trusted YOBI release provenance")
    subcommands = parser.add_subparsers(dest="command", required=True)
    write = subcommands.add_parser("write-state")
    write.add_argument("release_id")
    write.add_argument("archive_sha256")
    write.add_argument("knowledge_release_id")
    write.add_argument("--previous-knowledge-release-id")
    write.add_argument("--recommendation-release-family-id")
    write.add_argument("--previous-recommendation-release-family-id")
    read = subcommands.add_parser("read-field")
    read.add_argument("release_id")
    read.add_argument("field", choices=STATE_FIELDS)
    read.add_argument("--allow-missing", action="store_true")
    previous_write = subcommands.add_parser("write-previous")
    previous_write.add_argument("release_id")
    previous_read = subcommands.add_parser("read-previous")
    previous_read.add_argument("--allow-legacy", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "write-state":
            write_release_state(
                args.release_id,
                args.archive_sha256,
                args.previous_knowledge_release_id,
                args.knowledge_release_id,
                previous_recommendation_release_family_id=(
                    args.previous_recommendation_release_family_id
                ),
                recommendation_release_family_id=(
                    args.recommendation_release_family_id
                ),
            )
        elif args.command == "read-field":
            try:
                state = read_release_state(args.release_id)
            except ReleaseStateError as exc:
                if str(exc) == "RELEASE_STATE_NOT_FOUND" and args.allow_missing:
                    print()
                    return 0
                raise
            value = state[args.field]
            print(value if value is not None else "")
        elif args.command == "write-previous":
            write_previous_release(args.release_id)
        else:
            legacy = LEGACY_PREVIOUS_RELEASE_RECORD if args.allow_legacy else None
            print(read_previous_release(legacy_path=legacy))
    except ReleaseStateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

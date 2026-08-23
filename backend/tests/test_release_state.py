from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_release_state",
    ROOT / "deploy" / "release_state.py",
)
assert SPEC and SPEC.loader
release_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_state)


@pytest.fixture
def trusted_ids() -> tuple[int, int]:
    return os.geteuid(), os.getegid()


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    path = tmp_path / "release-state"
    path.mkdir(mode=0o750)
    return path


def test_release_state_preserves_null_previous_and_replaces_symlink_atomically(
    tmp_path: Path,
    state_root: Path,
    trusted_ids: tuple[int, int],
) -> None:
    uid, gid = trusted_ids
    release_id = "20260809T000000Z-123456789abc"
    target = state_root / f"{release_id}.json"
    victim = tmp_path / "victim.json"
    victim.write_text("do not overwrite", encoding="utf-8")
    target.symlink_to(victim)

    release_state.write_release_state(
        release_id,
        "a" * 64,
        None,
        "knowledge-demo-new",
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )

    assert victim.read_text(encoding="utf-8") == "do not overwrite"
    assert target.is_file() and not target.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    stored = release_state.read_release_state(
        release_id,
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )
    assert stored["previous_knowledge_release_id"] is None
    assert stored["knowledge_release_id"] == "knowledge-demo-new"
    assert stored["recommendation_release_family_id"] is None


def test_release_state_round_trips_recommendation_family_and_reads_v1(
    state_root: Path,
    trusted_ids: tuple[int, int],
) -> None:
    uid, gid = trusted_ids
    release_id = "release-v2"
    release_state.write_release_state(
        release_id,
        "c" * 64,
        "knowledge-old",
        "knowledge-new",
        previous_recommendation_release_family_id="family-old",
        recommendation_release_family_id="family-new",
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )
    stored = release_state.read_release_state(
        release_id,
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )
    assert stored["version"] == 2
    assert stored["previous_recommendation_release_family_id"] == "family-old"
    assert stored["recommendation_release_family_id"] == "family-new"

    legacy_id = "release-v1"
    legacy = {
        "version": 1,
        "release_id": legacy_id,
        "archive_sha256": "d" * 64,
        "previous_knowledge_release_id": None,
        "knowledge_release_id": "knowledge-legacy",
    }
    legacy_path = state_root / f"{legacy_id}.json"
    legacy_path.write_text(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    legacy_path.chmod(0o640)
    read_legacy = release_state.read_release_state(
        legacy_id,
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )
    assert read_legacy["version"] == 1
    assert read_legacy["recommendation_release_family_id"] is None
    assert read_legacy["previous_recommendation_release_family_id"] is None


def test_release_state_rejects_untrusted_directory_or_writable_file(
    state_root: Path,
    trusted_ids: tuple[int, int],
) -> None:
    uid, gid = trusted_ids
    release_id = "release-safe"
    state_root.chmod(0o770)
    with pytest.raises(
        release_state.ReleaseStateError,
        match="RELEASE_STATE_DIRECTORY_WRITABLE",
    ):
        release_state.write_release_state(
            release_id,
            "b" * 64,
            "knowledge-demo-old",
            "knowledge-demo-new",
            state_root=state_root,
            trusted_uid=uid,
            trusted_gid=gid,
        )

    state_root.chmod(0o750)
    path = release_state.write_release_state(
        release_id,
        "b" * 64,
        "knowledge-demo-old",
        "knowledge-demo-new",
        state_root=state_root,
        trusted_uid=uid,
        trusted_gid=gid,
    )
    path.chmod(0o660)
    with pytest.raises(
        release_state.ReleaseStateError,
        match="RELEASE_STATE_FILE_WRITABLE",
    ):
        release_state.read_release_state(
            release_id,
            state_root=state_root,
            trusted_uid=uid,
            trusted_gid=gid,
        )


def test_previous_release_legacy_read_is_nofollow_and_validated(
    tmp_path: Path,
    trusted_ids: tuple[int, int],
) -> None:
    uid, gid = trusted_ids
    control = tmp_path / "control"
    control.mkdir(mode=0o750)
    record = control / "previous_release"
    legacy = tmp_path / "legacy_previous"
    legacy.write_text("release-legacy\n", encoding="ascii")
    legacy.chmod(0o640)

    assert (
        release_state.read_previous_release(
            path=record,
            legacy_path=legacy,
            trusted_uid=uid,
            trusted_gid=gid,
        )
        == "release-legacy"
    )

    with pytest.raises(
        release_state.ReleaseStateError,
        match="RELEASE_STATE_FILE_OWNER_INVALID",
    ):
        release_state._read_trusted_bytes(
            legacy,
            trusted_uid=uid + 1,
            trusted_gid=gid,
            validate_parent=False,
        )

    victim = tmp_path / "untrusted"
    victim.write_text("release-attacker\n", encoding="ascii")
    legacy.unlink()
    legacy.symlink_to(victim)
    with pytest.raises(
        release_state.ReleaseStateError,
        match="RELEASE_STATE_FILE_INVALID",
    ):
        release_state.read_previous_release(
            path=record,
            legacy_path=legacy,
            trusted_uid=uid,
            trusted_gid=gid,
        )


def test_previous_release_write_replaces_fixed_symlink_without_following(
    tmp_path: Path,
    trusted_ids: tuple[int, int],
) -> None:
    uid, gid = trusted_ids
    control = tmp_path / "control"
    control.mkdir(mode=0o750)
    record = control / "previous_release"
    victim = tmp_path / "victim"
    victim.write_text("unchanged", encoding="ascii")
    record.symlink_to(victim)

    release_state.write_previous_release(
        "release-new",
        path=record,
        trusted_uid=uid,
        trusted_gid=gid,
    )

    assert victim.read_text(encoding="ascii") == "unchanged"
    assert record.read_text(encoding="ascii") == "release-new\n"
    assert not record.is_symlink()

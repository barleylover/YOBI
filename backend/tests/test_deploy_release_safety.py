from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_release_archive_contains_knowledge_and_all_migrations() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert "backend frontend/dist database deploy scripts knowledge" in source
    assert "001_core_schema.sql" in source
    assert "002_knowledge_and_cache.sql" in source
    assert "003_normalized_catalog_safety.sql" in source
    assert "004_three_level_spice.sql" in source
    assert "005_conversation_state.sql" in source
    assert "006_knowledge_graph.sql" in source
    assert "007_service_area_and_mutation_idempotency.sql" in source
    assert "008_checkout_cart_version.sql" in source
    assert "persist_runtime_release_policy" in source
    assert "actual_migration_list" in source
    assert "Migration directory must contain exactly 001-008" in source
    assert 'status["expected_migration_count"] == status["applied_migration_count"] == 8' in source
    assert 'status["latest_expected_migration"]' in source
    assert 'status["latest_applied_migration"]' in source
    assert 'raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")' in source
    assert "assert status[" not in source
    migration = source.index('"$new_release/scripts/migrate.py"')
    exact_gate = source.index('raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")')
    active_snapshot = source.index('old_knowledge_release_id="$(run_knowledge_manager get-active)"')
    seed = source.index('"$new_release/scripts/seed_demo.py" --upsert')
    assert migration < exact_gate < active_snapshot < seed


def test_deploy_loads_runtime_environment_without_shell_source() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert "source /etc/yobi/yobi.env" not in source
    assert source.count('"${runtime_env_runner[@]}"') == 4
    assert "run_with_runtime_env.py" in source


def test_release_identity_and_failure_restore_are_verified() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert 'ARCHIVE_SHA256="$(shasum -a 256 "$archive"' in deploy_source
    assert 'sha256sum "$remote_archive"' in deploy_source
    assert 'REMOTE_ARCHIVE="/home/${SSH_USER}/.yobi-release-${RELEASE_ID}-${ARCHIVE_NONCE}.tar.gz"' in deploy_source
    assert 'remote_archive="$3"' in deploy_source
    assert 'archive_owner="$(stat -c \'%U\' "$remote_archive")"' in deploy_source
    assert "cleanup_remote_archive" in deploy_source
    assert "/tmp/yobi-release.tar.gz" not in deploy_source
    assert ".yobi-release-manifest" in deploy_source
    assert "restore_old_release" in deploy_source
    assert "verify_old_release_on_failure" in deploy_source
    assert "Failed deployment retained release_id=" in deploy_source
    assert "Restored release_id=" in deploy_source
    assert "restore_original_release" in rollback_source
    assert "Restored release_id=" in rollback_source
    restore_bodies = (
        deploy_source.split("restore_old_release() {", 1)[1].split("}\n", 1)[0],
        rollback_source.split("restore_original_release() {", 1)[1].split("}\n", 1)[0],
    )
    for restore_body in restore_bodies:
        assert "check_local_services" in restore_body
        assert "readlink -f" in restore_body


def test_deploy_and_rollback_share_a_nonblocking_root_lock() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    for source in (deploy_source, rollback_source):
        assert 'DEPLOY_LOCK="/run/lock/yobi-deploy.lock"' in source
        assert 'flock -n "$deployment_lock_fd"' in source
        assert 'chmod 0600 "$DEPLOY_LOCK"' in source
        assert "Another YOBI deploy or rollback is already running." in source
    assert '"sudo -n bash -s --' in deploy_source


def test_release_roots_and_historical_targets_are_hardened_before_use() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")
    install_source = (ROOT / "deploy" / "install_vm.sh").read_text(encoding="utf-8")

    for source in (deploy_source, rollback_source):
        assert 'chown root:yobi "$RELEASES_ROOT"' in source
        assert 'chmod 0755 "$RELEASES_ROOT"' in source
        assert "chown -R --no-dereference root:yobi" in source
        assert "-perm /022 -print -quit" in source
        assert "validate_release_path" in source
    assert deploy_source.index('chmod 0755 "$RELEASES_ROOT"') < deploy_source.index(
        '[[ ! -e "$new_release" ]]'
    )
    assert deploy_source.index('harden_release_tree "$old_release"') < deploy_source.index(
        'write_ready_marker "$old_release"'
    )
    assert rollback_source.index('harden_release_tree "$current"') < rollback_source.index(
        'state_manager="$current/deploy/release_state.py"'
    )
    assert rollback_source.index('harden_release_tree "$target"') < rollback_source.index(
        '[[ -f "$target/$READY_MARKER"'
    )
    assert "rm -f -- \"$marker_path\"" in deploy_source
    assert "root:yobi:644" in deploy_source
    assert "install -d -o root -g root -m 0755 /opt/yobi" in install_source
    assert "install -d -o root -g yobi -m 0755 /opt/yobi/releases" in install_source
    assert "chown -R yobi:yobi" not in deploy_source


def test_rollback_exit_restores_legacy_targets_after_activation_starts() -> None:
    source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert "rollback_activation_started=false" in source
    assert source.count("rollback_activation_started=true") == 2
    restore_trap = source.split("restore_on_failure() {", 1)[1].split("}\n", 1)[0]
    assert '"$rollback_activation_started" == true' in restore_trap
    assert "restore_original_release" in restore_trap
    legacy_activation = "else\n  rollback_activation_started=true\nfi\n\nln -sfn"
    assert legacy_activation in source
    assert source.index(legacy_activation) < source.index('ln -sfn "$target" "$CURRENT_LINK"')


def test_success_commit_markers_precede_restore_flag_cleanup() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert deploy_source.rindex("deployment_complete=true") < deploy_source.rindex(
        "knowledge_restore_required=false"
    )
    assert rollback_source.rindex("rollback_complete=true") < rollback_source.rindex(
        "knowledge_restore_required=false"
    )
    assert rollback_source.rindex("rollback_complete=true") < rollback_source.rindex(
        "rollback_activation_started=false"
    )


def test_spa_and_asset_locations_retain_security_headers() -> None:
    source = (ROOT / "deploy" / "nginx" / "yobi.conf").read_text(encoding="utf-8")
    asset_location = source.split("location /assets/ {", 1)[1].split("\n    }", 1)[0]
    root_location = source.split("location / {", 1)[1].split("\n    }", 1)[0]
    required = (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
        'add_header X-Frame-Options "DENY" always;',
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
    )

    for location in (asset_location, root_location):
        assert all(header in location for header in required)


def test_rollback_uses_recorded_verified_target_not_directory_sorting() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert ".yobi-release-ready" in deploy_source
    assert "write-previous" in deploy_source
    assert 'READY_MARKER=".yobi-release-ready"' in rollback_source
    assert 'PREVIOUS_RECORD="$CONTROL_ROOT/previous_release"' in rollback_source
    assert "read-previous --allow-legacy" in rollback_source
    assert "find /opt/yobi/releases" not in rollback_source
    assert "Rollback target was never health-verified" in rollback_source
    assert 'ln -sfn "$current" "$CURRENT_LINK"' in rollback_source


def test_knowledge_release_pointer_is_restored_with_trusted_state() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")
    install_source = (ROOT / "deploy" / "install_vm.sh").read_text(encoding="utf-8")
    unit_source = (ROOT / "deploy" / "systemd" / "yobi-api.service").read_text(
        encoding="utf-8"
    )

    assert "old_knowledge_release_id=\"$(run_knowledge_manager get-active)\"" in deploy_source
    assert "write-state" in deploy_source
    assert "restore_knowledge_release" in deploy_source
    assert "clear-active" in deploy_source
    assert "read-field \"$target_id\" knowledge_release_id --allow-missing" in rollback_source
    assert "restore_original_knowledge" in rollback_source
    assert "lacks trusted state" in rollback_source
    assert "/opt/yobi/shared/control/release-state" in install_source
    assert "ReadWritePaths=/opt/yobi/shared" not in unit_source

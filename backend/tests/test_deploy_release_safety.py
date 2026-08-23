from __future__ import annotations

import ast
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
    assert "009_cart_confirmation_fingerprint.sql" in source
    assert "010_structured_hybrid_rag_recommendation.sql" in source
    assert "011_external_catalog_import.sql" in source
    assert "012_concept_preference_support_and_server_ranking.sql" in source
    assert "013_menu_preference_features_and_hybrid_rank.sql" in source
    assert "014_wiki_eligibility_indexes.sql" in source
    assert "015_synthetic_demo_enrichment.sql" in source
    assert "016_recommendation_v3_runtime.sql" in source
    assert "017_grounded_menu_presentation.sql" in source
    assert "018_llm_runtime_resilience.sql" in source
    assert "019_option_localization_runtime.sql" in source
    assert "020_country_aware_menu_presentation.sql" in source
    assert "persist_runtime_release_policy" in source
    assert "persist_runtime_compartment_identity" in source
    assert 'persist_runtime_compartment_identity(sys.argv[1])' in source
    assert "actual_migration_list" in source
    assert "Migration directory must contain exactly 001-020" in source
    assert 'status["expected_migration_count"] == status["applied_migration_count"] == 20' in source
    assert 'status["latest_expected_migration"]' in source
    assert 'status["latest_applied_migration"]' in source
    assert '== "020"' in source
    assert 'raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")' in source
    assert "assert status[" not in source
    runtime_import = source.index('import app.main; print("Verified Python 3.9 application imports.")')
    migration = source.index('"$new_release/scripts/migrate.py"')
    exact_gate = source.index('raise SystemExit("MIGRATION_LEDGER_NOT_EXACT")')
    active_snapshot = source.index('old_knowledge_release_id="$(run_knowledge_manager get-active)"')
    seed = source.index('"$new_release/scripts/seed_demo.py" --upsert')
    assert runtime_import < migration < exact_gate < active_snapshot < seed
    assert '"$new_release/scripts/catalog_mode.py" get-mode' in source
    assert '"$new_release/scripts/catalog_mode.py" verify-external' in source
    assert '|| "$menu_semantic_backfill" != "true"' in source
    assert "reuse_active_data_releases=true" in source
    assert '&& "$reuse_active_data_releases" != "true"' in source
    assert "including its additive synthetic enrichment pointer" in source
    assert "reusing active knowledge and recommendation family without data rebuilds" in source
    assert '"$new_release/scripts/manage_demo_address.py" --apply' in source
    assert '"$new_release/scripts/manage_demo_address.py" --verify-only' in source
    assert "--stage-only" in source
    assert "--activate-staged" in source
    assert "--scope staged --verify" in source
    assert "--scope active --verify" in source
    assert "recommendation_v2_live_harness.py\" predeploy" in source
    assert '--release-family-id "$new_recommendation_release_family_id"' in source
    assert "verify-external-gates" in source
    assert "release_gate_contract.py" in source
    assert source.index('"$new_release/scripts/manage_demo_address.py" --apply') < source.index(
        '"$new_release/scripts/catalog_mode.py" verify-external'
    )
    assert source.index("--stage-only") < source.index("--scope staged --verify")
    assert source.index("--scope staged --verify") < source.index(
        'sudo ln -sfn "$new_release" /opt/yobi/current'
    )
    assert source.index('"$new_release/scripts/recommendation_v2_live_harness.py" predeploy') < source.index(
        'sudo ln -sfn "$new_release" /opt/yobi/current'
    )
    assert source.index('sudo ln -sfn "$new_release" /opt/yobi/current') < source.index(
        "--activate-staged"
    )


def test_deploy_loads_runtime_environment_without_shell_source() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert "source /etc/yobi/yobi.env" not in source
    assert source.count('"${runtime_env_runner[@]}"') >= 7
    assert "run_with_runtime_env.py" in source
    assert 'PYTHONPATH="$new_release/backend:$new_release"' in source
    assert "structured_recommendation_smoke.py" in source
    assert "structured_fallback_smoke.py" in source
    assert 'readonly QUALITY_FIVE_ONLY="${YOBI_QUALITY_FIVE_ONLY:-false}"' in source
    assert (
        'readonly POST_QUALITY_REVIEW_DEPLOY="${YOBI_POST_QUALITY_REVIEW_DEPLOY:-false}"'
        in source
    )
    assert (
        'readonly MENU_SEMANTIC_BACKFILL="${YOBI_MENU_SEMANTIC_BACKFILL:-false}"'
        in source
    )
    assert "Menu semantic backfill requires the approved zero-provider provisional mode" in source
    assert "Remote menu semantic backfill requires zero-provider provisional mode" in source
    assert '--embedding-provider oci --dispatch-interval-seconds 1 --apply' in source
    assert source.index(
        '--embedding-provider oci --dispatch-interval-seconds 1 --apply'
    ) < source.index(
        '--embedding-provider oci --verify-only'
    )
    assert 'if [[ "$quality_five_only" != "true" \\' in source
    assert '&& "$post_quality_review_deploy" != "true" ]]; then' in source
    assert "live normal generation is covered by exactly five expanded-cuisine cases" in source
    assert "Remote quality-five deployment modes are mutually exclusive" in source
    assert "provider calls were already observed; final deploy performs zero provider calls" in source
    assert "--category-code cuisine_origins --option-code ITALIAN" in source
    assert "verify-reviewed-quality-five" in source
    assert "verify-post-review-external-gates" in source
    assert "COPYFILE_DISABLE=1 tar" in source
    assert "Release archive contains macOS metadata sidecars." in source
    assert "--exclude='.mypy_cache' --exclude='*/.mypy_cache'" in source
    assert "--exclude='.ruff_cache' --exclude='*/.ruff_cache'" in source


def test_python39_deployable_modules_defer_pep604_annotations() -> None:
    offenders: list[str] = []
    syntax_offenders: list[str] = []
    dataclass_slots_offenders: list[str] = []
    for root in (ROOT / "backend" / "app", ROOT / "scripts", ROOT / "deploy"):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            try:
                # ``9`` is accepted by Python 3.9 itself and asks newer runtimes
                # to reject grammar that the OCI VM interpreter cannot parse.
                ast.parse(source, filename=str(path), feature_version=9)
            except SyntaxError:
                syntax_offenders.append(str(path.relative_to(ROOT)))
            module = ast.parse(source)
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "dataclass"
                and any(
                    keyword.arg == "slots"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                )
                for node in ast.walk(module)
            ):
                dataclass_slots_offenders.append(str(path.relative_to(ROOT)))
            deferred = any(
                isinstance(statement, ast.ImportFrom)
                and statement.module == "__future__"
                and any(alias.name == "annotations" for alias in statement.names)
                for statement in module.body
            )
            if deferred:
                continue
            annotations: list[ast.expr] = []
            for node in ast.walk(module):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    annotations.extend(
                        argument.annotation
                        for argument in (
                            *node.args.posonlyargs,
                            *node.args.args,
                            *node.args.kwonlyargs,
                        )
                        if argument.annotation is not None
                    )
                    if node.args.vararg and node.args.vararg.annotation:
                        annotations.append(node.args.vararg.annotation)
                    if node.args.kwarg and node.args.kwarg.annotation:
                        annotations.append(node.args.kwarg.annotation)
                    if node.returns is not None:
                        annotations.append(node.returns)
                elif isinstance(node, ast.AnnAssign):
                    annotations.append(node.annotation)
            if any(
                isinstance(part, ast.BinOp) and isinstance(part.op, ast.BitOr)
                for annotation in annotations
                for part in ast.walk(annotation)
            ):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
    assert syntax_offenders == []
    assert dataclass_slots_offenders == []


def test_release_identity_and_failure_restore_are_verified() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert 'ARCHIVE_SHA256="$(shasum -a 256 "$archive"' in deploy_source
    assert "Deployment requires a clean Git worktree." in deploy_source
    assert "Deployment requires HEAD to match the pushed origin branch." in deploy_source
    assert 'source_git_commit="$(git -C "$ROOT_DIR" rev-parse --verify HEAD)"' in deploy_source
    assert "source_git_commit=%s" in deploy_source
    assert 'sha256sum "$remote_archive"' in deploy_source
    assert 'REMOTE_ARCHIVE="/home/${SSH_USER}/.yobi-release-${RELEASE_ID}-${ARCHIVE_NONCE}.tar.gz"' in deploy_source
    assert 'ssh -T -p "$ssh_port"' in deploy_source
    assert 'ARCHIVE_CHUNK_BYTES=131072' in deploy_source
    assert 'cat >> \'$REMOTE_ARCHIVE\'' in deploy_source
    assert "Release archive byte count verification failed" in deploy_source
    assert "scp -q" not in deploy_source
    provisional_marker_body = deploy_source.split(
        "write_provisional_marker() {", 1
    )[1].split("}\n", 1)[0]
    assert 'install -o root -g yobi -m 0644 /dev/null "$marker_path"' in provisional_marker_body
    assert '| tee "$marker_path" >/dev/null' in provisional_marker_body
    assert "/dev/stdin" not in provisional_marker_body
    assert '|| ! { [[ "$provisional_deploy" != "true" ]] \\' in deploy_source
    assert '|| write_provisional_marker "$new_release"; } \\' in deploy_source
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


def test_recovery_mode_requires_explicit_health_only_opt_in() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert 'YOBI_RECOVERY_ALLOW_UNREADY_CURRENT:-false' in source
    assert "YOBI_RECOVERY_ALLOW_UNREADY_CURRENT must be true or false" in source
    assert "check_local_health" in source
    assert "will not be registered as a rollback target" in source
    assert 'old_release_verified" == true && -n "$old_release"' in source


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
    legacy_activation = "else\n  rollback_activation_started=true\nfi"
    assert legacy_activation in source
    assert source.index(legacy_activation) < source.index('ln -sfn "$target" "$CURRENT_LINK"')


def test_success_commit_markers_precede_restore_flag_cleanup() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert deploy_source.rindex("deployment_complete=true") < deploy_source.rindex(
        "knowledge_restore_required=false"
    )
    assert deploy_source.rindex("deployment_complete=true") < deploy_source.rindex(
        "recommendation_restore_required=false"
    )
    assert rollback_source.rindex("rollback_complete=true") < rollback_source.rindex(
        "knowledge_restore_required=false"
    )
    assert rollback_source.rindex("rollback_complete=true") < rollback_source.rindex(
        "recommendation_restore_required=false"
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


def test_recommendation_release_pointer_and_live_v2_smoke_are_release_gates() -> None:
    deploy_source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    rollback_source = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")

    assert "manage_recommendation_release.py" in deploy_source
    assert "old_recommendation_release_family_id" in deploy_source
    assert "new_recommendation_release_family_id" in deploy_source
    assert "restore_recommendation_release" in deploy_source
    assert "--recommendation-release-family-id" in deploy_source
    assert "seed_demo.py\" --verify-only" in deploy_source
    assert "structured_recommendation_smoke.py" in deploy_source
    assert "structured_fallback_smoke.py" in deploy_source
    assert deploy_source.index("structured_recommendation_smoke.py") < deploy_source.index(
        "structured_fallback_smoke.py"
    )
    assert deploy_source.index("structured_fallback_smoke.py") < deploy_source.index(
        'write_ready_marker "$new_release"'
    )

    assert "manage_recommendation_release.py" in rollback_source
    assert "recommendation_release_family_id --allow-missing" in rollback_source
    assert "restore_original_recommendation" in rollback_source
    assert "clear-active" in rollback_source

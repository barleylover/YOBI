from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_release_archive_contains_knowledge_and_all_migrations() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert "backend frontend/dist database deploy scripts knowledge" in source
    assert "database/migrations/005_conversation_state.sql" in source
    assert "database/migrations/006_knowledge_graph.sql" in source
    assert "database/migrations/007_service_area_and_mutation_idempotency.sql" in source
    assert "database/migrations/008_checkout_cart_version.sql" in source
    assert "persist_runtime_retry_policy" in source


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
    assert "previous_release" in deploy_source
    assert 'READY_MARKER=".yobi-release-ready"' in rollback_source
    assert 'PREVIOUS_RECORD="$SHARED_ROOT/previous_release"' in rollback_source
    assert "find /opt/yobi/releases" not in rollback_source
    assert "Rollback target was never health-verified" in rollback_source
    assert 'ln -sfn "$current" "$CURRENT_LINK"' in rollback_source

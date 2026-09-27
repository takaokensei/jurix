from pathlib import Path

REQUIRED_FILES = [
    "scripts/production_preflight_v2.py",
    "scripts/security_audit_v2.py",
    "scripts/architecture_budget_v2.py",
    "scripts/http_smoke_v2.py",
    "scripts/backup_verify_v2.py",
    "scripts/storage_manifest_v2.py",
    "scripts/celery_queue_guard_v2.py",
    "src/apps/operations/management/commands/production_preflight_v2.py",
    "src/apps/operations/management/commands/check_vector_health_v2.py",
    "src/apps/operations/management/commands/check_corpus_integrity_v2.py",
    "src/apps/operations/management/commands/rag_release_guard_v2.py",
]


def test_production_contract_files_exist():
    required = [*REQUIRED_FILES, "docker/entrypoint.prod.sh"]
    missing = [item for item in required if not Path(item).is_file()]
    assert not missing, missing


def test_production_entrypoint_migrates_before_starting_process():
    entrypoint = Path("docker/entrypoint.prod.sh").read_text(encoding="utf-8")

    assert "python manage.py migrate --noinput" in entrypoint
    assert 'exec /usr/local/bin/jurix-runtime "$@"' in entrypoint


def test_security_audit_ignores_generated_artifacts(tmp_path):
    from scripts.security_audit_v2 import scan

    for directory in ("htmlcov", ".history"):
        target = tmp_path / directory / "generated.js"
        target.parent.mkdir(parents=True)
        target.write_text("eval('generated')\n", encoding="utf-8")

    assert scan(tmp_path) == []


def test_dockerignore_excludes_local_development_artifacts():
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    for entry in (".venv", ".history", "htmlcov", "tests", "*.sqlite3"):
        assert entry in dockerignore


def test_production_compose_isolates_runtime_volumes_and_container_names():
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "name: ${POSTGRES_VOLUME_NAME:-jurix_prod_postgres_data}" in compose
    assert "name: ${REDIS_VOLUME_NAME:-jurix_prod_redis_data}" in compose
    assert "name: ${JURIX_DATA_VOLUME_NAME:-jurix_prod_data}" in compose
    assert "container_name:" not in compose


def test_production_compose_has_process_appropriate_celery_healthchecks():
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "celery -A config inspect ping --timeout=2 | grep -q pong" in compose
    assert 'test: ["NONE"]' in compose


def test_production_compose_forwards_https_and_csrf_settings():
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

    for setting in (
        "CSRF_TRUSTED_ORIGINS",
        "SECURE_SSL_REDIRECT",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "SECURE_HSTS_PRELOAD",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
    ):
        assert f"  {setting}:" in compose


def test_production_image_builds_and_serves_static_assets():
    dockerfile = Path("docker/Dockerfile").read_text(encoding="utf-8")
    settings = Path("config/settings.py").read_text(encoding="utf-8")

    assert "collectstatic --noinput" in dockerfile
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in settings
    assert "CompressedManifestStaticFilesStorage" in settings
    assert "STATICFILES_DIRS =" not in settings


def test_strict_preflight_checks_for_a_non_empty_consolidated_corpus():
    source = Path("src/apps/operations/management/commands/production_preflight_v2.py").read_text(
        encoding="utf-8"
    )

    assert "READINESS_REQUIRE_CORPUS" in source
    assert "No consolidated normas are available" in source
    assert "ingest_sapl_bounded --max-normas 300" in source
    assert "Automatic sync is not " in source


def test_release_assurance_requires_reviewed_rag_manifest():
    workflow = Path(".github/workflows/production-assurance-v2.yml").read_text(encoding="utf-8")

    run_lines = [line.strip() for line in workflow.splitlines() if line.strip().startswith("run:")]
    gate_lines = [line for line in run_lines if "production_gate.py" in line]
    assert gate_lines
    assert any("--require-rag" in line for line in gate_lines)


def test_release_assurance_declares_redis_for_django_contract():
    workflow = Path(".github/workflows/production-assurance-v2.yml").read_text(encoding="utf-8")

    assert "redis:" in workflow
    assert workflow.count("REDIS_URL: redis://localhost:6379/0") >= 4


def test_release_assurance_triggers_for_runtime_and_test_changes():
    workflow = Path(".github/workflows/production-assurance-v2.yml").read_text(encoding="utf-8")

    for path in ("docker/**", "requirements.txt", "tests/**"):
        assert f"      - '{path}'" in workflow

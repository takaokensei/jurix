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
    missing = [item for item in REQUIRED_FILES if not Path(item).is_file()]
    assert not missing, missing

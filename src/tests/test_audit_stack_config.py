from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_audit_compose_isolated_from_normal_stack():
    compose = (ROOT / "docker-compose.audit.yml").read_text()

    assert "  db:" in compose and "  redis:" in compose and "  worker:" in compose
    assert "  beat:" not in compose
    assert '"127.0.0.1:55432:5432"' in compose
    assert '"127.0.0.1:16380:6379"' in compose
    assert "audit_pgdata:/var/lib/postgresql/data" in compose
    assert "env_file:" not in compose
    assert "./.env" not in compose and "./data" not in compose
    assert "audit-only-local-fixture" in compose
    assert "celery -A config worker" in compose
    assert "--pool=solo --concurrency=1" in compose
    assert "celery -A config inspect ping --timeout=5" in compose

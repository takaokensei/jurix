from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_audit_compose_isolated_from_normal_stack():
    compose = (ROOT / "docker-compose.audit.yml").read_text()

    assert all(f"  {service}:" in compose for service in ("db", "redis", "web", "worker"))
    assert "  beat:" not in compose
    assert '"127.0.0.1:55432:5432"' in compose
    assert '"127.0.0.1:16380:6379"' in compose
    assert "audit_pgdata:/var/lib/postgresql/data" in compose
    assert "env_file:" not in compose
    assert "./.env" not in compose and "./data" not in compose
    assert "audit-only-local-fixture" in compose
    assert "celery -A config worker" in compose
    assert 'JURIX_QA_ONLY: "1"' in compose
    assert 'DJANGO_SKIP_DOTENV: "1"' in compose
    assert "config.settings_normative_container_qa" in compose
    assert "audit_qa_root:/app/data/normative-qa" in compose
    assert '"127.0.0.1:8287:8000"' in compose
    assert compose.count("audit_qa_root:/app/data/normative-qa") == 2
    assert compose.count("OLLAMA_BASE_URL: http://host.docker.internal:11434") == 2
    assert "runserver" in compose and "0.0.0.0:8000" in compose and "--noreload" in compose
    assert "--pool=solo --concurrency=1" in compose
    assert "celery -A config inspect ping --timeout=5" in compose

"""Apply small deterministic fixes identified by the repository audit."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    # Generated ingestion split: core processing needs the normalization helper.
    replace(
        "src/apps/ingestion/core_tasks.py",
        "from .task_support import _invalidate_rag_cache\n",
        "from .task_support import _invalidate_rag_cache, _normalize_norma_tipo\n",
    )

    # Remove the dead eager CSP value; middleware already builds it per response.
    replace(
        "config/middleware.py",
        "\nCONTENT_SECURITY_POLICY = _build_content_security_policy()\n",
        "\n",
    )
    replace(
        "src/tests/test_frontend_static.py",
        "from config.middleware import CONTENT_SECURITY_POLICY",
        "from config.middleware import _build_content_security_policy",
    )
    replace(
        "src/tests/test_frontend_static.py",
        "CONTENT_SECURITY_POLICY.split(\";\")",
        "_build_content_security_policy().split(\";\")",
    )

    # README must not claim audited accessibility conformance.
    replace(
        "README.md",
        "<td align=\"center\">♿ Acessibilidade WCAG 2.1 AA</td>\n<td align=\"center\">✅ Completo</td>",
        "<td align=\"center\">♿ Acessibilidade WCAG 2.1 AA</td>\n<td align=\"center\">🟡 Em validação</td>",
    )
    replace(
        "README.md",
        "<strong>♿ Acessibilidade</strong>: WCAG 2.1 AA compliance",
        "<strong>♿ Acessibilidade</strong>: foco em WCAG 2.1 AA; conformidade depende de auditoria formal",
    )
    replace(
        "README.md",
        "├── 🧪 pytest.ini                    # Configurações do Pytest (Django, coverage)\n",
        "",
    )

    # Do not ship the audit scratch patch.
    scratch = ROOT / "jurix-phase19-21.patch"
    if scratch.exists():
        scratch.unlink()

    # The branch-local generator workflows are tooling, not application code.
    for path in [
        ROOT / ".github/workflows/complete-audit-refactor.yml",
        ROOT / ".github/workflows/audit-refactor-runner.yml",
    ]:
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()

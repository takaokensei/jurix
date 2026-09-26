"""Apply small deterministic fixes identified by the repository audit."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, *, optional: bool = False) -> None:
    p = ROOT / path
    if not p.exists():
        if optional:
            return
        raise SystemExit(f"expected file not found: {path}")
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if optional:
            return
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    replace("src/apps/ingestion/core_tasks.py", "from .task_support import _invalidate_rag_cache\n", "from .task_support import _invalidate_rag_cache, _normalize_norma_tipo\n", optional=True)
    replace("config/middleware.py", "\nCONTENT_SECURITY_POLICY = _build_content_security_policy()\n", "\n", optional=True)
    replace("src/tests/test_frontend_static.py", "from config.middleware import CONTENT_SECURITY_POLICY", "from config.middleware import _build_content_security_policy", optional=True)
    replace("src/tests/test_frontend_static.py", "CONTENT_SECURITY_POLICY.split(\";\")", "_build_content_security_policy().split(\";\")", optional=True)
    replace("README.md", "<td align=\"center\">♿ Acessibilidade WCAG 2.1 AA</td>\n<td align=\"center\">✅ Completo</td>", "<td align=\"center\">♿ Acessibilidade WCAG 2.1 AA</td>\n<td align=\"center\">🟡 Em validação</td>", optional=True)
    replace("README.md", "<strong>♿ Acessibilidade</strong>: WCAG 2.1 AA compliance", "<strong>♿ Acessibilidade</strong>: foco em WCAG 2.1 AA; conformidade depende de auditoria formal", optional=True)
    replace("README.md", "├── 🧪 pytest.ini                    # Configurações do Pytest (Django, coverage)\n", "", optional=True)

    scratch = ROOT / "jurix-phase19-21.patch"
    if scratch.exists():
        scratch.unlink()
    for path in [ROOT / ".github/workflows/complete-audit-refactor.yml", ROOT / ".github/workflows/audit-refactor-runner.yml"]:
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()

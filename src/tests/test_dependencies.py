"""
Dependency hygiene (audit P2.5): every third-party import must be declared in
requirements.txt (Pillow was imported by tasks.py but only present by accident, via
pytesseract) and every declared runtime dependency must be used (spaCy was installed
-- a very heavy dependency -- with no import anywhere).
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# import name -> distribution name, where they differ
IMPORT_TO_DIST = {
    "docx": "python-docx",
    "fitz": "pymupdf",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "dateutil": "python-dateutil",
    "psycopg2": "psycopg2-binary",
    "django_htmx": "django-htmx",
    "yaml": "pyyaml",
}
FIRST_PARTY = {"src", "config", "manage", "legislation", "ingestion", "core", "processing",
               "llm_engine", "clients"}

# Declared but never imported by our code, on purpose.
USED_WITHOUT_IMPORT = {
    "gunicorn",            # process server, started by the Dockerfile CMD
    "psycopg2-binary",     # loaded by Django's postgresql backend
    "django-htmx",         # enabled through INSTALLED_APPS / MIDDLEWARE strings
    "redis",               # Celery broker + Django's RedisCache backend, via URLs/settings
    "ruff", "pytest", "pytest-django", "pytest-cov", "pytest-mock", "boto3",   # tooling
}


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared():
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(_norm(re.split(r"[=<>!~\[; ]", line, maxsplit=1)[0]))
    return names


def _imported_third_party():
    found = {}
    for path in list(SRC.rglob("*.py")) + [ROOT / "manage.py"] + list((ROOT / "config").glob("*.py")):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for mod in mods:
                top = mod.split(".")[0]
                if top in sys.stdlib_module_names or top in FIRST_PARTY:
                    continue
                found.setdefault(_norm(IMPORT_TO_DIST.get(top, top)), path.relative_to(ROOT))
    return found


def test_every_third_party_import_is_declared():
    missing = {dist: str(where) for dist, where in _imported_third_party().items()
               if dist not in _declared() and dist not in {"pytest"}}
    assert missing == {}, f"imported but not in requirements.txt: {missing}"


def test_every_declared_runtime_dependency_is_used():
    used = set(_imported_third_party()) | {_norm(n) for n in USED_WITHOUT_IMPORT}
    unused = sorted(_declared() - used)
    assert unused == [], f"declared in requirements.txt but never imported: {unused}"

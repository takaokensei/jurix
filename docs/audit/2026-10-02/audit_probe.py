"""Read-only local audit probes; outputs live only under this audit directory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8", "replace").strip()

def snapshot():
    names = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    names = [n for n in names if not n.startswith("docs/audit/2026-10-02/")
             and ".proposed" not in n and not n.startswith("docs/audit/screenshots/audit-20261002-")]
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
              for n in names if (ROOT / n).is_file()}
    return {"branch": git("branch", "--show-current"), "head": git("rev-parse", "HEAD"),
            "status": git("status", "--short"), "staged": git("diff", "--cached", "--stat"),
            "unstaged": git("diff", "--stat"), "unpushed": git("log", "--oneline", "@{upstream}..HEAD"),
            "hashes": hashes,
            "local_database_hash": hashlib.sha256((ROOT / "db.sqlite3").read_bytes()).hexdigest()
            if (ROOT / "db.sqlite3").exists() else None}

if sys.argv[1] == "baseline":
    result = snapshot()
    (OUT / "git-baseline.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"hashes", "status", "unstaged"}}, indent=2))
    raise SystemExit

if sys.argv[1] == "final":
    before = json.loads((OUT / "git-baseline.json").read_text(encoding="utf-8"))
    after = snapshot()
    changed = [n for n, h in before["hashes"].items() if after["hashes"].get(n) != h]
    result = {"branch_before": before["branch"], "branch_after": after["branch"],
              "head_unchanged": before["head"] == after["head"], "preexisting_files_changed": changed,
              "database_unchanged": before["local_database_hash"] == after["local_database_hash"],
              "staged_unchanged": before["staged"] == after["staged"], "status": after["status"]}
    (OUT / "git-final.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.conf import settings
from src.apps.legislation.models import Norma, Dispositivo, ChatSession

if sys.argv[1] == "environment":
    result = {"django": django.get_version(), "python": sys.version.split()[0],
              "database_engine": settings.DATABASES["default"]["ENGINE"],
              "database_is_local_sqlite": settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"),
              "debug": settings.DEBUG, "cache_backend": settings.CACHES["default"]["BACKEND"],
              "llm_model": settings.OLLAMA_MODEL, "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
              "normas": Norma.objects.count(), "consolidated": Norma.objects.filter(status="consolidated").count(),
              "devices": Dispositivo.objects.count(), "chat_sessions_count": ChatSession.objects.count(),
              "public_examples": list(Norma.objects.filter(status="consolidated").order_by("-ano", "-id")
                  .values("id", "numero", "ano", "tipo", "data_publicacao", "data_vigencia")[:12])}
    (OUT / "environment.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))

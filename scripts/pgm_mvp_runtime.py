"""Launch and inspect the existing local PGM QA stack without ambient config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "jurix-normative-qa"
PORT = 8294
BUILD_FILES = {
    "requirements.txt", "uv.lock", "pyproject.toml", "docker-compose.audit.yml",
    "scripts/pgm_mvp_runtime.py", "scripts/start_pgm_mvp.ps1", "scripts/status_pgm_mvp.ps1",
}
BUILD_SUFFIXES = {".py", ".html", ".css", ".js", ".svg", ".json", ".sh"}


def runtime_file(name: str) -> bool:
    """Exclude private configuration, large data, caches and development outputs."""
    path = Path(name)
    if any(part.startswith(".") or part in {"__pycache__", "node_modules"} for part in path.parts):
        return False
    if name in BUILD_FILES:
        return True
    return (
        name.startswith(("src/", "config/", "docker/"))
        and not name.startswith("src/tests/")
        and path.suffix in BUILD_SUFFIXES
    )


def build_metadata(root: Path = ROOT) -> dict:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True,
    )
    names = sorted({name.decode("utf-8") for name in result.stdout.split(b"\0") if name})
    digest = hashlib.sha256()
    for name in names:
        if not runtime_file(name):
            continue
        path = root / name
        digest.update(name.encode("utf-8") + b"\0")
        # Deletion is part of the build identity, too.
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"deleted")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    return {"version": version, "revision": revision, "content_sha256": digest.hexdigest(), "profile": "qa"}


def _json_url(url: str, timeout: float = 2) -> dict | None:
    try:
        with urlopen(url, timeout=timeout) as response:
            value = json.load(response)
        return value if isinstance(value, dict) else None
    except (OSError, URLError, ValueError):
        return None


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def compatible(expected: dict, actual: dict | None) -> bool:
    return bool(actual) and all(actual.get(key) == expected[key] for key in (
        "revision", "content_sha256", "profile",
    ))


def _run(command: list[str], *, env: dict | None = None, timeout: int = 120) -> str:
    result = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(f"QA command failed ({result.returncode}): {result.stderr[-2500:]}")
    return result.stdout


def _docker_status() -> dict:
    containers = []
    for service in ("db", "redis", "web", "worker"):
        name = f"{PROJECT}-{service}-1"
        try:
            value = _run([
                "docker", "inspect", name, "--format",
                '{{json .State}}',
            ], timeout=8)
            state = json.loads(value)
            containers.append({
                "service": service, "running": state["Running"],
                "health": state.get("Health", {}).get("Status", "not_configured"),
            })
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
            containers.append({"service": service, "running": False, "health": "unavailable"})
    return {"containers": containers}


def status(port: int = PORT) -> dict:
    expected = build_metadata()
    base = f"http://127.0.0.1:{port}"
    instance = _json_url(base + "/api/v1/health/instance/")
    ready = _json_url(base + "/api/v1/health/ready/")
    ollama = _json_url("http://127.0.0.1:11434/api/version")
    tags = _json_url("http://127.0.0.1:11434/api/tags") or {}
    result = {
        "url": base + "/assistente/", "expected_build": expected,
        "instance": instance, "compatible": compatible(expected, instance),
        "web_listening": _listening(port), "readiness": ready,
        "database_listening": _listening(55432), "redis_listening": _listening(16380),
        "ollama": {
            "available": bool(ollama), "version": (ollama or {}).get("version"),
            "models": [{"name": model.get("name"), "digest": model.get("digest")}
                       for model in tags.get("models", [])],
        },
        **_docker_status(),
    }
    configured = ((instance or {}).get("generation") or {}).get("model")
    canonical_model = configured if not configured or ":" in configured else configured + ":latest"
    selected = next((model for model in result["ollama"]["models"] if model["name"] == canonical_model), None)
    result["ollama"]["configured_model"] = configured
    result["ollama"]["configured_model_available"] = selected is not None
    result["ollama"]["configured_model_digest"] = selected["digest"] if selected else None
    result["ready"] = bool(
        result["compatible"] and ready and ready.get("status") == "ready"
        and all(item["running"] and item["health"] == "healthy" for item in result["containers"])
    )
    return result


def start(port: int = PORT) -> dict:
    """Reuse a compatible instance; never stop a process listening on another build."""
    expected = build_metadata()
    if _listening(port):
        actual = _json_url(f"http://127.0.0.1:{port}/api/v1/health/instance/")
        if not compatible(expected, actual):
            raise RuntimeError(
                f"Port {port} is occupied by an incompatible instance. No process was stopped. "
                f"Inspect its PID with Get-NetTCPConnection -LocalPort {port}."
            )
        return status(port)

    # --env-file must be explicit: a project .env can select product resources.
    # Preserve unrelated process env but provide every interpolation variable.
    env = os.environ.copy()
    env.update({
        "JURIX_QA_WEB_PORT": str(port), "JURIX_BUILD_VERSION": expected["version"],
        "JURIX_BUILD_REVISION": expected["revision"],
        "JURIX_BUILD_CONTENT_SHA256": expected["content_sha256"],
        "JURIX_QA_SAPL_SYNC_SCHEDULE_ENABLED": "0",
        "JURIX_QA_DOM_NATAL_SYNC_SCHEDULE_ENABLED": "0",
    })
    scratch = ROOT / "data" / "mvp-runtime"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=scratch, suffix=".env", delete=False) as file:
        envfile = Path(file.name)
    compose = ["docker", "compose", "--env-file", str(envfile), "-p", PROJECT,
               "-f", str(ROOT / "docker-compose.audit.yml")]
    try:
        print("Starting the existing QA database and Redis...", file=sys.stderr, flush=True)
        _run([*compose, "up", "-d", "db", "redis"])
        print("Building this checkout for QA web and worker...", file=sys.stderr, flush=True)
        _run([*compose, "build", "web", "worker"], env=env, timeout=1200)
        # Only inspect migration state here; never apply schema changes implicitly.
        print("Checking unapplied migrations (no migration is applied)...", file=sys.stderr, flush=True)
        _run([*compose, "run", "--rm", "--no-deps", "web", "python", "manage.py", "migrate", "--check"], env=env)
        _run([*compose, "up", "-d", "--no-build", "web", "worker"], env=env)
    finally:
        envfile.unlink(missing_ok=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        current = status(port)
        if current["ready"]:
            return current
        time.sleep(2)
    raise RuntimeError("QA started but did not become ready within 120 s; inspect status_pgm_mvp.ps1.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("identity", "status", "start"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or args.port in {55432, 16380, 11434}:
        parser.error("select an unprivileged web port different from the QA dependencies")
    try:
        result = build_metadata() if args.action == "identity" else (
            start(args.port) if args.action == "start" else status(args.port)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if args.action == "identity" or result["ready"] else 2
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

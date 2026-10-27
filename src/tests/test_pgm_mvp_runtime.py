"""Safety contracts for launch identity and reuse of the local MVP."""

import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory, override_settings

from scripts import pgm_mvp_runtime as runtime
from src.apps.legislation.api_health import health_instance_api


def test_build_identity_changes_for_untracked_runtime_edit_not_private_or_data(tmp_path, monkeypatch):
    files = ["src/example.py", "src/new.css", ".env", "data/blob.pdf", "src/tests/test_x.py"]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("before")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.0"\n')

    def git(command, **kwargs):
        return SimpleNamespace(
            stdout=(b"\0".join(name.encode() for name in files) if "ls-files" in command else "a" * 40)
        )

    monkeypatch.setattr(runtime.subprocess, "run", git)
    first = runtime.build_metadata(tmp_path)
    for name in (".env", "data/blob.pdf", "src/tests/test_x.py"):
        (tmp_path / name).write_text("private change")
    assert runtime.build_metadata(tmp_path) == first
    (tmp_path / "src/new.css").write_text("new runtime content")
    assert runtime.build_metadata(tmp_path)["content_sha256"] != first["content_sha256"]
    (tmp_path / "src/example.py").unlink()
    assert runtime.build_metadata(tmp_path)["content_sha256"] != first["content_sha256"]


@pytest.mark.parametrize("changes", [{"profile": "production"}, {"revision": "old"}, {"content_sha256": "old"}])
def test_different_build_is_not_reused(changes):
    expected = {"profile": "qa", "revision": "a" * 40, "content_sha256": "b" * 64}
    assert not runtime.compatible(expected, {**expected, **changes})


def test_incompatible_occupied_port_never_invokes_docker(monkeypatch):
    monkeypatch.setattr(runtime, "build_metadata", lambda: {"revision": "new"})
    monkeypatch.setattr(runtime, "_listening", lambda port: True)
    monkeypatch.setattr(runtime, "_json_url", lambda url: None)
    calls = []
    monkeypatch.setattr(runtime, "_run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match="No process was stopped"):
        runtime.start()
    assert calls == []


def test_compatible_second_start_reuses_without_build_or_restart(monkeypatch):
    expected = {"profile": "qa", "revision": "a" * 40, "content_sha256": "b" * 64}
    monkeypatch.setattr(runtime, "build_metadata", lambda: expected)
    monkeypatch.setattr(runtime, "_listening", lambda port: True)
    monkeypatch.setattr(runtime, "_json_url", lambda url: expected)
    monkeypatch.setattr(runtime, "status", lambda port: {"ready": True})
    monkeypatch.setattr(runtime, "_run", lambda *args, **kwargs: pytest.fail("must not restart a compatible build"))
    assert runtime.start() == {"ready": True}


def test_instance_endpoint_is_qa_only_and_sanitizes_metadata(tmp_path):
    request = RequestFactory().get("/api/v1/health/instance/")
    with override_settings(JURIX_BUILD_PROFILE="production"):
        assert health_instance_api(request).status_code == 404
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "current.json").write_text(json.dumps({"corpus_revision": "c" * 64, "secret": "not-public"}))
    with override_settings(
        QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="qa", JURIX_BUILD_REVISION="a" * 40,
        JURIX_BUILD_CONTENT_SHA256="b" * 64,
    ):
        response = health_instance_api(request)
    data = json.loads(response.content)
    assert data["content_sha256"] == "b" * 64
    assert data["corpus_revision"] == "c" * 64
    assert "not-public" not in response.content.decode()
    assert str(tmp_path) not in response.content.decode()

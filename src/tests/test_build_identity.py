from types import SimpleNamespace

import pytest
from django.test import override_settings

from src.apps.core.build_identity import build_identity, workspace_build_context


def test_missing_build_metadata_is_reported_as_unknown_not_inferred():
    request = SimpleNamespace(GET={})
    with override_settings(
        JURIX_BUILD_VERSION="",
        JURIX_BUILD_REVISION="",
        JURIX_BUILD_PROFILE="",
    ):
        identity = build_identity(request)

    assert identity == {
        "version": "build local não identificado",
        "revision": "não informada",
        "profile": "Ambiente não identificado",
        "corpus": "Escopo padrão; corpus não certificado por esta tela",
    }


def test_only_explicit_sanitized_release_metadata_is_displayed():
    with override_settings(
        JURIX_BUILD_VERSION="1.4.2-qa.1",
        JURIX_BUILD_REVISION="ABCDEF0123456789",
        JURIX_BUILD_PROFILE="qa",
    ):
        identity = build_identity()

    assert identity == {
        "version": "1.4.2-qa.1",
        "revision": "abcdef0123456789",
        "profile": "QA isolado",
        "corpus": "Escopo padrão; corpus não certificado por esta tela",
    }


def test_invalid_or_secret_like_metadata_is_not_reflected():
    request = SimpleNamespace(GET={"corpus": "archive-qa"})
    with override_settings(
        JURIX_BUILD_VERSION="token=do-not-expose",
        JURIX_BUILD_REVISION="private-build-name",
        JURIX_BUILD_PROFILE="https://internal.example/secret",
    ):
        identity = build_identity(request)
        context = workspace_build_context(request)

    serialized = " ".join(identity.values())
    assert "do-not-expose" not in serialized
    assert "private-build-name" not in serialized
    assert "internal.example" not in serialized
    assert identity["version"] == "build local não identificado"
    assert identity["revision"] == "não informada"
    assert identity["profile"] == "Ambiente não identificado"
    assert identity["corpus"] == "Acervo histórico local (QA)"
    assert context["jurix_build"] == identity


@pytest.mark.django_db
def test_assistant_shell_discloses_qa_profile_and_archive_scope(client):
    with override_settings(
        JURIX_BUILD_VERSION="",
        JURIX_BUILD_REVISION="",
        JURIX_BUILD_PROFILE="qa",
    ):
        response = client.get("/assistente/?corpus=archive-qa")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'class="workspace-build-details"' in html
    assert "Detalhes técnicos da instância" in html
    assert "build local não identificado" in html
    assert "QA isolado" in html
    assert "Acervo histórico local (QA)" in html

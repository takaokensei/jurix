import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica

pytestmark = pytest.mark.django_db(transaction=True)


def test_provision_creates_least_privilege_document_reviewer_without_fixture_records(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    password = "temporary-pgm-reviewer-password-2026"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", password)
    before = (
        get_user_model().objects.count(),
        Norma.objects.count(),
        DocumentoNormativo.objects.count(),
        RevisaoJuridica.objects.count(),
    )

    call_command("provision_pgm_qa_reviewer")

    reviewer = get_user_model().objects.get(username="jurix-pgm-smoke-reviewer")
    after = (
        get_user_model().objects.count(),
        Norma.objects.count(),
        DocumentoNormativo.objects.count(),
        RevisaoJuridica.objects.count(),
    )
    assert reviewer.is_active and reviewer.is_staff and not reviewer.is_superuser
    assert reviewer.has_perm("legislation.view_documentonormativo")
    assert reviewer.user_permissions.count() == 1
    assert reviewer.check_password(password)
    assert after == (before[0] + 1, *before[1:])


@pytest.mark.parametrize(
    ("qa_only", "password"),
    [("0", "temporary-pgm-reviewer-password-2026"), ("1", "too-short")],
)
def test_provision_rejects_non_qa_or_short_password(monkeypatch, qa_only, password):
    monkeypatch.setenv("JURIX_QA_ONLY", qa_only)
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", password)
    with pytest.raises(CommandError):
        call_command("provision_pgm_qa_reviewer")
    assert not get_user_model().objects.filter(username="jurix-pgm-smoke-reviewer").exists()


def test_existing_account_is_not_overwritten_and_disable_only_deactivates_marker(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", "temporary-pgm-reviewer-password-2026")
    call_command("provision_pgm_qa_reviewer")
    reviewer = get_user_model().objects.get(username="jurix-pgm-smoke-reviewer")
    original_password = reviewer.password

    with pytest.raises(CommandError, match="já existe"):
        call_command("provision_pgm_qa_reviewer")
    reviewer.refresh_from_db()
    assert reviewer.password == original_password and reviewer.is_active

    call_command("provision_pgm_qa_reviewer", disable=True)
    reviewer.refresh_from_db()
    assert not reviewer.is_active and not reviewer.has_usable_password()


def test_unique_preview_reviewer_is_view_only_and_can_be_disabled_without_touching_legal_rows(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    password = "temporary-candidate-preview-reviewer-2026"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", password)
    username = "jurix-pgm-preview-a1b2c3d4"
    before = (Norma.objects.count(), DocumentoNormativo.objects.count(), RevisaoJuridica.objects.count())

    call_command("provision_pgm_qa_reviewer", username=username)

    reviewer = get_user_model().objects.get(username=username)
    assert reviewer.email == f"{username}@invalid"
    assert reviewer.is_active and reviewer.is_staff and not reviewer.is_superuser
    assert reviewer.get_all_permissions() == {"legislation.view_documentonormativo"}
    assert reviewer.check_password(password)
    assert (Norma.objects.count(), DocumentoNormativo.objects.count(), RevisaoJuridica.objects.count()) == before

    call_command("provision_pgm_qa_reviewer", username=username, disable=True)
    reviewer.refresh_from_db()
    assert not reviewer.is_active and not reviewer.has_usable_password()
    assert (Norma.objects.count(), DocumentoNormativo.objects.count(), RevisaoJuridica.objects.count()) == before


def test_preview_reviewer_pending_relations_scope_is_explicit_and_limited(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    password = "temporary-pending-relations-reviewer-2026"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", password)
    username = "jurix-pgm-preview-b7c9d203"

    call_command(
        "provision_pgm_qa_reviewer",
        username=username,
        include_pending_relations=True,
    )

    reviewer = get_user_model().objects.get(username=username)
    assert reviewer.is_active and reviewer.is_staff and not reviewer.is_superuser
    assert reviewer.get_all_permissions() == {
        "legislation.view_documentonormativo",
        "legislation.view_eventoalteracao",
        "legislation.review_eventonormativocandidato",
    }
    assert reviewer.check_password(password)

    call_command("provision_pgm_qa_reviewer", username=username, disable=True)
    reviewer.refresh_from_db()
    assert not reviewer.is_active and not reviewer.has_usable_password()


def test_preview_reviewer_name_is_narrowly_allowlisted(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", "temporary-candidate-preview-reviewer-2026")
    with pytest.raises(CommandError, match="Username"):
        call_command("provision_pgm_qa_reviewer", username="other-user")
    assert not get_user_model().objects.filter(username="other-user").exists()


def test_container_qa_reviewer_guard_rejects_an_unrecognized_database_host(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", "temporary-candidate-preview-reviewer-2026")
    with override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "test_jurix_audit",
                "USER": "jurix_audit",
                "HOST": "untrusted-db",
                "PORT": "5432",
            }
        }
    ):
        with pytest.raises(CommandError, match="Banco fora do perfil QA"):
            call_command("provision_pgm_qa_reviewer", username="jurix-pgm-preview-a1b2c3d5")

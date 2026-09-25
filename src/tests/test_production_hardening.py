from __future__ import annotations

from django.core.checks import Error, Warning
from django.test import override_settings

from src.apps.operations.checks import check_production_contract


def issue_ids(issues):
    return {issue.id for issue in issues}


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    USE_LOCMEM_CACHE=False,
    DATABASES={
        "default": {
            "PASSWORD": "different-production-password",
        }
    },
    STORAGE_BACKEND="local",
    JURIX_ATTACHMENT_ROOT="/app/data/chat_attachments",
    SAPL_OCR_MAX_PAGES=200,
    LLM_RATE_LIMIT_REQUESTS=20,
    SECURE_SSL_REDIRECT=False,
    SECURE_HSTS_SECONDS=31536000,
)
def test_valid_production_contract_has_no_errors():
    issues = check_production_contract()
    assert not [issue for issue in issues if isinstance(issue, Error)]


@override_settings(DEBUG=True, SECRET_KEY="x" * 64, ALLOWED_HOSTS=["*"], SAPL_OCR_MAX_PAGES=200)
def test_debug_and_wildcard_hosts_are_rejected():
    ids = issue_ids(check_production_contract())
    assert "jurix.E001" in ids
    assert "jurix.E003" in ids


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "jurix_pass_dev"}},
    STORAGE_BACKEND="local",
    JURIX_ATTACHMENT_ROOT="/app/data/chat_attachments",
    SAPL_OCR_MAX_PAGES=200,
)
def test_development_database_password_is_rejected():
    assert "jurix.E004" in issue_ids(check_production_contract())


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "production-password"}},
    USE_LOCMEM_CACHE=True,
    STORAGE_BACKEND="local",
    JURIX_ATTACHMENT_ROOT="/app/data/chat_attachments",
    SAPL_OCR_MAX_PAGES=200,
)
def test_locmem_cache_is_rejected():
    assert "jurix.E005" in issue_ids(check_production_contract())


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "production-password"}},
    STORAGE_BACKEND="s3",
    S3_ENDPOINT="",
    S3_BUCKET="",
    S3_ACCESS_KEY="",
    S3_SECRET_KEY="",
    SAPL_OCR_MAX_PAGES=200,
)
def test_s3_requires_complete_credentials():
    assert "jurix.E008" in issue_ids(check_production_contract())


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "production-password"}},
    STORAGE_BACKEND="filesystem",
    SAPL_OCR_MAX_PAGES=200,
)
def test_unknown_storage_backend_is_rejected():
    assert "jurix.E007" in issue_ids(check_production_contract())


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "production-password"}},
    STORAGE_BACKEND="local",
    JURIX_ATTACHMENT_ROOT="/app/data/chat_attachments",
    SAPL_OCR_MAX_PAGES=0,
)
def test_invalid_ocr_page_limit_is_rejected():
    assert "jurix.E006" in issue_ids(check_production_contract())


@override_settings(
    DEBUG=False,
    SECRET_KEY="x" * 64,
    ALLOWED_HOSTS=["jurix.example"],
    DATABASES={"default": {"PASSWORD": "production-password"}},
    STORAGE_BACKEND="local",
    JURIX_ATTACHMENT_ROOT="/app/data/chat_attachments",
    SAPL_OCR_MAX_PAGES=200,
    SECURE_HSTS_SECONDS=0,
)
def test_missing_hsts_is_a_warning_not_an_error():
    issues = check_production_contract()
    assert any(isinstance(issue, Warning) and issue.id == "jurix.W003" for issue in issues)
    assert not any(isinstance(issue, Error) for issue in issues)

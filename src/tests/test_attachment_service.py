from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from src.apps.legislation.attachment_service import AttachmentError, list_attachments, upload_attachment, delete_attachment, get_attachment_texts


class DummySession(dict):
    session_key = "test-session"
    modified = False

    def save(self):
        self.session_key = "test-session"


class DummyRequest:
    session = DummySession()


def test_upload_and_delete_text_attachment(tmp_path, settings, monkeypatch):
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    request = DummyRequest()
    upload = SimpleUploadedFile("consulta.txt", b"Lei municipal sobre zoneamento", content_type="text/plain")
    item = upload_attachment(request, upload)
    assert item["name"] == "consulta.txt"
    assert list_attachments(request)[0]["id"] == item["id"]
    assert get_attachment_texts(request, [item["id"]]) == ["Lei municipal sobre zoneamento"]
    assert delete_attachment(request, item["id"]) is True
    assert list_attachments(request) == []


def test_unsupported_extension_is_rejected(tmp_path, settings):
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    request = DummyRequest()
    with pytest.raises(AttachmentError):
        upload_attachment(request, SimpleUploadedFile("malware.exe", b"MZ"))


def test_empty_file_is_rejected(tmp_path, settings):
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    request = DummyRequest()
    with pytest.raises(AttachmentError):
        upload_attachment(request, SimpleUploadedFile("empty.txt", b""))

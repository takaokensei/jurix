
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


def test_expiration_collects_abandoned_session_only(tmp_path, settings):
    import os
    import time
    from src.apps.legislation.attachment_service import cleanup_expired_attachments
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    directory = tmp_path / ('a' * 64)
    directory.mkdir()
    expired = directory / 'expired.pdf'
    expired.write_bytes(b'old')
    live = directory / 'live.txt'
    live.write_text('live')
    old = time.time() - 10000
    os.utime(expired, (old, old))
    assert cleanup_expired_attachments() == 1
    assert live.exists()


def test_pdf_page_limit(tmp_path, settings):
    import fitz
    from src.apps.legislation.attachment_service import _extract_text
    path = tmp_path / 'too-many.pdf'
    with fitz.open() as document:
        for _ in range(201):
            document.new_page()
        document.save(path)
    with pytest.raises(AttachmentError):
        _extract_text(path, '.pdf')


def test_pdf_extraction_in_child_process(tmp_path):
    import fitz
    from src.apps.legislation.attachment_service import _extract_text
    path = tmp_path / 'law.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), 'Municipal law')
        document.save(path)
    assert 'Municipal law' in _extract_text(path, '.pdf')


def test_docx_expansion_limit(tmp_path):
    from zipfile import ZipFile, ZIP_DEFLATED
    from src.processing.attachment_worker import extract, MAX_EXPANDED
    path = tmp_path / 'large.docx'
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * (MAX_EXPANDED + 1))
    with pytest.raises(ValueError, match='descompactado'):
        extract(path)


def test_docx_extraction_in_child_process(tmp_path):
    from docx import Document
    from src.apps.legislation.attachment_service import _extract_text
    path = tmp_path / 'law.docx'
    document = Document()
    document.add_paragraph('Lei municipal')
    document.save(path)
    assert 'Lei municipal' in _extract_text(path, '.docx')

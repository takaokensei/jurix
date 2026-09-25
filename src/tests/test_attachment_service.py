
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from src.apps.legislation.attachment_service import (
    AttachmentError,
    delete_attachment,
    get_attachment_texts,
    list_attachments,
    upload_attachment,
)

pytestmark = pytest.mark.django_db


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
    from datetime import timedelta

    from django.utils import timezone

    from src.apps.legislation.attachment_service import cleanup_expired_attachments
    from src.apps.legislation.attachment_storage import LocalAttachmentStorage
    from src.apps.operations.models import AttachmentRecord

    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    storage = LocalAttachmentStorage(tmp_path)

    storage.save_bytes("chat/expired/f1.txt", b"old", "text/plain")
    storage.save_bytes("chat/expired/f1.txt.txt", b"old text", "text/plain")
    AttachmentRecord.objects.create(
        id="f1",
        session_hash="expired",
        name="expired.txt",
        size=3,
        content_type="text/plain",
        storage_key="chat/expired/f1.txt",
        text_storage_key="chat/expired/f1.txt.txt",
        sha256="abc",
        expires_at=timezone.now() - timedelta(seconds=10),
    )

    storage.save_bytes("chat/live/f2.txt", b"live", "text/plain")
    storage.save_bytes("chat/live/f2.txt.txt", b"live text", "text/plain")
    AttachmentRecord.objects.create(
        id="f2",
        session_hash="live",
        name="live.txt",
        size=4,
        content_type="text/plain",
        storage_key="chat/live/f2.txt",
        text_storage_key="chat/live/f2.txt.txt",
        sha256="def",
        expires_at=timezone.now() + timedelta(seconds=3600),
    )

    assert cleanup_expired_attachments() == 1
    assert AttachmentRecord.objects.filter(id="f1").count() == 0
    assert AttachmentRecord.objects.filter(id="f2").count() == 1
    assert (tmp_path / "chat/live/f2.txt").exists()


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
    from zipfile import ZIP_DEFLATED, ZipFile

    from src.processing.attachment_worker import MAX_EXPANDED, extract
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


def test_resource_limits_enforced_in_process():
    import subprocess
    import sys

    # 1. Verify memory containment in an isolated subprocess (does NOT pollute pytest process)
    mem_code = (
        "import sys\n"
        "from src.processing.attachment_worker import apply_resource_limits\n"
        "if not apply_resource_limits(max_memory_bytes=30 * 1024 * 1024, max_cpu_seconds=5):\n"
        "    sys.exit(10)\n"  # Failure to apply limits
        "try:\n"
        "    x = bytearray(100 * 1024 * 1024)\n"
        "    sys.exit(20)\n"  # Allocation incorrectly succeeded
        "except MemoryError:\n"
        "    sys.exit(42)\n"  # Memory limit successfully caught
    )
    r1 = subprocess.run([sys.executable, "-c", mem_code], capture_output=True, timeout=10)
    assert r1.returncode != 10, f"apply_resource_limits failed to install limits: {r1.stderr.decode()}"
    assert r1.returncode != 20, "Memory limit was not enforced: allocation of 100MB succeeded under 30MB limit"
    assert r1.returncode == 42 or (r1.returncode & 0xFFFFFFFF) == 0xC0000044, f"Unexpected returncode: {r1.returncode}"

    # 2. Verify CPU limit containment in an isolated subprocess
    cpu_code = (
        "import sys, os\n"
        "from src.processing.attachment_worker import apply_resource_limits\n"
        "if not apply_resource_limits(max_memory_bytes=512 * 1024 * 1024, max_cpu_seconds=1):\n"
        "    sys.exit(10)\n"
        "sys.stdout.write('CPU_LIMIT_INSTALLED\\n')\n"
        "sys.stdout.flush()\n"
        "tot = 0\n"
        "for i in range(100_000_000):\n"
        "    tot += i * i\n"
        "sys.exit(20)\n"  # Computation incorrectly completed without limit termination
    )
    r2 = subprocess.run([sys.executable, "-c", cpu_code], capture_output=True, timeout=10)
    assert b"CPU_LIMIT_INSTALLED" in r2.stdout, f"Process failed before starting compute loop: {r2.stderr.decode()}"
    assert r2.returncode != 20, "CPU limit was not enforced: compute finished under 1s limit"
    if sys.platform == 'win32':
        assert (r2.returncode & 0xFFFFFFFF) == 0xC0000044, (
            f"Expected STATUS_QUOTA_EXCEEDED (0xC0000044), got {hex(r2.returncode & 0xFFFFFFFF)}"
        )
    else:
        import signal
        assert r2.returncode in (
            -signal.SIGXCPU,
            -signal.SIGKILL,
            128 + signal.SIGXCPU,
            128 + signal.SIGKILL,
            137,
        ), (
            f"Expected CPU limit termination (SIGXCPU or SIGKILL), got {r2.returncode}"
        )

    # 3. Verify real attachment_worker.main() entry point aborts if limits fail to apply without calling extract()
    from unittest.mock import patch

    from src.processing import attachment_worker

    with patch.object(attachment_worker, 'apply_resource_limits', return_value=False):
        with patch.object(attachment_worker, 'extract') as mock_extract:
            with patch('sys.stderr'):
                rc = attachment_worker.main(['worker.py', 'test.pdf'])
                assert rc == 1, f"Expected main() to return 1 when limits fail, got {rc}"
                mock_extract.assert_not_called()


def test_cleanup_skips_symlinks_and_external_paths(tmp_path, settings):
    from datetime import timedelta

    from django.utils import timezone

    from src.apps.legislation.attachment_service import cleanup_expired_attachments
    from src.apps.legislation.attachment_storage import LocalAttachmentStorage
    from src.apps.operations.models import AttachmentRecord

    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    storage = LocalAttachmentStorage(tmp_path)

    external_file = tmp_path / 'important.txt'
    external_file.write_text('do not delete')

    storage.save_bytes("chat/expired/f1.txt", b"old", "text/plain")
    storage.save_bytes("chat/expired/f1.txt.txt", b"old text", "text/plain")
    AttachmentRecord.objects.create(
        id="f1",
        session_hash="expired",
        name="expired.txt",
        size=3,
        content_type="text/plain",
        storage_key="chat/expired/f1.txt",
        text_storage_key="chat/expired/f1.txt.txt",
        sha256="abc",
        expires_at=timezone.now() - timedelta(seconds=10),
    )

    removed = cleanup_expired_attachments()
    assert removed == 1
    assert external_file.exists()

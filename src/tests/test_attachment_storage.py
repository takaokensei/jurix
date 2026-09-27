import pytest

from src.apps.legislation.attachment_storage import LocalAttachmentStorage, StorageError


def test_local_storage_round_trip(tmp_path, settings):
    settings.JURIX_SINGLE_HOST = True
    storage = LocalAttachmentStorage(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("conteúdo jurídico", encoding="utf-8")
    storage.save_file("chat/a/source.txt", source, "text/plain")
    assert storage.read_bytes("chat/a/source.txt") == "conteúdo jurídico".encode()
    storage.delete("chat/a/source.txt")
    try:
        storage.read_bytes("chat/a/source.txt")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("deleted object is still readable")


def test_storage_rejects_path_escape(tmp_path, settings):
    settings.JURIX_SINGLE_HOST = True
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    storage = LocalAttachmentStorage(tmp_path)
    try:
        storage.read_bytes("../escape")
    except StorageError:
        pass
    else:
        raise AssertionError("path traversal key accepted")


def test_configured_external_root_requires_single_host_mode(tmp_path, settings):
    settings.JURIX_ATTACHMENT_ROOT = str(tmp_path)
    settings.JURIX_SINGLE_HOST = False
    with pytest.raises(StorageError):
        LocalAttachmentStorage()

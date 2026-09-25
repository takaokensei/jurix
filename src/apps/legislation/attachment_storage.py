"""Storage abstraction for chat attachments.

The public service deals only in storage keys and metadata. Local storage is used
for development; S3-compatible storage is used for production and MinIO.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import Protocol

from django.conf import settings


class StorageError(RuntimeError):
    pass


class AttachmentStorage(Protocol):
    def save_file(self, key: str, source: Path, content_type: str) -> None: ...
    def save_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    def read_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


def _safe_key(key: str) -> str:
    value = PurePosixPath(key)
    if value.is_absolute() or '..' in value.parts:
        raise StorageError('Chave de armazenamento inválida.')
    return value.as_posix()


class LocalAttachmentStorage:
    def __init__(self, root: str | Path | None = None):
        configured = root or getattr(settings, 'JURIX_ATTACHMENT_ROOT', '')
        self.root = Path(configured or Path(settings.BASE_DIR) / 'data' / 'chat_attachments').resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / _safe_key(key)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise StorageError('Chave de armazenamento fora da raiz permitida.') from exc
        return candidate

    def save_file(self, key: str, source: Path, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('wb') as dst:
            shutil.copyfileobj(src, dst)

    def save_bytes(self, key: str, data: bytes, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3AttachmentStorage:
    def __init__(self):
        try:
            import boto3
        except ImportError as exc:
            raise StorageError('boto3 não está instalado.') from exc
        bucket = getattr(settings, 'S3_BUCKET', '')
        if not bucket:
            raise StorageError('S3_BUCKET é obrigatório quando STORAGE_BACKEND=s3.')
        self.bucket = bucket
        self.client = boto3.client(
            's3',
            endpoint_url=getattr(settings, 'S3_ENDPOINT', '') or None,
            aws_access_key_id=getattr(settings, 'S3_ACCESS_KEY', '') or None,
            aws_secret_access_key=getattr(settings, 'S3_SECRET_KEY', '') or None,
            region_name=getattr(settings, 'S3_REGION', 'us-east-1'),
        )

    def save_file(self, key: str, source: Path, content_type: str) -> None:
        self.client.upload_file(
            str(source), self.bucket, _safe_key(key),
            ExtraArgs={'ContentType': content_type or 'application/octet-stream'},
        )

    def save_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=_safe_key(key), Body=data,
            ContentType=content_type or 'application/octet-stream',
        )

    def read_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))
        return response['Body'].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))


def get_attachment_storage() -> AttachmentStorage:
    backend = getattr(settings, 'STORAGE_BACKEND', 'local').strip().lower()
    if backend == 'local':
        return LocalAttachmentStorage()
    if backend in {'s3', 'minio'}:
        return S3AttachmentStorage()
    raise StorageError(f'STORAGE_BACKEND desconhecido: {backend}')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

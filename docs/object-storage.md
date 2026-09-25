# Object storage

Jurix stores attachment metadata in PostgreSQL and file bytes behind `STORAGE_BACKEND`. `local` is for development; `s3`/`minio` use the S3-compatible API.

Each record keeps a storage key, extracted-text key, SHA-256 digest, size, MIME type, creation time and expiration time. The raw Django session key is not persisted; ownership uses its SHA-256 hash.

Production should use S3/MinIO plus bucket lifecycle policies as a second cleanup layer.

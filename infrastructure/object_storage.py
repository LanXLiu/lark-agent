"""Public object-storage adapter entrypoints."""

from infrastructure.db.minio import MinioClient, MinioConfig, ensure_buckets, get_minio_client

__all__ = ["MinioClient", "MinioConfig", "ensure_buckets", "get_minio_client"]

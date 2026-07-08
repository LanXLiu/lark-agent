from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from channels.lark.lark_config import Settings


@dataclass(frozen=True)
class MinioUploadResult:
    bucket: str
    key: str


class MinioUploader:
    def __init__(self, settings: Settings) -> None:
        if not settings.minio_access_key or not settings.minio_secret_key:
            raise RuntimeError("缺少 MinIO 配置：MINIO_ACCESS_KEY / MINIO_SECRET_KEY")

        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import ClientError

        endpoint = strip_scheme(settings.minio_endpoint)
        scheme = "https" if settings.minio_use_ssl else "http"
        self.bucket = settings.minio_bucket
        self.raw_prefix = normalize_path_part(settings.minio_raw_prefix)
        self.collection = normalize_path_part(settings.qdrant_collection)
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            raise RuntimeError(
                f"MinIO 自检失败：无法访问 bucket={self.bucket}，请检查 endpoint / access key / secret key / bucket 权限"
            ) from exc

    def upload_lark_file(
        self,
        path: Path,
        *,
        chat_id: str,
        message_id: str,
        filename: str,
    ) -> MinioUploadResult:
        key = build_lark_raw_key(
            raw_prefix=self.raw_prefix,
            collection=self.collection,
            chat_id=chat_id,
            message_id=message_id,
            filename=filename,
        )
        self.client.upload_file(str(path), self.bucket, key)
        return MinioUploadResult(bucket=self.bucket, key=key)


def build_lark_raw_key(
    *,
    raw_prefix: str,
    collection: str,
    chat_id: str,
    message_id: str,
    filename: str,
) -> str:
    date_part = ""
    safe_name = normalize_path_part(filename)
    return "/".join(
        part
        for part in (
            raw_prefix,
            collection,
            "lark",
            normalize_path_part(chat_id),
            date_part,
            normalize_path_part(message_id),
            safe_name,
        )
        if part
    )


def normalize_path_part(value: str) -> str:
    cleaned = (value or "").strip().strip("/\\")
    for char in '<>:"\\|?*\x00':
        cleaned = cleaned.replace(char, "_")
    return cleaned or "unknown"


def strip_scheme(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    if value.lower().startswith("https://"):
        return value[len("https://") :]
    if value.lower().startswith("http://"):
        return value[len("http://") :]
    return value

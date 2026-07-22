"""
MinIO / S3 兼容对象存储客户端。

- 配置来源：``conf.settings.settings``；优先扁平键（``minio_endpoint`` / ``minio_access_key`` ...），
  缺失时回退到嵌套块 ``settings.Minio``。
- 客户端：``boto3.client("s3")`` + ``s3v4`` 签名，带连接 / 读取超时与有限重试，单例。
- 数据读写：桶（存在 / 创建 / 列举）、对象（上传 / 下载 / 列举 / 元信息 / 删除）、预签名 URL。

外层一般通过 ``get_minio_client()`` 获取 ``MinioClient`` 实例；也保留旧的函数式 API
（``ensure_buckets`` / ``upload_file`` / ``download_file`` / ``list_files`` / ``delete_file``
/ ``get_presigned_url``）供既有调用方使用。
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

from infrastructure.conf.settings import settings


# ------------------------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MinioConfig:
    """从 ``settings`` 标准化抽取的 MinIO 连接参数。"""

    endpoint: str
    access_key: str
    secret_key: str
    use_ssl: bool
    bucket_raw: str
    bucket_processed: str
    region: str = "us-east-1"
    connect_timeout: int = 5
    read_timeout: int = 60
    max_attempts: int = 3

    # -------- 构造 --------
    @classmethod
    def from_settings(cls) -> "MinioConfig":
        """
        读取顺序：扁平键 → 嵌套块 ``Minio`` → 默认值。

        Raises:
            ValueError: 缺少必填项（endpoint / access_key / secret_key）时给出可读提示。
        """
        nested: dict[str, Any] = getattr(settings, "Minio", None) or {}
        if not isinstance(nested, dict):
            nested = {}

        endpoint = _first_non_empty(
            getattr(settings, "minio_endpoint", None),
            nested.get("endpoint"),
        )
        access_key = _first_non_empty(
            getattr(settings, "minio_access_key", None),
            nested.get("access_key"),
        )
        secret_key = _first_non_empty(
            getattr(settings, "minio_secret_key", None),
            nested.get("secret_key"),
        )
        use_ssl = _to_bool(
            _first_non_none(
                getattr(settings, "minio_use_ssl", None),
                nested.get("use_ssl"),
                False,
            )
        )
        bucket_raw = _first_non_empty(
            getattr(settings, "minio_bucket_raw", None),
            nested.get("bucket_raw"),
            "knowledge-raw",
        )
        bucket_processed = _first_non_empty(
            getattr(settings, "minio_bucket_processed", None),
            nested.get("bucket_processed"),
            "knowledge-processed",
        )
        region = _first_non_empty(
            getattr(settings, "minio_region", None),
            nested.get("region"),
            "us-east-1",
        )

        missing = [
            name
            for name, val in (
                ("minio_endpoint", endpoint),
                ("minio_access_key", access_key),
                ("minio_secret_key", secret_key),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                "MinIO 配置缺失："
                f"{', '.join(missing)}；请在 infrastructure/conf/config_{{ENV}}.yaml 中补全"
                "（扁平键或 Minio 嵌套块均可）。"
            )

        return cls(
            endpoint=_strip_scheme(endpoint),
            access_key=access_key,
            secret_key=secret_key,
            use_ssl=use_ssl,
            bucket_raw=bucket_raw,
            bucket_processed=bucket_processed,
            region=region,
        )

    @property
    def endpoint_url(self) -> str:
        """带协议的 endpoint，例如 ``http://host:9000`` 或 ``https://host``。"""
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.endpoint}"


# ------------------------------------------------------------------------------------
# 客户端
# ------------------------------------------------------------------------------------
class MinioClient:
    """MinIO（S3 兼容）客户端：进程内单例。"""

    _instance: "MinioClient | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "MinioClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: MinioConfig | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        with MinioClient._lock:
            if getattr(self, "_initialized", False):
                return

            self.config: MinioConfig = config or MinioConfig.from_settings()
            self._client = boto3.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
                aws_access_key_id=self.config.access_key,
                aws_secret_access_key=self.config.secret_key,
                region_name=self.config.region,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=self.config.connect_timeout,
                    read_timeout=self.config.read_timeout,
                    retries={"max_attempts": self.config.max_attempts, "mode": "standard"},
                ),
            )
            logger.info("MinIO 客户端已初始化：{}", self.config.endpoint_url)
            self._initialized = True

    @property
    def raw(self):
        """暴露底层 boto3 S3 client，便于做未封装的高级用法。"""
        return self._client

    # -------- 桶 --------
    def list_buckets(self) -> list[str]:
        """返回当前账号可见的全部桶名。"""
        resp = self._client.list_buckets()
        return [b["Name"] for b in resp.get("Buckets", [])]

    def bucket_exists(self, name: str) -> bool:
        """桶是否存在；不存在或不可访问均返回 ``False``。"""
        try:
            self._client.head_bucket(Bucket=name)
            return True
        except ClientError:
            return False

    def ensure_bucket(self, name: str) -> None:
        """桶不存在则创建（已存在时静默跳过）。"""
        if self.bucket_exists(name):
            return
        try:
            self._client.create_bucket(Bucket=name)
            logger.info("已创建 MinIO 桶：{}", name)
        except ClientError as e:
            code = (e.response or {}).get("Error", {}).get("Code")
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                return
            raise

    def ensure_default_buckets(self) -> None:
        """确保 ``bucket_raw`` 与 ``bucket_processed`` 均存在。"""
        for b in (self.config.bucket_raw, self.config.bucket_processed):
            self.ensure_bucket(b)

    # -------- 对象：上传 --------
    def upload_file(
        self,
        bucket: str,
        key: str,
        file_path: str,
        content_type: str | None = None,
    ) -> None:
        """本地文件 → 对象。"""
        extra = {"ContentType": content_type} if content_type else None
        self._client.upload_file(Filename=file_path, Bucket=bucket, Key=key, ExtraArgs=extra)

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        """内存字节 → 对象。"""
        body = io.BytesIO(data)
        self.upload_fileobj(bucket, key, body, content_type=content_type)

    def upload_fileobj(
        self,
        bucket: str,
        key: str,
        fileobj: BinaryIO,
        content_type: str | None = None,
    ) -> None:
        """类文件对象（已打开 ``"rb"``）→ 对象。"""
        extra = {"ContentType": content_type} if content_type else None
        self._client.upload_fileobj(Fileobj=fileobj, Bucket=bucket, Key=key, ExtraArgs=extra)

    # -------- 对象：下载 --------
    def download_file(self, bucket: str, key: str, dest_path: str) -> None:
        """对象 → 本地文件。"""
        self._client.download_file(Bucket=bucket, Key=key, Filename=dest_path)

    def download_bytes(self, bucket: str, key: str) -> bytes:
        """对象 → 字节串（小对象适用）。"""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def download_fileobj(self, bucket: str, key: str, fileobj: BinaryIO) -> None:
        """对象 → 写入到任意 ``"wb"`` 文件对象。"""
        self._client.download_fileobj(Bucket=bucket, Key=key, Fileobj=fileobj)

    # -------- 对象：查询 --------
    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        """分页列举对象键，可选前缀过滤。"""
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                keys.append(obj["Key"])
        return keys

    def stat_object(self, bucket: str, key: str) -> dict[str, Any]:
        """返回对象元信息（``ETag`` / ``ContentLength`` / ``ContentType`` / ``LastModified`` 等）。"""
        return self._client.head_object(Bucket=bucket, Key=key)

    def object_exists(self, bucket: str, key: str) -> bool:
        """对象是否存在。"""
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    # -------- 对象：删除 --------
    def delete_object(self, bucket: str, key: str) -> None:
        """删除单个对象。"""
        self._client.delete_object(Bucket=bucket, Key=key)

    def delete_objects(self, bucket: str, keys: Iterable[str]) -> int:
        """批量删除；返回成功删除数。"""
        items = [{"Key": k} for k in keys]
        if not items:
            return 0
        deleted = 0
        # S3 delete_objects 单次最多 1000 条，自动分批
        for i in range(0, len(items), 1000):
            batch = items[i : i + 1000]
            resp = self._client.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            deleted += len(batch) - len(resp.get("Errors", []) or [])
        return deleted

    # -------- 预签名 URL --------
    def presigned_get_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """GET 预签名 URL，默认 1 小时有效。"""
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in
        )

    def presigned_put_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
        content_type: str | None = None,
    ) -> str:
        """PUT 预签名 URL，便于客户端直传。"""
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in
        )

    # -------- 健康检查 --------
    def health_check(self) -> bool:
        """连通性自检：能列桶则视为可用。"""
        try:
            self._client.list_buckets()
            return True
        except (ClientError, BotoCoreError) as e:
            logger.warning("MinIO 健康检查失败：{}", e)
            return False


# ------------------------------------------------------------------------------------
# 对外便捷入口（兼容旧 API）
# ------------------------------------------------------------------------------------
def get_minio_client() -> MinioClient:
    """获取进程内单例 ``MinioClient``。"""
    return MinioClient()


def ensure_buckets() -> None:
    """在 lifespan 中调用：确保默认两个业务桶存在。"""
    get_minio_client().ensure_default_buckets()


def upload_file(bucket: str, key: str, file_path: str) -> None:
    """兼容旧函数式 API。"""
    get_minio_client().upload_file(bucket, key, file_path)


def download_file(bucket: str, key: str, download_path: str) -> None:
    """兼容旧函数式 API。"""
    get_minio_client().download_file(bucket, key, download_path)


def list_files(bucket: str, prefix: str = "") -> list[str]:
    """兼容旧函数式 API。"""
    return get_minio_client().list_objects(bucket, prefix=prefix)


def delete_file(bucket: str, key: str) -> None:
    """兼容旧函数式 API。"""
    get_minio_client().delete_object(bucket, key)


def get_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    """兼容旧函数式 API。"""
    return get_minio_client().presigned_get_url(bucket, key, expires_in=expires_in)


# ------------------------------------------------------------------------------------
# 工具
# ------------------------------------------------------------------------------------
def _first_non_empty(*candidates: Any) -> str:
    """返回第一个非空字符串；全空则返回最后一个候选（可能是 ``""``）。"""
    last = ""
    for v in candidates:
        if v is None:
            continue
        s = str(v).strip()
        last = s
        if s:
            return s
    return last


def _first_non_none(*candidates: Any) -> Any:
    """返回第一个非 ``None`` 的值。"""
    for v in candidates:
        if v is not None:
            return v
    return None


def _to_bool(v: Any) -> bool:
    """容错布尔解析（兼容 ``"true"`` / ``1`` / ``yes``）。"""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _strip_scheme(endpoint: str) -> str:
    """boto3 的 ``endpoint_url`` 由代码拼协议，因此剥掉 YAML 里误写的 ``http(s)://``。"""
    e = endpoint.strip().rstrip("/")
    if e.lower().startswith("https://"):
        e = e[len("https://") :]
    elif e.lower().startswith("http://"):
        e = e[len("http://") :]
    return e

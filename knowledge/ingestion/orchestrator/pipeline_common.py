"""Common context and metadata helpers for pipeline stages."""

from __future__ import annotations

import datetime as _dt
import json
import mimetypes
import threading
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infrastructure.conf.settings import settings
from infrastructure.db.minio import MinioClient, get_minio_client


STATUS_RAW = "raw"
STATUS_MARKDOWN = "markdown"
STATUS_CHUNK = "chunk"
STATUS_VECTORIZED = "vectorized"


def now_iso() -> str:
    """UTC ISO-8601 timestamp for audit records."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StageResult:
    """Serializable result returned by each orchestration stage."""

    source_key: str
    stage: str
    markdown_key: str | None = None
    chunk_key: str | None = None
    qdrant_collection: str | None = None
    markdown_chars: int = 0
    chunk_count: int = 0
    converter: str = "unknown"


class PipelineStageContext:
    """Shared storage, key-building, and JSONL metadata utilities."""

    BUCKET = "knowledgebase"
    DEFAULT_RAW_PREFIX = "raw/knowledgebase/"
    DEFAULT_MARKDOWN_PREFIX = "markdown/"
    DEFAULT_CHUNK_PREFIX = "chunk/"

    def __init__(
        self,
        *,
        metadata_path: str | Path | None = None,
        raw_to_markdown_metadata_path: str | Path = "metadata/raw_to_markdown_metadata.jsonl",
        markdown_to_chunk_metadata_path: str | Path = "metadata/markdown_to_chunk_metadata.jsonl",
        chunk_to_qdrant_metadata_path: str | Path = "metadata/chunk_to_qdrant_metadata.jsonl",
        source_prefix: str | None = None,
        markdown_prefix: str = DEFAULT_MARKDOWN_PREFIX,
        chunk_prefix: str = DEFAULT_CHUNK_PREFIX,
        strip_raw_prefix: bool = True,
        client: MinioClient | None = None,
    ) -> None:
        self.client: MinioClient = client or get_minio_client()
        if metadata_path is not None:
            metadata_dir = Path(metadata_path).expanduser()
            if metadata_dir.suffix:
                metadata_dir = metadata_dir.parent
            raw_to_markdown_metadata_path = metadata_dir / "raw_to_markdown_metadata.jsonl"
            markdown_to_chunk_metadata_path = metadata_dir / "markdown_to_chunk_metadata.jsonl"
            chunk_to_qdrant_metadata_path = metadata_dir / "chunk_to_qdrant_metadata.jsonl"
        self.raw_to_markdown_metadata_path = Path(
            raw_to_markdown_metadata_path
        ).expanduser().resolve()
        self.markdown_to_chunk_metadata_path = Path(
            markdown_to_chunk_metadata_path
        ).expanduser().resolve()
        self.chunk_to_qdrant_metadata_path = Path(
            chunk_to_qdrant_metadata_path
        ).expanduser().resolve()
        self.raw_to_markdown_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.markdown_to_chunk_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.chunk_to_qdrant_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_prefix = self.normalize_prefix(
            source_prefix or self.default_source_prefix()
        )
        self.markdown_prefix = self.normalize_prefix(markdown_prefix)
        self.chunk_prefix = self.normalize_prefix(chunk_prefix)
        self.strip_raw_prefix = strip_raw_prefix
        self._meta_lock = threading.Lock()
        self.raw_to_markdown_index = self.load_processed_index(
            self.raw_to_markdown_metadata_path
        )
        self.markdown_to_chunk_index = self.load_processed_index(
            self.markdown_to_chunk_metadata_path
        )
        self.chunk_to_qdrant_index = self.load_processed_index(
            self.chunk_to_qdrant_metadata_path
        )
        self.processed_index = {
            **self.raw_to_markdown_index,
            **self.markdown_to_chunk_index,
            **self.chunk_to_qdrant_index,
        }

    def stat_source_object(self, key: str) -> dict[str, Any]:
        """Adapt MinIO head_object output to the object shape used by metadata records."""
        stat = self.client.stat_object(self.BUCKET, key)
        return {
            "Key": key,
            "Size": int(stat.get("ContentLength") or stat.get("Size") or 0),
            "ETag": stat.get("ETag"),
            "ContentType": stat.get("ContentType"),
            "LastModified": stat.get("LastModified"),
        }

    def list_source_keys(self, prefix: str | None = None) -> list[str]:
        """List source object keys, excluding generated markdown/chunk outputs."""
        effective_prefix = self.normalize_prefix(prefix) if prefix else self.source_prefix
        keys = self.client.list_objects(self.BUCKET, prefix=effective_prefix)
        return [
            key
            for key in keys
            if key
            and not key.endswith("/")
            and not key.startswith(self.markdown_prefix)
            and not key.startswith(self.chunk_prefix)
        ]

    def has_markdown_record(self, raw_key: str) -> bool:
        """Whether raw -> markdown has already succeeded for this source key."""
        rec = self.raw_to_markdown_index.get(raw_key) or {}
        return rec.get("status") == STATUS_MARKDOWN and bool(rec.get("markdown_key"))

    def has_chunk_record(self, raw_key: str) -> bool:
        """Whether markdown -> chunk has already succeeded for this source key."""
        rec = self.markdown_to_chunk_index.get(raw_key) or {}
        return rec.get("status") == STATUS_CHUNK and bool(rec.get("chunk_key"))

    def has_vectorized_record(self, raw_key: str) -> bool:
        """Whether chunk -> Qdrant has already succeeded for this source key."""
        rec = self.chunk_to_qdrant_index.get(raw_key) or {}
        return rec.get("status") == STATUS_VECTORIZED and bool(rec.get("qdrant_collection"))

    def get_chunk_key(self, raw_key: str) -> str | None:
        rec = self.markdown_to_chunk_index.get(raw_key) or {}
        value = rec.get("chunk_key")
        return str(value) if value else None

    def get_markdown_key(self, raw_key: str) -> str | None:
        """Return the recorded Markdown key for a source key, if present."""
        rec = self.raw_to_markdown_index.get(raw_key) or {}
        value = rec.get("markdown_key")
        return str(value) if value else None

    def get_converter(self, raw_key: str) -> str:
        """Return converter recorded by raw -> markdown, if present."""
        rec = self.raw_to_markdown_index.get(raw_key) or {}
        return str(rec.get("converter") or "unknown")

    def download_raw(self, key: str) -> bytes:
        return self.client.download_bytes(self.BUCKET, key)

    def upload_markdown(self, md_key: str, md_text: str) -> None:
        self.client.upload_bytes(
            self.BUCKET,
            md_key,
            md_text.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    def download_markdown(self, md_key: str) -> str:
        return self.client.download_bytes(self.BUCKET, md_key).decode(
            "utf-8",
            errors="replace",
        )

    def upload_chunk_json(self, chunk_key: str, payload_bytes: bytes) -> None:
        self.client.upload_bytes(
            self.BUCKET,
            chunk_key,
            payload_bytes,
            content_type="application/json; charset=utf-8",
        )

    def build_markdown_key(self, key: str) -> str:
        rel = self._relative_output_key(key)
        return f"{self.markdown_prefix}{Path(rel).with_suffix('.md').as_posix()}"

    def build_chunk_key(self, key: str) -> str:
        rel = self._relative_output_key(key)
        return f"{self.chunk_prefix}{Path(rel).with_suffix('.json').as_posix()}"

    def build_metadata_record(self, obj: dict[str, Any]) -> dict[str, Any]:
        key = obj.get("Key", "")
        path = Path(key)
        suffix = path.suffix.lower()
        content_type = obj.get("ContentType") or mimetypes.guess_type(path.name)[0] or ""
        existing = self.processed_index.get(key)
        uuid_val = (existing.get("uuid") if existing else None) or str(_uuid.uuid4())
        return {
            "uuid": uuid_val,
            "filename": path.name,
            "first_path": key,
            "size": int(obj.get("Size") or 0),
            "suffix": suffix,
            "content_type": content_type,
            "bucket": self.BUCKET,
        }

    def record_markdown(
        self,
        *,
        obj: dict[str, Any],
        key: str,
        md_key: str,
        md_text: str,
        conv_meta: dict[str, Any],
    ) -> None:
        rec = self.build_metadata_record(obj)
        rec.update(
            {
                "etag": self.normalize_etag(obj.get("ETag")),
                "stage": "raw_to_markdown",
                "status": STATUS_MARKDOWN,
                "markdown_key": md_key,
                "markdown_chars": len(md_text),
                "converter": conv_meta.get("converter") or "unknown",
                "processed_at": now_iso(),
            }
        )
        self.append_record(rec, self.raw_to_markdown_metadata_path)
        self.raw_to_markdown_index[key] = rec

    def record_chunk(
        self,
        *,
        obj: dict[str, Any],
        key: str,
        md_key: str,
        md_chars: int,
        chunk_key: str,
        chunk_count: int,
        chunk_bytes: int,
        converter: str,
    ) -> None:
        rec = self.build_metadata_record(obj)
        rec.update(
            {
                "etag": self.normalize_etag(obj.get("ETag")),
                "stage": "markdown_to_chunk",
                "status": STATUS_CHUNK,
                "markdown_key": md_key,
                "markdown_chars": md_chars,
                "chunk_key": chunk_key,
                "chunk_count": chunk_count,
                "chunk_bytes": chunk_bytes,
                "converter": converter,
                "processed_at": now_iso(),
            }
        )
        self.append_record(rec, self.markdown_to_chunk_metadata_path)
        self.markdown_to_chunk_index[key] = rec

    def record_vectorized(
        self,
        *,
        obj: dict[str, Any],
        key: str,
        chunk_key: str,
        collection: str,
        doc_uuid: str,
        point_count: int,
        tenant_id: str = "",
    ) -> None:
        rec = self.build_metadata_record(obj)
        chunk_rec = self.markdown_to_chunk_index.get(key) or {}
        rec.update(
            {
                "etag": self.normalize_etag(obj.get("ETag")),
                "stage": "chunk_to_qdrant",
                "status": STATUS_VECTORIZED,
                "chunk_key": chunk_key,
                "chunk_count": chunk_rec.get("chunk_count", point_count),
                "qdrant_collection": collection,
                "doc_uuid": doc_uuid,
                "point_count": point_count,
                "tenant_id": tenant_id,
                "processed_at": now_iso(),
            }
        )
        self.append_record(rec, self.chunk_to_qdrant_metadata_path)
        self.chunk_to_qdrant_index[key] = rec

    def record_failure(self, obj: dict[str, Any], key: str, error: str, *, stage: str) -> None:
        rec = self.build_metadata_record(obj)
        rec.update(
            {
                "etag": self.normalize_etag(obj.get("ETag")),
                "status": STATUS_RAW,
                "stage": stage,
                "error": error[:500],
                "processed_at": now_iso(),
            }
        )
        if stage in {"raw_to_markdown", "convert", "markdown"}:
            target = self.raw_to_markdown_metadata_path
            self.raw_to_markdown_index[key] = rec
        elif stage in {"chunk_to_qdrant", "vectorize", "qdrant"}:
            target = self.chunk_to_qdrant_metadata_path
            self.chunk_to_qdrant_index[key] = rec
        else:
            target = self.markdown_to_chunk_metadata_path
            self.markdown_to_chunk_index[key] = rec
        self.append_record(rec, target)

    def append_record(self, record: dict[str, Any], metadata_path: Path) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._meta_lock:
            with metadata_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
        key = record.get("first_path")
        if key:
            self.processed_index[key] = record

    def load_processed_index(self, metadata_path: Path) -> dict[str, dict[str, Any]]:
        if not metadata_path.exists():
            return {}

        index: dict[str, dict[str, Any]] = {}
        with metadata_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = rec.get("first_path")
                if key:
                    index[key] = rec
        return index

    def _relative_output_key(self, key: str) -> str:
        rel = key
        if self.strip_raw_prefix and rel.startswith("raw/"):
            rel = rel[len("raw/") :]
        return rel

    @staticmethod
    def normalize_prefix(prefix: str) -> str:
        p = (prefix or "").strip().lstrip("/")
        if p and not p.endswith("/"):
            p += "/"
        return p

    @classmethod
    def default_source_prefix(cls) -> str:
        qdrant = getattr(settings, "Qdrant", None) or {}
        collection = ""
        if isinstance(qdrant, dict):
            collection = str(qdrant.get("collection") or "").strip()
        collection = collection or str(
            getattr(settings, "qdrant_collection", "") or ""
        ).strip()
        if collection:
            return f"raw/{collection}/"
        return cls.DEFAULT_RAW_PREFIX

    @staticmethod
    def normalize_etag(etag: str | None) -> str:
        if not etag:
            return ""
        return etag.strip().strip('"').lower()

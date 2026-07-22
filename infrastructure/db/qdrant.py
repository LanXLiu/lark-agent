"""Qdrant 向量数据库客户端封装（7 collection + dense/sparse 混合检索）。"""

from __future__ import annotations

import threading
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from qdrant_client import QdrantClient as _QdrantClient
from qdrant_client.http import models

from infrastructure.conf.settings import settings
from knowledge.utils.collection_router import DEFAULT_COLLECTIONS, infer_collection_from_raw_key

# Qdrant 间歇性 502/网络抖动时自动重试（共享服务器不稳）
_QDRANT_MAX_ATTEMPTS = 5
_QDRANT_RETRY_BASE_DELAY = 0.5


def _qdrant_retry(fn, *, what: str):
    """对单次 Qdrant 调用做重试；全部失败抛最后一次异常。"""
    last_exc: Exception | None = None
    for attempt in range(1, _QDRANT_MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 —— 502/网络类统一重试
            last_exc = exc
            if attempt < _QDRANT_MAX_ATTEMPTS:
                delay = _QDRANT_RETRY_BASE_DELAY * attempt
                logger.warning(
                    "Qdrant {} 失败（第 {}/{} 次），{:.1f}s 后重试：{}",
                    what, attempt, _QDRANT_MAX_ATTEMPTS, delay, str(exc)[:80],
                )
                time.sleep(delay)
            else:
                logger.error("Qdrant {} 连续 {} 次失败", what, _QDRANT_MAX_ATTEMPTS)
    raise last_exc if last_exc else RuntimeError(f"Qdrant {what} failed")


@dataclass(frozen=True)
class QdrantConfig:
    """标准化后的 Qdrant 连接与 schema 配置。"""

    host: str
    port: int = 6333
    api_key: str = ""
    collection: str = "knowledge_base"
    vector_size: int = 1024
    use_ssl: bool = False
    timeout: int = 30
    dense_vector_name: str = "dense"
    sparse_vector_name: str = "bm25"
    sparse_model: str = "Qdrant/bm25"
    point_id_namespace: str = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    default_collection: str = "temporary"
    collections: tuple[str, ...] = DEFAULT_COLLECTIONS
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100
    hybrid_vector_weight: float = 0.7
    hybrid_keyword_weight: float = 0.3
    hybrid_prefetch_limit: int = 20

    @classmethod
    def from_settings(cls) -> "QdrantConfig":
        nested: dict[str, Any] = getattr(settings, "Qdrant", None) or {}
        if not isinstance(nested, dict):
            nested = {}

        collections_raw = nested.get("collections")
        if isinstance(collections_raw, list) and collections_raw:
            collections = tuple(str(c).strip() for c in collections_raw if str(c).strip())
        else:
            collections = DEFAULT_COLLECTIONS

        hnsw = nested.get("hnsw") if isinstance(nested.get("hnsw"), dict) else {}
        hybrid = nested.get("hybrid") if isinstance(nested.get("hybrid"), dict) else {}

        return cls(
            host=_strip_scheme(str(_first_non_empty(nested.get("host"), "127.0.0.1"))),
            port=int(_first_non_empty(nested.get("port"), 6333)),
            api_key=str(_first_non_none(nested.get("api_key"), "") or ""),
            collection=str(_first_non_empty(nested.get("collection"), "knowledge_base")),
            vector_size=int(_first_non_empty(nested.get("vector_size"), 1024)),
            use_ssl=_to_bool(_first_non_none(nested.get("use_ssl"), False)),
            timeout=int(_first_non_empty(nested.get("timeout"), 30)),
            dense_vector_name=str(
                _first_non_empty(nested.get("dense_vector_name"), "dense")
            ),
            sparse_vector_name=str(
                _first_non_empty(nested.get("sparse_vector_name"), "bm25")
            ),
            sparse_model=str(_first_non_empty(nested.get("sparse_model"), "Qdrant/bm25")),
            point_id_namespace=str(
                _first_non_empty(
                    nested.get("point_id_namespace"),
                    "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                )
            ),
            default_collection=str(
                _first_non_empty(nested.get("default_collection"), "temporary")
            ),
            collections=collections,
            hnsw_m=int(_first_non_empty(hnsw.get("m"), 16)),
            hnsw_ef_construct=int(_first_non_empty(hnsw.get("ef_construct"), 100)),
            hybrid_vector_weight=float(
                _first_non_empty(hybrid.get("vector_weight"), 0.7)
            ),
            hybrid_keyword_weight=float(
                _first_non_empty(hybrid.get("keyword_weight"), 0.3)
            ),
            hybrid_prefetch_limit=int(
                _first_non_empty(hybrid.get("prefetch_limit"), 20)
            ),
        )

    @property
    def url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def point_namespace_uuid(self) -> _uuid.UUID:
        return _uuid.UUID(self.point_id_namespace)


def make_point_id(config: QdrantConfig, doc_uuid: str, chunk_index: int) -> str:
    """Qdrant 点主键：uuid5(namespace, doc_uuid_chunk_index)。"""
    name = f"{doc_uuid}_{chunk_index}"
    return str(_uuid.uuid5(config.point_namespace_uuid, name))


def infer_collection(raw_key: str, config: QdrantConfig | None = None) -> str:
    cfg = config or QdrantConfig.from_settings()
    return infer_collection_from_raw_key(
        raw_key,
        collections=cfg.collections,
        fallback=cfg.default_collection,
    )


class QdrantClient:
    """Qdrant 客户端单例：collection schema、写入、混合检索、按文档删除。"""

    _instance: "QdrantClient | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "QdrantClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: QdrantConfig | None = None) -> None:
        if self._initialized:
            return
        self.config = config or QdrantConfig.from_settings()
        self._client = _QdrantClient(
            url=self.config.url,
            api_key=self.config.api_key or None,
            timeout=self.config.timeout,
        )
        self._initialized = True
        logger.info("Qdrant 客户端已初始化：{}", self.config.url)

    @property
    def raw(self) -> _QdrantClient:
        return self._client

    def health_check(self) -> bool:
        self._client.get_collections()
        return True

    def collection_exists(self, collection_name: str) -> bool:
        collections = self._client.get_collections().collections
        return any(c.name == collection_name for c in collections)

    def ensure_collection_schema(self, collection_name: str) -> None:
        """创建带 dense(HNSW) + sparse(BM25) 的 collection，并补齐 payload 索引。"""
        cfg = self.config
        if self.collection_exists(collection_name):
            logger.debug("Qdrant collection 已存在：{}", collection_name)
            self.ensure_payload_indexes(collection_name)
            return

        self._client.create_collection(
            collection_name=collection_name,
            vectors_config={
                cfg.dense_vector_name: models.VectorParams(
                    size=cfg.vector_size,
                    distance=models.Distance.COSINE,
                    hnsw_config=models.HnswConfigDiff(
                        m=cfg.hnsw_m,
                        ef_construct=cfg.hnsw_ef_construct,
                    ),
                ),
            },
            sparse_vectors_config={
                cfg.sparse_vector_name: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )
        logger.info(
            "Qdrant collection 已创建：{} dense={} sparse={} dim={}",
            collection_name,
            cfg.dense_vector_name,
            cfg.sparse_vector_name,
            cfg.vector_size,
        )
        self.ensure_payload_indexes(collection_name)

    def ensure_all_collections(self) -> None:
        for name in self.config.collections:
            self.ensure_collection_schema(name)

    def ensure_payload_indexes(self, collection_name: str) -> None:
        """为过滤/全文检索建立 payload 索引。"""
        index_specs: list[tuple[str, models.PayloadSchemaType]] = [
            ("doc_uuid", models.PayloadSchemaType.KEYWORD),
            ("tenant_id", models.PayloadSchemaType.KEYWORD),
            ("source", models.PayloadSchemaType.KEYWORD),
            ("filename", models.PayloadSchemaType.KEYWORD),
            ("doc_type", models.PayloadSchemaType.KEYWORD),
            ("chunk_kind", models.PayloadSchemaType.KEYWORD),
            ("converter", models.PayloadSchemaType.KEYWORD),
            ("chunker_strategy", models.PayloadSchemaType.KEYWORD),
            ("is_deleted", models.PayloadSchemaType.BOOL),
            ("content", models.PayloadSchemaType.TEXT),
            ("title", models.PayloadSchemaType.TEXT),
        ]
        for field_name, schema_type in index_specs:
            try:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "payload 索引可能已存在 collection={} field={} err={}",
                    collection_name,
                    field_name,
                    exc,
                )

    def upsert_points(
        self,
        points: list[models.PointStruct],
        collection_name: str,
    ) -> None:
        if not points:
            return
        self._client.upsert(collection_name=collection_name, points=points)

    def _base_filter(
        self,
        *,
        tenant_id: str | None = None,
        include_deleted: bool = False,
    ) -> models.Filter | None:
        must: list[models.Condition] = []
        if tenant_id:
            must.append(
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id),
                )
            )
        must_not: list[models.Condition] = []
        if not include_deleted:
            must_not.append(
                models.FieldCondition(
                    key="is_deleted",
                    match=models.MatchValue(value=True),
                )
            )
        if not must and not must_not:
            return None
        return models.Filter(must=must or None, must_not=must_not or None)

    def hybrid_search(
        self,
        *,
        collection_name: str,
        query_dense: list[float],
        query_sparse: models.SparseVector,
        limit: int = 10,
        tenant_id: str | None = None,
        extra_filter: models.Filter | None = None,
    ):
        """RRF 融合 dense + sparse 检索。"""
        cfg = self.config
        base = self._base_filter(tenant_id=tenant_id)
        query_filter = base
        if extra_filter is not None and base is not None:
            query_filter = models.Filter(must=[base, extra_filter])
        elif extra_filter is not None:
            query_filter = extra_filter

        prefetch_limit = max(limit, cfg.hybrid_prefetch_limit)
        return _qdrant_retry(
            lambda: self._client.query_points(
                collection_name=collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_dense,
                        using=cfg.dense_vector_name,
                        limit=prefetch_limit,
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=query_sparse,
                        using=cfg.sparse_vector_name,
                        limit=prefetch_limit,
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            ),
            what="hybrid_search",
        )

    def scroll_points_by_doc_uuid(
        self,
        collection_name: str,
        doc_uuid: str,
        *,
        tenant_id: str | None = None,
        include_deleted: bool = True,
    ) -> list[models.Record]:
        """滚动拉取某文档的全部 point（用于软删/硬删）。"""
        doc_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_uuid",
                    match=models.MatchValue(value=doc_uuid),
                )
            ]
        )
        base = self._base_filter(
            tenant_id=tenant_id,
            include_deleted=include_deleted,
        )
        if base is not None:
            query_filter = models.Filter(must=[doc_filter, base])
        else:
            query_filter = doc_filter

        records: list[models.Record] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=collection_name,
                scroll_filter=query_filter,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            records.extend(points)
            if offset is None:
                break
        return records

    def scroll_siblings(
        self,
        collection_name: str,
        *,
        doc_uuid: str,
        breadcrumb_prefix: str,
        tenant_id: str | None = None,
        limit: int = 64,
    ) -> list[models.Record]:
        """拉取「同文档 + breadcrumb 以指定父路径开头」的兄弟 chunk（父子召回用）。

        breadcrumb_prefix 为命中 chunk 的父路径（其 breadcrumb 去掉最后一段）。
        做法：按 doc_uuid 精确拉取该文档全部 chunk（带 payload），在内存里按
        breadcrumb 前缀过滤——避免 Qdrant 全文索引对中文分词不可靠的问题，
        且单文档 chunk 数有限，开销可接受。
        """
        prefix = (breadcrumb_prefix or "").strip()
        if not prefix:
            return []
        doc_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_uuid", match=models.MatchValue(value=doc_uuid)
                )
            ]
        )
        base = self._base_filter(tenant_id=tenant_id, include_deleted=False)
        query_filter = (
            models.Filter(must=[doc_filter, base]) if base is not None else doc_filter
        )

        matched: list[models.Record] = []
        offset = None
        while True:
            points, offset = _qdrant_retry(
                lambda: self._client.scroll(
                    collection_name=collection_name,
                    scroll_filter=query_filter,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                ),
                what="scroll_siblings",
            )
            for p in points:
                bc = str((p.payload or {}).get("breadcrumb") or "")
                if bc.startswith(prefix):
                    matched.append(p)
            if offset is None or len(matched) >= limit:
                break
        return matched[:limit]

    def delete_by_doc_uuid(
        self,
        collection_name: str,
        doc_uuid: str,
        *,
        tenant_id: str | None = None,
        hard: bool = False,
    ) -> int:
        """按 doc_uuid 软删（默认）或硬删，返回影响点数。"""
        if hard:
            must: list[models.Condition] = [
                models.FieldCondition(
                    key="doc_uuid",
                    match=models.MatchValue(value=doc_uuid),
                )
            ]
            if tenant_id:
                must.append(
                    models.FieldCondition(
                        key="tenant_id",
                        match=models.MatchValue(value=tenant_id),
                    )
                )
            self._client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=must),
                ),
            )
            logger.info(
                "Qdrant 硬删除 collection={} doc_uuid={} tenant_id={}",
                collection_name,
                doc_uuid,
                tenant_id or "*",
            )
            return -1

        records = self.scroll_points_by_doc_uuid(
            collection_name,
            doc_uuid,
            tenant_id=tenant_id,
            include_deleted=True,
        )
        if not records:
            logger.warning(
                "Qdrant 软删除未找到 point collection={} doc_uuid={}",
                collection_name,
                doc_uuid,
            )
            return 0

        point_ids = [record.id for record in records]
        self._client.set_payload(
            collection_name=collection_name,
            payload={"is_deleted": True},
            points=point_ids,
        )
        logger.info(
            "Qdrant 软删除 collection={} doc_uuid={} points={}",
            collection_name,
            doc_uuid,
            len(point_ids),
        )
        return len(point_ids)

    def search_dense(
        self,
        query_vector: list[float],
        collection_name: str,
        *,
        limit: int = 10,
        tenant_id: str | None = None,
        query_filter: models.Filter | None = None,
    ):
        """仅 dense 向量检索（兼容旧接口）。"""
        base = self._base_filter(tenant_id=tenant_id)
        final_filter = base
        if query_filter is not None and base is not None:
            final_filter = models.Filter(must=[base, query_filter])
        elif query_filter is not None:
            final_filter = query_filter

        return self._client.search(
            collection_name=collection_name,
            query_vector=(self.config.dense_vector_name, query_vector),
            query_filter=final_filter,
            limit=limit,
            with_payload=True,
        )


def get_qdrant_client() -> QdrantClient:
    return QdrantClient()


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _strip_scheme(value: str) -> str:
    return value.replace("http://", "").replace("https://", "").rstrip("/")


__all__ = [
    "QdrantConfig",
    "QdrantClient",
    "get_qdrant_client",
    "make_point_id",
    "infer_collection",
    "DEFAULT_COLLECTIONS",
]

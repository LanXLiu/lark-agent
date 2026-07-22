"""直接把 MinIO 里 chunk/ 目录下的所有 chunk JSON 向量化入 Qdrant。

绕过两套管线 metadata 不互通的问题：直接扫 MinIO chunk 前缀，逐个读 chunk JSON
（含 doc_uuid / chunks / source / markdown_key / filename），向量化后 upsert。
breadcrumb 已在切片 metadata 里，build_point_struct 会写入 payload（父子召回可用）。

用法：
  python -m ops.scripts.chunk_minio_to_qdrant                      # 全部 chunk/
  python -m ops.scripts.chunk_minio_to_qdrant --prefix chunk/knowledgebase/lark/oc_xxx/
  python -m ops.scripts.chunk_minio_to_qdrant --collection knowledgebase
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loguru import logger

from infrastructure.object_storage import get_minio_client
from infrastructure.vector_store import get_qdrant_client
from infrastructure.model.embedding_client import EmbeddingClient
from knowledge.utils.payload_builder import build_point_struct, chunk_dict_to_result
from knowledge.utils.sparse_embedder import SparseEmbedder

BUCKET = "knowledgebase"


def iter_chunk_keys(client, prefix: str):
    paginator = client.raw.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key", "")
            if key.endswith(".json"):
                yield key


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="chunk/", help="MinIO chunk 前缀，默认 chunk/")
    ap.add_argument("--collection", default=None, help="目标 collection，默认按配置/推断")
    ap.add_argument("--embed-batch", type=int, default=32)
    args = ap.parse_args()

    minio = get_minio_client()
    qdrant = get_qdrant_client()
    embedder = EmbeddingClient()
    sparse = SparseEmbedder(qdrant.config)

    collection = args.collection or qdrant.config.default_collection
    qdrant.ensure_collection_schema(collection)
    logger.info("目标 collection={} 扫描 prefix={}", collection, args.prefix)

    keys = list(iter_chunk_keys(minio, args.prefix))
    logger.info("发现 chunk JSON {} 个", len(keys))

    total_files = 0
    total_points = 0
    failed = 0
    for ck in keys:
        try:
            payload = json.loads(minio.download_bytes(BUCKET, ck).decode("utf-8"))
            doc_uuid = str(payload.get("doc_uuid") or "")
            if not doc_uuid:
                logger.warning("chunk JSON 无 doc_uuid，跳过 {}", ck)
                continue
            chunks = [chunk_dict_to_result(it) for it in payload.get("chunks") or []]
            if not chunks:
                continue
            doc_meta = {
                "source": payload.get("source") or "",
                "markdown_key": payload.get("markdown_key") or "",
                "filename": payload.get("filename") or ck.split("/")[-1],
                "converter": payload.get("converter") or "unknown",
                "chunker_strategy": payload.get("chunker_strategy") or "unknown",
            }
            texts = [c.text for c in chunks]
            points = []
            for start in range(0, len(texts), args.embed_batch):
                batch = chunks[start : start + args.embed_batch]
                bt = [c.text for c in batch]
                dvs = embedder.encode_passage(bt)
                svs = sparse.embed_texts(bt)
                for chunk, dv, sv in zip(batch, dvs, svs):
                    points.append(
                        build_point_struct(
                            config=qdrant.config,
                            doc_uuid=doc_uuid,
                            chunk=chunk,
                            dense_vector=dv,
                            sparse_vector=sv,
                            doc_meta=doc_meta,
                        )
                    )
            qdrant.upsert_points(points, collection)
            total_files += 1
            total_points += len(points)
            logger.info("✔ {} -> {} points (doc_uuid={})", doc_meta["filename"], len(points), doc_uuid)
        except Exception as e:  # noqa: BLE001 —— 单文件失败不影响整体，记下继续
            failed += 1
            logger.exception("✘ 向量化失败 key={}: {}", ck, e)

    logger.info(
        "完成：文件={} 成功, points={}, 失败={}",
        total_files, total_points, failed,
    )


if __name__ == "__main__":
    main()

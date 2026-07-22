#!/usr/bin/env python3
"""按 doc_uuid 删除 Qdrant 文档切片（默认软删）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from infrastructure.vector_store import get_qdrant_client


def delete_doc(
    doc_uuid: str,
    collection: str,
    tenant_id: str = "",
    *,
    hard: bool = False,
) -> int:
    """删除指定文档在 Qdrant 中的全部切片。"""
    client = get_qdrant_client()
    client.health_check()
    if not client.collection_exists(collection):
        raise RuntimeError(f"collection 不存在: {collection}")
    return client.delete_by_doc_uuid(
        collection,
        doc_uuid,
        tenant_id=tenant_id or None,
        hard=hard,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="删除 Qdrant 文档向量")
    parser.add_argument("doc_uuid", help="文档 UUID（与 chunk JSON 中 doc_uuid 一致）")
    parser.add_argument(
        "collection",
        help="Qdrant collection 名称，如 rules / company / temporary",
    )
    parser.add_argument("--tenant-id", default="", help="可选租户 ID 过滤")
    parser.add_argument(
        "--hard",
        action="store_true",
        help="物理删除 points；默认仅设置 is_deleted=true",
    )
    args = parser.parse_args()

    affected = delete_doc(
        args.doc_uuid,
        args.collection,
        tenant_id=args.tenant_id,
        hard=args.hard,
    )
    mode = "硬删" if args.hard else "软删"
    logger.info("{} 完成 doc_uuid={} collection={} affected={}", mode, args.doc_uuid, args.collection, affected)


if __name__ == "__main__":
    main()

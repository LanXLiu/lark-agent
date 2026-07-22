#!/usr/bin/env python3
"""初始化 Qdrant 7 个 collection（dense HNSW + sparse BM25 + payload 索引）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from infrastructure.vector_store import get_qdrant_client


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 Qdrant collections")
    parser.add_argument(
        "--collection",
        action="append",
        dest="collections",
        help="仅初始化指定 collection，可重复传入；默认初始化配置中的全部 7 个",
    )
    args = parser.parse_args()

    client = get_qdrant_client()
    client.health_check()
    targets = args.collections or list(client.config.collections)
    for name in targets:
        client.ensure_collection_schema(name)
        logger.info("collection 就绪：{}", name)
    logger.info("初始化完成，共 {} 个 collection", len(targets))


if __name__ == "__main__":
    main()

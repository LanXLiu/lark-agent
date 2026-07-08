#!/usr/bin/env python3
"""命令行混合召回测试。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from recall import HybridRecaller, RecallRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="混合召回 CLI")
    parser.add_argument("query", help="检索问题")
    parser.add_argument(
        "--collection",
        required=True,
        help="Qdrant collection，如 rules / company",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--doc-uuid", default=None)
    parser.add_argument("--no-rerank", action="store_true", help="关闭 cross-encoder 精排")
    parser.add_argument(
        "--candidate-top-k",
        type=int,
        default=None,
        help="精排前候选条数（默认读配置 recall.rerank.candidate_top_k）",
    )
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    result = HybridRecaller().search(
        RecallRequest(
            query=args.query,
            collection=args.collection,
            top_k=args.top_k,
            tenant_id=args.tenant_id,
            doc_uuid=args.doc_uuid,
            enable_rerank=False if args.no_rerank else None,
            candidate_top_k=args.candidate_top_k,
        )
    )

    if args.json:
        payload = {
            "query": result.query,
            "collection": result.collection,
            "total": result.total,
            "latency_ms": result.latency_ms,
            "hits": [
                {
                    "score": h.score,
                    "id": h.id,
                    "filename": h.filename,
                    "title": h.title,
                    "content": h.content[:300],
                }
                for h in result.hits
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    rerank_tag = f" rerank={result.model_rerank}" if result.rerank_enabled else ""
    print(
        f"collection={result.collection} total={result.total} "
        f"latency={result.latency_ms}ms{rerank_tag}"
    )
    for i, h in enumerate(result.hits, 1):
        preview = h.content.replace("\n", " ")[:200]
        rr = f" rerank={h.rerank_score:.4f}" if h.rerank_score is not None else ""
        print(f"\n[{i}] score={h.score:.4f}{rr} {h.filename} #{h.chunk_index}")
        print(f"    {preview}")


if __name__ == "__main__":
    main()

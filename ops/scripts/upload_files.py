"""把本地文件 / 目录直接上传到 MinIO 的 raw 区，接入现有入库管线。

不经过飞书：适合在服务器上把本地磁盘的文档灌进知识库。文件落到
``raw/<collection>/<prefix>/<相对路径>``，之后照跑 orchestrator 即可
（转换 → 切片 → 向量化），与飞书来的文件走完全相同的后续流程。

复用现有能力，不重写上传/入库逻辑：
- 上传：db.minio.MinioClient.upload_file（orchestrator 自己也用它）；
- 支持的扩展名：knowledge.ingestion.DEFAULT_SUPPORTED_EXTS；
- collection：默认取 db.qdrant 的 config.default_collection。

用法：
  python -m ops.scripts.upload_files --path ./docs                      # 递归上传整个目录
  python -m ops.scripts.upload_files --path ./a.pdf                     # 单个文件
  python -m ops.scripts.upload_files --path ./docs --collection knowledgebase
  python -m ops.scripts.upload_files --path ./docs --dry-run            # 只看将上传什么，不实际传
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loguru import logger

from infrastructure.object_storage import get_minio_client
from infrastructure.vector_store import get_qdrant_client
from knowledge.ingestion import DEFAULT_SUPPORTED_EXTS

BUCKET = "knowledgebase"


def normalize_path_part(value: str) -> str:
    """清洗单个路径段里的非法字符（等价于 minio_uploader 的同名函数，避免 import 飞书模块）。"""
    cleaned = (value or "").strip().strip("/\\")
    for char in '<>:"\\|?*\x00':
        cleaned = cleaned.replace(char, "_")
    return cleaned or "unknown"


def collect_files(path: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """收集待上传文件。

    返回 (accepted, skipped)：
    - accepted: [(绝对路径, 相对路径)]，相对路径用于在 raw 下保留目录层级；
    - skipped:  扩展名不支持而跳过的文件。
    单文件时相对路径就是文件名；目录时递归、相对该目录。
    """
    accepted: list[tuple[Path, Path]] = []
    skipped: list[Path] = []

    if path.is_file():
        if path.suffix.lower() in DEFAULT_SUPPORTED_EXTS:
            accepted.append((path, Path(path.name)))
        else:
            skipped.append(path)
        return accepted, skipped

    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        if child.suffix.lower() in DEFAULT_SUPPORTED_EXTS:
            accepted.append((child, child.relative_to(path)))
        else:
            skipped.append(child)
    return accepted, skipped


def build_key(collection: str, prefix: str, rel_path: Path) -> str:
    """构造 raw key：raw/<collection>/<prefix>/<相对路径>，逐段清洗、保留层级。"""
    parts = [
        "raw",
        normalize_path_part(collection),
        normalize_path_part(prefix),
        *[normalize_path_part(p) for p in rel_path.parts],
    ]
    return "/".join(part for part in parts if part)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="把本地文件/目录上传到 MinIO 的 raw 区，供 orchestrator 入库"
    )
    ap.add_argument("--path", required=True, help="要上传的文件或目录（目录会递归）")
    ap.add_argument("--collection", default=None, help="目标库名，默认按 Qdrant 配置推断")
    ap.add_argument("--prefix", default="upload", help="raw 下的来源目录，默认 upload")
    ap.add_argument("--dry-run", action="store_true", help="只列出将上传的文件与 key，不实际上传")
    args = ap.parse_args()

    src = Path(args.path).expanduser()
    if not src.exists():
        ap.error(f"路径不存在：{src}")

    collection = args.collection or get_qdrant_client().config.default_collection

    accepted, skipped = collect_files(src)
    if not accepted:
        logger.warning("没有可上传的受支持文件（支持的扩展名：{}）", sorted(DEFAULT_SUPPORTED_EXTS))
        _print_skipped(skipped)
        return

    logger.info(
        "collection={} prefix={} 待上传={} 跳过={} {}",
        collection,
        args.prefix,
        len(accepted),
        len(skipped),
        "(dry-run)" if args.dry_run else "",
    )

    minio = None if args.dry_run else get_minio_client()
    uploaded = 0
    failed = 0
    for abs_path, rel_path in accepted:
        key = build_key(collection, args.prefix, rel_path)
        if args.dry_run:
            print(f"  [dry-run] {abs_path} -> {BUCKET}/{key}")
            continue
        try:
            content_type = mimetypes.guess_type(abs_path.name)[0]
            minio.upload_file(BUCKET, key, str(abs_path), content_type)
            uploaded += 1
            logger.info("已上传 {} -> {}/{}", abs_path.name, BUCKET, key)
        except Exception as exc:  # noqa: BLE001 —— 单个失败不影响其余文件
            failed += 1
            logger.error("上传失败 {}：{}", abs_path, exc)

    _print_skipped(skipped)

    if args.dry_run:
        print(f"\n[dry-run] 将上传 {len(accepted)} 个文件到 {BUCKET}/raw/{collection}/{args.prefix}/")
        return

    print(f"\n上传完成：成功 {uploaded}，失败 {failed}，跳过 {len(skipped)}")
    print("下一步（入库）：")
    print("  python -m knowledge.ingestion.orchestrator.knowledge_pipeline")
    print(f"  python -m ops.scripts.chunk_minio_to_qdrant --collection {collection}")


def _print_skipped(skipped: list[Path]) -> None:
    if not skipped:
        return
    print(f"\n跳过（扩展名不支持）{len(skipped)} 个：")
    for p in skipped:
        print(f"  - {p}")


if __name__ == "__main__":
    main()

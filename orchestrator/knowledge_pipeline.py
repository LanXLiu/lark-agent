# ruff: noqa: E402 — 主入口里需要在 import 业务模块前调整 sys.path
"""
KnowledgeBase 全量处理管线（三态机 + 断点续传 + 切片入库）。

三态流转
--------
每个 ``first_path``（即 MinIO 源 key）在 JSONL 中**只看最后一条记录**决定下一步动作：

    raw       ←  上传了但未处理 / 处理失败
    markdown  ←  已转 MD（已上传到 ``markdown/...``），但未切片
    chunk     ←  已切片完成（``chunk/...`` 已生成）

业务流程（按文件顺序，单文件错误不影响后续）：

1. **加载断点索引**：启动时读取本地 JSON Lines 文件（默认
   ``metadata/files_metadata.jsonl``）。同一 ``first_path`` 多条记录以**最后一条**
   为准（last-wins）。
2. **遍历**：递归扫描 MinIO ``knowledgebase`` 桶；跳过目录占位、跳过 ``markdown/``
   ``chunk/`` 等自身产出前缀、跳过未注册的扩展名。
3. **续传判定**：对每个待处理对象，若 ETag 一致（或 ETag 不可用时退化为 size 一致）：

   - 最后状态 = ``chunk``    → **完全跳过**（已完成）；
   - 最后状态 = ``markdown`` → **跳过转换，直接做切片**（从 MinIO 拉 ``.md`` 进切片）；
   - 最后状态 = ``raw``      → **从头再来**（上次失败）。

   ETag 不一致视为"源文件被覆盖更新" → 重新走完整流程（沿用同一 UUID 串审计链）。

4. **文档转换**：复用 ``file_to_markdown.unified_entry.convert_bytes`` 做 PDF/DOCX/PPT/XLSX/图片/JSON
   → Markdown 转换；``.md`` / ``.markdown`` 透传，``.txt`` 简单包装。

   PPT / Word 的视觉与表格行为**与 HTTP 接口完全一致**：

   - PPT：默认走视觉版（LibreOffice → PDF → PNG → VLM），失败自动回退到 python-pptx 文本版；
   - Word：图片优先 PPStructure OCR，识别字符不足时由 VLM 兜底"看图说话"；
   - Excel / Word / PPT 中的表格 → 先转为 JSON 数组（每行一条 record）→ 再拼装为
     「字段名：内容 字段名：内容」纯文本（详见 :mod:`file_to_markdown.table_renderer`）；
     其他来源（PDF / 图片 OCR / VLM 输出）若仍有 ``| ... |`` 残留，
     :func:`file_to_markdown.markdown_postprocess.finalize_for_kb` 兜底统一转换。

5. **回写 Markdown**：把 Markdown 上传回同桶 ``markdown/<相对路径>.md``，保留目录层级；
   自动剥掉原始 key 前缀 ``raw/`` 以满足任务说明里的目录约定。
   → 此刻立即写入一条 ``status=markdown`` 记录到 JSONL（落盘抵抗中断）。
6. **切片**：通过 :class:`chunker.ChunkerFactory` 按 ``chunk_strategy`` 选切片器
   （默认走 ``chunker.default_strategy`` 配置，可选 ``text`` / ``recursive`` /
   ``semantic`` / ``markdown_structure``）。所有 chunker 实现 :class:`chunker.BaseChunker`，
   异步 ``chunk()`` 返回 ``list[ChunkResult]``。结果序列化为 JSON 上传到
   ``chunk/<相对路径>.json``（**二级路径与 Markdown 完全一致**，仅扩展名换成 ``.json``）。
   → 上传成功后再写入 ``status=chunk`` 记录（包含 ``chunk_key`` / ``chunk_count`` 等）。
7. **失败登记**：任意环节抛错都会写入 ``status=raw`` + ``error`` 记录，便于下次重试。

底层调用：

- MinIO：复用 ``db.minio.get_minio_client()`` 单例（不重复实现连接逻辑）。
- 转换：复用 ``file_to_markdown.unified_entry.convert_bytes``（不重复实现转换器）。
- 切片：复用 ``chunker.ChunkerFactory``（不重复实现切片器）。
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

# 允许直接 ``python orchestrator/knowledge_pipeline.py`` 运行：
# 把项目根目录（本文件的父目录的父目录）加入 sys.path，便于解析 ``db`` / ``conf`` 等顶层包。
_PROJECT_ROOT = _Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import asyncio
import datetime as _dt
import json
import mimetypes
import threading
import time
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


def _now_iso() -> str:
    """UTC ISO-8601 时间戳（秒级，带 ``Z`` 后缀），用于落库审计。"""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

from chunker import BaseChunker, ChunkerFactory, ChunkResult
from conf.settings import settings
from db.minio import MinioClient, get_minio_client

# 由 file_to_markdown.unified_entry.convert_bytes 真正处理的扩展名
_UNIFIED_EXTS: set[str] = {
    ".pdf",
    ".docx",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".json",
}
# 直接透传 / 轻包装为 Markdown 的扩展名
_PASSTHROUGH_EXTS: set[str] = {".md", ".markdown", ".txt"}
DEFAULT_SUPPORTED_EXTS: set[str] = _UNIFIED_EXTS | _PASSTHROUGH_EXTS

# JSONL 中可能出现的 status 取值
STATUS_RAW = "raw"            # 上传了但未处理 / 处理失败
STATUS_MARKDOWN = "markdown"  # 已转 MD，未切片
STATUS_CHUNK = "chunk"        # 已切片完成


# ------------------------------------------------------------------------------------
# 统计
# ------------------------------------------------------------------------------------
@dataclass
class PipelineStats:
    """单次 ``KnowledgeBasePipeline.run`` 的处理统计。"""

    total: int = 0       # 遍历到的对象数
    skipped: int = 0     # 命中跳过规则的对象（目录占位 / 扩展名不支持 / 命中 skip_prefixes）
    resumed: int = 0     # 历史 JSONL 中已是 chunk 且 ETag 一致 → 完全跳过
    converted: int = 0   # 文档转换成功（写出 markdown）
    uploaded: int = 0    # Markdown 回写 MinIO 成功
    chunked: int = 0     # 切片 + 上传 chunk JSON 成功
    failed: int = 0      # 任意环节抛错的对象（写入 status=raw 记录）

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "skipped": self.skipped,
            "resumed": self.resumed,
            "converted": self.converted,
            "uploaded": self.uploaded,
            "chunked": self.chunked,
            "failed": self.failed,
        }


# ------------------------------------------------------------------------------------
# 管线
# ------------------------------------------------------------------------------------
class KnowledgeBasePipeline:
    """
    扫描 MinIO ``knowledgebase`` 桶并完成「登记 → 转换 → 回写」一条龙。

    Args:
        metadata_path: 本地 JSON Lines 文件路径；不存在的父目录会自动创建。
        markdown_prefix: Markdown 回写目录前缀（默认 ``markdown/``）。
        chunk_prefix: Chunk JSON 回写目录前缀（默认 ``chunk/``）。**与
            ``markdown_prefix`` 的二级路径完全对齐**，仅扩展名换成 ``.json``。
        skip_prefixes: 跳过遍历的对象前缀（默认包含 ``markdown_prefix`` / ``chunk_prefix``
            自身，防止把产出反复读回去当源文件）。
        strip_raw_prefix: ``True`` 时，回写路径会剥掉原始 key 的 ``raw/`` 前缀，
            符合任务示例 ``company/a/demo.pdf -> markdown/company/a/demo.md``。
        supported_exts: 允许处理的扩展名集合；默认见 ``DEFAULT_SUPPORTED_EXTS``。
        client: 可选注入的 ``MinioClient``（便于测试）；不传则使用项目单例。
        pptx_visual: PPT 转换是否走视觉版（LibreOffice + Poppler + VLM）。
            默认 ``True``，**与 ``/convert/slides`` 接口默认行为保持一致**。
            视觉版失败时（缺依赖 / 网络 / VLM key 错）由 ``unified_entry``
            自动回退到 python-pptx 文本版，不会让单个 PPT 拖垮整轮 pipeline。
        pptx_dpi: 视觉版 PDF → PNG 渲染 DPI（默认 200）。
        enable_word_vlm_fallback: Word 路径中，当 PPStructure 对某张图识别的有效
            字符数 < ``word_vlm_min_chars`` 时，是否调 VLM 做"看图说话"兜底。
            默认 ``True``，**与 ``/convert/docx`` 接口默认行为保持一致**；
            ``settings.MODELS.VLM.api_key`` 为空时自动禁用，不会报错。
        word_vlm_min_chars: 双重阈值（默认 20）——OCR 字符 < 此值触发 VLM；
            VLM 字符 > 此值才并入文档。
        enable_chunk: ``False`` 时只做 MD 转换 + 回写，**不做切片**（status 停在 ``markdown``，
            下次跑可以再补做切片）。默认 ``True``。
        chunk_strategy: 切片器策略名，传给 :class:`chunker.ChunkerFactory`；为 ``None``
            时使用 ``chunker.default_strategy`` 配置（默认 ``recursive``）。
            可选：``text`` / ``recursive`` / ``semantic`` / ``markdown_structure``。
        chunk_max_chars / chunk_overlap_chars: 调用 ``chunker.chunk()`` 时传入的
            ``chunk_size`` / ``chunk_overlap`` 参数。``semantic`` 策略使用自己的
            ``min_chunk_size`` / ``max_chunk_size`` 配置，会忽略这些 kwargs。
        chunk_min_chars: 保留参数，目前在 chunker 调用中不直接使用；可作为下游过滤参考。
        force: ``True`` 时忽略本地 JSONL 中的历史记录，对所有命中扩展名的对象**重新处理**。
            历史记录仍保留在 JSONL 中以便审计，新记录追加在文件末尾。
    """

    BUCKET = "knowledgebase"
    DEFAULT_RAW_PREFIX = "raw/knowledgebase/"
    DEFAULT_MARKDOWN_PREFIX = "markdown/"
    DEFAULT_CHUNK_PREFIX = "chunk/"

    def __init__(
        self,
        metadata_path: str | Path = "metadata/files_metadata.jsonl",
        source_prefix: str | None = None,
        markdown_prefix: str = DEFAULT_MARKDOWN_PREFIX,
        chunk_prefix: str = DEFAULT_CHUNK_PREFIX,
        skip_prefixes: Iterable[str] | None = None,
        *,
        strip_raw_prefix: bool = True,
        supported_exts: Iterable[str] | None = None,
        client: MinioClient | None = None,
        # ---- 与 HTTP 接口默认值保持一致 ----
        pptx_visual: bool = True,
        pptx_dpi: int = 200,
        enable_word_vlm_fallback: bool = True,
        word_vlm_min_chars: int = 20,
        # ---- 切片 ----
        enable_chunk: bool = True,
        chunk_strategy: str | None = None,
        chunk_max_chars: int = 1500,
        chunk_min_chars: int = 50,
        chunk_overlap_chars: int = 100,
        # ---- 断点续传 ----
        force: bool = False,
    ) -> None:
        self.client: MinioClient = client or get_minio_client()

        self.metadata_path = Path(metadata_path).expanduser().resolve()
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        self.source_prefix = self._normalize_prefix(
            source_prefix or self._default_source_prefix()
        )
        self.markdown_prefix = self._normalize_prefix(markdown_prefix)
        self.chunk_prefix = self._normalize_prefix(chunk_prefix)
        default_skip = tuple(p for p in (self.markdown_prefix, self.chunk_prefix) if p)
        self.skip_prefixes: tuple[str, ...] = (
            tuple(skip_prefixes) if skip_prefixes else default_skip
        )

        self.strip_raw_prefix = strip_raw_prefix
        self.supported_exts: set[str] = (
            {self._norm_ext(s) for s in supported_exts}
            if supported_exts is not None
            else set(DEFAULT_SUPPORTED_EXTS)
        )

        # 转换参数（透传给 file_to_markdown.unified_entry.convert_bytes）
        self.pptx_visual = bool(pptx_visual)
        self.pptx_dpi = int(pptx_dpi)
        self.enable_word_vlm_fallback = bool(enable_word_vlm_fallback)
        self.word_vlm_min_chars = int(word_vlm_min_chars)

        # 切片参数
        self.enable_chunk = bool(enable_chunk)
        self.chunk_strategy = chunk_strategy
        self.chunk_max_chars = int(chunk_max_chars)
        self.chunk_min_chars = int(chunk_min_chars)
        self.chunk_overlap_chars = int(chunk_overlap_chars)
        # 通过工厂拿到具体策略实例（默认从 yaml 配置读 default_strategy）
        self._chunker: BaseChunker = ChunkerFactory.create(chunk_strategy)

        self.force = bool(force)
        self._meta_lock = threading.Lock()
        # 断点索引：first_path -> 最近一条记录（不分 status，last-wins）
        self._processed_index: dict[str, dict[str, Any]] = (
            {} if self.force else self._load_processed_index()
        )

        logger.info(
            "KnowledgeBasePipeline 初始化完成：bucket={}, metadata={}, "
            "source_prefix={}, markdown_prefix={}, chunk_prefix={}, pptx_visual={}, pptx_dpi={}, "
            "word_vlm_fallback={}/{}chars, enable_chunk={}, chunker={}, "
            "chunk_max_chars={}, history={} records{}",
            self.BUCKET,
            self.metadata_path,
            self.source_prefix,
            self.markdown_prefix,
            self.chunk_prefix,
            self.pptx_visual,
            self.pptx_dpi,
            self.enable_word_vlm_fallback,
            self.word_vlm_min_chars,
            self.enable_chunk,
            getattr(self._chunker, "name", type(self._chunker).__name__),
            self.chunk_max_chars,
            len(self._processed_index),
            " (force=True, ignored)" if self.force else "",
        )

    # ----------------------------------------------------------------- 主入口
    def run(self) -> PipelineStats:
        """执行一轮完整的「遍历 → （续传判定 → ）转换 → 回写 → 切片 → 登记」。"""
        stats = PipelineStats()
        t0 = time.perf_counter()
        logger.info(
            "Pipeline 启动 | 历史记录 = {} | enable_chunk = {} | force = {}",
            len(self._processed_index),
            self.enable_chunk,
            self.force,
        )

        try:
            iterator = self._iter_all_objects()
        except (ClientError, BotoCoreError) as e:
            logger.error("无法列举桶 {}：{}", self.BUCKET, e)
            return stats

        for obj in iterator:
            stats.total += 1
            key = obj.get("Key", "")
            if self._should_skip(key):
                stats.skipped += 1
                logger.debug("跳过：{}", key)
                continue
            self._process_one(obj, key, stats)

        dt = time.perf_counter() - t0
        logger.info(
            "Pipeline 完成：total={total}, converted={converted}, uploaded={uploaded}, "
            "chunked={chunked}, skipped={skipped}, resumed={resumed}, failed={failed}, "
            "耗时={elapsed:.1f}s",
            **stats.to_dict(),
            elapsed=dt,
        )
        return stats

    # ----------------------------------------------------------------- 单文件状态机
    def _process_one(
        self,
        obj: dict[str, Any],
        key: str,
        stats: PipelineStats,
    ) -> None:
        """单文件状态机：根据历史记录决定从哪一阶段开始执行。

        - ETag 一致 + last_status == ``chunk``    → 完全跳过；
        - ETag 一致 + last_status == ``markdown`` → 跳过转换，从 MinIO 拉 .md 直接切片；
        - 其他情况（无记录 / ETag 变化 / 上次失败）→ 走全流程。

        任意环节异常 → 写一条 ``status=raw`` 失败记录，下次自动重试。
        """
        prev = self._processed_index.get(key)
        etag_match = self._etag_match(prev, obj) if prev else False
        last_status = (prev or {}).get("status") if prev else None

        # ---- 已完成：完全跳过 ----
        if etag_match and last_status == STATUS_CHUNK:
            stats.resumed += 1
            logger.info("⏭ 续传跳过 key={} (status=chunk, etag 一致)", key)
            return

        # ---- 已转 MD，仅补切片 ----
        if etag_match and last_status == STATUS_MARKDOWN and self.enable_chunk:
            try:
                md_key = prev.get("markdown_key") or self._build_markdown_key(key)
                md_text = self._download_markdown(md_key)
                self._chunk_and_upload(
                    obj=obj, key=key, md_key=md_key, md_text=md_text,
                    converter=prev.get("converter") or "unknown",
                )
                stats.chunked += 1
                logger.info("✔ 补切片完成 key={} ← {}", key, md_key)
            except Exception as e:  # 切片失败 → 留作下次重试，状态仍是 markdown
                stats.failed += 1
                logger.exception("✘ 补切片失败 key={}: {}", key, e)
                self._record_failure(obj, key, str(e), stage="chunk")
            return

        # ---- 走完整流程 ----
        try:
            content = self._download(key)
            md_text, conv_meta = self._convert(content, key)
            stats.converted += 1

            md_key = self._build_markdown_key(key)
            self._upload_markdown(md_key, md_text)
            stats.uploaded += 1
            self._record_markdown(
                obj=obj, key=key, md_key=md_key,
                md_text=md_text, conv_meta=conv_meta,
            )
            logger.info(
                "✔ 转换 uuid={} key={} -> {} | md_chars={} | converter={}",
                self._processed_index[key]["uuid"], key, md_key, len(md_text),
                conv_meta.get("converter", "?"),
            )
        except Exception as e:
            stats.failed += 1
            logger.exception("✘ 转换失败 key={}: {}", key, e)
            self._record_failure(obj, key, str(e), stage="convert")
            return

        # 切片
        if not self.enable_chunk:
            return
        try:
            self._chunk_and_upload(
                obj=obj, key=key, md_key=md_key, md_text=md_text,
                converter=conv_meta.get("converter") or "unknown",
            )
            stats.chunked += 1
        except Exception as e:
            stats.failed += 1
            logger.exception("✘ 切片失败 key={}: {}", key, e)
            self._record_failure(obj, key, str(e), stage="chunk")

    # ----------------------------------------------------------------- 遍历
    def _iter_all_objects(self) -> Iterator[dict[str, Any]]:
        """分页递归列出 source_prefix 下的对象（不带 ``Delimiter``，即递归）。"""
        paginator = self.client.raw.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.BUCKET, Prefix=self.source_prefix):
            for obj in page.get("Contents", []) or []:
                yield obj

    def _should_skip(self, key: str) -> bool:
        """是否跳过：空键 / 目录占位 / 命中 skip_prefixes / 扩展名不支持。"""
        if not key:
            return True
        if key.endswith("/"):
            return True
        for p in self.skip_prefixes:
            if p and key.startswith(p):
                return True
        suffix = Path(key).suffix.lower()
        if suffix not in self.supported_exts:
            return True
        return False

    # ----------------------------------------------------------------- 元数据登记
    def _build_metadata_record(self, obj: dict[str, Any]) -> dict[str, Any]:
        """
        构造一条基础元数据。

        - **UUID 复用策略**：若 ``first_path`` 在历史索引中已有记录，沿用旧 UUID
          （把同一逻辑文件的多次更新串成一条审计链）；否则生成新 UUID。
        """
        key: str = obj["Key"]
        path = Path(key)
        suffix = path.suffix.lower()
        content_type = (
            mimetypes.guess_type(key)[0]
            or obj.get("ContentType")
            or "application/octet-stream"
        )
        existing = self._processed_index.get(key)
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

    def _append_record(self, record: dict[str, Any]) -> None:
        """立即追加一行 JSON 到本地 JSONL 文件（线程安全，``flush`` 落盘抵抗中断）。"""
        line = json.dumps(record, ensure_ascii=False)
        with self._meta_lock:
            with self.metadata_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
        # 同步刷断点索引（以本次记录为最新状态）
        key = record.get("first_path")
        if key:
            self._processed_index[key] = record

    def _record_markdown(
        self,
        *,
        obj: dict[str, Any],
        key: str,
        md_key: str,
        md_text: str,
        conv_meta: dict[str, Any],
    ) -> None:
        """登记一条 ``status=markdown`` 记录（转换 + 上传成功后立即写）。"""
        rec = self._build_metadata_record(obj)
        rec.update({
            "etag": self._normalize_etag(obj.get("ETag")),
            "status": STATUS_MARKDOWN,
            "markdown_key": md_key,
            "markdown_chars": len(md_text),
            "converter": conv_meta.get("converter") or "unknown",
            "processed_at": _now_iso(),
        })
        self._append_record(rec)

    def _record_chunk(
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
        """登记一条 ``status=chunk`` 记录（切片 + 上传 JSON 成功后立即写）。"""
        rec = self._build_metadata_record(obj)
        rec.update({
            "etag": self._normalize_etag(obj.get("ETag")),
            "status": STATUS_CHUNK,
            "markdown_key": md_key,
            "markdown_chars": md_chars,
            "chunk_key": chunk_key,
            "chunk_count": chunk_count,
            "chunk_bytes": chunk_bytes,
            "converter": converter,
            "processed_at": _now_iso(),
        })
        self._append_record(rec)

    def _record_failure(
        self,
        obj: dict[str, Any],
        key: str,
        error: str,
        *,
        stage: str,
    ) -> None:
        """登记一条 ``status=raw`` 失败记录，``error`` / ``stage`` 字段便于排查。"""
        rec = self._build_metadata_record(obj)
        rec.update({
            "etag": self._normalize_etag(obj.get("ETag")),
            "status": STATUS_RAW,
            "stage": stage,
            "error": error[:500],  # 避免单条记录撑爆
            "processed_at": _now_iso(),
        })
        self._append_record(rec)

    # ----------------------------------------------------------------- 断点续传
    _STATUS_RANK = {STATUS_RAW: 0, STATUS_MARKDOWN: 1, STATUS_CHUNK: 2}

    @classmethod
    def _status_rank(cls, rec: dict[str, Any]) -> int:
        return cls._STATUS_RANK.get(rec.get("status") or "", -1)

    def _load_processed_index(self) -> dict[str, dict[str, Any]]:
        """
        加载本地 JSONL 中**每个 first_path 的最优记录**。

        规则（每行按顺序读，从前往后聚合）：

        - 没见过的 ``first_path`` → 直接占位；
        - **不同 ETag**（源文件被覆盖更新）→ **覆盖**为最新一条（认为这是新版本的"当前进度"）；
        - **相同 ETag** → 选择 ``status_rank`` 更高的那条（``chunk`` > ``markdown`` > ``raw``），
          相同 rank 由后写记录覆盖。
          → 由此，"先成功 md 后失败 chunk"会保留 md 记录，下次自动只补切片；
          连续多次失败时保留最后一次失败的 error 文案。

        异常 / 文件不存在 → 返回 ``{}``，按全量处理继续。
        """
        if not self.metadata_path.exists():
            return {}
        index: dict[str, dict[str, Any]] = {}
        try:
            with self.metadata_path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = rec.get("first_path")
                    if not key:
                        continue
                    prev = index.get(key)
                    if prev is None:
                        index[key] = rec
                        continue
                    same_etag = self._etag_match(prev, {"ETag": rec.get("etag"),
                                                       "Size": rec.get("size")})
                    if not same_etag:
                        # 不同 ETag → 视作"新版本"覆盖旧版本
                        index[key] = rec
                        continue
                    # 同 ETag → 取更高 status；相同 rank 由后写覆盖
                    if self._status_rank(rec) >= self._status_rank(prev):
                        index[key] = rec
        except OSError as e:
            logger.warning("读取历史元数据失败：{}（按全量处理继续）", e)
            return {}
        return index

    def _etag_match(self, rec: dict[str, Any], obj: dict[str, Any]) -> bool:
        """判断历史记录与当前 MinIO 对象是否是"同一份"。

        - 两边 ETag 都可用 → 严格匹配；
        - ETag 缺失（极少数 MinIO 配置或分片上传场景）→ 退化为 size 比对。
        """
        old_etag = self._normalize_etag(rec.get("etag"))
        new_etag = self._normalize_etag(obj.get("ETag"))
        if old_etag and new_etag:
            return old_etag == new_etag
        return int(rec.get("size") or -1) == int(obj.get("Size") or -2)

    @staticmethod
    def _normalize_etag(etag: str | None) -> str:
        """boto3 返回的 ETag 形如 ``'"abc123"'``（带引号）；统一剥引号 / 大小写不敏感。"""
        if not etag:
            return ""
        return etag.strip().strip('"').lower()

    # ----------------------------------------------------------------- 下载 / 转换 / 回写
    def _download(self, key: str) -> bytes:
        return self.client.download_bytes(self.BUCKET, key)

    def _convert(self, content: bytes, key: str) -> tuple[str, dict[str, Any]]:
        """
        按扩展名路由：

        - ``.md`` / ``.markdown``：原文透传；
        - ``.txt``：包一层 ``# <basename>`` 标题；
        - 其余支持格式：调用 ``file_to_markdown.unified_entry.convert_bytes``。

        PPT / Word 会按 :class:`KnowledgeBasePipeline` 构造时配置的视觉/兜底
        参数透传 kwargs，**与 HTTP 接口 ``/convert/slides`` ``/convert/docx`` 的语义保持一致**。
        """
        suffix = Path(key).suffix.lower()
        filename = Path(key).name

        if suffix in {".md", ".markdown"}:
            return (
                content.decode("utf-8", errors="replace"),
                {"converter": "passthrough_md", "extension": suffix},
            )
        if suffix == ".txt":
            text = content.decode("utf-8", errors="replace")
            md = f"# {Path(filename).stem}\n\n{text}\n"
            return md, {"converter": "passthrough_txt", "extension": suffix}

        from file_to_markdown.unified_entry import convert_bytes

        kwargs: dict[str, Any] = {}
        if suffix in {".pptx", ".ppt"}:
            kwargs["pptx_visual"] = self.pptx_visual
            kwargs["pptx_dpi"] = self.pptx_dpi
        elif suffix == ".docx":
            kwargs["enable_word_vlm_fallback"] = self.enable_word_vlm_fallback
            kwargs["word_vlm_min_chars"] = self.word_vlm_min_chars

        result = convert_bytes(suffix, content, filename, **kwargs)
        return result.markdown, result.metadata

    def _build_markdown_key(self, key: str) -> str:
        """``raw/company/a/demo.pdf`` → ``markdown/company/a/demo.md``。"""
        rel = key
        if self.strip_raw_prefix and rel.startswith("raw/"):
            rel = rel[len("raw/") :]
        target = Path(rel).with_suffix(".md")
        return f"{self.markdown_prefix}{target.as_posix()}"

    def _build_chunk_key(self, key: str) -> str:
        """``raw/company/a/demo.pdf`` → ``chunk/company/a/demo.json``（二级路径与 .md 完全一致）。"""
        rel = key
        if self.strip_raw_prefix and rel.startswith("raw/"):
            rel = rel[len("raw/") :]
        target = Path(rel).with_suffix(".json")
        return f"{self.chunk_prefix}{target.as_posix()}"

    def _upload_markdown(self, md_key: str, md_text: str) -> None:
        self.client.upload_bytes(
            self.BUCKET,
            md_key,
            md_text.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    def _upload_chunk_json(self, chunk_key: str, payload_bytes: bytes) -> None:
        self.client.upload_bytes(
            self.BUCKET,
            chunk_key,
            payload_bytes,
            content_type="application/json; charset=utf-8",
        )

    def _download_markdown(self, md_key: str) -> str:
        """从 MinIO 拉一份已生成的 markdown 回来（用于"只补切片"分支）。"""
        return self.client.download_bytes(self.BUCKET, md_key).decode(
            "utf-8", errors="replace"
        )

    # ----------------------------------------------------------------- 切片
    def _run_chunker(self, md_text: str, file_ext: str) -> list[ChunkResult]:
        """同步外壳：在已 / 未运行 event loop 的两种环境里都能正确跑 async chunker。"""
        coro = self._chunker.chunk(
            md_text,
            chunk_size=self.chunk_max_chars,
            chunk_overlap=self.chunk_overlap_chars,
            file_ext=file_ext,
        )
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # 已有 event loop（例如被异步上下文调用），开一个新 loop 跑完
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    def _chunk_and_upload(
        self,
        *,
        obj: dict[str, Any],
        key: str,
        md_key: str,
        md_text: str,
        converter: str,
    ) -> None:
        """执行切片 + 上传 chunk JSON + 写 ``status=chunk`` 记录。"""
        rec_base = self._build_metadata_record(obj)
        file_ext = Path(key).suffix.lower()
        chunks: list[ChunkResult] = self._run_chunker(md_text, file_ext)

        payload_obj = {
            "doc_uuid": rec_base["uuid"],
            "source": key,
            "markdown_key": md_key,
            "filename": rec_base["filename"],
            "converter": converter,
            "chunker_strategy": getattr(
                self._chunker, "name", type(self._chunker).__name__
            ),
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "index": c.index,
                    "text": c.text,
                    "token_count": c.token_count,
                    "metadata": c.metadata,
                }
                for c in chunks
            ],
        }
        payload = json.dumps(payload_obj, ensure_ascii=False, indent=2)
        payload_bytes = payload.encode("utf-8")

        chunk_key = self._build_chunk_key(key)
        self._upload_chunk_json(chunk_key, payload_bytes)
        self._record_chunk(
            obj=obj,
            key=key,
            md_key=md_key,
            md_chars=len(md_text),
            chunk_key=chunk_key,
            chunk_count=len(chunks),
            chunk_bytes=len(payload_bytes),
            converter=converter,
        )
        logger.info(
            "✔ 切片 uuid={} key={} -> {} | chunks={} | size={}B",
            rec_base["uuid"], key, chunk_key, len(chunks), len(payload_bytes),
        )

    # ----------------------------------------------------------------- 工具
    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        p = (prefix or "").strip().lstrip("/")
        if p and not p.endswith("/"):
            p += "/"
        return p

    @classmethod
    def _default_source_prefix(cls) -> str:
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
    def _norm_ext(s: str) -> str:
        s = (s or "").strip().lower()
        if not s.startswith("."):
            s = "." + s
        return s


# ------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------
def main() -> None:
    """
    命令行入口：``python -m orchestrator.knowledge_pipeline [flags]``。

    支持的 flag（顺序无关）::

        --metadata-path=PATH         本地 JSONL 元数据落地路径（断点索引复用同一文件）
        --source-prefix=STR          仅读取的 MinIO 源对象前缀（默认 raw/<Qdrant.collection>/）
        --markdown-prefix=STR        MD 回写 prefix（默认 markdown/）
        --chunk-prefix=STR           Chunk JSON 回写 prefix（默认 chunk/）
        --no-pptx-visual             关闭 PPT 视觉版（默认开），仅走 python-pptx 文本版
        --pptx-dpi=200               视觉版渲染 DPI
        --no-word-vlm-fallback       关闭 Word 图片 VLM 兜底（默认开）
        --word-vlm-min-chars=20      VLM / OCR 双重阈值
        --no-chunk                   只做 MD 转换 + 回写，不做切片（status 停在 markdown）
        --chunk-strategy=NAME        切片策略：text / recursive / semantic / markdown_structure
                                     （省略时使用 chunker.default_strategy 配置）
        --chunk-max-chars=1500       传给 chunker.chunk() 的 chunk_size
        --chunk-min-chars=50         保留参数，仅用作下游过滤参考
        --chunk-overlap-chars=100    传给 chunker.chunk() 的 chunk_overlap
        --force                      忽略历史 JSONL，全量重处理（旧记录保留作审计）

    不传任何 flag 时与 ``/convert/slides`` / ``/convert/docx`` 的默认行为完全一致：
    PPT 走视觉版、Word 开 VLM 兜底、表格转「字段：值」纯文本；并自动做切片入库。

    断点续传（三态机）
    -----------------
    - last_status = ``chunk``    → 整条**完全跳过**；
    - last_status = ``markdown`` → 跳过转换，**只补切片**（从 MinIO 拉 .md）；
    - last_status = ``raw`` / 无记录 / ETag 变化 → **走完整流程**。

    用 ``--force`` 可一键忽略历史索引，旧记录保留作审计，新记录追加文件末尾。
    """
    kwargs: dict[str, Any] = {}
    for a in sys.argv[1:]:
        if a == "--no-pptx-visual":
            kwargs["pptx_visual"] = False
        elif a == "--no-word-vlm-fallback":
            kwargs["enable_word_vlm_fallback"] = False
        elif a == "--no-chunk":
            kwargs["enable_chunk"] = False
        elif a == "--force":
            kwargs["force"] = True
        elif a.startswith("--metadata-path="):
            kwargs["metadata_path"] = a.split("=", 1)[1]
        elif a.startswith("--source-prefix="):
            kwargs["source_prefix"] = a.split("=", 1)[1]
        elif a.startswith("--markdown-prefix="):
            kwargs["markdown_prefix"] = a.split("=", 1)[1]
        elif a.startswith("--chunk-prefix="):
            kwargs["chunk_prefix"] = a.split("=", 1)[1]
        elif a.startswith("--chunk-strategy="):
            kwargs["chunk_strategy"] = a.split("=", 1)[1]
        elif a.startswith("--pptx-dpi="):
            try:
                kwargs["pptx_dpi"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("--word-vlm-min-chars="):
            try:
                kwargs["word_vlm_min_chars"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("--chunk-max-chars="):
            try:
                kwargs["chunk_max_chars"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("--chunk-min-chars="):
            try:
                kwargs["chunk_min_chars"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("--chunk-overlap-chars="):
            try:
                kwargs["chunk_overlap_chars"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a in ("-h", "--help"):
            print(main.__doc__)
            return

    pipeline = KnowledgeBasePipeline(**kwargs)
    pipeline.run()


if __name__ == "__main__":
    main()

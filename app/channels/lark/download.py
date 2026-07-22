from __future__ import annotations

import argparse
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

from app.channels.lark.lark_config import load_settings
from app.channels.lark.lark_markdown import clean_lark_markdown
from app.channels.lark.lark_api import (
    LarkApiError,
    download_message_resource,
    export_cloud_document,
    get_doc_markdown,
    get_tenant_access_token,
    list_chat_messages,
    resolve_wiki_node,
)
from app.channels.lark.minio_uploader import MinioUploader

LOGGER = logging.getLogger(__name__)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>）)]+")
SUPPORTED_KB_EXTENSIONS = {
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
    ".md",
    ".markdown",
    ".txt",
}


@dataclass(frozen=True)
class ResourceCandidate:
    kind: str
    message_id: str
    key: str
    resource_type: str
    filename: str


@dataclass(frozen=True)
class CloudDocumentCandidate:
    message_id: str
    url: str
    doc_type: str
    token: str
    file_extension: str


@dataclass(frozen=True)
class DownloadResult:
    item_type: str
    message_id: str
    source: str
    destination: Path
    minio_key: str | None = None
    error: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="下载指定飞书群中的云文档和消息附件")
    parser.add_argument("--chat-id", help="群聊 chat_id；不传时读取 LARK_DEFAULT_CHAT_ID")
    parser.add_argument("--output-dir", default="downloads", help="下载目录，默认 downloads")
    parser.add_argument("--days", type=int, help="Scan messages from the last N days")
    parser.add_argument("--start-time", help="Start time, for example 2026-06-01 or 2026-06-01 10:30:00")
    parser.add_argument("--end-time", help="End time, for example 2026-06-03 or 2026-06-03 18:00:00")
    parser.add_argument("--page-limit", type=int, help="Maximum message pages to scan; omitted means all pages")
    parser.add_argument("--page-size", type=int, default=50, help="每页消息数，默认 50")
    parser.add_argument(
        "--target",
        choices=("local", "minio"),
        required=True,
        help="Download target: local saves to disk, minio uploads to MinIO only",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    settings = load_settings(require_enterprise_server=False)
    chat_id = args.chat_id or settings.lark_default_chat_id
    if not chat_id:
        parser.error("请通过 --chat-id 指定群聊 chat_id，或在 .env 中配置 LARK_DEFAULT_CHAT_ID")

    if args.page_limit is not None and args.page_limit < 1:
        parser.error("--page-limit must be greater than or equal to 1")

    tenant_access_token = get_tenant_access_token(
        settings.lark_open_api_base_url,
        settings.lark_app_id,
        settings.lark_app_secret,
    )
    start_time, end_time = resolve_time_range(args, parser)
    messages = list_chat_messages(
        settings.lark_open_api_base_url,
        tenant_access_token,
        chat_id,
        start_time=start_time,
        end_time=end_time,
        page_size=args.page_size,
        page_limit=args.page_limit,
    )

    resources, cloud_docs, skipped = collect_download_candidates(messages)
    downloaded = 0
    uploaded = 0
    failed = 0
    results: list[DownloadResult] = []

    with tempfile.TemporaryDirectory(prefix="lark-download-") as temp_dir:
        if args.target == "local":
            output_dir = Path(args.output_dir) / chat_id
            uploader = None
            artifact_root = output_dir
        else:
            output_dir = Path(args.output_dir) / chat_id
            uploader = MinioUploader(settings)
            artifact_root = Path(temp_dir) / chat_id

        LOGGER.info(
            "扫描完成：messages=%s resources=%s cloud_docs=%s skipped=%s target=%s",
            len(messages),
            len(resources),
            len(cloud_docs),
            len(skipped),
            args.target,
        )

        for resource in resources:
            destination = artifact_root / "attachments" / resource.filename
            try:
                download_message_resource(
                    settings.lark_open_api_base_url,
                    tenant_access_token,
                    resource.message_id,
                    resource.key,
                    resource.resource_type,
                    destination,
                )
                downloaded += 1
                upload = None
                if uploader is not None:
                    upload = uploader.upload_lark_file(
                        destination,
                        chat_id=chat_id,
                        message_id=resource.message_id,
                        filename=destination.name,
                    )
                    uploaded += 1
                results.append(
                    DownloadResult(
                        item_type=f"attachment/{resource.resource_type}",
                        message_id=resource.message_id,
                        source=resource.key,
                        destination=destination,
                        minio_key=upload.key if upload else None,
                    )
                )
                if upload:
                    LOGGER.info("已上传附件到 MinIO：%s -> %s/%s", destination, upload.bucket, upload.key)
                else:
                    LOGGER.info("已下载附件到本地：%s", destination)
            except Exception as exc:
                failed += 1
                results.append(
                    DownloadResult(
                        item_type=f"attachment/{resource.resource_type}",
                        message_id=resource.message_id,
                        source=resource.key,
                        destination=destination,
                        error=str(exc),
                    )
                )
                LOGGER.warning("附件处理失败：message_id=%s key=%s error=%s", resource.message_id, resource.key, exc)

        for document in cloud_docs:
            destination = artifact_root / "cloud_docs" / cloud_doc_filename(document)
            final_destination = destination.with_suffix(f".{document.file_extension}")
            try:
                doc_type = document.doc_type
                token = document.token
                file_extension = document.file_extension
                if doc_type == "wiki":
                    doc_type, token = resolve_wiki_node(
                        settings.lark_open_api_base_url,
                        tenant_access_token,
                        document.token,
                    )
                    file_extension = default_export_extension(doc_type)

                # 新版文档(docx)：直接取飞书原生 markdown，结构保真（标题#、表格| |），
                # 比「导 docx 再第三方转 md」好。其它类型(sheet/bitable)仍走导出。
                if doc_type == "docx":
                    file_extension = "md"
                    final_destination = destination.with_suffix(".md")
                    raw_md = get_doc_markdown(
                        settings.lark_open_api_base_url,
                        tenant_access_token,
                        token,
                        doc_type="docx",
                    )
                    cleaned = clean_lark_markdown(raw_md)
                    final_destination.parent.mkdir(parents=True, exist_ok=True)
                    final_destination.write_text(cleaned, encoding="utf-8")
                else:
                    final_destination = destination.with_suffix(f".{file_extension}")
                    export_cloud_document(
                        settings.lark_open_api_base_url,
                        tenant_access_token,
                        doc_type,
                        token,
                        file_extension,
                        final_destination,
                    )
                downloaded += 1
                upload = None
                if uploader is not None:
                    upload = uploader.upload_lark_file(
                        final_destination,
                        chat_id=chat_id,
                        message_id=document.message_id,
                        filename=final_destination.name,
                    )
                    uploaded += 1
                results.append(
                    DownloadResult(
                        item_type=f"cloud_doc/{doc_type}",
                        message_id=document.message_id,
                        source=document.url,
                        destination=final_destination,
                        minio_key=upload.key if upload else None,
                    )
                )
                if upload:
                    LOGGER.info("已导出并上传云文档到 MinIO：%s -> %s/%s", final_destination, upload.bucket, upload.key)
                else:
                    LOGGER.info("已导出云文档到本地：%s", final_destination)
            except LarkApiError as exc:
                failed += 1
                results.append(
                    DownloadResult(
                        item_type=f"cloud_doc/{document.doc_type}",
                        message_id=document.message_id,
                        source=document.url,
                        destination=final_destination,
                        error=str(exc),
                    )
                )
                LOGGER.warning("云文档导出失败：url=%s error=%s", document.url, exc)

    LOGGER.info("下载任务完成：target=%s downloaded=%s uploaded=%s skipped=%s failed=%s", args.target, downloaded, uploaded, len(skipped), failed)
    print_download_summary(results, skipped)


def resolve_time_range(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[int | None, int | None]:
    if args.days is not None and (args.start_time or args.end_time):
        parser.error("--days cannot be used together with --start-time or --end-time")

    if args.days is not None:
        if args.days < 0:
            parser.error("--days must be greater than or equal to 0")
        now = int(datetime.now().timestamp())
        return now - args.days * 24 * 60 * 60, now

    try:
        start_time = parse_time_argument(args.start_time, end_of_day=False)
        end_time = parse_time_argument(args.end_time, end_of_day=True)
    except ValueError as exc:
        parser.error(str(exc))
    if start_time is not None and end_time is not None and start_time > end_time:
        parser.error("--start-time must be earlier than or equal to --end-time")
    return start_time, end_time


def parse_time_argument(value: str | None, *, end_of_day: bool) -> int | None:
    if not value:
        return None

    value = value.strip()
    if value.isdigit():
        return int(value)

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed_date = datetime.fromisoformat(value).date()
            parsed_time = time.max if end_of_day else time.min
            return int(datetime.combine(parsed_date, parsed_time).timestamp())

        return int(datetime.fromisoformat(value).timestamp())
    except ValueError as exc:
        raise ValueError(
            f"Invalid time value: {value}. Use YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, or Unix seconds."
        ) from exc


def collect_download_candidates(
    messages: list[dict[str, Any]],
) -> tuple[list[ResourceCandidate], list[CloudDocumentCandidate], list[str]]:
    resources: list[ResourceCandidate] = []
    cloud_docs: list[CloudDocumentCandidate] = []
    skipped: list[str] = []
    seen_resources: set[tuple[str, str, str]] = set()
    seen_docs: set[tuple[str, str]] = set()

    for message in messages:
        message_id = message.get("message_id") or ""
        msg_type = message.get("msg_type") or message.get("message_type") or ""
        content = parse_content(message.get("body", {}).get("content") or message.get("content"))
        filenames = extract_filename_hints(content)

        for key, resource_type in extract_message_resources(content, msg_type):
            dedupe_key = (message_id, key, resource_type)
            if dedupe_key in seen_resources:
                continue
            seen_resources.add(dedupe_key)
            filename = safe_filename(
                filenames.get(key)
                or f"{message_id}_{resource_type}_{key}{default_resource_suffix(resource_type)}"
            )
            if not is_supported_for_kb(filename):
                skipped.append(f"attachment message_id={message_id} filename={filename}")
                continue
            resources.append(
                ResourceCandidate(
                    kind=msg_type or resource_type,
                    message_id=message_id,
                    key=key,
                    resource_type=resource_type,
                    filename=filename,
                )
            )

        for url in extract_urls(content):
            document = parse_cloud_document_url(message_id, url)
            if not document:
                continue
            dedupe_key = (document.doc_type, document.token)
            if dedupe_key in seen_docs:
                continue
            seen_docs.add(dedupe_key)
            if not is_supported_for_kb(f"placeholder.{document.file_extension}"):
                skipped.append(
                    f"cloud_doc message_id={message_id} type={document.doc_type} extension={document.file_extension}"
                )
                continue
            cloud_docs.append(document)

    return resources, cloud_docs, skipped


def parse_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def extract_message_resources(content: Any, msg_type: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in iter_json_items(content):
        if not isinstance(value, str):
            continue
        if key in {"file_key", "fileKey"}:
            pairs.append((value, "file"))
        elif key in {"image_key", "imageKey"}:
            pairs.append((value, "image"))
    if msg_type == "file" and isinstance(content, dict) and isinstance(content.get("file_key"), str):
        pairs.append((content["file_key"], "file"))
    return pairs


def extract_filename_hints(content: Any) -> dict[str, str]:
    hints: dict[str, str] = {}
    if not isinstance(content, dict):
        return hints
    file_key = content.get("file_key") or content.get("fileKey")
    file_name = content.get("file_name") or content.get("fileName") or content.get("name")
    if isinstance(file_key, str) and isinstance(file_name, str):
        hints[file_key] = file_name
    return hints


def extract_urls(content: Any) -> list[str]:
    text_parts: list[str] = []
    collect_text(content, text_parts)
    urls: list[str] = []
    for text in text_parts:
        urls.extend(URL_PATTERN.findall(text))
    return urls


def collect_text(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            collect_text(item, out)
    elif isinstance(value, list):
        for item in value:
            collect_text(item, out)


def iter_json_items(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from iter_json_items(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_items(item)


def parse_cloud_document_url(message_id: str, url: str) -> CloudDocumentCandidate | None:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        # 畸形 URL（如含 [ ] 被误判为 IPv6）直接跳过，不影响整批下载
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None

    mapping = {
        "docx": ("docx", "docx"),
        "docs": ("doc", "docx"),
        "sheets": ("sheet", "xlsx"),
        "base": ("bitable", "xlsx"),
        "bitable": ("bitable", "xlsx"),
        "wiki": ("wiki", "docx"),
    }
    for index, part in enumerate(parts[:-1]):
        if part not in mapping:
            continue
        token = parts[index + 1]
        doc_type, extension = mapping[part]
        return CloudDocumentCandidate(
            message_id=message_id,
            url=url,
            doc_type=doc_type,
            token=token,
            file_extension=extension,
        )
    return None


def default_export_extension(doc_type: str) -> str:
    return {
        "doc": "docx",
        "docx": "docx",
        "sheet": "xlsx",
        "bitable": "xlsx",
    }.get(doc_type, "docx")


def cloud_doc_filename(document: CloudDocumentCandidate) -> str:
    return safe_filename(f"{document.message_id}_{document.doc_type}_{document.token}")


def default_resource_suffix(resource_type: str) -> str:
    return {
        "image": ".jpg",
        "file": "",
    }.get(resource_type, "")


def is_supported_for_kb(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_KB_EXTENSIONS


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
    cleaned = cleaned.strip(" .")
    return cleaned[:180] or "download"


def print_download_summary(results: list[DownloadResult], skipped: list[str]) -> None:
    successful = [result for result in results if result.error is None]
    failed = [result for result in results if result.error is not None]

    print()
    print("Download summary")
    print(f"  success: {len(successful)}")
    for result in successful:
        print(
            f"    - [{result.item_type}] message_id={result.message_id} "
            f"source={result.source} -> {result.destination}"
        )
        if result.minio_key:
            print(f"      minio: {result.minio_key}")

    print(f"  skipped unsupported: {len(skipped)}")
    for item in skipped:
        print(f"    - {item}")

    print(f"  failed: {len(failed)}")
    for result in failed:
        print(
            f"    - [{result.item_type}] message_id={result.message_id} "
            f"source={result.source} -> {result.destination}"
        )
        print(f"      error: {result.error}")


if __name__ == "__main__":
    main()

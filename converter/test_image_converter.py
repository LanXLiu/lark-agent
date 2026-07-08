"""
本地验证 image_converter 与统一入口 convert_bytes（无 FastAPI、无 pytest）。

用法（在项目根目录）::

    python converter/test_image_converter.py /path/to/image.png

依赖：与正式环境相同的 ``file_to_markdown`` / Paddle 等；仅打印结果与耗时。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

# 允许 ``python converter/test_image_converter.py`` 从任意 cwd 启动
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _try_json_serialize(label: str, markdown: str, metadata: dict) -> None:
    """先裸 ``json.dumps(metadata)``，再对整包做 ``jsonable_encoder`` 后 dumps，用于排查不可序列化字段。"""
    payload = {"markdown": markdown, "metadata": metadata, "filename": "probe"}
    print(f"\n--- JSON 可序列化检查: {label} ---")
    try:
        json.dumps(metadata)
        print("metadata 裸 json.dumps: 通过")
    except TypeError as e:
        print(f"metadata 裸 json.dumps: 失败 -> {e!r}")

    try:
        from fastapi.encoders import jsonable_encoder

        safe = jsonable_encoder(payload)
        json.dumps(safe)
        print("整包 jsonable_encoder + json.dumps: 通过")
    except Exception as e:
        print(f"整包 jsonable_encoder + json.dumps: 失败 -> {e!r}")
        traceback.print_exc()


class ImageConverterSelfTest:
    """仅用于本地手测：底层 ``convert_bytes`` + ``ImageConverter.convert``。"""

    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path.resolve()

    def run_convert_bytes(self) -> None:
        """与 HTTP 层一致：读字节 + ``file_to_markdown.unified_entry.convert_bytes``。"""
        from file_to_markdown.unified_entry import convert_bytes

        print("\n========== convert_bytes（统一入口）==========")
        if not self.image_path.is_file():
            print(f"文件不存在: {self.image_path}")
            return

        ext = self.image_path.suffix.lower()
        raw_name = self.image_path.name
        try:
            data = self.image_path.read_bytes()
        except OSError as e:
            print(f"读取文件失败: {e}")
            return

        t0 = time.perf_counter()
        try:
            result = convert_bytes(ext, data, raw_name)
        except Exception as e:
            print(f"convert_bytes 异常: {e!r}")
            traceback.print_exc()
            return
        elapsed = time.perf_counter() - t0

        print(f"耗时: {elapsed:.3f} s")
        print(f"markdown 长度: {len(result.markdown)}")
        print("--- markdown 全文 ---")
        print(result.markdown)
        print("--- metadata (repr) ---")
        print(repr(result.metadata))
        _try_json_serialize("convert_bytes", result.markdown, result.metadata)

    async def run_image_converter(self) -> None:
        """``ImageConverter.convert``：内部走 ``convert_via_file_to_markdown``。"""
        from converter.image_converter import ImageConverter

        print("\n========== ImageConverter.convert（异步封装）==========")
        if not self.image_path.is_file():
            print(f"文件不存在: {self.image_path}")
            return

        ic = ImageConverter()
        if not ic.validate(self.image_path):
            print(f"后缀不在支持列表: {self.image_path.suffix}")
            return

        t0 = time.perf_counter()
        try:
            out = await ic.convert(self.image_path)
        except Exception as e:
            print(f"ImageConverter.convert 异常: {e!r}")
            traceback.print_exc()
            return
        elapsed = time.perf_counter() - t0

        print(f"耗时: {elapsed:.3f} s")
        print(f"markdown 长度: {len(out.markdown)}")
        print("--- markdown 全文 ---")
        print(out.markdown)
        print("--- metadata (repr) ---")
        print(repr(out.metadata))
        _try_json_serialize("ImageConverter", out.markdown, out.metadata)


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not argv:
        default_png = (
            _ROOT / "file_to_markdown" / "temp_word_images" / "8bd36239a19c9c440bcb7d861867e8ec.png"
        )
        if default_png.is_file():
            p = default_png
            print(f"未传路径，使用默认: {p}")
        else:
            print("用法: python converter/test_image_converter.py <本地图片路径>")
            sys.exit(1)
    else:
        p = Path(argv[0])

    tester = ImageConverterSelfTest(p)
    tester.run_convert_bytes()
    try:
        asyncio.run(tester.run_image_converter())
    except RuntimeError:
        # 极少数环境已有 running loop
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(tester.run_image_converter())
        finally:
            loop.close()


if __name__ == "__main__":
    main()

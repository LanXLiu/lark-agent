# -*- coding: utf-8 -*-
"""
转换器手动/批量测试脚本。

支持单文件预览或目录批量输出 ``.md``，用于验证 ``ConverterFactory`` 与统一转换链路。
"""
import sys
from pathlib import Path

# ---- Path fix: ensure project root is in sys.path when running directly ----
if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
# --------------------------------------------------------------------------

import asyncio
from knowledge.ingestion.converter.converter_factory import ConverterFactory


class ConverterTester:
    """A simple tester class to verify converter effects."""

    @staticmethod
    async def convert_single(file_path: str, output_path: str = None):
        """Convert a single file and display / save the result."""
        src = Path(file_path)
        if not src.exists():
            print(f"[ERROR] File not found: {src}")
            return

        try:
            converter = ConverterFactory.get_converter(src)
            if not converter.validate(src):
                print(f"[ERROR] Unsupported file extension: {src.suffix}")
                print(f"        Supported: {ConverterFactory.supported_extensions()}")
                return

            result = await converter.convert(src)

            if output_path:
                out = Path(output_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(result.markdown, encoding="utf-8")
                print(f"[OK] Converted {src} -> {out}")
            else:
                print("=" * 60)
                print("Markdown content (first 500 characters):")
                print("-" * 40)
                print(result.markdown[:500])
                if len(result.markdown) > 500:
                    print("... (truncated, full length: {})".format(len(result.markdown)))
                print("-" * 40)

            print(f"Metadata: {result.metadata}")
            print(f"Valid result: {bool(result)}")
        except Exception as e:
            print(f"[ERROR] Conversion failed for {src}: {e}")

    @staticmethod
    async def batch_convert(input_dir: str, output_dir: str):
        """Convert all supported files in input_dir, save as .md to output_dir."""
        input_path = Path(input_dir)
        output_path = Path(output_dir)

        if not input_path.is_dir():
            print(f"[ERROR] Input directory not found: {input_dir}")
            return

        output_path.mkdir(parents=True, exist_ok=True)

        supported_exts = ConverterFactory.supported_extensions()
        files = [f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in supported_exts]

        if not files:
            print(f"[INFO] No supported files found in {input_dir}")
            print(f"       Supported extensions: {supported_exts}")
            return

        print(f"Found {len(files)} file(s) to convert.\n")

        success = 0
        fail = 0
        for src in files:
            md_name = src.stem + ".md"
            out = output_path / md_name
            try:
                converter = ConverterFactory.get_converter(src)
                result = await converter.convert(src)
                out.write_text(result.markdown, encoding="utf-8")
                print(f"  [OK] {src.name} -> {out.name}")
                success += 1
            except Exception as e:
                print(f"  [FAIL] {src.name}: {e}")
                fail += 1

        print(f"\nSummary: {success} succeeded, {fail} failed")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python converter/test_converter.py <input_dir> <output_dir>")
        print("  python converter/test_converter.py <single_file> [output.md]")
        print()
        print("Examples:")
        print('  python converter/test_converter.py "storage/input/20260507input" "storage/output/20260507output"')
        print('  python converter/test_converter.py sample.pdf')
        print('  python converter/test_converter.py sample.pptx output.md')
        sys.exit(1)

    arg1 = sys.argv[1]
    arg2 = sys.argv[2] if len(sys.argv) > 2 else None

    if arg2 and Path(arg1).is_dir():
        # Two arguments and first is a directory -> batch convert
        asyncio.run(ConverterTester.batch_convert(arg1, arg2))
    else:
        # Single file (with optional output path)
        asyncio.run(ConverterTester.convert_single(arg1, arg2))


if __name__ == "__main__":
    main()

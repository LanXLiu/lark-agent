"""
本地验证 pptx 转换器与统一入口 ``convert_bytes``（无 FastAPI、无 pytest）。

用法（在项目根目录）::

    python converter/test_pptx_converter.py /path/to/foo.pptx
    python converter/test_pptx_converter.py foo.pptx --visual              # 启用视觉版（VLM）
    python converter/test_pptx_converter.py foo.pptx --visual --dpi=240

可识别的 flag（顺序无关，传不传都行）：

- ``--visual``        启用视觉版（LibreOffice + Poppler + VLM）；不传则走 python-pptx 文本版
- ``--no-visual``     强制关闭视觉版（默认就是关）
- ``--dpi=<int>``     视觉版渲染 DPI，默认 200

视觉版的输出固定为**纯文本 Markdown**，不会嵌入任何 ``![pN](...)`` 图片引用。
依赖：与正式环境相同的 ``file_to_markdown``。仅打印结果与耗时，不写文件。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

# 允许 ``python converter/test_pptx_converter.py`` 从任意 cwd 启动
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------- 工具
def _parse_flags(argv: list[str]) -> tuple[list[str], dict]:
    """简单 flag 解析：返回 (位置参数列表, 选项字典)。不引入 argparse。"""
    positional: list[str] = []
    opts: dict = {"visual": False, "dpi": None}
    for a in argv:
        if a in ("--visual", "-v"):
            opts["visual"] = True
        elif a == "--no-visual":
            opts["visual"] = False
        elif a.startswith("--dpi="):
            try:
                opts["dpi"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("-"):
            # 未知 flag 静默忽略
            continue
        else:
            positional.append(a)
    return positional, opts


def _try_json_serialize(label: str, markdown: str, metadata: dict) -> None:
    """先裸 ``json.dumps(metadata)``，再 ``jsonable_encoder`` 后 dumps，排查不可序列化字段。"""
    print(f"\n--- JSON 可序列化检查: {label} ---")
    try:
        json.dumps(metadata)
        print("metadata 裸 json.dumps: 通过")
    except TypeError as e:
        print(f"metadata 裸 json.dumps: 失败 -> {e!r}")

    try:
        from fastapi.encoders import jsonable_encoder

        safe = jsonable_encoder(
            {"markdown": markdown, "metadata": metadata, "filename": "probe"}
        )
        json.dumps(safe)
        print("整包 jsonable_encoder + json.dumps: 通过")
    except Exception as e:
        print(f"整包 jsonable_encoder + json.dumps: 失败 -> {e!r}")
        traceback.print_exc()


def _print_markdown(label: str, markdown: str, head_chars: int = 4000) -> None:
    """长 Markdown（如视觉版含 base64 图片）截断打印，避免淹没终端。"""
    print(f"--- {label} markdown 长度: {len(markdown)} ---")
    if len(markdown) <= head_chars:
        print(markdown)
    else:
        print(markdown[:head_chars])
        print(f"\n[... 截断，剩余 {len(markdown) - head_chars} 字符未显示 ...]")


# --------------------------------------------------------------------- 测试器
class PptxConverterSelfTest:
    """仅用于本地手测：底层 ``convert_bytes`` + ``PptxConverter.convert``。"""

    def __init__(self, ppt_path: Path, *, visual: bool, dpi: int | None):
        self.ppt_path = ppt_path.resolve()
        self.visual = visual
        self.dpi = dpi
        # 给 unified_entry / 转换器透传的 kwargs
        self.kwargs: dict = {"pptx_visual": visual}
        if dpi is not None:
            self.kwargs["pptx_dpi"] = dpi

    # -------- 1) 跟 HTTP 路由完全一样的入口
    def run_convert_bytes(self) -> None:
        from file_to_markdown.unified_entry import convert_bytes

        print("\n========== convert_bytes（统一入口）==========")
        print(f"文件: {self.ppt_path}")
        print(f"参数: {self.kwargs}")

        if not self.ppt_path.is_file():
            print(f"文件不存在: {self.ppt_path}")
            return

        ext = self.ppt_path.suffix.lower()
        try:
            data = self.ppt_path.read_bytes()
        except OSError as e:
            print(f"读取文件失败: {e}")
            return

        t0 = time.perf_counter()
        try:
            result = convert_bytes(ext, data, self.ppt_path.name, **self.kwargs)
        except Exception as e:
            print(f"convert_bytes 异常: {e!r}")
            traceback.print_exc()
            return
        elapsed = time.perf_counter() - t0

        print(f"耗时: {elapsed:.3f} s")
        _print_markdown("convert_bytes", result.markdown)
        print("--- metadata ---")
        print(repr(result.metadata))
        _try_json_serialize("convert_bytes", result.markdown, result.metadata)

    # -------- 2) 异步薄封装路径（与 BaseConverter 抽象层一致）
    async def run_pptx_converter(self) -> None:
        from converter.pptx_converter import PptxConverter

        print("\n========== PptxConverter.convert（异步封装）==========")
        if not self.ppt_path.is_file():
            print(f"文件不存在: {self.ppt_path}")
            return

        pc = PptxConverter()
        if not pc.validate(self.ppt_path):
            print(f"后缀不在支持列表: {self.ppt_path.suffix}")
            return

        t0 = time.perf_counter()
        try:
            out = await pc.convert(self.ppt_path, **self.kwargs)
        except Exception as e:
            print(f"PptxConverter.convert 异常: {e!r}")
            traceback.print_exc()
            return
        elapsed = time.perf_counter() - t0

        print(f"耗时: {elapsed:.3f} s")
        _print_markdown("PptxConverter", out.markdown)
        print("--- metadata ---")
        print(repr(out.metadata))
        _try_json_serialize("PptxConverter", out.markdown, out.metadata)


# --------------------------------------------------------------------- main
def main() -> None:
    positional, opts = _parse_flags(sys.argv[1:])

    if not positional:
        # 默认尝试用户之前测试过的样本，没有就提示用法
        default_ppt = _ROOT / "test" / "化工&工业.pptx"
        if default_ppt.is_file():
            p = default_ppt
            print(f"未传路径，使用默认: {p}")
        else:
            print("用法: python converter/test_pptx_converter.py <本地 ppt 路径> [--visual] [--dpi=200]")
            sys.exit(1)
    else:
        p = Path(positional[0])

    if not p.is_absolute():
        # 相对路径优先按 cwd 解析；解析不到再退回项目根；都没有则给出明确提示
        p_cwd = Path.cwd() / p
        p_root = _ROOT / p
        if p_cwd.is_file():
            p = p_cwd
        elif p_root.is_file():
            p = p_root
        else:
            print(
                "❌ 没找到 PPT 文件，已尝试以下两个位置：\n"
                f"   1) {p_cwd}\n"
                f"   2) {p_root}\n"
                "请确认文件名拼写、所在目录，或直接传绝对路径。\n"
                "提示：bash 里包含 & / 空格 / 中文的文件名要用单引号包起来。"
            )
            sys.exit(1)

    tester = PptxConverterSelfTest(p, visual=opts["visual"], dpi=opts["dpi"])
    print(
        f"\n模式: {'视觉版（VLM）' if opts['visual'] else 'python-pptx 文本版'}"
        f"  dpi={opts['dpi'] or 'default'}"
    )

    tester.run_convert_bytes()
    try:
        asyncio.run(tester.run_pptx_converter())
    except RuntimeError:
        # 极少数环境已有 running loop
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(tester.run_pptx_converter())
        finally:
            loop.close()


if __name__ == "__main__":
    main()

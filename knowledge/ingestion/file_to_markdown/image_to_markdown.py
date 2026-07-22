"""图像 → Markdown（飞桨 PaddleOCR PP-StructureV3）。

与根目录 ``test.py`` 一致：默认 ``PPStructureV3(device="cpu")``，由框架自动拉取/使用官方模型，
避免手写各 ``*_model_dir`` 路径导致无法运行。

可选环境变量：

- ``PADDLE_OCR_DEVICE``：默认 ``cpu``（与已跑通测试一致；GPU 可设为 ``gpu:0`` 等）。
- ``PADDLEX_MODEL_BASE``：若设置且目录存在，则按该根目录拼接各子模型目录传入管线
  （与旧版本地权重布局兼容）；未设置则走与 ``test.py`` 相同的最简构造。
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .html_to_markdown import HtmlToMarkdownConverter

_pp_structure_v3_cls: Callable[..., Any] | None = None


def _import_pp_structure_v3():
    global _pp_structure_v3_cls
    if _pp_structure_v3_cls is not None:
        return _pp_structure_v3_cls
    try:
        from paddleocr import PPStructureV3 as cls
    except ImportError as e:
        raise ImportError(
            "图像结构解析需要安装飞桨生态依赖，例如：\n"
            "  pip install paddlepaddle paddleocr\n"
            "（GPU 版本请参考 https://www.paddlepaddle.org.cn/install/quick ）\n"
            "原始错误: "
            + str(e)
        ) from e
    _pp_structure_v3_cls = cls
    return cls


def _paddle_device() -> str:
    return os.environ.get("PADDLE_OCR_DEVICE", "cpu")


def _model_base_dir() -> str | None:
    raw = os.environ.get("PADDLEX_MODEL_BASE", "").strip()
    if not raw:
        return None
    path = raw.rstrip("/")
    return path if os.path.isdir(path) else None


def _build_pipeline_kwargs(
    use_doc_orientation_classify: bool,
    use_doc_unwarping: bool,
) -> dict[str, Any]:
    """与 test.py 对齐：默认仅传 device；若配置了有效模型根目录再追加各 model_dir。"""
    device = _paddle_device()
    base = _model_base_dir()

    kwargs: dict[str, Any] = {
        "device": device,
        "use_doc_orientation_classify": use_doc_orientation_classify,
        "use_doc_unwarping": use_doc_unwarping,
    }

    if base:
        kwargs.update(
            {
                "layout_detection_model_dir": f"{base}/PP-DocLayout_plus-L",
                "chart_recognition_model_dir": f"{base}/PP-Chart2Table",
                "formula_recognition_model_dir": f"{base}/PP-FormulaNet_plus-L",
                "region_detection_model_dir": f"{base}/PP-DocBlockLayout",
                "table_orientation_classify_model_dir": f"{base}/PP-LCNet_x1_0_doc_ori",
                "text_detection_model_dir": f"{base}/PP-OCRv5_server_det",
                "textline_orientation_model_dir": f"{base}/PP-LCNet_x1_0_textline_ori",
                "table_classification_model_dir": f"{base}/PP-LCNet_x1_0_table_cls",
                "wired_table_cells_detection_model_dir": f"{base}/RT-DETR-L_wired_table_cell_det",
                "wireless_table_cells_detection_model_dir": f"{base}/RT-DETR-L_wireless_table_cell_det",
                "wired_table_structure_recognition_model_dir": f"{base}/SLANeXt_wired",
                "wireless_table_structure_recognition_model_dir": f"{base}/SLANet_plus",
                "text_recognition_model_dir": f"{base}/PP-OCRv5_server_rec",
            }
        )

    return kwargs


_singleton_lock = threading.Lock()


class ImageToMarkdownConverter:
    """图像转 Markdown：PPStructureV3，单例加载。"""

    _instance: ImageToMarkdownConverter | None = None
    _initialized: bool = False
    _reset_lock = threading.Lock()

    def reset(self) -> None:
        with self._reset_lock:
            if not hasattr(self, "pipeline") or self.pipeline is None:
                return
            try:
                if hasattr(self.pipeline, "clear_cache"):
                    self.pipeline.clear_cache()
                if hasattr(self.pipeline, "release_memory"):
                    self.pipeline.release_memory()
                if hasattr(self.pipeline, "_reset_state"):
                    self.pipeline._reset_state()
            except Exception as e:
                print(f"重置 OCR 状态时出错: {e}")
                self._reinitialize()

    def _reinitialize(self) -> None:
        try:
            o = getattr(self, "_use_doc_orientation_classify", False)
            u = getattr(self, "_use_doc_unwarping", False)
            ImageToMarkdownConverter._initialized = False
            self.pipeline = None
            self.__init__(o, u)
        except Exception as e:
            print(f"重新初始化 OCR 失败: {e}")

    def __new__(cls, *args: Any, **kwargs: Any):
        if cls._instance is None:
            with _singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
    ) -> None:
        if ImageToMarkdownConverter._initialized:
            return

        with _singleton_lock:
            if ImageToMarkdownConverter._initialized:
                return

            print("首次初始化：加载 PPStructureV3（与 test.py 一致：默认仅指定 device）...")
            PPStructureV3 = _import_pp_structure_v3()
            self._use_doc_orientation_classify = use_doc_orientation_classify
            self._use_doc_unwarping = use_doc_unwarping

            pipe_kw = _build_pipeline_kwargs(use_doc_orientation_classify, use_doc_unwarping)
            if _model_base_dir() is None:
                # 与 test.py 一致：默认只传 device；可选开关仅在为 True 时传入
                minimal: dict[str, Any] = {"device": pipe_kw["device"]}
                if use_doc_orientation_classify:
                    minimal["use_doc_orientation_classify"] = True
                if use_doc_unwarping:
                    minimal["use_doc_unwarping"] = True
                self.pipeline = PPStructureV3(**minimal)
            else:
                self.pipeline = PPStructureV3(**pipe_kw)

            self.html_converter = HtmlToMarkdownConverter()
            ImageToMarkdownConverter._initialized = True
            print("模型加载完成！")

    def convert(self, file_content: bytes, filename: str) -> str:
        try:
            self.reset()

            if not file_content or len(file_content) < 100:
                return "# 图像转换错误\n\n错误：图片数据为空或太小，不是有效图片"

            try:
                import io

                from PIL import Image

                img = Image.open(io.BytesIO(file_content))
                img.verify()
            except Exception as img_err:
                return f"# 图像转换错误\n\n图片格式错误/损坏：{str(img_err)}"

            file_ext = os.path.splitext(filename)[1].lower() or ".png"
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as temp_file:
                temp_file.write(file_content)
                temp_path = temp_file.name

            try:
                temp_output_dir = tempfile.mkdtemp(prefix="paddle_ocr_")
                result = self._convert_image_internal(temp_path, temp_output_dir)
                markdown_content = result["markdown_text"]
                if not markdown_content or not markdown_content.strip():
                    return "# 图像转换结果\n\n转换完成但未提取到文本内容"
                return markdown_content
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                if "temp_output_dir" in locals() and os.path.exists(temp_output_dir):
                    shutil.rmtree(temp_output_dir, ignore_errors=True)

        except ImportError as e:
            return f"# 图像转换结果\n\n缺少飞桨 OCR 依赖：{e}"
        except Exception as e:
            return f"# 图像转换错误\n\n转换过程中出现错误: {str(e)}"

    def _convert_image_internal(self, input_image_path: str, output_dir: str) -> dict:
        """与 test.py 相同：predict → save_to_json / save_to_markdown。"""
        try:
            print(f"开始处理图像: {input_image_path}")
            start_time = time.time()

            # test.py: pipeline.predict("./path/to.png")
            results = self.pipeline.predict(input=input_image_path)

            print(f"PPStructure 处理完成，耗时: {time.time() - start_time:.2f} 秒，结果数: {len(results)}")

            for res in results:
                res.save_to_json(save_path=output_dir)
                res.save_to_markdown(save_path=output_dir)
                if hasattr(res, "save_to_word"):
                    try:
                        res.save_to_word(save_path=output_dir)
                    except Exception:
                        pass

            md_files = sorted(glob.glob(str(Path(output_dir) / "*.md")))
            json_files = sorted(glob.glob(str(Path(output_dir) / "*_res.json")))

            full_markdown = ""
            all_json: list[Any] = []
            min_files = min(len(md_files), len(json_files))

            for i in range(min_files):
                md_path = md_files[i]
                json_path = json_files[i]
                try:
                    with open(md_path, encoding="utf-8") as f:
                        md_content = f.read()
                        full_markdown += self.html_converter.convert(md_content) + "\n\n"
                except Exception as e:
                    print(f"读取 Markdown 失败: {e}")
                    full_markdown += f"# 页面 {i + 1}\n\n读取失败: {str(e)}\n\n"
                try:
                    with open(json_path, encoding="utf-8") as f:
                        all_json.append(json.load(f))
                except Exception as e:
                    all_json.append({"error": str(e)})

            if not full_markdown.strip() and md_files:
                for md_path in md_files:
                    try:
                        with open(md_path, encoding="utf-8") as f:
                            full_markdown += self.html_converter.convert(f.read()) + "\n\n"
                    except Exception as e:
                        full_markdown += f"\n\n（读取 {md_path} 失败: {e}）"

            return {
                "markdown_text": full_markdown.strip(),
                "json": all_json,
            }

        except Exception as e:
            print(f"图像转换错误: {e}")
            return {
                "markdown_text": f"# 图像转换错误\n\n转换过程中出现错误: {str(e)}",
                "json": [],
            }


def get_image_to_markdown_converter(
    use_doc_orientation_classify: bool = False,
    use_doc_unwarping: bool = False,
) -> ImageToMarkdownConverter:
    return ImageToMarkdownConverter(use_doc_orientation_classify, use_doc_unwarping)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    single = here / "temp_word_images" / "8bd36239a19c9c440bcb7d861867e8ec.png"
    if not single.is_file():
        print(f"测试图片不存在: {single}")
    else:
        c = get_image_to_markdown_converter()
        out = c.convert(single.read_bytes(), single.name)
        print(out[:2000] if len(out) > 2000 else out)

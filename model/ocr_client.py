"""
图像 OCR 客户端。

支持本地 ``pytesseract`` 或远程 HTTP OCR 接口（占位实现），与 ``BaseModelClient`` 接口部分对齐。
"""

from pathlib import Path

from model.base import BaseModelClient, ModelResponse


class OCRClient(BaseModelClient):
    """
    OCR 识别封装类。

    ``recognize`` 为主入口；``_call_api`` 未使用，仅为满足抽象基类约束。
    """

    def __init__(self, use_api: bool = False, api_url: str | None = None, api_key: str | None = None):
        """
        初始化 OCR 模式与远程参数。

        Args:
            use_api: True 时走 ``_api_ocr``，否则走本地 ``_local_ocr``。
            api_url: 远程 OCR 服务根地址。
            api_key: 远程鉴权密钥。
        """
        self.use_api = use_api
        self.api_url = api_url
        self.api_key = api_key

    async def recognize(self, image_path: Path, language: str = "chi_sim+eng") -> str:
        """
        对图片路径执行 OCR，返回纯文本。

        Args:
            image_path: 图像文件路径。
            language: Tesseract 语言包组合，默认中英。

        Returns:
            识别出的文本；依赖缺失时返回提示占位字符串。
        """
        if self.use_api:
            return await self._api_ocr(image_path)
        return await self._local_ocr(image_path, language)

    async def _local_ocr(self, image_path: Path, language: str) -> str:
        """
        使用 Pillow + pytesseract 在本地识别。

        Args:
            image_path: 图片路径。
            language: Tesseract ``-l`` 参数。

        Returns:
            去除首尾空白的识别文本或错误提示。
        """
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(str(image_path))
            text = pytesseract.image_to_string(image, lang=language)
            return text.strip()
        except ImportError:
            return "[OCR unavailable: install pytesseract and tesseract-ocr]"

    async def _api_ocr(self, image_path: Path) -> str:
        """
        将图片 Base64 后 POST 到 ``{api_url}/ocr``（示例约定）。

        Args:
            image_path: 待上传图片路径。

        Returns:
            响应 JSON 中 ``text`` 字段，缺省为空字符串。
        """
        import base64

        image_b64 = base64.b64encode(image_path.read_bytes()).decode()

        payload = {
            "model": "ocr-v1",
            "image": image_b64,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self.api_url}/ocr", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("text", "")

    async def _call_api(self, payload: dict) -> ModelResponse:
        """OCR 不走统一 payload 通道，请使用 ``recognize``。"""
        raise NotImplementedError("Use recognize() directly for OCR")

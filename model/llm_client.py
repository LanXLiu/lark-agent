"""
大语言模型对话客户端（OpenAI 兼容 ``/chat/completions``）。

封装异步 POST、鉴权头与响应到 ``ModelResponse`` 的映射。
"""

from typing import Any

from httpx import AsyncClient

from conf.settings import settings
from model.base import BaseModelClient, ModelResponse


class LLMClient(BaseModelClient):
    """
    通用 LLM HTTP 客户端。

    默认使用 ``settings`` 中的密钥、基址与对话模型名。
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        """
        初始化客户端。

        Args:
            api_key: Bearer Token，缺省 ``settings.llm_api_key``。
            base_url: API 根 URL，缺省 ``settings.llm_base_url``。
            model: 模型名，缺省 ``settings.llm_model``。
        """
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self._client = AsyncClient(timeout=120)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs,
    ) -> ModelResponse:
        """
        发送多轮对话请求。

        Args:
            messages: OpenAI 格式的 ``[{"role": "...", "content": "..."}, ...]``。
            temperature: 采样温度。
            max_tokens: 回复最大 token 上限。
            **kwargs: 透传至请求体（如 ``top_p`` 等）。

        Returns:
            解析后的 ``ModelResponse``。
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        return await self._call_api(payload)

    async def _call_api(self, payload: dict[str, Any]) -> ModelResponse:
        """
        执行 chat completions POST 并解析首条 choice。

        Args:
            payload: 完整请求 JSON 体。

        Returns:
            ``ModelResponse``；若上游结构变化需同步调整字段路径。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        return ModelResponse(
            content=choice["message"]["content"],
            model_name=data["model"],
            usage=data.get("usage", {}),
        )

    async def close(self) -> None:
        """释放 HTTP 客户端资源。"""
        await self._client.aclose()

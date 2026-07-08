"""把百炼（阿里云 DashScope）接入 Ragas。

Ragas 默认走 OpenAI；百炼是 OpenAI 兼容接口，因此直接用 langchain 的
``ChatOpenAI`` / ``OpenAIEmbeddings`` 指向百炼的 base_url，再用 Ragas 的
wrapper 包一层即可，无需自写复杂适配。

所有密钥 / 地址从环境变量读取（见 .env.example），不在代码里硬编码。
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

# 百炼 OpenAI 兼容网关根路径（/chat/completions、/embeddings 都挂在这下面）
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"评估需要环境变量 {name}，请在 .env 里设置（参考 .env.example）。"
        )
    return value


def build_judge_llm():
    """构造给 Ragas 当「裁判」的 LLM（百炼 deepseek）。"""
    api_key = _require("BAILIAN_API_KEY")
    base_url = os.getenv("BAILIAN_BASE_URL", _DEFAULT_BASE_URL)
    # 评估要稳定可复现，temperature 压到 0
    llm = ChatOpenAI(
        model=os.getenv("EVAL_JUDGE_MODEL", os.getenv("BAILIAN_MODEL", "deepseek-v4-pro")),
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=float(os.getenv("EVAL_JUDGE_TIMEOUT", "120")),
    )
    return LangchainLLMWrapper(llm)


def build_judge_embeddings():
    """构造给 Ragas 算语义相似度的 embedding（百炼 text-embedding-v3）。"""
    api_key = _require("BAILIAN_API_KEY")
    base_url = os.getenv("BAILIAN_BASE_URL", _DEFAULT_BASE_URL)
    embeddings = OpenAIEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        api_key=api_key,
        base_url=base_url,
    )
    return LangchainEmbeddingsWrapper(embeddings)

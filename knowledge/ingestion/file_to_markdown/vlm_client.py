"""通用 VLM（多模态视觉模型）调用工具。

OpenAI 兼容 ``/chat/completions`` + 图像 ``data:<mime>;base64,...`` 输入。

被 :mod:`file_to_markdown.pptx_visual_to_markdown` 和
:mod:`file_to_markdown.word_to_markdown` 共用：

- :func:`read_vlm_settings`     从 ``conf.settings.MODELS.VLM`` 读取默认配置，缺失回落到模块默认。
- :func:`describe_image`        对一张图片调用 VLM，返回模型回复文本（失败抛 ``RuntimeError``）。

模块自带的硬编码默认 **不包含** API key——必须由 settings 或显式参数提供。
"""

from __future__ import annotations

import base64
import sys
import time
from typing import Any

# ============================== 默认（与 test/ocr.py 一致）==============================
_DEFAULT_VLM_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
_DEFAULT_VLM_KEY = ""
_DEFAULT_VLM_MODEL = "doubao-1-5-vision-pro-32k-250115"
_DEFAULT_DPI = 200
_DEFAULT_TIMEOUT_SEC = 180
# =====================================================================================

# 命中以下子串 → 视为瞬态错误（网络抖动 / 网关 5xx / 连接被对端重置等），重试一般能过；
# 401 / 403 / 422 / VLM 返回结构异常等**不**算瞬态，立刻放弃以省时间。
_TRANSIENT_ERROR_HINTS = (
    "Connection aborted",
    "Connection reset",
    "ConnectionError",
    "ConnectionResetError",
    "RemoteDisconnected",
    "Read timed out",
    "Timeout",
    "timed out",
    "502",
    "503",
    "504",
)


def is_transient_error(err: BaseException) -> bool:
    """根据异常字符串粗判是否值得重试。误判最多多一次请求，可接受。"""
    s = repr(err)
    return any(h in s for h in _TRANSIENT_ERROR_HINTS)


def read_vlm_settings() -> dict[str, Any]:
    """
    读取 ``settings.MODELS.VLM`` 配置，缺失/异常一律回落到模块默认值。

    支持的键（YAML）::

        MODELS:
          VLM:
            url: "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
            api_key: "ark-xxx"
            model: "doubao-1-5-vision-pro-32k-250115"
            dpi: 200
            timeout_sec: 180

    Returns:
        固定 5 个键的 dict：``url`` / ``api_key`` / ``model`` / ``dpi`` / ``timeout_sec``。
    """
    out: dict[str, Any] = {
        "url": _DEFAULT_VLM_URL,
        "api_key": _DEFAULT_VLM_KEY,
        "model": _DEFAULT_VLM_MODEL,
        "dpi": _DEFAULT_DPI,
        "timeout_sec": _DEFAULT_TIMEOUT_SEC,
    }
    try:
        from infrastructure.conf.settings import settings  # 延迟导入：避免循环依赖

        vlm = (getattr(settings, "MODELS", {}) or {}).get("VLM", {}) or {}
        for k in out:
            v = vlm.get(k)
            if v not in (None, ""):
                out[k] = v
    except Exception:
        # settings 不可用（独立脚本/测试场景）时静默回落
        pass
    return out


def describe_image(
    image_bytes: bytes,
    *,
    prompt: str,
    mime_type: str = "image/png",
    url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_sec: int | None = None,
) -> str:
    """
    对一张图片调用 VLM，返回模型生成的文本。

    Args:
        image_bytes: 原始图片字节流。
        prompt:      文本指令（提示词）。
        mime_type:   图片 MIME；PNG 用 ``"image/png"``，JPEG 用 ``"image/jpeg"``。
        url:         覆盖 settings 的 VLM URL（不传则用 settings）。
        api_key:     覆盖 settings 的 api_key（不传则用 settings；最终为空时抛错）。
        model:       覆盖 settings 的模型 ID。
        timeout_sec: 单次请求超时（秒）。

    Returns:
        模型 ``choices[0].message.content`` 字符串（已 ``str``）。

    Raises:
        RuntimeError: api_key 缺失 / HTTP 非 200 / 响应结构异常。
    """
    import requests  # 延迟导入

    cfg = read_vlm_settings()
    url = url or cfg["url"]
    api_key = api_key or cfg["api_key"]
    model = model or cfg["model"]
    timeout_sec = int(timeout_sec or cfg["timeout_sec"])

    if not api_key:
        raise RuntimeError(
            "VLM api_key 未配置；请在 config_local.yaml 的 MODELS.VLM.api_key 填入有效 Token。"
        )

    b64 = base64.b64encode(image_bytes).decode("ascii")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            }
        ],
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    if resp.status_code != 200:
        raise RuntimeError(
            f"VLM 调用失败 status={resp.status_code} body={resp.text[:600]}"
        )
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"VLM 返回结构异常：{e}; raw={resp.text[:600]}") from e


def describe_image_with_retry(
    image_bytes: bytes,
    *,
    prompt: str,
    mime_type: str = "image/png",
    url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_sec: int | None = None,
    max_retries: int = 2,
    retry_backoff_sec: float = 1.0,
    log_label: str = "vlm",
) -> str:
    """
    :func:`describe_image` 的**瞬态错误重试**封装。

    - 抛出被 :func:`is_transient_error` 命中的异常 → 按 ``(attempt+1) * retry_backoff_sec``
      线性退避（默认 1s → 2s），重试至多 ``max_retries`` 次；
    - 非瞬态错误（401/403/key 错 / 返回结构异常等） → 立刻终止，把最后一次异常原样抛出；
    - 全部尝试都失败 → 同样把最后一次异常抛出，由调用方决定是 ``return None`` 还是
      ``return ""`` 或继续上抛。

    Args:
        log_label: 日志前缀；建议传入业务上下文（如 ``"pptx page 3"`` / ``"word→md"``）。

    Returns:
        VLM 回复文本。

    Raises:
        最后一次失败的异常（通常是 :class:`RuntimeError` 或网络层异常）。
    """
    last_err: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return describe_image(
                image_bytes,
                prompt=prompt,
                mime_type=mime_type,
                url=url,
                api_key=api_key,
                model=model,
                timeout_sec=timeout_sec,
            )
        except Exception as e:  # noqa: BLE001 — 网络层异常种类多，按瞬态/非瞬态分流
            last_err = e
            if attempt < max_retries and is_transient_error(e):
                sleep = retry_backoff_sec * (attempt + 1)
                print(
                    f"[{log_label}] VLM 调用瞬态失败 "
                    f"(attempt {attempt + 1}/{max_retries + 1})，{sleep:.1f}s 后重试：{e!r}",
                    file=sys.stderr,
                )
                time.sleep(sleep)
                continue
            break
    # 走到这里 last_err 一定非 None（循环要么 return 要么把异常存进 last_err）
    assert last_err is not None
    raise last_err


__all__ = [
    "read_vlm_settings",
    "describe_image",
    "describe_image_with_retry",
    "is_transient_error",
]

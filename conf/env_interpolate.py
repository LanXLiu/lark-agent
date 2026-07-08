"""YAML 环境变量占位符替换。

配置文件里的敏感项（密钥 / 主机 / 端口）写成 ``${VAR}`` 占位符，加载时从环境
变量注入真实值——仓库里不再出现明文密钥。支持默认值语法 ``${VAR:-default}``：
未设置环境变量时用 default；无默认值且环境变量缺失则直接报错（fail-fast），
避免拿空密钥静默跑起来后连不上还查不出原因。

用法（在 yaml.load 之后）：
    data = interpolate_env(data)
"""

from __future__ import annotations

import os
import re
from typing import Any

# 匹配 ${VAR} 或 ${VAR:-default}
_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class MissingEnvVarError(RuntimeError):
    """配置引用了某环境变量但它没设置，且没有默认值。"""


def _resolve(match: re.Match[str]) -> str:
    var_name = match.group(1)
    default = match.group(2)
    value = os.getenv(var_name)
    if value is not None:
        return value
    if default is not None:
        return default
    raise MissingEnvVarError(
        f"配置引用了环境变量 ${{{var_name}}}，但它没有设置，也没有默认值。"
        f"请在 .env 或环境里设置 {var_name}（参考 .env.example）。"
    )


def _interpolate_str(text: str) -> str:
    return _PATTERN.sub(_resolve, text)


def interpolate_env(value: Any) -> Any:
    """递归替换 dict / list / str 中的 ${VAR} 占位符。非字符串原样返回。"""
    if isinstance(value, str):
        return _interpolate_str(value)
    if isinstance(value, dict):
        return {k: interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_env(item) for item in value]
    return value

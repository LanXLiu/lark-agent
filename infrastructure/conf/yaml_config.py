"""
管线特性开关读取模块。

从与 ``infrastructure.conf.settings`` 相同的 ``infrastructure/conf/config_{ENV}.yaml`` 读取顶层配置块
（如 ``chunker``、``quality``、``retriever``），供分块器、过滤步骤等读取细粒度参数。
"""

from __future__ import annotations

import functools
from typing import Any

import yaml

from infrastructure.conf.env_interpolate import interpolate_env
from infrastructure.conf.settings import config_yaml_path


@functools.lru_cache(maxsize=1)
def _raw_config() -> dict[str, Any]:
    """
    解析并缓存整份 YAML 为字典（进程内只读缓存一次）。

    Returns:
        YAML 根对象；若非 dict 则返回空字典，避免下游崩溃。
    """
    path = config_yaml_path()
    with open(path, encoding="utf-8") as fp:
        data = yaml.load(fp, Loader=yaml.FullLoader)
    data = interpolate_env(data)
    return data if isinstance(data, dict) else {}


def get(key: str, default: Any = None) -> Any:
    """
    读取 YAML 顶层键对应的配置块或值。

    Args:
        key: 顶层键名，例如 ``"chunker"``、``"quality"``。
        default: 键不存在时返回的默认值。

    Returns:
        配置值或 ``default``。
    """
    return _raw_config().get(key, default)


def reload_config() -> None:
    """
    清空 YAML 解析缓存。

    在测试切换 ``ENV`` 或热更新配置后调用，使下次 ``get`` 重新读盘。
    """
    _raw_config.cache_clear()

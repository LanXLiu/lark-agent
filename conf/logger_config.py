"""
日志初始化模块。

依据 ``conf/config_{ENV}.yaml`` 中 ``Log`` 段的 ``ErrorPath``、``InfoPath`` 创建目录，
并配置 loguru：控制台 + 按日滚动的 INFO / ERROR 文件日志。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from conf.yaml_config import get


def setup_logger() -> None:
    """
    配置全局 loguru 输出目标与级别。

    无返回值。若 YAML 未配置 ``Log``，则使用默认相对路径 ``logs/error/``、``logs/info/``。
    """
    log_cfg = get("Log") or {}
    err_base = log_cfg.get("ErrorPath", "logs/error/")
    info_base = log_cfg.get("InfoPath", "logs/info/")
    err_dir = Path(err_base)
    info_dir = Path(info_base)
    err_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    # 按日切割，保留 14 天 INFO
    logger.add(
        info_dir / "{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="14 days",
        level="INFO",
        encoding="utf-8",
    )
    # ERROR 单独文件，保留更久便于排障
    logger.add(
        err_dir / "{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="ERROR",
        encoding="utf-8",
    )

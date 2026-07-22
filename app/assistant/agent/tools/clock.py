"""get_current_time 工具：返回当前日期/星期/时间。

LLM 回答"最新""本月""最近""今天"等时间相关问题前，应先调用本工具拿到
当前时间基准(大模型自身不知道"今天几号")。飞书机器人为常驻服务，datetime.now
可用(与 app/channels/lark/observability.py 一致)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.assistant.agent.tools.base import ToolContext, ToolResult
from app.assistant.agent.tools.registry import register_tool

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@register_tool
class GetCurrentTimeTool:
    name = "get_current_time"
    description = (
        "获取当前日期、星期和时间。回答涉及'最新''本月''最近''今天''本周'等"
        "相对时间的问题前，先调用本工具获得时间基准。"
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        now = datetime.now()
        text = f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')} {_WEEKDAYS[now.weekday()]}"
        return ToolResult(text=text)

"""
表格 → 「字段名：内容 字段名：内容」纯文本渲染。

输入：二维表格（首行 = 字段名 / header，其余行 = 数据 / record）。
输出：

- :func:`rows_to_records`        →  list[dict[str, str]]（标准 JSON 数组形态）
- :func:`records_to_text`        →  "字段名：内容 字段名：内容\\n字段名：内容 ..." 纯文本
- :func:`table_to_field_value_text`  组合 helper：(headers, rows) 一步到位转纯文本

约定与契约
==========
1. 一行 record → 一行文本，pair 间用 **单个半角空格** 分隔；
2. 字段名与值之间使用 **全角冒号** ``：``；
3. 字段顺序严格按 ``headers`` 输入顺序；
4. 单元格内换行 / 制表符会被压成空格，避免一条 record 被截成多行；
5. 字段值为空时该 pair 自动跳过（不会出现 ``字段：`` 这种空尾巴）；
6. ``headers`` 中的空字段名会被替换为占位 ``字段``；重名 header 会自动加 ``_2`` / ``_3`` 后缀防止覆盖。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# 单元格内的换行/制表符在拼接成一行时会破坏「一行 = 一条 record」契约，
# 在此统一压成空格。
_CELL_LINEBREAK = re.compile(r"[\r\n\t]+")


def _norm_cell(v: Any) -> str:
    """单元格值标准化：None → ""；其它 → str + 去换行/制表 + strip。"""
    if v is None:
        return ""
    s = v if isinstance(v, str) else str(v)
    s = _CELL_LINEBREAK.sub(" ", s).strip()
    return s


def rows_to_records(
    headers: Iterable[Any],
    rows: Iterable[Iterable[Any]],
) -> list[dict[str, str]]:
    """
    把 ``(headers, rows)`` 折叠为标准 JSON 数组（每行一条 record）。

    - 行尾不足列数的单元格补空字符串；
    - 字段顺序严格保持 ``headers`` 输入顺序；
    - header 重名时，从第 2 个起加后缀 ``_2`` / ``_3`` ... 防止 dict 键覆盖；
    - header 为空时使用占位字段名 ``字段``（同样会按上述规则去重）。
    """
    hs_raw = [_norm_cell(h) for h in headers]
    seen: dict[str, int] = {}
    hs: list[str] = []
    for h in hs_raw:
        key = h or "字段"
        if key in seen:
            seen[key] += 1
            hs.append(f"{key}_{seen[key]}")
        else:
            seen[key] = 1
            hs.append(key)

    n = len(hs)
    records: list[dict[str, str]] = []
    for row in rows:
        cells = list(row)
        rec: dict[str, str] = {}
        for i in range(n):
            v = cells[i] if i < len(cells) else ""
            rec[hs[i]] = _norm_cell(v)
        records.append(rec)
    return records


def records_to_text(records: list[dict[str, str]]) -> str:
    """
    把 ``rows_to_records`` 的结果按「字段名：内容 字段名：内容」格式拼成纯文本。

    - 每条 record → 一行；
    - 同一行内 pair 间使用单个半角空格；
    - 字段值为空的 pair 自动跳过；
    - 整行 pair 都被跳过时，该行整体省略（不出现空行）。
    """
    out_lines: list[str] = []
    for rec in records:
        parts = [f"{k}：{v}" for k, v in rec.items() if v != ""]
        if parts:
            out_lines.append(" ".join(parts))
    return "\n".join(out_lines)


def table_to_field_value_text(
    headers: Iterable[Any],
    rows: Iterable[Iterable[Any]],
) -> str:
    """便捷 helper：``(headers, rows)`` → 「字段名：内容 …」整段纯文本。"""
    return records_to_text(rows_to_records(headers, rows))


__all__ = [
    "rows_to_records",
    "records_to_text",
    "table_to_field_value_text",
]

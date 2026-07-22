"""Load runtime assistant skills from Markdown files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AssistantSkill:
    name: str
    version: str
    summary: str
    content: str
    data: dict[str, Any]

    def tool_rule(self, tool_name: str) -> dict[str, Any]:
        tools = self.data.get("tools", {})
        if not isinstance(tools, dict):
            return {}
        rule = tools.get(tool_name, {})
        return rule if isinstance(rule, dict) else {}


class SkillLoader:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).parent)

    def load(self, filename: str) -> AssistantSkill:
        path = (self.base_dir / filename).resolve()
        content = path.read_text(encoding="utf-8")
        metadata, body = _split_front_matter(content)
        data = _parse_markdown_skill(body)

        name = _required_str(metadata, "name", path)
        version = _required_str(metadata, "version", path)
        summary = _required_str(metadata, "summary", path)
        return AssistantSkill(name=name, version=version, summary=summary, content=body.strip(), data=data)


def load_skill(filename: str) -> AssistantSkill:
    return SkillLoader().load(filename)


def _required_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Skill file {path} must define non-empty string field: {key}")
    return value.strip()


def _split_front_matter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", 4)
    if end < 0:
        return {}, content
    raw = content[4:end]
    body = content[end + len("\n---\n") :]
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, body


def _parse_markdown_skill(body: str) -> dict[str, Any]:
    return {
        "shared_constraints": {
            "no_sql_generation": "Never generate SQL." in body,
            "max_window_days": 30 if "max_window_days`: 30" in body else None,
            "rate_limit": {"max_calls": 3, "window_seconds": 60}
            if "3 calls per 60 seconds" in body
            else {},
        },
        "workflow": {
            "before_tool_exposure": _section_bullets(body, "Before tool exposure:"),
        },
        "tools": {
            "inventory_lookup": _tool_rule(body, "inventory_lookup"),
            "inventory_batch_lookup": _tool_rule(body, "inventory_batch_lookup"),
            "order_status": _tool_rule(body, "order_status"),
            "product_lookup": _tool_rule(body, "product_lookup"),
        },
    }


def _tool_rule(body: str, tool_name: str) -> dict[str, Any]:
    section = _heading_section(body, f"## Tool: {tool_name}")
    return {
        "required_all": _field_list(section, "Required fields:"),
        "optional": _field_list(section, "Optional fields:"),
        "clarification": {"text": "\n".join(_section_bullets(section, "Clarification:"))},
    }


def _heading_section(body: str, heading: str) -> str:
    start = body.find(heading)
    if start < 0:
        return ""
    next_heading = body.find("\n## ", start + len(heading))
    return body[start:] if next_heading < 0 else body[start:next_heading]


def _field_list(section: str, label: str) -> list[str]:
    return [item.strip("`") for item in _section_bullets(section, label)]


def _section_bullets(text: str, label: str) -> list[str]:
    start = text.find(label)
    if start < 0:
        return []
    lines = text[start + len(label) :].splitlines()
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if bullets:
                break
            continue
        if stripped.startswith("#") or stripped.endswith(":"):
            if bullets:
                break
            continue
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
            continue
        if bullets:
            break
    return bullets

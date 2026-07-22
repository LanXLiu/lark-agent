from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_lark_channel_uses_runtime_boundary() -> None:
    modules = _imported_modules(PROJECT_ROOT / "app" / "channels" / "lark" / "bot.py")

    assert "app.assistant.factory" in modules
    assert "app.assistant.memory" in modules
    assert "app.assistant.qa_service" in modules
    assert not any(module.startswith("knowledge.retrieval") for module in modules)
    assert not any(module.startswith("infrastructure.db") for module in modules)


def test_public_architecture_packages_import() -> None:
    import app.assistant
    import infrastructure.object_storage
    import infrastructure.vector_store
    import knowledge.ingestion
    import knowledge.retrieval

    assert app.assistant.AgentService
    assert knowledge.ingestion.KnowledgeBasePipeline
    assert knowledge.retrieval.HybridRecaller

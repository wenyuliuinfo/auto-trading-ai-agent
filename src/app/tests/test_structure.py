"""Layer boundary checks (CONVENTIONS.md §2.1, root pnpm check:structure)."""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _modules_under(rel: str) -> list[Path]:
    return sorted((APP_ROOT / rel).glob("*.py"))


def test_api_never_imports_integrations_or_evaluation() -> None:
    for path in _modules_under("api"):
        imports = _imports(path)
        assert not any("app.integrations" in i or "app.evaluation" in i for i in imports)


def test_agents_never_import_api_or_evaluation() -> None:
    for path in _modules_under("agents"):
        imports = _imports(path)
        assert not any("app.api" in i or "app.evaluation" in i for i in imports)


def test_evaluation_never_imported_from_api_or_agents() -> None:
    api_imports = set().union(
        *(_imports(p) for p in _modules_under("api"))
    )
    agent_imports = set().union(
        *(_imports(p) for p in _modules_under("agents"))
    )
    assert not any("app.evaluation" in i for i in api_imports | agent_imports)


def test_worker_lives_at_app_boundary() -> None:
    worker_imports = _imports(APP_ROOT / "worker.py")
    assert any("app.agents.graph" in i for i in worker_imports)

"""架构纯度测试（蓝图 §10）：oh-contracts 禁止业务包 import 与任何 IO。

静态 AST 检查，防止契约层腐化为业务层（架构专家 P1-3：schema 归属 contracts）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import oh_contracts

_SRC = Path(oh_contracts.__file__).parent

_FORBIDDEN_BUSINESS_PREFIXES = (
    "oh_storage",
    "oh_pipeline",
    "oh_agents",
    "oh_api",
    "oh_sources",
    "oh_llm",
    "oh_web",
    "oh_devtools",
)

_FORBIDDEN_IO_MODULES = {
    "pathlib",
    "os",
    "shutil",
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "httpx",
    "sqlite3",
    "io",
}
_FORBIDDEN_IO_CALLS = {"open", "input"}


def _trees() -> list[tuple[str, ast.Module]]:
    return [(p.name, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(_SRC.rglob("*.py"))]


def test_no_business_imports() -> None:
    for name, tree in _trees():
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for mod in modules:
                root = mod.split(".")[0]
                assert root not in _FORBIDDEN_BUSINESS_PREFIXES, f"{name}: 禁止 import {mod}"


def test_no_io() -> None:
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    msg = f"{name}: 契约层禁止 IO 模块 {alias.name}"
                    assert root not in _FORBIDDEN_IO_MODULES, msg
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                msg = f"{name}: 契约层禁止 IO 模块 {node.module}"
                assert root not in _FORBIDDEN_IO_MODULES, msg
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                msg = f"{name}: 契约层禁止调用 {node.func.id}()"
                assert node.func.id not in _FORBIDDEN_IO_CALLS, msg


def test_all_public_names_reexported() -> None:
    import oh_contracts as pkg

    exported = set(pkg.__all__)
    for name, tree in _trees():
        if name == "__init__.py":
            continue
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith("_"):
                assert node.name in exported, f"{name}: {node.name} 未在 __all__ 导出"

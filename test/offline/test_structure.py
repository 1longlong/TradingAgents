"""Structural AST constraints for the trading subsystem."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
SOURCE_DIRS = (SRC_ROOT / "trading", SRC_ROOT / "safety")
ENGINE_PATH = SRC_ROOT / "safety" / "engine.py"
CLOCK_PATH = SRC_ROOT / "trading" / "clock.py"

_BANNED_NETWORK_ROOTS = {
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "aiohttp",
    "http",
    "socket",
    "yfinance",
    "alpaca",
    "alpaca_trade_api",
    "ib_insync",
    "ibapi",
    "ccxt",
    "polygon",
    "websocket",
    "websockets",
}
_BANNED_PREFIXES = ("tradingagents.dataflows",)
_WALL_CLOCK_CALLS = {
    "datetime.now",
    "datetime.datetime.now",
    "datetime.utcnow",
    "datetime.datetime.utcnow",
    "date.today",
    "datetime.date.today",
    "time.time",
    "time.localtime",
    "time.gmtime",
}


def _sources():
    for directory in SOURCE_DIRS:
        for path in sorted(directory.rglob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                modules.add(module)
            for alias in node.names:
                modules.add(f"{module}.{alias.name}" if module else alias.name)
    return modules


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                aliases[alias.asname or alias.name] = (
                    f"{module}.{alias.name}" if module else alias.name
                )
    return aliases


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _resolved_call(node: ast.Call, aliases: dict[str, str]) -> str | None:
    path = _dotted(node.func)
    if path is None:
        return None
    parts = path.split(".")
    if parts[0] in aliases:
        parts = aliases[parts[0]].split(".") + parts[1:]
    return ".".join(parts)


@pytest.mark.unit
def test_inv02_executor_is_imported_only_by_the_safety_engine():
    """[INV-02] No subsystem module bypasses the engine import boundary."""
    importers: dict[str, set[str]] = {}
    for path, tree in _sources():
        for module in _imported_modules(tree):
            if module == "trading.executor" or module.startswith("trading.executor."):
                importers.setdefault(str(path.relative_to(REPO_ROOT)), set()).add(module)

    assert importers, "the safety engine must import the executor"
    unexpected = {
        path: modules
        for path, modules in importers.items()
        if path != str(ENGINE_PATH.relative_to(REPO_ROOT))
    }
    assert unexpected == {}, f"executor imported outside safety/engine.py: {unexpected}"


@pytest.mark.unit
def test_fr05_no_wall_clock_calls_outside_clock_module():
    """[FR-05] Only the injected clock module reads real wall-clock time."""
    violations = []
    for path, tree in _sources():
        if path == CLOCK_PATH:
            continue
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            resolved = _resolved_call(node, aliases)
            if resolved in _WALL_CLOCK_CALLS:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} calls {resolved}"
                )
    assert violations == []


@pytest.mark.unit
def test_fr01_no_network_or_broker_sdk_imports_in_subsystem():
    """[FR-01] Trading and safety code cannot import network or broker clients."""
    violations = []
    for path, tree in _sources():
        for module in _imported_modules(tree):
            root = module.split(".")[0]
            if root in _BANNED_NETWORK_ROOTS or any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in _BANNED_PREFIXES
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert violations == []

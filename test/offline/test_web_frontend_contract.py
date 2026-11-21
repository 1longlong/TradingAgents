"""Frontend contracts for the iteration-1 read-only UI.

Covers the static, machine-checkable parts of REQ-WEB-014 (i18n),
REQ-WEB-021 (browser matrix) and REQ-WEB-025 (sanitized Markdown). Behavioral
Playwright assertions belong to the frontend E2E suite; this file does not
pretend to replace them.
"""

from __future__ import annotations

import json

import pytest

from test.offline.web_fixture_app import require_frontend_file

pytestmark = pytest.mark.unit


def _flatten_keys(value, prefix=""):
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(child, dict):
                keys.update(_flatten_keys(child, path))
            else:
                keys.add(path)
    return keys


def test_frontend_package_declares_approved_stack_and_scripts():
    package = json.loads(require_frontend_file("package.json").read_text())
    dependencies = set(package.get("dependencies", {}))
    dev_dependencies = set(package.get("devDependencies", {}))
    scripts = package.get("scripts", {})

    assert {
        "react",
        "react-dom",
        "react-router-dom",
        "@tanstack/react-query",
        "react-i18next",
        "i18next",
        "react-markdown",
        "remark-gfm",
        "rehype-sanitize",
    } <= dependencies
    assert {"vite", "typescript", "vitest", "@playwright/test"} <= dev_dependencies
    assert {"dev", "build", "lint", "typecheck", "test", "e2e"} <= set(scripts)


def test_i18n_catalogues_have_identical_keys():
    english = json.loads(require_frontend_file("src/i18n/en.json").read_text())
    chinese = json.loads(require_frontend_file("src/i18n/zh.json").read_text())

    english_keys = _flatten_keys(english)
    chinese_keys = _flatten_keys(chinese)
    assert english_keys
    assert english_keys == chinese_keys, {
        "missing_in_zh": sorted(english_keys - chinese_keys),
        "missing_in_en": sorted(chinese_keys - english_keys),
    }


def test_markdown_component_uses_a_sanitizer_and_no_raw_html():
    text = require_frontend_file("src/components/Markdown.tsx").read_text()
    assert "rehypeSanitize" in text
    assert "dangerouslySetInnerHTML" not in text


def test_no_component_uses_dangerously_set_inner_html():
    root = require_frontend_file("package.json").parent
    offenders = [
        str(path)
        for path in (root / "src").rglob("*.tsx")
        if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_browser_matrix_covers_chrome_edge_firefox_and_safari():
    matrix = json.loads(require_frontend_file("browser-matrix.json").read_text())
    names = {str(entry.get("name", "")).lower() for entry in matrix}
    assert {"chrome", "edge", "firefox", "safari"} <= names


def test_playwright_config_covers_three_engines():
    config = require_frontend_file("playwright.config.ts").read_text()
    for engine in ("chromium", "firefox", "webkit"):
        assert engine in config


def test_e2e_history_spec_exists():
    root = require_frontend_file("package.json").parent
    specs = list((root / "e2e").glob("*.spec.ts"))
    assert specs, "expected at least one Playwright history spec"

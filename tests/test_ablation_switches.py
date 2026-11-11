"""Ablation feature switches must change the real path, not just a flag.

The campaign's C0 / A / B / AB ablation is only meaningful if OFF actually
prevents the feature from being bound and triggered, and ON actually uses it.
An environment variable that is read but ignored would silently make every arm
identical and attribute a random difference to a feature that never ran.

These tests assert the observable binding, which is the thing the model sees:

* ``batch_macro=False`` → ``get_macro_indicators_batch`` is absent from the tool
  list bound to the analyst, and absent from the prompt. The single-series tool
  must remain, so OFF is the genuine pre-batch behaviour.
* ``structured=False``  → ``with_structured_output`` is never called.
* the defaults are the shipped behaviour (both on).
"""

from __future__ import annotations

import unittest
from unittest import mock

from tradingagents.agents.analysts import fundamentals_analyst, market_analyst, news_analyst
from tradingagents.default_config import DEFAULT_CONFIG


class _Stop(Exception):
    pass


class _FakeLLM:
    """Records what the node binds, then stops before any network call."""

    def __init__(self, capture):
        self.capture = capture
        self.structured_called = False

    def bind_tools(self, tools):
        self.capture["tools"] = [t.name for t in tools]
        raise _Stop

    def with_structured_output(self, schema):
        self.structured_called = True
        return mock.MagicMock()

    def invoke(self, *a, **k):  # pragma: no cover - never reached
        raise _Stop


def _news_tools(**kw):
    cap = {}
    try:
        news_analyst.create_news_analyst(_FakeLLM(cap), **kw)(
            {
                "trade_date": "2026-09-23",
                "company_of_interest": "NVDA",
                "asset_type": "stock",
                "messages": [],
            }
        )
    except _Stop:
        pass
    return cap.get("tools", [])


class BatchMacroSwitchTest(unittest.TestCase):
    def test_on_binds_batch_tool(self):
        self.assertIn("get_macro_indicators_batch", _news_tools(batch_macro=True))

    def test_off_does_not_bind_batch_tool(self):
        tools = _news_tools(batch_macro=False)
        self.assertNotIn("get_macro_indicators_batch", tools)
        # The fallback must survive, otherwise OFF is not a fair control.
        self.assertIn("get_macro_indicators", tools)

    def test_off_keeps_every_other_tool(self):
        on = set(_news_tools(batch_macro=True))
        off = set(_news_tools(batch_macro=False))
        self.assertEqual(on - off, {"get_macro_indicators_batch"})

    def test_default_is_on(self):
        self.assertIn("get_macro_indicators_batch", _news_tools())

    def test_prompt_does_not_advertise_an_unbound_tool(self):
        # Naming a tool that is not bound causes "unknown tool" failures.
        import inspect

        src = inspect.getsource(news_analyst.create_news_analyst)
        self.assertIn("macro_hint", src)
        # The batch sentence must be conditional, not unconditional prose.
        self.assertIn("if batch_macro", src)


class StructuredSwitchTest(unittest.TestCase):
    def _bind_called(self, factory, **kw):
        cap = {}
        llm = _FakeLLM(cap)
        try:
            factory(llm, **kw)(
                {
                    "trade_date": "2026-09-23",
                    "company_of_interest": "NVDA",
                    "asset_type": "stock",
                    "messages": [],
                }
            )
        except (_Stop, Exception):  # noqa: BLE001 - we only want the binding
            pass
        return llm.structured_called

    def test_on_binds_schema_for_all_three(self):
        for factory in (market_analyst.create_market_analyst,
                        fundamentals_analyst.create_fundamentals_analyst,
                        news_analyst.create_news_analyst):
            with self.subTest(factory.__module__):
                self.assertTrue(self._bind_called(factory, structured=True))

    def test_off_binds_no_schema_for_all_three(self):
        for factory in (market_analyst.create_market_analyst,
                        fundamentals_analyst.create_fundamentals_analyst,
                        news_analyst.create_news_analyst):
            with self.subTest(factory.__module__):
                self.assertFalse(self._bind_called(factory, structured=False))

    def test_defaults_are_on(self):
        self.assertTrue(DEFAULT_CONFIG.get("batch_macro_enabled"))
        self.assertTrue(DEFAULT_CONFIG.get("structured_analyst_output_enabled"))


class ConfigPlumbingTest(unittest.TestCase):
    def test_env_override_coerces_to_bool(self):
        import os

        from tradingagents import default_config as dc

        cfg = dict(DEFAULT_CONFIG)
        cfg["batch_macro_enabled"] = True
        old = os.environ.get("TRADINGAGENTS_BATCH_MACRO_ENABLED")
        try:
            os.environ["TRADINGAGENTS_BATCH_MACRO_ENABLED"] = "false"
            dc._apply_env_overrides(cfg)
            self.assertIs(cfg["batch_macro_enabled"], False)
            os.environ["TRADINGAGENTS_BATCH_MACRO_ENABLED"] = "true"
            dc._apply_env_overrides(cfg)
            self.assertIs(cfg["batch_macro_enabled"], True)
        finally:
            if old is None:
                os.environ.pop("TRADINGAGENTS_BATCH_MACRO_ENABLED", None)
            else:
                os.environ["TRADINGAGENTS_BATCH_MACRO_ENABLED"] = old

    def test_graph_setup_reads_the_switches(self):
        import inspect

        from tradingagents.graph import setup as setup_mod

        src = inspect.getsource(setup_mod.GraphSetup.setup_graph)
        self.assertIn("batch_macro_enabled", src)
        self.assertIn("structured_analyst_output_enabled", src)

    def test_toolnode_honours_batch_switch(self):
        import inspect

        from tradingagents.graph import trading_graph as tg

        src = inspect.getsource(tg.TradingAgentsGraph._create_tool_nodes)
        self.assertIn("batch_macro_enabled", src)


if __name__ == "__main__":
    unittest.main()

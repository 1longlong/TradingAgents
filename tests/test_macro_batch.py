"""Batch macro retrieval: additive, information-preserving, and crash-proof.

The batch tool exists only to remove round trips. These tests pin three
properties that make that safe:

1. **Faithfulness** — each series' text is byte-identical to what the
   single-series tool returns, so batching cannot lose or alter information.
2. **Total on malformed input** — a plain argument-format slip from the model
   must never abort the run. ``list[str]`` was the first array-typed argument in
   this codebase, and LangGraph re-raises non-``ToolInvocationError`` exceptions
   from a ToolNode, so an uncoerced ``indicators="cpi"`` would have killed a run.
3. **Honest failure** — one bad series does not suppress the others, and a
   *total* outage is labelled rather than looking like a successful batch (the
   router returns a string, never an exception, so this needs an explicit check).

The 17 cases the campaign brief requires are each named
``test_case_<n>_*`` below.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.agents.utils import macro_data_tools as mt
from tradingagents.agents.utils.macro_data_tools import (
    MAX_BATCH_INDICATORS,
    get_macro_indicators_batch,
)

DATE = "2026-09-23"


def _fake_route(mapping=None, default=None):
    """Stand-in for route_to_vendor('get_macro_indicators', ...)."""
    calls = []

    def route(method, indicator, curr_date, look_back_days):
        calls.append((method, indicator, curr_date, look_back_days))
        if mapping and indicator in mapping:
            value = mapping[indicator]
            if isinstance(value, Exception):
                raise value
            return value
        if default is not None:
            return default
        return f"## FRED: {indicator} report for {curr_date}"

    route.calls = calls
    return route


def _invoke(indicators, route, look_back_days=None):
    with patch.object(mt, "route_to_vendor", route):
        return get_macro_indicators_batch.invoke(
            {
                "indicators": indicators,
                "curr_date": DATE,
                "look_back_days": look_back_days,
                "trade_date": DATE,
            }
        )


class FaithfulnessTest(unittest.TestCase):
    def test_batch_of_one_equals_single_tool_text(self):
        route = _fake_route()
        single = route("get_macro_indicators", "cpi", DATE, None)
        self.assertEqual(_invoke(["cpi"], route), single)

    def test_every_series_preserved_in_request_order(self):
        route = _fake_route()
        indicators = ["cpi", "unemployment", "10y_treasury"]
        out = _invoke(indicators, route)
        positions = []
        for ind in indicators:
            expected = route("get_macro_indicators", ind, DATE, None)
            idx = out.find(expected)
            self.assertNotEqual(idx, -1, f"{ind} missing from batch output")
            positions.append(idx)
        self.assertEqual(positions, sorted(positions))

    def test_same_method_date_and_window_for_every_series(self):
        route = _fake_route()
        _invoke(["cpi", "vix"], route, look_back_days=180)
        self.assertEqual(len(route.calls), 2)
        for method, _indicator, curr_date, look_back in route.calls:
            self.assertEqual(method, "get_macro_indicators")
            self.assertEqual(curr_date, DATE)
            self.assertEqual(look_back, 180)

    def test_no_indicator_is_invented(self):
        # Nothing is fetched beyond what was asked for.
        route = _fake_route()
        _invoke(["cpi", "vix"], route)
        self.assertEqual([c[1] for c in route.calls], ["cpi", "vix"])


class MalformedInputTest(unittest.TestCase):
    """The 17 required argument/error cases. None may raise."""

    def test_case_01_bare_string(self):
        route = _fake_route()
        self.assertEqual(
            _invoke("cpi", route), route("get_macro_indicators", "cpi", DATE, None)
        )

    def test_case_02_proper_array(self):
        route = _fake_route()
        out = _invoke(["cpi", "vix"], route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("## FRED: vix report", out)

    def test_case_03_comma_separated_string(self):
        route = _fake_route()
        out = _invoke("cpi, vix", route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("## FRED: vix report", out)
        self.assertEqual([c[1] for c in route.calls], ["cpi", "vix"])

    def test_case_04_case_and_space_variants_dedupe(self):
        route = _fake_route()
        _invoke(["CPI", " cpi ", "Cpi"], route)
        self.assertEqual(len(route.calls), 1)

    def test_case_05_empty_list(self):
        route = _fake_route()
        out = _invoke([], route)
        self.assertIn("No macro indicators", out)
        self.assertEqual(route.calls, [])

    def test_case_06_empty_string(self):
        route = _fake_route()
        out = _invoke("", route)
        self.assertIn("No macro indicators", out)
        self.assertEqual(route.calls, [])

    def test_case_07_none(self):
        route = _fake_route()
        out = _invoke(None, route)
        self.assertIn("No macro indicators", out)
        self.assertEqual(route.calls, [])

    def test_case_08_duplicates(self):
        route = _fake_route()
        _invoke(["cpi", "cpi", "vix", "CPI"], route)
        self.assertEqual([c[1] for c in route.calls], ["cpi", "vix"])

    def test_case_09_unknown_indicator_is_reported_inline(self):
        route = _fake_route(mapping={"bogus": ValueError("unknown series")})
        out = _invoke(["cpi", "bogus", "unemployment"], route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("## FRED: unemployment report", out)
        self.assertIn("DATA_UNAVAILABLE", out)
        self.assertIn("do not estimate or fabricate", out)

    def test_case_10_over_limit_refused_without_fetching(self):
        route = _fake_route()
        out = _invoke([f"series{i}" for i in range(MAX_BATCH_INDICATORS + 1)], route)
        self.assertIn("Too many indicators", out)
        self.assertEqual(route.calls, [])

    def test_case_11_bad_json_list_text(self):
        # Model emits a bracketed list it cannot parse ("['cpi', vix]").
        route = _fake_route()
        out = _invoke("['cpi', vix]", route)
        self.assertIn("cpi", out)
        self.assertIn("vix", out)

    def test_case_11b_json_double_quoted_list(self):
        route = _fake_route()
        out = _invoke('["cpi", "vix"]', route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("## FRED: vix report", out)

    def test_case_12_partial_timeout_keeps_other_series(self):
        route = _fake_route(mapping={"vix": TimeoutError("read timed out")})
        out = _invoke(["cpi", "vix"], route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("TimeoutError", out)
        self.assertIn("DATA_UNAVAILABLE", out)

    def test_case_13_total_timeout_is_labelled(self):
        route = _fake_route(default="DATA_UNAVAILABLE: FRED timed out after 30s.")
        out = _invoke(["cpi", "vix"], route)
        # Both series are unavailable: the batch must say so up front rather
        # than looking like a successful result whose body happens to be prose.
        self.assertTrue(out.startswith("DATA_UNAVAILABLE: none of the 2 requested"))
        self.assertIn("do not infer", out)

    def test_case_14_rate_limit_is_reported(self):
        route = _fake_route(default="DATA_UNAVAILABLE: FRED rate limit exceeded (120/min).")
        out = _invoke(["cpi"], route)
        self.assertIn("rate limit", out)
        self.assertTrue(out.startswith("DATA_UNAVAILABLE: none of the 1 requested"))

    def test_case_15_model_misuse_dict_input(self):
        # A mapping where a list belongs: take its keys, never raise.
        route = _fake_route()
        out = _invoke({"cpi": 1, "vix": 2}, route)
        self.assertIn("## FRED: cpi report", out)
        self.assertIn("## FRED: vix report", out)

    def test_case_16_retry_does_not_duplicate_series(self):
        # A retried identical call is idempotent: same request, same output,
        # and still one vendor call per distinct series.
        route = _fake_route()
        first = _invoke(["cpi", "vix"], route)
        second = _invoke(["cpi", "vix"], route)
        self.assertEqual(first, second)
        self.assertEqual(len(route.calls), 4)

    def test_case_17_cancelled_or_exception_does_not_escape(self):
        # Cancellation surfaces as an exception from the vendor call; the batch
        # must contain it, or a cancelled run would look like a partial success
        # with silently missing series.
        route = _fake_route(mapping={"cpi": RuntimeError("cancelled")})
        out = _invoke(["cpi"], route)
        self.assertIn("RuntimeError", out)
        self.assertIn("DATA_UNAVAILABLE", out)


class SafetyNetTest(unittest.TestCase):
    """Every shape the model has been observed to send, all must not raise."""

    def test_all_shapes_never_raise(self):
        route = _fake_route()
        for raw in (
            "cpi",
            "cpi, vix",
            "['cpi', 'vix']",
            '["cpi","vix"]',
            ("cpi", "vix"),
            {"cpi", "vix"},
            None,
            "",
            [],
            {"cpi": 1},
            123,
            ["cpi", None, " "],
        ):
            with self.subTest(raw=raw):
                _invoke(raw, route)  # must not raise

    def test_coercion_is_total(self):
        for raw in (None, "", "cpi", ["cpi"], ("cpi",), {"cpi"}, 5, {"cpi": 1}):
            with self.subTest(raw=raw):
                result = mt._coerce_indicator_list(raw)
                self.assertIsInstance(result, list)
                self.assertTrue(all(isinstance(item, str) for item in result))

    def test_direct_func_call_also_coerces(self):
        # .func bypasses pydantic entirely; the body must defend itself.
        route = _fake_route()
        with patch.object(mt, "route_to_vendor", route):
            out = mt.get_macro_indicators_batch.func("cpi", DATE, None, DATE)
        self.assertIn("## FRED: cpi report", out)


class BindingTest(unittest.TestCase):
    def test_tool_reachable_from_agent_and_tool_node(self):
        from tradingagents.agents.utils import agent_utils
        from tradingagents.agents.analysts import news_analyst
        from tradingagents.graph import trading_graph

        self.assertIn("get_macro_indicators_batch", agent_utils.__all__)
        na_src = open(news_analyst.__file__).read()
        self.assertIn("get_macro_indicators_batch", na_src)
        self.assertIn("prefer the batch", na_src)
        tg_src = open(trading_graph.__file__).read()
        self.assertIn("get_macro_indicators_batch", tg_src)

    def test_single_series_tool_still_bound_as_fallback(self):
        # The brief requires the single-indicator tool to remain available.
        from tradingagents.agents.analysts import news_analyst

        self.assertIn("get_macro_indicators,", open(news_analyst.__file__).read())


if __name__ == "__main__":
    unittest.main()

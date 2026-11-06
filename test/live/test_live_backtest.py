"""Opt-in 3-day live backtest smoke test.

Configure the API through the repository's normal mechanism:
- provider: TRADINGAGENTS_LLM_PROVIDER (or the default config)
- models: TRADINGAGENTS_DEEP_THINK_LLM / TRADINGAGENTS_QUICK_THINK_LLM
- key: the provider-specific variable, e.g. OPENAI_API_KEY or DEEPSEEK_API_KEY
- opt in: RUN_LIVE_TRADING_TESTS=1
"""

from __future__ import annotations

import csv
import io
import os
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yfinance as yf
from dotenv import load_dotenv

from trading.backtest import (
    BacktestResult,
    BacktestRunner,
    HistoricalQuoteProvider,
    RealDecisionProvider,
    WeekdayCalendar,
)
from trading.clock import SimulationClock
from trading.models import EventType, SafetyConfig
from trading.runtime import DEFAULT_INITIAL_CASH, RuntimeConfig, build_runtime

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)

LIVE_PROXY = os.environ.get(
    "TRADINGAGENTS_LIVE_PROXY",
    "http://127.0.0.1:7897",
)
try:
    yf.config.network.proxy = LIVE_PROXY
except AttributeError:
    yf.set_config(proxy=LIVE_PROXY)

_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "dashscope_cn": "DASHSCOPE_CN_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}


def _llm_available() -> bool:
    from tradingagents.default_config import DEFAULT_CONFIG

    provider = str(DEFAULT_CONFIG.get("llm_provider", "")).lower()
    if provider in {"ollama", "openai_compatible"}:
        return bool(DEFAULT_CONFIG.get("backend_url")) or provider == "ollama"
    env_name = _PROVIDER_KEYS.get(provider)
    if env_name is None:
        return False
    key = os.environ.get(env_name, "").strip()
    return bool(key) and key != "placeholder"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _llm_available(),
        reason="no real LLM API key configured for the selected provider",
    ),
]

SYMBOL = "NVDA"
START_DATE = date(2024, 1, 8)
END_DATE = date(2024, 1, 10)
RUN_ID = "live-smoke-20240108-20240110"


def _fetch_close(symbol: str, day: date):
    """Fetch exactly one historical close through the read-only dataflow."""
    from tradingagents.dataflows.y_finance import get_YFin_data_online

    text = get_YFin_data_online(symbol, day.isoformat(), day.isoformat())
    rows_text = "\n".join(
        line for line in text.splitlines() if line.strip() and not line.startswith("#")
    )
    rows = list(csv.DictReader(io.StringIO(rows_text)))
    if not rows:
        return None
    close = rows[-1].get("Close")
    if close is None or not str(close).strip():
        return None
    return Decimal(str(close).strip())


def _graph_factory(tmp_path, config):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    def factory():
        run_config = deepcopy(config)
        run_config.update(
            {
                "results_dir": str(tmp_path / "results"),
                "data_cache_dir": str(tmp_path / "cache"),
                "memory_log_path": str(tmp_path / "trading_memory.md"),
                "checkpoint_enabled": False,
            }
        )
        return TradingAgentsGraph(
            selected_analysts=["market"],
            config=run_config,
        )

    return factory


@pytest.mark.integration
def test_live_three_day_backtest_smoke(tmp_path):
    """Run three real simulated days through the actual graph and data feed."""
    from tradingagents.default_config import DEFAULT_CONFIG

    safety = SafetyConfig(
        soft_max_order_notional=Decimal("10000"),
        hard_max_order_notional=Decimal("10000"),
        max_position_fraction=Decimal("1.0"),
    )
    clock = SimulationClock(START_DATE)
    runtime = build_runtime(
        RuntimeConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            initial_cash=DEFAULT_INITIAL_CASH,
            safety=safety,
        ),
        clock,
    )
    runner = BacktestRunner(
        pipeline=runtime.pipeline,
        engine=runtime.engine,
        state_store=runtime.store,
        decision_provider=RealDecisionProvider(
            _graph_factory(tmp_path, DEFAULT_CONFIG),
        ),
        quote_provider=HistoricalQuoteProvider(_fetch_close),
        calendar=WeekdayCalendar(),
        clock=clock,
        portfolio=runtime.portfolio,
        symbol=SYMBOL,
        start_date=START_DATE,
        end_date=END_DATE,
        run_id=RUN_ID,
        initial_cash=DEFAULT_INITIAL_CASH,
    )

    result = runner.run()

    assert isinstance(result, BacktestResult)
    assert result.days_processed == 3
    assert result.days_skipped == 0
    assert result.final_equity > 0
    runtime.audit.verify_integrity()
    events = runtime.audit.read_all()
    assert any(event.event_type is EventType.DECISION_RECEIVED for event in events)
    assert not any("broker" in str(event.payload).lower() for event in events)
    _, cursor = runtime.store.load()
    assert cursor is not None
    assert cursor.last_completed_date == END_DATE

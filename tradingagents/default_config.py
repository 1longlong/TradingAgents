import math
import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_MAX_TOKENS":           "max_tokens",
    # Market-analyst tool governance (opt-in). An analyst tool allowance, not a
    # run budget or a vendor retry count: it bounds how many tool rounds/calls
    # the market analyst may cycle through. Off unless explicitly enabled.
    "TRADINGAGENTS_MARKET_TOOL_GOVERNANCE_ENABLED": "market_tool_governance.enabled",
    "TRADINGAGENTS_MARKET_TOOL_GOVERNANCE_MAX_ROUNDS": "market_tool_governance.max_rounds",
    "TRADINGAGENTS_MARKET_TOOL_GOVERNANCE_MAX_CALLS": "market_tool_governance.max_calls",
    # Fundamentals-analyst tool governance (opt-in, independent of the market
    # section). Same allowance rules; off unless explicitly enabled.
    "TRADINGAGENTS_FUNDAMENTALS_TOOL_GOVERNANCE_ENABLED":
        "fundamentals_tool_governance.enabled",
    "TRADINGAGENTS_FUNDAMENTALS_TOOL_GOVERNANCE_MAX_ROUNDS":
        "fundamentals_tool_governance.max_rounds",
    "TRADINGAGENTS_FUNDAMENTALS_TOOL_GOVERNANCE_MAX_CALLS":
        "fundamentals_tool_governance.max_calls",
    # Vendor-retry budget, merged into the nested dict. Every value is checked by
    # dataflows.retry_session when a tool call routes: negatives, booleans,
    # NaN/Infinity and fractional attempts are refused, never clamped.
    "TRADINGAGENTS_VENDOR_RETRY_MAX_SECONDS": "data_vendor_retry.max_total_seconds",
    "TRADINGAGENTS_VENDOR_RETRY_MAX_REQUEST_SECONDS": "data_vendor_retry.max_request_seconds",
    "TRADINGAGENTS_VENDOR_RETRY_MAX_WAIT_SECONDS":
        "data_vendor_retry.max_cumulative_wait_seconds",
    "TRADINGAGENTS_VENDOR_RETRY_MAX_ATTEMPTS": "data_vendor_retry.max_attempts",
    "TRADINGAGENTS_VENDOR_RETRY_MAX_TOTAL_ATTEMPTS": "data_vendor_retry.max_total_attempts",
    "TRADINGAGENTS_VENDOR_RETRY_BASE_DELAY_SECONDS": "data_vendor_retry.base_delay_seconds",
    "TRADINGAGENTS_VENDOR_RETRY_MAX_RETRY_AFTER_SECONDS":
        "data_vendor_retry.max_retry_after_seconds",
    "TRADINGAGENTS_VENDOR_RETRY_JITTER_FRACTION": "data_vendor_retry.jitter_fraction",
    # Vendor circuit breaker. The section is validated by
    # dataflows.vendor_breaker on every route, so an enabled value that is not
    # a boolean, an unknown key or a non-positive threshold fails loudly there.
    "TRADINGAGENTS_VENDOR_BREAKER_ENABLED": "data_vendor_breaker.enabled",
    "TRADINGAGENTS_VENDOR_BREAKER_FAILURE_THRESHOLD": (
        "data_vendor_breaker.failure_threshold"
    ),
    "TRADINGAGENTS_VENDOR_BREAKER_COOLDOWN_SECONDS": (
        "data_vendor_breaker.cooldown_seconds"
    ),
    # Provider-specific reasoning/thinking knobs (None = each provider's own
    # default). Settable here for non-interactive runs; the CLI also offers an
    # interactive choice, which is skipped when the matching var is set.
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ``ValueError`` rather than silently falling back to a
    default — a misspelled boolean (e.g. ``treu``) or non-numeric int should fail
    loudly at startup, not quietly misconfigure an unattended run. Numeric
    strings must be finite: ``nan`` and ``inf`` (and a float where an attempt
    count is expected) are refused here, and again when the retry budget is
    built.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        text = value.strip()
        if not (text.isascii() and text.lstrip("+-").isdigit()):
            raise ValueError(f"expected a whole number, got {value!r}")
        return int(text)
    if isinstance(reference, float):
        try:
            parsed = float(value)
        except ValueError:
            raise ValueError(f"expected a number, got {value!r}") from None
        if not math.isfinite(parsed):
            raise ValueError(f"expected a finite number, got {value!r}")
        return parsed
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place.

    A key may address one level of a nested dict ("outer.inner"). An unknown
    nested key is added rather than rejected, because the overrides run while
    the very dict that defines those keys is being built; the type is then the
    one the same setting's flat siblings use.
    """
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        outer, _, inner = key.partition(".")
        if inner:
            section = config.setdefault(outer, {})
            reference = section.get(inner, 1.0)
        else:
            reference = config.get(key)
        try:
            value = _coerce(raw, reference)
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
        if inner:
            section[inner] = value
        else:
            config[key] = value
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.6",
    "quick_think_llm": "gpt-5.6-luna",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # SDK retry budget forwarded to every provider chat client. None leaves each
    # provider/SDK at its own default (usually 2). Raise it to ride out bursty
    # 429 throttling on rate-limited deployments instead of aborting a run (#1091).
    "llm_max_retries": None,
    # Cap on output tokens forwarded to every provider chat client. None leaves
    # each provider at its own default. Set it to bound a model that emits
    # unbounded reasoning/output and hangs or trips a gateway idle timeout
    # (e.g. some deepseek-v4-flash deployments, #1204).
    "max_tokens": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain — requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        "prediction_markets": "polymarket",  # Options: polymarket (keyless)
    },
    # Bounded retries owned by the routing layer (dataflows.interface). One tool
    # call shares these across its whole vendor chain; switching vendors does
    # not reset them. Counts are VENDOR-FUNCTION invocations, not HTTP requests:
    # one invocation may issue several (e.g. one per global-news query). Every
    # value is validated strictly -- a negative, boolean, fractional, NaN or
    # infinite value raises instead of being clamped.
    "data_vendor_retry": {
        # Max invocations of one vendor per tool call, first attempt included:
        # 1 means "never retry this vendor" (the total is exactly 1 request
        # attempt); 2 means "one retry" (2 attempts in total).
        "max_attempts": 2,
        # Optional per-vendor overrides of the above. Alpha Vantage is pinned to
        # a single attempt by default because its free tier is a narrow quota
        # and a failed call may still be metered; a retry is opt-in.
        "vendor_max_attempts": {"alpha_vantage": 1},
        # Max invocations of ALL vendors combined for one tool call.
        "max_total_attempts": 4,
        # Wall-clock budget for the whole chain, shared across vendors. Checked
        # before every start (first call, retry, vendor switch) and after every
        # wait; when it is spent no new request is started. Every
        # timeout-capable request gets the time left, never more. It is a
        # budget, not a hard promise: a client that accepts no timeout (e.g.
        # some yfinance attributes) can only be bounded by its own default.
        "max_total_seconds": 45.0,
        # Cap on any single HTTP request. A request's timeout is the time left
        # capped by this, and it never falls below it because of the cap alone;
        # when less than the minimum for a valid request is left, the request
        # is not started at all.
        "max_request_seconds": 15.0,
        # Cumulative cap on the retry waits the chain may take (sum of every
        # backoff/Retry-After wait). Distinct from max_retry_after_seconds,
        # which only decides whether ONE asked-for wait is worth taking.
        "max_cumulative_wait_seconds": 20.0,
        # Wait before a retry the vendor gave no Retry-After for, doubled each
        # attempt and reduced by up to jitter_fraction (never lengthened).
        "base_delay_seconds": 1.0,
        # A throttle that asks for a longer pause than this is not waited out:
        # the chain moves to the next vendor instead of stalling the run.
        # This is a per-wait threshold, not a cap on the total: the total is
        # max_cumulative_wait_seconds.
        "max_retry_after_seconds": 10.0,
        # Fraction of a self-chosen backoff that may be shaved off at random, to
        # spread concurrent retries (0 = deterministic). A server's Retry-After
        # is honoured exactly and is never shortened by jitter.
        "jitter_fraction": 0.2,
    },
    # Per-vendor circuit breaker, owned by the routing layer. Disabled by
    # default: with ``enabled: false`` nothing is acquired, no state is created
    # and routing behaves exactly as before. When enabled, a vendor that fails
    # for a *proven-momentary* reason on ``failure_threshold`` consecutive
    # logical calls is skipped for ``cooldown_seconds`` (not started, no HTTP
    # request, no attempt), then one probe decides whether it recovers.
    #
    # What counts as a failure is read from error metadata only: a short
    # throttle (429/502/503/504/timeout within ``max_retry_after_seconds``)
    # that the call did not recover from. Auth, refused requests, missing keys,
    # daily/monthly quotas, TLS/URL problems, parse bugs and the local retry
    # budget running out do *not* count. Keyed by vendor *and* endpoint *and*
    # these two settings, so all symbols of one endpoint share protection
    # while a different endpoint or policy keeps separate state. State is
    # in-process memory: it is kept across tool calls and never shared between
    # processes, and a restart clears it.
    "data_vendor_breaker": {
        "enabled": False,
        "failure_threshold": 3,
        "cooldown_seconds": 60.0,
    },
    # Market-analyst tool governance (opt-in, default OFF). An **analyst tool
    # allowance**: it caps how many tool rounds (one per batch the model asks
    # for) and executed calls the market analyst may spend before a single,
    # unbound wrap-up call writes ``market_report`` from the evidence already
    # collected. It is not a run-level budget and it does not count HTTP
    # requests or vendor attempts (that is the retry/breaker layer above).
    # Values are validated strictly: an unknown key, a non-boolean ``enabled``,
    # or a non-positive/non-integer cap raises instead of being clamped.
    "market_tool_governance": {
        "enabled": False,
        "max_rounds": 4,   # model->tools->model cycles for the market analyst
        "max_calls": 10,   # calls actually executed for the market analyst
    },
    # Fundamentals-analyst tool governance (opt-in, default OFF, independent of
    # the market section above). Same allowance rules; once the allowance is
    # spent a single unbound wrap-up call writes ``fundamentals_report`` from
    # the fundamental evidence already collected. Validated strictly.
    "fundamentals_tool_governance": {
        "enabled": False,
        "max_rounds": 4,   # model->tools->model cycles for the fundamentals analyst
        "max_calls": 8,    # calls actually executed for the fundamentals analyst
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    # Trading days after the analysis date over which a decision's outcome is
    # measured, for reflection and for the backtest figures.
    "holding_period_days": 5,
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})

"""REQ-WEB-003/013, FR-DDT-004, ADR-007: Web-only policy recovery isolation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from tradingagents.debate.config import (
    DEFAULT_DEBATE_TERMINATION_CONFIG,
    resolve_debate_termination_config,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph as CoreGraph


class WebAnalysisGraph(CoreGraph):
    """Reuse every core behavior; isolate checkpoints for custom debate policies."""

    def _run_signature(self, asset_type: str, portfolio=None) -> str:
        signature = super()._run_signature(asset_type, portfolio)
        policy = asdict(resolve_debate_termination_config(self.config))
        defaults = asdict(DEFAULT_DEBATE_TERMINATION_CONFIG)
        # Core already includes both round caps and portfolio/asset/analyst identity.
        comparable = {key: value for key, value in policy.items() if key != "max_debate_rounds"}
        baseline = {key: value for key, value in defaults.items() if key != "max_debate_rounds"}
        if comparable == baseline:
            return signature
        encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        return f"{signature}|web_debate_policy={digest}"

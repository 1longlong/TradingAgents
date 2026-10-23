"""Phase 3B offline tests for the ``debate_termination`` configuration group.

No network, no LLM. Covers type/range/cross-constraint validation, unknown-key
rejection, the legacy ``max_debate_rounds`` back-compat, Python 3.10
compatibility, and the disabled legacy fixed-round routing.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from tradingagents.debate.config import (
    DEFAULT_DEBATE_TERMINATION_CONFIG,
    DebateTerminationConfig,
    resolve_debate_termination_config,
)


class TestDefaults:
    def test_default_config_is_valid_and_frozen(self):
        cfg = DEFAULT_DEBATE_TERMINATION_CONFIG
        assert isinstance(cfg, DebateTerminationConfig)
        cfg.validate()  # must not raise
        with pytest.raises(FrozenInstanceError):
            cfg.enabled = False  # type: ignore[misc]

    def test_absent_group_uses_legacy_max_rounds(self):
        # The full legacy default is 1 round; an absent group must reproduce it.
        cfg = resolve_debate_termination_config({})
        assert cfg.max_debate_rounds == 1
        assert cfg.enabled is True

    def test_absent_group_equals_default_config(self):
        assert resolve_debate_termination_config(None) == DEFAULT_DEBATE_TERMINATION_CONFIG
        assert resolve_debate_termination_config({}) == DEFAULT_DEBATE_TERMINATION_CONFIG

    def test_legacy_top_level_max_rounds_is_honoured_when_group_absent(self):
        cfg = resolve_debate_termination_config({"max_debate_rounds": 5})
        assert cfg.max_debate_rounds == 5

    def test_group_max_rounds_overrides_legacy_top_level(self):
        cfg = resolve_debate_termination_config(
            {"max_debate_rounds": 5, "debate_termination": {"max_debate_rounds": 7}}
        )
        assert cfg.max_debate_rounds == 7


class TestValidation:
    def test_enabled_must_be_bool(self):
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"enabled": "yes"})  # type: ignore[arg-type]

    def test_no_new_evidence_patience_must_be_positive_int(self):
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"no_new_evidence_patience": 0})
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"no_new_evidence_patience": -1})
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"no_new_evidence_patience": 1.5})  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"no_new_evidence_patience": True})  # type: ignore[arg-type]

    def test_stance_distance_threshold_range(self):
        for bad in (-0.1, 4.1, "x"):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"stance_distance_threshold": bad})
        cfg = DebateTerminationConfig.from_dict({"stance_distance_threshold": 2})
        assert cfg.stance_distance_threshold == 2

    def test_confidence_delta_threshold_range(self):
        for bad in (-0.1, 1.1, "x", True):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"confidence_delta_threshold": bad})
        cfg = DebateTerminationConfig.from_dict({"confidence_delta_threshold": 0.5})
        assert cfg.confidence_delta_threshold == 0.5

    @pytest.mark.parametrize("field", ["max_calls", "max_tokens"])
    def test_positive_int_limits(self, field):
        for bad in (0, -1, "x", True):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({field: bad})

    def test_max_time_positive_number(self):
        for bad in (0, -1, "x", True):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"max_time": bad})

    def test_reserved_and_estimate_non_negative(self):
        for bad in (-1, True, "x"):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"reserved_summary_tokens": bad})
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"next_round_estimate_tokens": bad})
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"reserved_summary_seconds": bad})
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"next_round_estimate_seconds": bad})

    def test_max_debate_rounds_positive_int(self):
        for bad in (0, -1, True, 1.5, "x"):  # type: ignore[arg-type]
            with pytest.raises(ValueError):
                DebateTerminationConfig.from_dict({"max_debate_rounds": bad})

    def test_reserve_must_not_consume_whole_budget(self):
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict(
                {"max_tokens": 100, "reserved_summary_tokens": 100}
            )
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict(
                {"max_time": 60, "reserved_summary_seconds": 60}
            )
        # Exactly the boundary is fine: reserve must be strictly less than max.
        cfg = DebateTerminationConfig.from_dict(
            {"max_tokens": 100, "reserved_summary_tokens": 99}
        )
        assert cfg.reserved_summary_tokens == 99

    def test_empty_field_strings_rejected(self):
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"evidence_manifest_field": ""})
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict({"trace_field": ""})

    def test_python_310_compatible_types(self):
        # No PEP 695 ``X | Y`` in signatures that 3.10 would reject at def time;
        # the module imports cleanly and the config builds under 3.10 semantics.
        cfg = DebateTerminationConfig.from_dict(
            {"max_debate_rounds": 4, "enabled": True}
        )
        assert cfg.max_debate_rounds == 4
        # ``dict[str, ...]`` generics on a 3.10 interpreter still evaluate fine
        # under ``from __future__ import annotations``.
        assert isinstance(cfg.to_root_config(), dict)


class TestUnknownKeys:
    def test_unknown_group_key_rejected(self):
        with pytest.raises(ValueError, match="unknown key"):
            resolve_debate_termination_config({"debate_termination": {"bogus": 1}})

    def test_unknown_key_rejected_by_from_dict(self):
        with pytest.raises(ValueError, match="unknown key"):
            DebateTerminationConfig.from_dict({"not_a_field": True})

    def test_non_dict_group_rejected(self):
        for bad in ("x", 5, ["a"], (True,)):
            with pytest.raises(ValueError):
                resolve_debate_termination_config({"debate_termination": bad})

    def test_non_dict_from_dict_rejected(self):
        with pytest.raises(ValueError):
            DebateTerminationConfig.from_dict(["a"])  # type: ignore[arg-type]


class TestLegacyDisabledRouting:
    """``enabled=False`` must preserve the legacy fixed-round route."""

    def _disabled(self, max_rounds: int = 1) -> DebateTerminationConfig:
        return DebateTerminationConfig.from_dict(
            {"enabled": False, "max_debate_rounds": max_rounds}
        )

    def test_round_1_not_reached_continues_to_bull(self):
        from tradingagents.debate.evaluator_node import (
            RULE_DISABLED_FIXED,
            _disabled_round_decision,
        )
        from tradingagents.debate.models import DebateRoute, StopReason

        decision = _disabled_round_decision({"count": 1}, self._disabled(1))
        assert decision.route == DebateRoute.CONTINUE
        assert decision.stop_reason == StopReason.CONTINUE_FOR_NEW_EVIDENCE
        assert decision.next_speaker == "Bull"
        assert decision.trace[0].rule == RULE_DISABLED_FIXED

    def test_round_limit_reached_summarizes_max_rounds(self):
        from tradingagents.debate.evaluator_node import _disabled_round_decision
        from tradingagents.debate.models import DebateRoute, StopReason

        # 2 * max_debate_rounds == 2 turns == 1 round completed.
        decision = _disabled_round_decision({"count": 2}, self._disabled(1))
        assert decision.route == DebateRoute.SUMMARIZE
        assert decision.stop_reason == StopReason.MAX_ROUNDS_REACHED
        assert decision.next_speaker == ""

    @pytest.mark.parametrize("count,max_rounds,expected_route", [
        (0, 1, "continue"),
        (1, 1, "continue"),
        (2, 1, "summarize"),
        (3, 1, "summarize"),
        (5, 3, "continue"),
        (6, 3, "summarize"),
        (7, 3, "summarize"),
    ])
    def test_fixed_count_threshold(self, count, max_rounds, expected_route):
        from tradingagents.debate.evaluator_node import _disabled_round_decision

        decision = _disabled_round_decision({"count": count}, self._disabled(max_rounds))
        assert decision.route.value == expected_route

    def test_disabled_node_writes_no_metrics(self):
        from tradingagents.debate.evaluator_node import create_debate_evaluator_node

        node = create_debate_evaluator_node(config=self._disabled(1))
        state = {
            "investment_debate_state": {"count": 2, "turns": []},
        }
        out = node(state)
        decision = out["debate_termination_decision"]
        assert decision["route"] == "summarize"
        assert decision["stop_reason"] == "max_rounds_reached"
        # Disabled mode reproduces the legacy count route without appending metrics.
        assert out["investment_debate_state"].get("round_metrics", []) == []

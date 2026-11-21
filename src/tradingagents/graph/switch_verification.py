"""Verify that a built graph actually consumed the switches its spec declared.

The failure this guards against
-------------------------------
A spec can say ``single_pass: true`` while the graph that actually runs was
built with ``single_pass: false``. Nothing in the normal run path would notice:
the run completes, the telemetry is written, and the arm is silently mislabelled
in the results. Because the whole experiment is a 2x2 comparison, a silently
mislabelled arm is worse than a missing one.

How it works
------------
``GraphSetup`` receives the switches through ``self.config`` and passes the
derived booleans to the analyst factories as keyword arguments, and to the news
``ToolNode`` as bound tools. This module intercepts those calls and compares
what was *asked for* against what was actually *passed*.

Two facts are easy to get wrong, and both are pinned by tests:

1. ``GraphSetup`` binds its analyst factories into **its own module globals** at
   import time, so the interception must patch ``tradingagents.graph.setup``
   (see V1 ``REMEDIATION.md`` REM-1). Patching ``tradingagents.agents`` has no
   effect on what the graph calls.
2. ``GraphSetup`` computes ``single_pass AND structured``, so an arm declaring
   ``single_pass=true, structured=false`` runs with single-pass OFF. The
   comparison must therefore be against the AND, not against ``single_pass``
   alone (REM-4).

A consumer that was never called is an error, not a skip: an analyst whose
switch was never observed proves nothing (REM-R2-3).
"""

from __future__ import annotations

from typing import Any

#: Config key behind each switch.
SWITCH_CONFIG_KEYS = {
    "batch_macro": "batch_macro_enabled",
    "structured": "structured_analyst_output_enabled",
    "single_pass": "single_pass_finalization_enabled",
    "s2_downstream": None,  # declared only; no implementation
}

#: Analyst name -> the switch(es) its factory receives.
ANALYST_CONSUMERS = {
    "market": ("structured", "single_pass"),
    "news": ("batch_macro", "structured", "single_pass"),
    "fundamentals": ("structured", "single_pass"),
}

#: All switches an arm can declare.
ALL_SWITCHES = tuple(SWITCH_CONFIG_KEYS)


class SwitchNotConsumed(RuntimeError):
    """The graph did not consume the switches the spec declared."""


def _require_bool(switches: dict, name: str) -> bool:
    if name not in switches:
        raise SwitchNotConsumed(f"spec is missing switch {name!r}")
    value = switches[name]
    # A truthy string such as "yes" would pass a bare ``==`` comparison against
    # True in a sloppy implementation; require a real bool.
    if not isinstance(value, bool):
        raise SwitchNotConsumed(
            f"switch {name!r} must be a bool, got {type(value).__name__} {value!r}"
        )
    return value


def validate_spec_switches(switches: dict) -> None:
    """Reject a spec whose declared switches are not usable as declared."""
    for name in ALL_SWITCHES:
        _require_bool(switches, name)
    if switches["s2_downstream"] is not True:
        raise SwitchNotConsumed(
            "switch 's2_downstream' has no OFF implementation; refusing to run it "
            "as if it were disabled"
        )


def expected_analyst_kwargs(switches: dict) -> dict[str, dict[str, bool]]:
    """What ``GraphSetup`` must pass to each analyst, derived from the spec."""
    validate_spec_switches(switches)
    structured = switches["structured"]
    return {
        "market": {"structured": structured,
                   "single_pass": switches["single_pass"] and structured},
        "news": {"batch_macro": switches["batch_macro"],
                 "structured": structured,
                 "single_pass": switches["single_pass"] and structured},
        "fundamentals": {"structured": structured,
                         "single_pass": switches["single_pass"] and structured},
    }


def verify_switches_consumed(
    switches: dict,
    *,
    observed: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Compare declared switches against the kwargs the graph really used.

    ``observed`` maps analyst name -> the kwargs actually passed to its factory.
    Every consumer in :data:`ANALYST_CONSUMERS` that the spec asked for must be
    present; a missing consumer raises rather than passing vacuously.

    Raises :class:`SwitchNotConsumed` on any mismatch.
    """
    wanted = expected_analyst_kwargs(switches)
    if observed is None:
        raise SwitchNotConsumed(
            "no switch consumers were captured; refusing to report a vacuous pass"
        )

    for analyst, expected in wanted.items():
        if analyst == "social":
            continue
        if analyst not in observed:
            raise SwitchNotConsumed(
                f"analyst {analyst!r} was never constructed, so its switches "
                "were not consumed"
            )
        if not isinstance(observed[analyst], dict):
            raise SwitchNotConsumed(
                f"analyst {analyst!r} consumer record is not a mapping"
            )
        for key, value in expected.items():
            if key not in observed[analyst]:
                raise SwitchNotConsumed(
                    f"analyst {analyst!r} did not receive switch {key!r}"
                )
            got = observed[analyst][key]
            if not isinstance(got, bool):
                raise SwitchNotConsumed(
                    f"analyst {analyst!r} received non-bool {key}={got!r}"
                )
            if got is not value:
                raise SwitchNotConsumed(
                    f"analyst {analyst!r} not consumed as specified: "
                    f"{key} expected {value}, got {got}"
                )


def consume_switches_from_setup(graph_setup) -> dict[str, dict[str, Any]]:
    """Read back what a constructed ``GraphSetup`` derived from its config.

    ``GraphSetup.setup_graph`` builds the per-analyst lambdas locally, so there
    is no attribute to read and the factories cannot be intercepted from here.
    The derivation itself is short and lives at one place
    (``tradingagents/graph/setup.py``); this mirrors it so the run path can
    compare *what the graph will pass* against *what the arm declares*.

    The two facts that make a naive mirror wrong are pinned by tests
    (``tests/test_switch_consumption.py``): ``single_pass`` is the AND with
    ``structured``, and ``batch_macro`` is only passed to the news analyst.

    Mirroring is acceptable for a fail-closed check but it is **not** proof that
    ``setup.py`` still computes what this function assumes. That proof is the
    interceptor test that drives the real ``GraphSetup``; if ``setup.py`` drifts,
    that test fails and this function must be updated with it.
    """
    config = graph_setup.config
    structured = bool(config.get("structured_analyst_output_enabled", True))
    single_pass = bool(config.get("single_pass_finalization_enabled", False)) and structured
    batch_macro = bool(config.get("batch_macro_enabled", True))
    return {
        "market": {"structured": structured, "single_pass": single_pass},
        "news": {"batch_macro": batch_macro, "structured": structured,
                 "single_pass": single_pass},
        "fundamentals": {"structured": structured, "single_pass": single_pass},
    }


def verify_news_toolnode(switches: dict, bound_tools: set[str]) -> None:
    """The batch-macro switch must govern the news analyst's tool binding."""
    validate_spec_switches(switches)
    batch_tool = "get_macro_indicators_batch"
    if switches["batch_macro"]:
        if batch_tool not in bound_tools:
            raise SwitchNotConsumed(
                f"batch_macro=True but the news analyst was not given {batch_tool}"
            )
    elif batch_tool in bound_tools:
        raise SwitchNotConsumed(
            f"batch_macro=False but the news analyst was given {batch_tool}"
        )

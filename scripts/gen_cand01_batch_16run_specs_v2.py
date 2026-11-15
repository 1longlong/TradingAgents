#!/usr/bin/env python
"""Generate the CAND-01 x Batch-Macro 2x2 16-run spec set (protocol V2).

Why this file exists
--------------------
The V1 generator (``scripts/gen_cand01_batch_16run_specs.py``) was never
committed and was lost; it is not recoverable from any ref, stash, bundle or
backup of this repository. The 16 V1 specs are still on disk, but the function
that produced them (and therefore the only definition of their
``config_sha256``) is gone. Hand-editing those specs would violate the
pre-registration rule, so the experiment is **re-registered** as V2: a new,
fully self-describing generator whose hash algorithm is documented, tested and
reproducible.

The generator is deliberately dependency-free (stdlib only) so that it can be
run from any checkout, and it is *deterministic*: the same definition file and
the same seed always produce byte-identical specs.

What it writes
--------------
Under ``--out`` (a fresh, empty directory)::

    experiment.json            round-level description (not itself runnable)
    specs/<RUN_ID>/experiment.json   per-run experiment definition
    specs/<RUN_ID>/spec.json         the run spec the child is handed
    specs/<RUN_ID>/code_state.json   provenance of the generating state
    SWITCH_MATRIX.csv          one row per run: the four switches
    RUN_MANIFEST_TEMPLATE.csv  one row per run: identity, order, switches, hashes
    CONFIG_HASH_MANIFEST.csv   one row per run: the full config_sha256
    EXECUTION_ORDER.txt        the randomised order, with its generator

Exit codes: 0 ok, 2 refused (bad definition / unsupported switch / non-empty out).

Usage
-----
    python scripts/gen_cand01_batch_16run_specs_v2.py --out <dir>
    python scripts/gen_cand01_batch_16run_specs_v2.py --out <dir> --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- the frozen experiment definition ---------------------------------------
#
# Every design fact here is recovered from the surviving V1 artefacts:
#   * ``cand01_batch_16run/generated/experiment.json``      -- arms, cases, seed
#   * ``cand01_batch_16run/CAND01_BATCH_2X2_PROTOCOL.md`` §4.3-§4.5
#   * ``generated/specs/R01_NVDA_C0/spec.json``             -- per-run shape
# Nothing below may drift without re-registering a new protocol version.

SCHEMA_VERSION = 2
EXPERIMENT_ID = "cand01_batch_2x2_16run_v2"
PROTOCOL_VERSION = "V2"

SEED = 20261114
BLOCKS = ("NVDA", "AAPL", "JPM", "XOM")
ARMS = ("B", "AB", "C0", "CC")

#: The 2x2 design. ``s2_downstream`` is declared but has no implementation in
#: the product code; see ``require_supported_switches``.
ARM_SWITCHES = {
    "B":  {"batch_macro": False, "single_pass": False, "structured": True,  "s2_downstream": True},
    "AB": {"batch_macro": True,  "single_pass": False, "structured": True,  "s2_downstream": True},
    "C0": {"batch_macro": False, "single_pass": True,  "structured": True,  "s2_downstream": True},
    "CC": {"batch_macro": True,  "single_pass": True,  "structured": True,  "s2_downstream": True},
}

#: Switches the product code actually consumes, mapped to the env var that
#: delivers them to the child (see ``tradingagents/default_config.py``).
SWITCH_ENV_VARS = {
    "batch_macro": "TRADINGAGENTS_BATCH_MACRO_ENABLED",
    "single_pass": "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED",
    "structured": "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED",
}

#: Switches that are recorded for completeness but have no OFF implementation.
UNSUPPORTED_SWITCHES = {"s2_downstream"}

TRADE_DATE = "2026-09-23"
ANALYSTS = ["market", "news", "fundamentals"]
RESEARCH_ROUNDS = 1
RISK_ROUNDS = 1
OUTPUT_LANGUAGE = "English"
CACHE_POLICY = "preserve_existing"
CHECKPOINT_ENABLED = False
MAX_TOTAL_TOKENS = None
PROVIDER = "openai_compatible"
QUICK_MODEL = "CS5351/DeepSeek-V4-Flash"
DEEP_MODEL = "CS5351/DeepSeek-V4-Flash"

#: Finnhub-only news scope. Recorded in the definition so the specs cannot be
#: regenerated against a different news configuration without the hash moving.
NEWS_SCOPE = {
    "company_news": "finnhub",
    "global_news": "finnhub:CONFIG_DISABLED",
    "gdelt": "excluded",
}

#: ``config_sha256`` hashes exactly these keys of the per-run experiment
#: definition. Excluded on purpose: ``config_sha256`` itself (it cannot hash
#: itself), ``description`` (prose, not configuration), ``results_dir``-derived
#: fields and any absolute path (machine-specific by construction).
HASHED_FIELDS = (
    "experiment_id",
    "schema_version",
    "switches_required",
    "provider",
    "quick_model",
    "deep_model",
    "output_language",
    "cache_policy",
    "checkpoint_enabled",
    "budget",
    "cases",
    "switches",
    "news_scope",
)


class RefusedError(RuntimeError):
    """Raised when the definition asks for something the code cannot honour."""


# --- hashing -----------------------------------------------------------------


def canonical_json(obj) -> str:
    """The one canonical serialisation used for every hash in this module.

    UTF-8, keys sorted, no insignificant whitespace, ``ensure_ascii=False`` so
    non-ASCII text hashes as its real characters rather than escapes.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def config_sha256(experiment: dict) -> str:
    """SHA-256 over the frozen subset of a per-run experiment definition.

    The algorithm is part of the protocol:

    ==============  =====================================================
    Input           the fields named in :data:`HASHED_FIELDS`
    Encoding        UTF-8
    Serialisation   ``json.dumps(..., sort_keys=True, ensure_ascii=False,
                    separators=(",", ":"))``
    Digest          lowercase hex SHA-256
    Excluded        ``config_sha256`` itself, ``description``, absolute paths
    ==============  =====================================================

    Because the field list is frozen, adding a non-configuration key to the
    definition cannot change the hash, and changing any configuration key
    always does.
    """
    unknown = set(HASHED_FIELDS) - set(experiment)
    if unknown:
        raise KeyError(f"missing hashed field(s): {sorted(unknown)}")
    subset = {key: experiment[key] for key in HASHED_FIELDS}
    return hashlib.sha256(canonical_json(subset).encode("utf-8")).hexdigest()


def spec_body_sha256(spec: dict) -> str:
    """SHA-256 of a run spec minus the machine-specific ``results_dir``.

    Two roots on two machines produce the same ``spec_body_sha256`` for the same
    run; they never share ``spec_sha256`` or ``results_dir``.
    """
    body = {k: v for k, v in spec.items() if k != "results_dir"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- design ------------------------------------------------------------------


def execution_order(seed: int = SEED) -> dict[str, list[str]]:
    """The pre-registered within-block arm order.

    One ``random.Random(seed)`` is created **once**; ``shuffle`` is then called
    once per block, with blocks visited in :data:`BLOCKS` order. The algorithm is
    Python's Mersenne Twister via the stdlib ``random`` module; reproducing the
    order requires the same stdlib (CPython >= 3.11, whose ``shuffle`` is
    stable). This is asserted by ``tests/test_cand01_batch_16run_v2_infra.py``.
    """
    rng = random.Random(seed)
    order = {}
    for block in BLOCKS:
        arms = list(ARMS)
        rng.shuffle(arms)
        order[block] = arms
    return order


def run_ids(order: dict[str, list[str]]) -> list[dict]:
    """Assign ``Rnn`` in execution order: id ``nn`` == execution position ``nn``."""
    runs = []
    for block in BLOCKS:
        for arm in order[block]:
            runs.append({
                "run_id": f"R{len(runs) + 1:02d}",
                "position": len(runs) + 1,
                "ticker": block,
                "arm": arm,
            })
    return runs


def require_supported_switches(switches: dict) -> None:
    """Refuse a definition that turns off a switch with no OFF implementation.

    ``s2_downstream=False`` is not implemented in the product code. Silently
    running it as ``True`` would relabel the arm, so this refuses instead. The
    same rule applies to any key of :data:`UNSUPPORTED_SWITCHES`.
    """
    for name in UNSUPPORTED_SWITCHES:
        if name in switches and not switches[name]:
            raise RefusedError(
                f"switch {name!r} has no OFF implementation in the product code; "
                "refusing to generate a spec that would silently run it as ON"
            )


def case_for(ticker: str) -> dict:
    return {
        "case_id": f"{ticker.lower()}_{TRADE_DATE.replace('-', '_')}",
        "ticker": ticker,
        "trade_date": TRADE_DATE,
        "analysts": list(ANALYSTS),
        "research_rounds": RESEARCH_ROUNDS,
        "risk_rounds": RISK_ROUNDS,
    }


def per_run_experiment(run: dict) -> dict:
    """One run's experiment definition, before ``config_sha256`` is added."""
    switches = dict(ARM_SWITCHES[run["arm"]])
    require_supported_switches(switches)
    definition = {
        "experiment_id": run["run_id"],
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "switches_required": True,
        "provider": PROVIDER,
        "quick_model": QUICK_MODEL,
        "deep_model": DEEP_MODEL,
        "output_language": OUTPUT_LANGUAGE,
        "cache_policy": CACHE_POLICY,
        "checkpoint_enabled": CHECKPOINT_ENABLED,
        "budget": {"max_total_tokens": MAX_TOTAL_TOKENS},
        "cases": [case_for(run["ticker"])],
        "switches": switches,
        "news_scope": dict(NEWS_SCOPE),
        "measured_runs": 1,
        "description": (
            f"CAND-01 x batch-macro 2x2, arm {run['arm']} on {run['ticker']} "
            f"(execution position {run['position']}); protocol {PROTOCOL_VERSION}"
        ),
    }
    definition["config_sha256"] = config_sha256(definition)
    return definition


def _experiment_root(out_root: Path | None = None) -> str:
    """The repository root the generated specs belong to.

    Anchored on this generator's own location (``<repo>/scripts/...``), not on
    ``out_root``: ``--out`` may point anywhere, so a depth relative to it would
    pin the guard to the wrong directory. If ``out_root`` is inside a
    repository it must be *this* one, otherwise the specs would be registered
    against a tree that is not the tree that generated them.
    """
    root = Path(__file__).resolve().parents[1]
    if not (root / "tradingagents").is_dir():
        raise RefusedError(
            f"generator is not inside a repository root: {root} has no "
            f"tradingagents/ package"
        )
    if out_root is not None:
        out = Path(out_root).resolve()
        if (out / "tradingagents").is_dir() and out != root:
            raise RefusedError(
                f"--out {out} is a different repository than {root}; refusing "
                f"to register specs against another checkout"
            )
    return str(root)


def run_spec(run: dict, experiment: dict, out_root: Path) -> dict:
    """The spec handed to the child, mirroring ``token_benchmark.prepare_run_spec``.

    The field set is the Harness's own plus the two additions the experiment
    needs: ``switches`` (so the child can verify what it was asked to run) and
    ``config_sha256`` (so the child can verify nothing drifted).
    """
    case = experiment["cases"][0]
    run_dir = (
        out_root / "specs" / f"{run['run_id']}_{run['ticker']}_{run['arm']}"
        / "runs" / "run_01" / "attempt_01"
    )
    return {
        "experiment_id": run["run_id"],
        "case": case,
        "provider": experiment["provider"],
        "quick_model": experiment["quick_model"],
        "deep_model": experiment["deep_model"],
        "output_language": experiment["output_language"],
        "cache_policy": experiment["cache_policy"],
        "results_dir": str(
            run_dir / "runtime" / run["ticker"] / case["trade_date"]
        ),
        "run_index": 1,
        # The tree this spec was registered against. ``_run_single`` refuses a
        # run whose imported ``tradingagents`` is not under it.
        "experiment_root": _experiment_root(out_root),
        "switches": experiment["switches"],
        "switches_source": "declared",
        # The declared news scope travels with the spec so the child can refuse
        # a run whose provider set is not the frozen Finnhub-only one. It is
        # already part of the hashed definition, so adding it here does not
        # move ``config_sha256``.
        "news_scope": experiment["news_scope"],
        "config_sha256": experiment["config_sha256"],
    }


def code_state(experiment_sha: str) -> dict:
    """Provenance of the checkout that produced the specs (no secrets)."""
    root = Path(__file__).resolve().parent.parent
    now = datetime.now(timezone.utc).isoformat()

    def _git(*args):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, check=False,
            )
            return out.stdout.strip() or None
        except OSError:  # pragma: no cover - git always present in practice
            return None

    try:
        rel = str(Path(__file__).resolve().relative_to(root))
    except ValueError:  # pragma: no cover
        rel = str(Path(__file__).resolve())

    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # "Dirty" means the *code* differs from HEAD, which is exactly what the
    # gate means by it (`git diff --binary`). Counting untracked files made the
    # flag permanently true in this worktree, where ~19MB of historical
    # experiment evidence is deliberately untracked, so the delivered record
    # said "dirty" for a tree the gate accepts as clean -- a contradiction a
    # reader would read as "generated from uncommitted code".
    diff = subprocess.run(["git", "-C", str(root), "diff", "--binary"],
                          capture_output=True, text=True, check=False)
    dirty = bool(diff.stdout.strip())
    # A delivered artefact that names a checkout must name the checkout that
    # *produced it*, not whatever tree happens to be checked out when someone
    # re-runs `--check` -- and it must not imply the specs were generated under
    # the frozen commit when they were generated before the freeze. Audit C-02
    # found these files still carrying the RC1 parent commit and a dirty flag
    # with no explanation, which read as "generated from unfrozen code". The
    # commit recorded is therefore explicit about the relationship.
    frozen_file = root / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/c3/FROZEN_COMMIT"
    frozen = None
    if frozen_file.is_file():
        text = frozen_file.read_text(encoding="utf-8").strip()
        if text:
            frozen = text
    # "Precedes" is a claim about ancestry, not about inequality. Comparing the
    # two hashes for equality and calling every difference "precedes" labelled a
    # commit that is a *descendant* of the freeze as though it came before it --
    # Audit A round 4 (H-D) found all 16 delivered files saying so. Ask git.
    def _is_ancestor(older: str, newer: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    if not head:
        head_relation = "unknown"
    elif frozen and head == frozen:
        head_relation = "is_frozen_commit"
    elif frozen and _is_ancestor(head, frozen):
        head_relation = "precedes_frozen_commit"
    elif frozen and _is_ancestor(frozen, head):
        head_relation = "follows_frozen_commit"
    elif frozen:
        head_relation = "unrelated_to_frozen_commit"
    else:
        head_relation = "unfrozen"
    return {
        "schema_version": 1,
        "phase": "spec_generation",
        "timestamp_utc": now,
        "generator": rel,
        "generator_sha256": file_sha256(Path(__file__).resolve()),
        "experiment_definition_sha256": experiment_sha,
        "git_head_commit": head,
        "git_branch": branch,
        "git_working_tree_dirty": dirty,
        "git_head_relation_to_freeze": head_relation,
        "frozen_commit": frozen,
        "python_version": sys.version.split()[0],
    }


# --- csv helpers -------------------------------------------------------------


def _csv(rows: list[dict], columns: list[str]) -> str:
    def cell(value):
        text = "" if value is None else str(value)
        return f'"{text}"' if any(c in text for c in ',"\n') else text

    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(cell(row.get(c)) for c in columns))
    return "\n".join(lines) + "\n"


# --- generation --------------------------------------------------------------


def build(out_root: Path) -> dict[str, str]:
    """Build every artefact in memory; return ``relative path -> content``."""
    order = execution_order()
    runs = run_ids(order)

    # Guard rails the protocol depends on.
    ids = [r["run_id"] for r in runs]
    if len(set(ids)) != 16:  # pragma: no cover - structural
        raise RefusedError("run IDs are not unique")
    cells = [(r["ticker"], r["arm"]) for r in runs]
    if len(set(cells)) != 16:  # pragma: no cover - structural
        raise RefusedError("the 4x4 design does not cover every cell exactly once")
    for block in BLOCKS:
        if len([r for r in runs if r["ticker"] == block]) != len(ARMS):
            raise RefusedError(f"block {block} does not have all four arms")

    experiments = {r["run_id"]: per_run_experiment(r) for r in runs}
    hashes = [e["config_sha256"] for e in experiments.values()]
    if len(set(hashes)) != 16:
        raise RefusedError("config_sha256 values are not distinct across runs")

    artifacts: dict[str, str] = {}

    round_experiment = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "description": (
            "CAND-01 x batch-macro 2x2: 4 stocks x 4 arms, one measured run each. "
            "Per-run definitions are in specs/<run_id>/experiment.json."
        ),
        "switches_required": True,
        "arms": {arm: dict(sw) for arm, sw in ARM_SWITCHES.items()},
        "block_order": list(BLOCKS),
        "cases": [case_for(t) for t in BLOCKS],
        "seed": SEED,
        "randomisation": (
            "one random.Random(seed); shuffle(['B','AB','C0','CC']) once per block "
            "in BLOCKS order (CPython stdlib random, Mersenne Twister)"
        ),
        "measured_runs": 1,
        "provider": PROVIDER,
        "quick_model": QUICK_MODEL,
        "deep_model": DEEP_MODEL,
        "output_language": OUTPUT_LANGUAGE,
        "cache_policy": CACHE_POLICY,
        "checkpoint_enabled": CHECKPOINT_ENABLED,
        "budget": {"max_total_tokens": MAX_TOTAL_TOKENS},
        "news_scope": dict(NEWS_SCOPE),
        "per_run_definitions": "specs/<run_id>/experiment.json",
    }
    artifacts["experiment.json"] = json.dumps(round_experiment, indent=2, sort_keys=True) + "\n"

    definition_sha = hashlib.sha256(
        canonical_json({k: experiments[k] for k in sorted(experiments)}).encode("utf-8")
    ).hexdigest()
    state = code_state(definition_sha)
    state_text = json.dumps(state, indent=2, sort_keys=True) + "\n"

    for run in runs:
        rid = run["run_id"]
        directory = f"specs/{rid}_{run['ticker']}_{run['arm']}"
        experiment = experiments[rid]
        spec = run_spec(run, experiment, out_root)
        artifacts[f"{directory}/experiment.json"] = (
            json.dumps(experiment, indent=2, sort_keys=True) + "\n"
        )
        artifacts[f"{directory}/spec.json"] = (
            json.dumps(spec, indent=2, sort_keys=True) + "\n"
        )
        artifacts[f"{directory}/code_state.json"] = state_text

    switch_rows, template_rows, hash_rows = [], [], []
    for run in runs:
        experiment = experiments[run["run_id"]]
        sw = experiment["switches"]
        spec = run_spec(run, experiment, out_root)
        directory = f"specs/{run['run_id']}_{run['ticker']}_{run['arm']}"
        switch_rows.append({
            "run_id": run["run_id"],
            "position": run["position"],
            "ticker": run["ticker"],
            "arm": run["arm"],
            "batch_macro": sw["batch_macro"],
            "single_pass": sw["single_pass"],
            "structured": sw["structured"],
            "s2_downstream": sw["s2_downstream"],
        })
        template_rows.append({
            "run_id": run["run_id"],
            "position": run["position"],
            "block": run["ticker"],
            "arm": run["arm"],
            "trade_date": TRADE_DATE,
            "batch_macro": sw["batch_macro"],
            "single_pass": sw["single_pass"],
            "structured": sw["structured"],
            "s2_downstream": sw["s2_downstream"],
            "config_sha256": experiment["config_sha256"],
            "spec_body_sha256": spec_body_sha256(spec),
            "spec_path": f"{directory}/spec.json",
            "experiment_path": f"{directory}/experiment.json",
        })
        hash_rows.append({
            "run_id": run["run_id"],
            "block": run["ticker"],
            "arm": run["arm"],
            "config_sha256": experiment["config_sha256"],
        })

    artifacts["SWITCH_MATRIX.csv"] = _csv(
        switch_rows,
        ["run_id", "position", "ticker", "arm",
         "batch_macro", "single_pass", "structured", "s2_downstream"],
    )
    artifacts["RUN_MANIFEST_TEMPLATE.csv"] = _csv(
        template_rows,
        ["run_id", "position", "block", "arm", "trade_date", "batch_macro",
         "single_pass", "structured", "s2_downstream", "config_sha256",
         "spec_body_sha256", "spec_path", "experiment_path"],
    )
    artifacts["CONFIG_HASH_MANIFEST.csv"] = _csv(
        hash_rows, ["run_id", "block", "arm", "config_sha256"],
    )
    artifacts["EXECUTION_ORDER.txt"] = (
        f"seed = {SEED}\n"
        f"generator = random.Random({SEED}) once; "
        f"shuffle(['B','AB','C0','CC']) once per block in order "
        f"{list(BLOCKS)}\n"
        f"algorithm = CPython stdlib random.shuffle (Mersenne Twister)\n"
        f"protocol = {PROTOCOL_VERSION}\n\n"
        + "\n".join(f"{b}: {order[b]}" for b in BLOCKS)
        + "\n"
    )
    return artifacts


def write_artifacts(out_root: Path, artifacts: dict[str, str]) -> list[Path]:
    written = []
    for rel, content in sorted(artifacts.items()):
        path = out_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def ensure_writable_out_dir(out_root: Path) -> None:
    """Refuse to write into a directory that already holds generated output.

    The first version of this guard only looked for ``experiment.json``, so a
    directory that already contained ``specs/R01…/spec.json`` but not that one
    file was silently overwritten (independent audit B4). Any of the generator's
    own top-level artefacts, or a non-empty ``specs/`` tree, is enough to refuse:
    every one of them is evidence that a previous registration exists.
    """
    out_root = Path(out_root)
    markers = ("experiment.json", "SWITCH_MATRIX.csv", "CONFIG_HASH_MANIFEST.csv",
               "RUN_MANIFEST_TEMPLATE.csv", "EXECUTION_ORDER.txt")
    present = [name for name in markers if (out_root / name).exists()]
    specs_dir = out_root / "specs"
    if specs_dir.exists() and any(specs_dir.iterdir()):
        present.append("specs/")
    if present:
        raise RefusedError(
            f"refusing to overwrite existing artefacts in {out_root} "
            f"(found {', '.join(present)})"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, type=Path,
                        help="output directory; must not already contain specs/")
    parser.add_argument("--check", action="store_true",
                        help="build in memory and compare against --out")
    args = parser.parse_args(argv)

    out_root = args.out.resolve()
    if not args.check:
        try:
            ensure_writable_out_dir(out_root)
        except RefusedError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2

    try:
        artifacts = build(out_root)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.check:
        drift = []
        volatile_drift: list[str] = []
        for rel, content in artifacts.items():
            path = out_root / rel
            if not path.exists():
                drift.append(f"missing: {rel}")
                continue
            if rel.endswith("code_state.json"):
                # ``timestamp_utc`` and the dirty-tree flag are properties of
                # *when* the generation ran, and ``generator_sha256`` is a
                # property of the generator *file* — so editing the generator
                # legitimately changes it while every hash-bearing artefact
                # (specs, matrices, manifests) stays byte-identical. ``--check``
                # reports these as ``volatile`` lines and does not fail on them;
                # a real drift in any other field still fails the check.
                #
                # ``git_head_commit`` and ``git_branch`` are the same kind of
                # property: they record the checkout that generated the specs.
                # Every later commit moves HEAD, so treating them as stable made
                # ``--check`` fail on every tree that is not the registration
                # commit -- which is every clean checkout (audit B-03).
                current = json.loads(path.read_text(encoding="utf-8"))
                fresh = json.loads(content)
                volatile = {"timestamp_utc", "git_working_tree_dirty",
                            "generator_sha256", "git_head_commit", "git_branch",
                            "git_head_relation_to_freeze", "frozen_commit"}
                differences = {
                    key for key in set(current) | set(fresh)
                    if current.get(key) != fresh.get(key)
                }
                unexpected = differences - volatile
                if unexpected:
                    drift.append(f"differs (non-volatile fields): {rel} {sorted(unexpected)}")
                elif differences:
                    volatile_drift.append(f"{rel}: {sorted(differences)}")
                continue
            if path.read_text(encoding="utf-8") != content:
                drift.append(f"differs: {rel}")
        if drift:
            print("SPEC DRIFT DETECTED", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1
        for line in volatile_drift:
            print(f"volatile (expected): {line}")
        print(f"OK: {len(artifacts)} artefacts reproduce; "
              f"{len(volatile_drift)} differ only in volatile fields")
        return 0

    written = write_artifacts(out_root, artifacts)
    print(f"wrote {len(written)} files under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

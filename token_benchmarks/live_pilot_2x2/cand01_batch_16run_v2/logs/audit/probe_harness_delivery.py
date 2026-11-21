"""Item 10, adversarial half: does the *harness path* deliver a spec's switches?

`scripts/token_benchmark.py::_run_single` is what the harness actually spawns.
It is imported read-only and its config-assembly is replicated exactly, then we
show which switches the graph would see for a CC-arm spec when the parent env is
neutral. No LLM and no network is touched: only DEFAULT_CONFIG is inspected.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path("/tmp/opencode/planC2_wt")
sys.path.insert(0, str(REPO))

spec = json.loads(
    (REPO / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs/"
     "R03_NVDA_CC/spec.json").read_text()
)
print("spec R03 (arm CC) declared switches:", spec["switches"])
print("spec keys:", sorted(spec))
print("does spec carry the env var names the child needs?", sorted(
    k for k in spec if k.startswith("TRADINGAGENTS_")) or "(none)")

# Exact replication of token_benchmark.py::_run_single lines 2064-2076
from tradingagents.default_config import DEFAULT_CONFIG

config = dict(DEFAULT_CONFIG)
config["results_dir"] = spec.get("results_dir")
config["llm_provider"] = spec.get("provider")
config["quick_think_llm"] = spec.get("quick_model")
config["deep_think_llm"] = spec.get("deep_model")
config["max_debate_rounds"] = spec["case"].get("research_rounds")
config["max_risk_discuss_rounds"] = spec["case"].get("risk_rounds")
config["output_language"] = spec.get("output_language")
config["checkpoint_enabled"] = False

effective = {k: config[k] for k in (
    "batch_macro_enabled", "single_pass_finalization_enabled",
    "structured_analyst_output_enabled")}
wanted = {
    "batch_macro_enabled": spec["switches"]["batch_macro"],
    "single_pass_finalization_enabled": spec["switches"]["single_pass"],
    "structured_analyst_output_enabled": spec["switches"]["structured"],
}
print("\neffective config the graph would be built with:", effective)
print("spec declared                                 :", wanted)
print("MATCH:", effective == wanted)
print("\nParent env had TRADINGAGENTS_* set?:",
      sorted(k for k in os.environ if k.startswith("TRADINGAGENTS_")) or "(none)")

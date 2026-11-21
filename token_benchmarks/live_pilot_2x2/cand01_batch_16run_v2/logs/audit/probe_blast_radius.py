"""How many of the 16 specs would run with the wrong effective switches if the
documented delivery route (env vars) is not applied? Arm C0/CC are exactly the
arms whose labelling depends on it."""
import json
import sys
from pathlib import Path

REPO = Path("/tmp/opencode/planC2_wt")
sys.path.insert(0, str(REPO))
from tradingagents.default_config import DEFAULT_CONFIG

# token_benchmark._run_single never touches the three switch keys, so the value
# that reaches GraphSetup is whatever DEFAULT_CONFIG holds in the child env.
neutral = {k: DEFAULT_CONFIG[k] for k in (
    "batch_macro_enabled", "single_pass_finalization_enabled",
    "structured_analyst_output_enabled")}
print("child-effective switches under a neutral env:", neutral, "\n")

V2 = REPO / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs"
bad = []
for d in sorted(V2.iterdir()):
    sp = json.loads((d / "spec.json").read_text())
    sw = sp["switches"]
    want = {
        "batch_macro_enabled": sw["batch_macro"],
        "single_pass_finalization_enabled": sw["single_pass"],
        "structured_analyst_output_enabled": sw["structured"],
    }
    ok = want == neutral
    if not ok:
        bad.append((d.name, want, neutral))
    print(f"{d.name:16s} {'OK      ' if ok else 'MISLABEL'} "
          f"declared single_pass={sw['single_pass']!s:5s} "
          f"macros={sw['batch_macro']!s:5s} -> would run {neutral}")
print(f"\n{len(bad)}/16 specs would run with switches that differ "
      f"from their declared/labelled arm")
print("affected runs:", ", ".join(b[0] for b in bad))

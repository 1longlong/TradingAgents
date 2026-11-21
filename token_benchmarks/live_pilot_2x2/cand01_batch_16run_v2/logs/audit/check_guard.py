"""Item 6: is s2_downstream=false REFUSED, via the generator's *public guard*
and via the product-code guard? Imported generator only to CALL the guard,
not to check its own output."""
import importlib.util
import json
import sys
from pathlib import Path

GEN = Path("/tmp/opencode/planC2_wt/scripts/gen_cand01_batch_16run_specs_v2.py")
spec = importlib.util.spec_from_file_location("gv2_callonly", GEN)
gv2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gv2)

print("--- A. generator guard require_supported_switches({'s2_downstream': False})")
try:
    gv2.require_supported_switches({"batch_macro": False, "single_pass": False,
                                    "structured": True, "s2_downstream": False})
    print("NOT REFUSED  <-- would be a defect")
except gv2.RefusedError as e:
    print(f"REFUSED OK: {e}")

print("--- B. guard with only s2_downstream=False (no other keys)")
try:
    gv2.require_supported_switches({"s2_downstream": False})
    print("NOT REFUSED  <-- would be a defect")
except gv2.RefusedError as e:
    print(f"REFUSED OK: {e}")

print("--- C. guard with s2_downstream=True accepted")
try:
    gv2.require_supported_switches({"s2_downstream": True})
    print("ACCEPTED OK")
except gv2.RefusedError as e:
    print(f"WRONGLY REFUSED: {e}")

print("--- D. is the guard reachable from the real build path? patch ARM_SWITCHES")
orig = gv2.ARM_SWITCHES["B"]
gv2.ARM_SWITCHES["B"] = dict(orig, s2_downstream=False)
try:
    gv2.per_run_experiment({"run_id": "R01", "position": 1, "ticker": "NVDA", "arm": "B"})
    print("NOT REFUSED via per_run_experiment  <-- defect")
except gv2.RefusedError as e:
    print(f"REFUSED OK via per_run_experiment: {e}")
try:
    gv2.build(Path("/tmp/opencode/auditB/never_written"))
    print("NOT REFUSED via build()  <-- defect")
except gv2.RefusedError as e:
    print(f"REFUSED OK via build(): {e}")
gv2.ARM_SWITCHES["B"] = orig

print("--- E. product-code guard validate_spec_switches (switch_verification)")
sys.path.insert(0, "/tmp/opencode/planC2_wt")
from tradingagents.graph.switch_verification import (
    SwitchNotConsumed, validate_spec_switches)
for label, sw in [
    ("s2=False", {"batch_macro": False, "single_pass": False, "structured": True, "s2_downstream": False}),
    ("s2=True ", {"batch_macro": False, "single_pass": False, "structured": True, "s2_downstream": True}),
]:
    try:
        validate_spec_switches(sw)
        print(f"{label}: accepted")
    except SwitchNotConsumed as e:
        print(f"{label}: REFUSED -> {e}")

print("--- F. every delivered spec uses s2_downstream == True")
V2 = Path("/tmp/opencode/planC2_wt/token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs")
vals = set()
for d in V2.iterdir():
    e = json.loads((d / "experiment.json").read_text())
    s = json.loads((d / "spec.json").read_text())
    vals.add((e["switches"]["s2_downstream"], s["switches"]["s2_downstream"]))
    validate_spec_switches(s["switches"])
print(f"distinct (exp,spec) s2_downstream values across 16: {vals}")

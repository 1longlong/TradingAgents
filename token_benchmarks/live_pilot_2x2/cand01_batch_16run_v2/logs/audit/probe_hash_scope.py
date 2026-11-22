"""Probe hash scope: what is NOT covered by config_sha256, and is that a real risk?"""
import hashlib, json, re
from pathlib import Path

ROOT = Path("/tmp/opencode/planC2_wt")
V2 = ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs"
HASHED = ["experiment_id", "schema_version", "switches_required", "provider",
          "quick_model", "deep_model", "output_language", "cache_policy",
          "checkpoint_enabled", "budget", "cases", "switches", "news_scope"]

def canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
def h(o): return hashlib.sha256(canon(o).encode()).hexdigest()

exps = {d.name.split("_")[0]: json.loads((d / "experiment.json").read_text()) for d in V2.iterdir()}

print("== A. generator_sha256 in code_state matches the file on disk")
stored = json.loads((V2 / "R01_NVDA_C0" / "code_state.json").read_text())["generator_sha256"]
actual = hashlib.sha256((ROOT / "scripts/gen_cand01_batch_16run_specs_v2.py").read_bytes()).hexdigest()
print(f"stored={stored}\nactual={actual}\nmatch={stored == actual}")

print("\n== B. experiment_definition_sha256: re-derive from the documented rule "
      "(sha256 of canonical json of {run_id: experiment} for run_id sorted)")
got = hashlib.sha256(canon({k: exps[k] for k in sorted(exps)}).encode()).hexdigest()
stored_def = json.loads((V2 / "R01_NVDA_C0" / "code_state.json").read_text())["experiment_definition_sha256"]
print(f"stored={stored_def}\nactual={got}\nmatch={stored_def == got}")

print("\n== C. does swapping the WHOLE switches dict between two runs keep a hash valid?")
r01, r03 = exps["R01"], exps["R03"]
swapped = dict(r01); swapped["switches"] = dict(r03["switches"]); swapped.pop("config_sha256")
print(f"R01 with CC switches hashes to {h({k: swapped[k] for k in HASHED})[:16]}… "
      f"(R03 real = {r03['config_sha256'][:16]}…) -> "
      f"{'equals R03 hash: cross-run hash reuse possible' if h({k: swapped[k] for k in HASHED}) == r03['config_sha256'] else 'differs'}")

print("\n== D. which per-run fields are NOT hashed (documented as excluded) and "
      "are they load-bearing?")
allkeys = set(exps["R01"])
print("experiment.json keys:", sorted(allkeys))
print("NOT hashed:", sorted(allkeys - set(HASHED)))

print("\n== E. run identity <-> hash binding: is experiment_id hashed?")
print("'experiment_id' in HASHED:", "experiment_id" in HASHED,
      "-> value is the RUN ID (R01..R16), so identity IS bound")

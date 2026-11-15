"""Item 10: does the env var actually change DEFAULT_CONFIG in a FRESH child?"""
import importlib
import json
import os
import subprocess
import sys

REPO = "/tmp/opencode/planC2_wt"
PY = f"{REPO}/.venv/bin/python"

CODE = (
    "import json;from tradingagents.default_config import DEFAULT_CONFIG as C;"
    "print(json.dumps({k:C[k] for k in ('batch_macro_enabled',"
    "'single_pass_finalization_enabled','structured_analyst_output_enabled')}))"
)

CASES = {
    "unset (defaults)": {},
    "B":    {"TRADINGAGENTS_BATCH_MACRO_ENABLED": "false",
             "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED": "false",
             "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED": "true"},
    "AB":   {"TRADINGAGENTS_BATCH_MACRO_ENABLED": "true",
             "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED": "false",
             "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED": "true"},
    "C0":   {"TRADINGAGENTS_BATCH_MACRO_ENABLED": "false",
             "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED": "true",
             "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED": "true"},
    "CC":   {"TRADINGAGENTS_BATCH_MACRO_ENABLED": "true",
             "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED": "true",
             "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED": "true"},
}

results = {}
for arm, extra in CASES.items():
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRADINGAGENTS_")}
    env["TZ"] = "UTC"
    env.update(extra)
    p = subprocess.run([PY, "-c", CODE], capture_output=True, text=True, env=env, cwd=REPO)
    assert p.returncode == 0, p.stderr
    results[arm] = json.loads(p.stdout)
    print(f"{arm:20s} {p.stdout.strip()}")

print("\n--- negative control: a bogus value must be rejected, not ignored")
env = {k: v for k, v in os.environ.items() if not k.startswith("TRADINGAGENTS_")}
env["TRADINGAGENTS_BATCH_MACRO_ENABLED"] = "maybe"
p = subprocess.run([PY, "-c", CODE], capture_output=True, text=True, env=env, cwd=REPO)
print(f"rc={p.returncode} stderr_tail={p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ''}")

print("\n--- negative control: cache of module-level DEFAULT_CONFIG across reimport")
code2 = (
    "import importlib,json,os\n"
    "import tradingagents.default_config as dc\n"
    "a=dc.DEFAULT_CONFIG['batch_macro_enabled']\n"
    "print('first',a)\n"
)
p = subprocess.run([PY, "-c", code2], capture_output=True, text=True, env=env, cwd=REPO)
print(p.stdout.strip() or p.stderr.strip()[-200:])

print("\n--- consistency against delivered specs")
V2 = f"{REPO}/token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs"
import pathlib
mism = 0
for d in sorted(pathlib.Path(V2).iterdir()):
    e = json.loads((d / "experiment.json").read_text())
    sw = e["switches"]
    arm = e["description"].split(" arm ")[1].split(" ")[0]
    got = results[arm]
    want = {
        "batch_macro_enabled": sw["batch_macro"],
        "single_pass_finalization_enabled": sw["single_pass"],
        "structured_analyst_output_enabled": sw["structured"],
    }
    ok = got == want
    mism += 0 if ok else 1
    print(f"{d.name:16s} arm={arm:3s} env->config {got} want {want} {'OK' if ok else 'MISMATCH'}")
print(f"mismatches={mism}/16")

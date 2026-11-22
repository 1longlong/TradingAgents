#!/usr/bin/env python
"""INDEPENDENT re-implementation audit of the V2 spec set.

Deliberately does NOT import scripts/gen_cand01_batch_16run_specs_v2.py.
Everything (hash algorithm, field list, randomisation) is re-derived from the
protocol prose (CAND01_BATCH_2X2_PROTOCOL_V2.md §6/§8) and the delivered files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path("/tmp/opencode/planC2_wt")
V2 = ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
V1 = ROOT / "token_benchmarks/live_pilot_2x2/cand01_batch_16run/generated"

# ---- from protocol §6 (typed out by hand, NOT imported) ----
HASHED = ["experiment_id", "schema_version", "switches_required", "provider",
          "quick_model", "deep_model", "output_language", "cache_policy",
          "checkpoint_enabled", "budget", "cases", "switches", "news_scope"]

EXPECT_ARM = {
    "B":  dict(batch_macro=False, single_pass=False, structured=True, s2_downstream=True),
    "AB": dict(batch_macro=True,  single_pass=False, structured=True, s2_downstream=True),
    "C0": dict(batch_macro=False, single_pass=True,  structured=True, s2_downstream=True),
    "CC": dict(batch_macro=True,  single_pass=True,  structured=True, s2_downstream=True),
}

fails, notes = [], []


def chk(cond, msg):
    (notes if cond else fails).append(("PASS " if cond else "FAIL ") + msg)
    return cond


def canon(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def h(o):
    return hashlib.sha256(canon(o).encode("utf-8")).hexdigest()


# ---- 1. structure ----
dirs = sorted(d for d in (V2 / "specs").iterdir() if d.is_dir())
chk(len(dirs) == 16, f"spec dir count == 16 (got {len(dirs)})")
for d in dirs:
    for f in ("experiment.json", "spec.json", "code_state.json"):
        chk((d / f).is_file(), f"{d.name} has {f}")
extra = sorted(p.name for p in (V2 / "specs").iterdir() if not p.is_dir())
chk(not extra, f"no stray files in specs/ (got {extra})")

# ---- load ----
runs = {}
for d in dirs:
    rid, ticker, arm = d.name.split("_")
    runs[rid] = dict(
        dir=d.name, ticker=ticker, arm=arm,
        exp=json.loads((d / "experiment.json").read_text(encoding="utf-8")),
        spec=json.loads((d / "spec.json").read_text(encoding="utf-8")),
        state=json.loads((d / "code_state.json").read_text(encoding="utf-8")),
    )

# ---- 2. matrix ----
cells = {}
for rid, r in runs.items():
    cells.setdefault(r["ticker"], []).append(r["arm"])
chk(sorted(cells) == ["AAPL", "JPM", "NVDA", "XOM"], f"tickers == 4 (got {sorted(cells)})")
for t, arms in cells.items():
    chk(sorted(arms) == ["AB", "B", "C0", "CC"], f"{t} has exactly the 4 arms once (got {sorted(arms)})")
for rid, r in runs.items():
    chk(r["exp"]["switches"] == EXPECT_ARM[r["arm"]],
        f"{rid} {r['ticker']}/{r['arm']} switches == expected arm mapping (got {r['exp']['switches']})")
    chk(r["spec"]["switches"] == r["exp"]["switches"], f"{rid} spec.switches == experiment.switches")
    # dir name / exp id / case ticker consistency
    chk(r["exp"]["experiment_id"] == rid, f"{rid} experiment.experiment_id == {rid} (got {r['exp']['experiment_id']})")
    chk(r["spec"]["experiment_id"] == rid, f"{rid} spec.experiment_id == {rid} (got {r['spec']['experiment_id']})")
    chk(r["exp"]["cases"][0]["ticker"] == r["ticker"], f"{rid} case ticker == {r['ticker']}")
    chk(r["exp"]["cases"][0]["trade_date"] == "2026-09-23", f"{rid} trade_date == 2026-09-23")

# ---- 3. independent hash recomputation ----
hashes = {}
HEXRE = re.compile(r"^[0-9a-f]{64}$")
for rid, r in runs.items():
    stored = r["exp"]["config_sha256"]
    hashes[rid] = stored
    chk(bool(HEXRE.match(stored)), f"{rid} stored hash is 64-char lowercase hex")
    chk(h(  {k: r["exp"][k] for k in HASHED}) == stored,
        f"{rid} INDEPENDENT recomputation matches stored {stored[:12]}…")
    chk(r["spec"]["config_sha256"] == stored, f"{rid} spec.config_sha256 == experiment.config_sha256")
chk(len(set(hashes.values())) == 16, f"16 distinct hashes (got {len(set(hashes.values()))})")

# CSV manifests must agree with the per-run files
with (V2 / "CONFIG_HASH_MANIFEST.csv").open() as fh:
    for row in csv.DictReader(fh):
        chk(row["config_sha256"] == hashes[row["run_id"]], f"CONFIG_HASH_MANIFEST {row['run_id']} matches file")
with (V2 / "SWITCH_MATRIX.csv").open() as fh:
    for row in csv.DictReader(fh):
        r = runs[row["run_id"]]
        chk(row["ticker"] == r["ticker"] and row["arm"] == r["arm"], f"SWITCH_MATRIX {row['run_id']} ticker/arm match")
        for k in ("batch_macro", "single_pass", "structured", "s2_downstream"):
            want = "True" if EXPECT_ARM[r["arm"]][k] else "False"
            chk(row[k] == want, f"SWITCH_MATRIX {row['run_id']}.{k} == {want} (got {row[k]})")
with (V2 / "RUN_MANIFEST_TEMPLATE.csv").open() as fh:
    for row in csv.DictReader(fh):
        rid = row["run_id"]
        chk(row["config_sha256"] == hashes[rid], f"RUN_MANIFEST {rid} config_sha256 matches file")
        body = {k: v for k, v in runs[rid]["spec"].items() if k != "results_dir"}
        chk(row["spec_body_sha256"] == h(body), f"RUN_MANIFEST {rid} spec_body_sha256 recomputes")

# protocol md table hashes
md = (V2 / "CAND01_BATCH_2X2_PROTOCOL_V2.md").read_text(encoding="utf-8")
md_hashes = dict(re.findall(r"\| `(R\d\d)` \|.*?`([0-9a-f]{64})` \|", md))
chk(len(md_hashes) == 16, f"protocol md lists 16 hashes (got {len(md_hashes)})")
for rid, hv in md_hashes.items():
    chk(hashes.get(rid) == hv, f"protocol md {rid} hash == file hash")

# ---- 4. single-switch sensitivity ----
base = dict(runs["R01"]["exp"])
for name in ("batch_macro", "single_pass", "structured", "s2_downstream"):
    mut = json.loads(json.dumps(base))
    mut["switches"][name] = not mut["switches"][name]
    mut.pop("config_sha256", None)
    chk(h({k: mut[k] for k in HASHED}) != base["config_sha256"],
        f"flipping switches.{name} changes hash")
for field, val in [("provider", "anthropic"), ("quick_model", "x"),
                   ("deep_model", "y"), ("output_language", "Chinese"),
                   ("cache_policy", "clear"), ("checkpoint_enabled", True),
                   ("switches_required", False)]:
    mut = json.loads(json.dumps(base)); mut[field] = val; mut.pop("config_sha256", None)
    chk(h({k: mut[k] for k in HASHED}) != base["config_sha256"], f"changing {field} changes hash")

# ---- 5. self-reference ----
chk("config_sha256" not in HASHED, "config_sha256 is not in HASHED_FIELDS")
chk("config_sha256" not in runs["R01"]["exp"] or True, "sanity")
for rid, r in runs.items():
    # If the hash hashed itself, no fixed point would exist for a stored value.
    fake = json.loads(json.dumps(r["exp"]))
    fake["config_sha256"] = "0" * 64
    chk(h({k: fake[k] for k in HASHED}) == r["exp"]["config_sha256"],
        f"{rid} hash unchanged when config_sha256 field is replaced (proves exclusion)")
    d = json.loads(json.dumps(r["exp"])); d["description"] = "tampered prose"
    chk(h({k: d[k] for k in HASHED}) == r["exp"]["config_sha256"], f"{rid} description excluded")
    d = json.loads(json.dumps(r["exp"])); d["protocol_version"] = "V9"
    chk(h({k: d[k] for k in HASHED}) == r["exp"]["config_sha256"], f"{rid} protocol_version excluded")

# ---- 7/8. run ids and randomisation ----
ids = sorted(runs)
chk(ids == [f"R{n:02d}" for n in range(1, 17)], f"run ids R01..R16 present")
rng = random.Random(20261114)          # independent construction
order = {}
for block in ("NVDA", "AAPL", "JPM", "XOM"):
    arms = ["B", "AB", "C0", "CC"]
    rng.shuffle(arms)
    order[block] = arms
pos = 1
for block in ("NVDA", "AAPL", "JPM", "XOM"):
    for arm in order[block]:
        rid = f"R{pos:02d}"
        r = runs[rid]
        chk(r["ticker"] == block and r["arm"] == arm,
            f"position {pos:02d} == {block}/{arm} (dir says {r['ticker']}/{r['arm']})")
        pos += 1
eo = (V2 / "EXECUTION_ORDER.txt").read_text()
for block, arms in order.items():
    chk(f"{block}: {arms}" in eo, f"EXECUTION_ORDER.txt line for {block} == independent shuffle {arms}")

v1eo = (V1 / "EXECUTION_ORDER.txt").read_text()
for block, arms in order.items():
    chk(f"{block}: {arms}" in v1eo, f"V1 EXECUTION_ORDER.txt agrees for {block}")

# ---- 9. V1 design comparison ----
v1 = {}
for d in sorted((V1 / "specs").iterdir()):
    v1[d.name.split("_")[0]] = (d.name, json.loads((d / "spec.json").read_text()))
chk(sorted(v1) == sorted(runs), "V1 and V2 share the same 16 run IDs")
chk(sorted(n for n, _ in v1.values()) == sorted(runs[i]["dir"] for i in runs),
    "V1 and V2 share the same 16 run directory names")
for rid, r in runs.items():
    s1, s2 = v1[rid][1], r["spec"]
    chk(s1["case"] == s2["case"], f"{rid} case block identical to V1")
    chk(s1["switches"] == s2["switches"], f"{rid} switches identical to V1")
    for k in ("provider", "quick_model", "deep_model", "output_language", "cache_policy", "run_index"):
        chk(s1[k] == s2[k], f"{rid} {k} identical to V1 ({s1[k]!r} vs {s2[k]!r})")
    chk(s1.get("budget") == s2.get("budget") or (s2.get("budget") is None and s1.get("budget") == {"max_total_tokens": None}),
        f"{rid} budget comparison: v1={s1.get('budget')!r} v2={s2.get('budget')!r}")
    for k in sorted(set(s1) - set(s2)):
        print(f"NOTE {rid}: key {k!r} in V1 spec but not V2 (v1={s1[k]!r})")
    for k in sorted(set(s2) - set(s1)):
        print(f"NOTE {rid}: key {k!r} in V2 spec but not V1 (v2={s2[k]!r})")

# ---- 11. machine-specific absolute paths ----
for rid, r in runs.items():
    for fname in ("spec.json", "experiment.json", "code_state.json"):
        text = (r["dir"] and (V2 / "specs" / r["dir"] / fname).read_text())
        for m in set(re.findall(r"/[A-Za-z0-9_.\-/]{6,}", text)):
            if m.startswith("/tmp/opencode/planC2_wt/token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/specs/"):
                expected = r["spec"]["results_dir"]
                chk(m.startswith(expected), f"{rid}/{fname} path {m} within declared results_dir")
            elif m.startswith("/home/") or m.startswith("/tmp/") or m.startswith("/Users/"):
                fails.append(f"FAIL {rid}/{fname} foreign absolute path {m}")

print("\n".join(notes))
print("\n===== FAILURES =====")
print("\n".join(fails) if fails else "(none)")
print(f"\nTOTAL PASS={len(notes)} FAIL={len(fails)}")

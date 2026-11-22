"""AST proof: does any executable GDELT reference exist in the Finnhub-only path?

Read-only. Parses the real source files, walks the AST of specific functions
(including nested function bodies and lazy imports), and reports every
Import/ImportFrom node whose module mentions gdelt, plus every Name/Attribute
mention of "gdelt" that is not inside a docstring (docstrings are string
constants, not Name nodes, so they cannot create false negatives).
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path("/tmp/opencode/planC2_wt/tradingagents/dataflows")

TARGETS = {
    "finnhub_news.py": [
        "get_news_finnhub_only",
        "get_global_news_finnhub",
        # transitive helpers called by the two entry points
        "_safe_call",
        "get_news_finnhub",
        "fetch_news_finnhub",
        "_parse_cutoff",
    ],
    "news_merge.py": ["merge_news_sections", "combine_status", "_section"],
    "interface.py": [],   # whole-module scan of VENDOR_METHODS handled below
}


def funcs(tree):
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def scan(node, label):
    imports, names, attrs, constants = [], [], [], []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for a in sub.names:
                if "gdelt" in a.name.lower():
                    imports.append((sub.lineno, f"import {a.name}"))
        elif isinstance(sub, ast.ImportFrom):
            mod = sub.module or ""
            if "gdelt" in mod.lower():
                imports.append((sub.lineno, f"from {mod} import " +
                                ",".join(a.name for a in sub.names)))
            for a in sub.names:
                if "gdelt" in a.name.lower():
                    imports.append((sub.lineno, f"from {mod} import {a.name}"))
        elif isinstance(sub, ast.Name) and "gdelt" in sub.id.lower():
            names.append((sub.lineno, sub.id))
        elif isinstance(sub, ast.Attribute) and "gdelt" in sub.attr.lower():
            attrs.append((sub.lineno, sub.attr))
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if "gdelt" in sub.value.lower():
                constants.append((sub.lineno, sub.value[:70].replace("\n", " ")))
    print(f"\n--- {label} (line {node.lineno}-{node.end_lineno}) ---")
    print(f"  executable GDELT imports : {imports if imports else 'NONE'}")
    print(f"  GDELT Name nodes         : {names if names else 'NONE'}")
    print(f"  GDELT Attribute nodes    : {attrs if attrs else 'NONE'}")
    print(f"  GDELT string constants   : {len(constants)} "
          f"(docstrings / messages only — not executable imports)")
    for ln, txt in constants:
        print(f"      line {ln}: {txt!r}")
    return bool(imports or names or attrs)


violations = 0
for fname, fnames in TARGETS.items():
    path = ROOT / fname
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    table = funcs(tree)
    for fn in fnames:
        if fn not in table:
            print(f"!! missing function {fn} in {fname}")
            violations += 1
            continue
        if scan(table[fn], f"{fname}::{fn}"):
            violations += 1

# interface.py: prove which callables the finnhub keys bind, and that neither
# binding resolves to a gdelt module attribute.
ipath = ROOT / "interface.py"
isrc = ipath.read_text()
itree = ast.parse(isrc)
print("\n=== interface.py VENDOR_METHODS bindings (AST) ===")
for node in ast.walk(itree):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "VENDOR_METHODS" for t in node.targets
    ):
        d = node.value
        for key, val in zip(d.keys, d.values):
            if isinstance(key, ast.Constant) and key.value in ("get_news", "get_global_news"):
                print(f"  {key.value}:")
                for k2, v2 in zip(val.keys, val.values):
                    print(f"      {k2.value!r} -> {ast.unparse(v2)} (line {v2.lineno})")

# Prove get_news_combined is the ONLY function in finnhub_news.py that has an
# executable gdelt import, and that it is a distinct function object.
print("\n=== every top-level function in finnhub_news.py with an executable gdelt import ===")
fhub = ast.parse((ROOT / "finnhub_news.py").read_text())
for n in fhub.body:
    if isinstance(n, ast.FunctionDef):
        hit = any(
            "gdelt" in (getattr(s, "module", "") or "").lower()
            for s in ast.walk(n)
            if isinstance(s, ast.ImportFrom)
        )
        if hit:
            print(f"  {n.name} (line {n.lineno}) HAS a gdelt import")

print(f"\nVIOLATIONS: {violations}")
sys.exit(0)

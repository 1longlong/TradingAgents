"""Does the 16-run experiment harness actually give the app a Finnhub key?

Read-only. Calls the REAL `scripts.token_benchmark.apply_cityu_env` and
`credential_state` with a temp secrets file containing FINNHUB_API_KEY.
"""
import importlib.util
import os
import pathlib
import sys

REPO = "/tmp/opencode/planC2_wt"
sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location(
    "tb", str(pathlib.Path(REPO) / "scripts" / "token_benchmark.py"))
tb = importlib.util.module_from_spec(spec)
sys.modules["tb"] = tb
spec.loader.exec_module(tb)
print("module:", tb.__file__)

secrets = pathlib.Path("/tmp/opencode/auditA/auditA_secrets.env")
secrets.write_text(
    "CITYU_FOUNDRY_API_KEY=fake\n"
    "CITYU_FOUNDRY_BASE_URL=https://fake.invalid/v1\n"
    "FRED_API_KEY=fake-fred\n"
    "FINNHUB_API_KEY=real-finnhub-key-from-secrets\n"
)
print("secrets file:", secrets)
print("  contains FINNHUB_API_KEY:", "FINNHUB_API_KEY" in secrets.read_text())

env = {k: v for k, v in os.environ.items() if not k.startswith(("FINNHUB", "FRED_"))}
applied = tb.apply_cityu_env(env, secrets)
print("\napply_cityu_env applied:", applied)
print("env['FINNHUB_API_KEY'] present :", "FINNHUB_API_KEY" in env,
      "->", repr(env.get("FINNHUB_API_KEY")))
print("credential_state:", tb.credential_state(env))

print("\n=== impact on the real Finnhub path when the key is absent ===")
saved = os.environ.pop("FINNHUB_API_KEY", None)
try:
    import tradingagents.dataflows.finnhub_news as fn
    import tradingagents.dataflows.interface as iface
    assert fn.__file__.startswith(REPO), fn.__file__
    out = fn.get_news_finnhub_only("NVDA", "2026-09-18", "2026-09-23")
    print("\n".join("  | " + l for l in out.splitlines()[:6]))
    print("\n  key in output text?", "real-finnhub-key" in out)
finally:
    if saved is not None:
        os.environ["FINNHUB_API_KEY"] = saved

print("\nVERDICT: harness maps FINNHUB_API_KEY ->", "FINNHUB_API_KEY" in env)

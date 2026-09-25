"""
Run this from services/agent-worker/ (same folder as requirements.txt):

    python debug_gemini.py

Checks, in order:
  1. Is there a .env file where Python can actually find it?
  2. Which of the 5 per-agent Gemini keys are set?
  3. A real generate_content() call for each agent that has a key.

This exists because `python -c "..."` one-liners in PowerShell swallow
import errors/warnings in a way that's easy to misread, and silently use
whatever CWD you happen to be in for dotenv discovery. This script pins
its own working directory so "did .env actually load" is never ambiguous.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"

print(f"[1] Looking for .env at: {ENV_PATH}")
if not ENV_PATH.exists():
    print("    NOT FOUND. Either:")
    print("    - your .env lives at the repo root instead (common setup mistake -- ")
    print("      this service loads .env relative to its own folder), or")
    print("    - you haven't copied .env.example to .env yet.")
    print("    Copy/move a .env with real values into this exact folder and re-run.")
    sys.exit(1)
else:
    print("    found.")

load_dotenv(dotenv_path=ENV_PATH, override=True)

AGENT_KEYS = ["discovery", "eda_clean", "rag_summary", "report_gen", "extras"]

print("\n[2] Per-agent Gemini key status:")
missing = []
for agent in AGENT_KEYS:
    var = f"GEMINI_API_KEY_{agent.upper()}"
    val = os.environ.get(var)
    status = "SET" if val else "MISSING"
    if not val:
        missing.append(var)
    masked = f"{val[:4]}...{val[-4:]}" if val else "-"
    print(f"    {var:<28} {status:<8} {masked}")

if missing:
    print(f"\n    {len(missing)} key(s) missing. Add them to {ENV_PATH} as:")
    for var in missing:
        print(f"      {var}=your-real-key-here")
    print("    You can use the SAME real Gemini key for all 5 for now --")
    print("    separate keys only matter once you want per-agent cost")
    print("    attribution/rate limits in a real Gemini Cloud project.")

print("\n[3] Live call test (only for agents with a key set):")
sys.path.insert(0, str(HERE))
from agent_worker.llm.factory import get_provider  # noqa: E402

os.environ["LLM_PROVIDER"] = "gemini"

any_ok = False
for agent in AGENT_KEYS:
    var = f"GEMINI_API_KEY_{agent.upper()}"
    if not os.environ.get(var):
        print(f"    [{agent}] skipped ({var} not set)")
        continue
    try:
        provider = get_provider(agent)
        result = provider.complete("Reply with exactly one word: OK", agent_key=agent)
        print(f"    [{agent}] OK -> {result.text.strip()!r}")
        any_ok = True
    except Exception as e:
        print(f"    [{agent}] FAILED -> {type(e).__name__}: {e}")

print("\nDone." if any_ok else "\nNo successful calls -- fix the missing keys above and re-run.")
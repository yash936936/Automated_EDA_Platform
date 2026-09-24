import os
from .base import LLMProvider
from .gemini_provider import GeminiProvider
from .fake_provider import FakeProvider

# One entry per agent (Discovery, EDA/Clean, RAG/Summary, Report Gen, Extras)
# -- each gets its own env-var-backed API key for cost attribution and
# independent rate-limit tuning, per the design doc. Provider choice is a
# config value (env var), not a call-site decision, so swapping Gemini for
# Jev later is a config change only.
AGENT_KEYS = ["discovery", "eda_clean", "rag_summary", "report_gen", "extras"]

_PROVIDER_REGISTRY = {
    "gemini": GeminiProvider,
    "fake": FakeProvider,
}


def get_provider(agent_key: str) -> LLMProvider:
    if agent_key not in AGENT_KEYS:
        raise ValueError(f"unknown agent_key '{agent_key}', expected one of {AGENT_KEYS}")
    provider_name = os.environ.get("LLM_PROVIDER", "fake")  # defaults to fake in sandbox
    provider_cls = _PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        raise ValueError(f"unknown LLM_PROVIDER '{provider_name}'")
    return provider_cls()

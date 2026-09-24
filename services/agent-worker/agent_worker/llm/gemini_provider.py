import os
from .base import LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    """v1 LLM provider. Real calls require GEMINI_API_KEY_<AGENT> env vars
    (one per agent, per the design doc's cost-attribution requirement) --
    not set in this sandbox, so `complete()` raises unless a key is present.
    This is intentional: Phase 0 proves the *interface contract*, not a live
    Gemini call (no API key available in this environment)."""

    def complete(self, prompt: str, *, agent_key: str) -> LLMResponse:
        api_key = os.environ.get(f"GEMINI_API_KEY_{agent_key.upper()}")
        if not api_key:
            raise RuntimeError(
                f"No Gemini API key configured for agent '{agent_key}' "
                f"(expected env var GEMINI_API_KEY_{agent_key.upper()})"
            )
        # Real implementation would call the Gemini API here using `api_key`.
        raise NotImplementedError("Live Gemini call not wired up in Phase 0 sandbox")

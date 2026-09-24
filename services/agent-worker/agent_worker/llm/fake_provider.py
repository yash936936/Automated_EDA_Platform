from .base import LLMProvider, LLMResponse


class FakeProvider(LLMProvider):
    """Deterministic stand-in used for Phase 0 interface testing only, so
    the contract (per-agent key attribution, swappability) can be verified
    without needing a real Gemini/Jev credential in this sandbox."""

    def complete(self, prompt: str, *, agent_key: str) -> LLMResponse:
        return LLMResponse(
            text=f"[fake completion for agent={agent_key}] {prompt[:40]}",
            provider="fake",
            agent_key_used=agent_key,
        )

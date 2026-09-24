from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    provider: str
    agent_key_used: str


class LLMProvider(ABC):
    """Provider-agnostic interface (Phase 0.4). Swapping Gemini <-> Jev <->
    anything else must never require call-site changes -- only a different
    provider instance behind this interface."""

    @abstractmethod
    def complete(self, prompt: str, *, agent_key: str) -> LLMResponse:
        ...

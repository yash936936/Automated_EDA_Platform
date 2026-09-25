import os
from dotenv import load_dotenv
from google import genai
from .base import LLMProvider, LLMResponse

# Load .env here too (not just in worker.py) so this provider works correctly
# when imported from a standalone script/REPL, not only from the worker
# process. load_dotenv() is a no-op if the vars are already in the environment.
load_dotenv()

# NOTE: uses the current `google-genai` SDK (package name "google-genai",
# import path "google.genai"). The old `google-generativeai` package
# ("google.generativeai") is deprecated/EOL as of late 2026 -- do not
# reinstall it; requirements.txt has been updated accordingly.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


class GeminiProvider(LLMProvider):
    """v1 LLM provider. Real calls require GEMINI_API_KEY_<AGENT> env vars
    (one per agent, per the design doc's cost-attribution requirement)."""

    def complete(self, prompt: str, *, agent_key: str) -> LLMResponse:
        env_var = f"GEMINI_API_KEY_{agent_key.upper()}"
        api_key = os.environ.get(env_var)
        if not api_key:
            raise RuntimeError(
                f"No Gemini API key configured for agent '{agent_key}' "
                f"(expected env var {env_var} in your .env file, and make "
                f"sure something actually loads .env before this runs)"
            )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
        )
        return LLMResponse(text=response.text, provider="gemini", agent_key_used=agent_key)
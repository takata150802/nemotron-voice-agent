"""Harden the existing OpenAI-compatible service for local llama.cpp only."""

import httpx
from openai import AsyncOpenAI
from pipecat.services.openai.llm import OpenAILLMService

from services.local_config import local_url


class LocalOpenAILLMService(OpenAILLMService):
    """Keep upstream streaming parsing; only customize client ownership.

    Pipecat 1.5.0 ignores a caller-provided http_client in create_client.
    This override prevents inherited proxies from routing local inference
    externally and closes the session's client during pipeline cleanup.
    """

    def create_client(self, *, api_key=None, base_url=None, **kwargs):
        """Create the existing SDK client with mandatory local addressing."""
        return AsyncOpenAI(
            api_key="not-needed",
            base_url=local_url(base_url),
            http_client=httpx.AsyncClient(trust_env=False, timeout=120),
        )

    async def cleanup(self):
        """Release the HTTP pool as part of the standard Pipecat lifecycle."""
        await self._client.close()
        await super().cleanup()

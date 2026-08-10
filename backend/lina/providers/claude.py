"""Claude — a beautiful instrument, but expensive. Only used when configured."""

import logging
import os

from anthropic import AsyncAnthropic
from anthropic import APIError as AnthropicAPIError

from .base import AIProvider, ProviderError

log = logging.getLogger("lina.voice")

DEFAULT_MODEL = "claude-sonnet-4-6"
ENV_API_KEY = "ANTHROPIC_API_KEY"


class ClaudeProvider(AIProvider):
    name = "claude"
    label = "Claude"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — Claude is unavailable")
        self.model = model or os.getenv("LINA_MODEL") or DEFAULT_MODEL
        self._client = AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        system: str,
        messages: list[dict],
        **kwargs,
    ) -> str:
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 4096),
                system=system or "",
                messages=messages,
            )
            return response.content[0].text
        except AnthropicAPIError as exc:
            raise ProviderError(f"claude request failed: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.close()

"""OpenAI-compatible chat provider — the common base for DeepSeek,
OpenRouter, and Gemini (all expose the `/chat/completions` contract)."""

import logging
from typing import Any

import httpx

from .base import AIProvider, ProviderError

log = logging.getLogger("lina.voice")


class OpenAICompatProvider(AIProvider):
    """A chat-completions provider reached over HTTP.

    Configuration is entirely constructor-driven so nothing is hardcoded:
    the base URL, model, and API key all come from environment variables
    resolved by the factory.
    """

    name = "openai-compat"
    label = "OpenAI-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        name: str | None = None,
        label: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        if name:
            self.name = name
        if label:
            self.label = label
        self._client: httpx.AsyncClient | None = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        payload_messages: list[dict[str, Any]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        try:
            response = await self._http.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"{self.name} returned an unparseable body") from exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

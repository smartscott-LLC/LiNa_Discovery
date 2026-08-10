"""Gemini — generous free tier via its OpenAI-compatible endpoint."""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-2.0-flash"
ENV_API_KEY = "GEMINI_API_KEY"


class GeminiProvider(OpenAICompatProvider):
    name = "gemini"
    label = "Gemini"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — Gemini is unavailable")
        super().__init__(
            base_url=base_url or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model or os.getenv("AI_MODEL") or DEFAULT_MODEL,
            name=self.name,
            label=self.label,
        )

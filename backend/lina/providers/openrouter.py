"""OpenRouter — dozens of models, including free-tier ones."""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324:free"
ENV_API_KEY = "OPENROUTER_API_KEY"


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    label = "OpenRouter"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — OpenRouter is unavailable")
        super().__init__(
            base_url=base_url or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model or os.getenv("AI_MODEL") or DEFAULT_MODEL,
            name=self.name,
            label=self.label,
        )

"""DeepSeek — the default voice. Affordable, high quality, OpenAI-compatible."""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
ENV_API_KEY = "DEEPSEEK_API_KEY"


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    label = "DeepSeek"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — DeepSeek is unavailable")
        super().__init__(
            base_url=base_url or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model or os.getenv("AI_MODEL") or DEFAULT_MODEL,
            name=self.name,
            label=self.label,
        )

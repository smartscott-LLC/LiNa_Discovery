"""SiliconFlow — primary fallback voice. OpenAI-compatible, high quality."""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://api.siliconflow.com/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
ENV_API_KEY = "SILICON_FLOW_API_KEY"


class SiliconFlowProvider(OpenAICompatProvider):
    name = "siliconflow"
    label = "SiliconFlow"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — SiliconFlow is unavailable")
        super().__init__(
            base_url=base_url or os.getenv("SILICON_FLOW_URL") or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model or os.getenv("SILICON_FLOW_MODEL") or DEFAULT_MODEL,
            name=self.name,
            label=self.label,
        )
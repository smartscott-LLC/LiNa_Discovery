"""HuggingFace — secondary fallback voice. Router for open models."""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_MODEL = "prism-ml/Ternary-Bonsai-27B-gguf:together"
ENV_API_KEY = "HUGGING_FACE_ACCESS_TOKEN"


class HuggingFaceProvider(OpenAICompatProvider):
    name = "huggingface"
    label = "HuggingFace"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — HuggingFace is unavailable")
        super().__init__(
            base_url=base_url or os.getenv("HUGGING_FACE_URL") or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model or os.getenv("HUGGING_FACE_MODEL") or DEFAULT_MODEL,
            name=self.name,
            label=self.label,
        )
"""Hugging Face — the fallback voice when her own engine is down.

Hugging Face's OpenAI-compatible router endpoint. This is the second
instrument in the chain (behind her local engine, ahead of DeepSeek): a
reliable fallback so she is never left voiceless while the local model
issue is being solved.

Environment:
    HUGGING_FACE_URL     — the router endpoint (default: https://router.huggingface.co/v1)
    HUGGING_FACE_MODEL   — the model id (e.g. prism-ml/Ternary-Bonsai-27B-gguf:together)
    HUGGING_FACE_ACCESS_TOKEN — the token the endpoint authenticates with
    (The typo'd HUGGUNG_FACE_MODEL is also read, so the current .env works as-is.)
"""

import os

from .openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_MODEL = "prism-ml/Ternary-Bonsai-27B-gguf:together"
ENV_API_KEY = "HUGGING_FACE_ACCESS_TOKEN"
ENV_URL = "HUGGING_FACE_URL"
ENV_MODEL = "HUGGING_FACE_MODEL"


class HuggingFaceProvider(OpenAICompatProvider):
    name = "huggingface"
    label = "Hugging Face"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv(ENV_API_KEY)
        if not api_key:
            raise ValueError(f"{ENV_API_KEY} is not set — Hugging Face is unavailable")
        # Read the model from either spelling so the current .env works as-is.
        model = (
            model
            or os.getenv(ENV_MODEL)
            or os.getenv("HUGGUNG_FACE_MODEL")
            or DEFAULT_MODEL
        )
        super().__init__(
            base_url=base_url or os.getenv(ENV_URL) or DEFAULT_BASE_URL,
            api_key=api_key,
            model=model,
            name=self.name,
            label=self.label,
        )
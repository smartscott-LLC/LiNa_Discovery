"""Voice providers — LINA's pluggable instrument layer.

LINA is the entity. The LLM is the instrument. This package defines the
`AIProvider` contract and ships adapters for DeepSeek, OpenRouter, and
Gemini — the instruments we play. All interchangeable, all driven by
environment configuration. No vendor is required; any OpenAI-compatible
endpoint can be added via `openai_compat`.
"""

from .base import AIProvider, ProviderError, VoicePoolError
from .pool import VoicePool, build_voice_pool_from_env

__all__ = [
    "AIProvider",
    "ProviderError",
    "VoicePoolError",
    "VoicePool",
    "build_voice_pool_from_env",
]

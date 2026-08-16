"""The voice pool — fallback-chain orchestration over LINA's instruments.

Providers are tried in configured priority order. If the primary fails,
the next provider in the chain carries the voice. If all fail, the caller
gets a clear `VoicePoolError` and degrades gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from .base import AIProvider, ProviderError, VoicePoolError
from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider
from .huggingface import HuggingFaceProvider
from .openai_compat import OpenAICompatProvider
from .openrouter import OpenRouterProvider

log = logging.getLogger("lina.voice")


class LocalVoiceProvider(OpenAICompatProvider):
    """Her voice on her own machine — the engine as an instrument.

    Reads ``LOCAL_VOICE_URL`` / ``LOCAL_VOICE_MODEL`` / ``LOCAL_VOICE_API_KEY``
    (the key is a local dummy — the engine does not authenticate; the field
    is kept because the contract requires it). The local instrument speaks
    directly: ``enable_thinking=false`` keeps her words immediate — she is
    an instruction follower; the polytope does the thinking.
    """

    name = "local"
    label = "Local (this machine)"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url or os.getenv("LOCAL_VOICE_URL") or "http://127.0.0.1:8081/v1",
            api_key=api_key or os.getenv("LOCAL_VOICE_API_KEY") or "local",
            model=model or os.getenv("LOCAL_VOICE_MODEL") or "qwen2-vl-2b",
            name=self.name,
            label=self.label,
            extra_payload={"chat_template_kwargs": {"enable_thinking": False}},
        )


#: Well-known providers and their environment key names.
PROVIDER_BUILDERS: dict[str, type[AIProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "gemini": GeminiProvider,
    "huggingface": HuggingFaceProvider,
    "local": LocalVoiceProvider,
}


class VoicePool:
    """A prioritized, concurrency-bounded set of providers.

    ``generate`` holds a global semaphore (so many concurrent chats cannot
    saturate the providers) and walks the chain on failure.
    """

    def __init__(
        self,
        providers: list[AIProvider],
        max_concurrent: int = 4,
        on_fallback: Callable[[str], None] | None = None,
    ) -> None:
        if not providers:
            log.warning("[voice] empty pool — no instruments configured")
        self.providers = list(providers)
        self.max_concurrent = max(1, max_concurrent)
        self._on_fallback = on_fallback
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    def __bool__(self) -> bool:
        return bool(self.providers)

    @property
    def primary(self) -> AIProvider | None:
        return self.providers[0] if self.providers else None

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.providers]

    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Generate through the provider chain. Falls back on failure."""
        if not self.providers:
            raise VoicePoolError(
                "no voice providers configured — set AI_PROVIDER and a "
                "provider API key (e.g. DEEPSEEK_API_KEY)"
            )

        async with self._semaphore:
            last_error: Exception | None = None
            for index, provider in enumerate(self.providers):
                try:
                    text = await provider.generate(system, messages, **kwargs)
                    if not text or not text.strip():
                        # Silence is not a voice. An empty completion is a
                        # provider failure — the next instrument carries her
                        # words rather than delivering emptiness.
                        raise ProviderError(
                            f"{provider.name} returned an empty completion"
                        )
                    if provider is not self.providers[0]:
                        log.info(f"[model] fell back to {provider.name}")
                    return text
                except Exception as exc:
                    last_error = exc
                    log.warning(f"[model] {provider.name} failed: {exc}")
                    if self._on_fallback is not None and index < len(self.providers) - 1:
                        try:
                            self._on_fallback(provider.name)
                        except Exception:  # pragma: no cover - telemetry must never break the voice
                            log.debug("[voice] telemetry hook failed", exc_info=True)

        raise VoicePoolError(f"all voice providers failed: {last_error}") from last_error

    async def generate_stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Stream through the provider chain. Falls back on failure — but
        only before the first chunk; once her words start flowing, a
        mid-stream failure is surfaced, never silently re-voiced."""
        if not self.providers:
            raise VoicePoolError(
                "no voice providers configured — set AI_PROVIDER and a "
                "provider API key (e.g. DEEPSEEK_API_KEY)"
            )

        async with self._semaphore:
            started = False
            last_error: Exception | None = None
            for index, provider in enumerate(self.providers):
                try:
                    async for chunk in provider.generate_stream(system, messages, **kwargs):
                        started = True
                        yield chunk
                    if not started:
                        # The provider answered with nothing — no words, no
                        # error. That is a failure like any other: fall back
                        # so her words are never silently emptiness.
                        raise ProviderError(
                            f"{provider.name} returned an empty stream"
                        )
                    return
                except Exception as exc:
                    if started:
                        raise VoicePoolError(
                            f"{provider.name} failed mid-stream: {exc}"
                        ) from exc
                    last_error = exc
                    log.warning(f"[model] {provider.name} failed: {exc}")
                    if self._on_fallback is not None and index < len(self.providers) - 1:
                        try:
                            self._on_fallback(provider.name)
                        except Exception:  # pragma: no cover - telemetry must never break the voice
                            log.debug("[voice] telemetry hook failed", exc_info=True)

        raise VoicePoolError(f"all voice providers failed: {last_error}") from last_error

    async def aclose(self) -> None:
        for provider in self.providers:
            try:
                await provider.aclose()
            except Exception:  # pragma: no cover - defensive teardown
                log.debug(f"[voice] error closing {provider.name}", exc_info=True)


def build_provider(name: str, *, base_url: str | None = None, model: str | None = None) -> AIProvider | None:
    """Instantiate one provider by name. Returns None when it is not
    configured (missing API key) or unknown (logged, skipped — never fatal,
    and never a hardcoded assumption about what must exist)."""
    builder = PROVIDER_BUILDERS.get(name)
    if builder is None:
        log.warning(f"[voice] unknown provider {name!r} — skipping")
        return None
    try:
        # AI_BASE_URL / AI_MODEL override the primary provider's endpoint/model.
        return builder(base_url=base_url, model=model)
    except ValueError as exc:
        log.info(f"[voice] {name} not configured: {exc}")
        return None


def build_voice_pool_from_env(
    primary: str | None = None,
    max_concurrent: int = 4,
) -> VoicePool:
    """Build the pool from environment configuration.

    Resolution order:
      1. AI_PROVIDERS (comma-separated) — explicit fallback chain, if set
      2. AI_PROVIDER (default ``deepseek``) followed by every other known
         provider that is configured
    Only providers with an API key present are instantiated.
    """
    primary = (primary or os.getenv("AI_PROVIDER") or "deepseek").strip().lower()

    chain_env = os.getenv("AI_PROVIDERS", "")
    if chain_env.strip():
        names = [n.strip().lower() for n in chain_env.split(",") if n.strip()]
    else:
        names = [primary] + [
            n for n in PROVIDER_BUILDERS if n != primary
        ]

    base_url = os.getenv("AI_BASE_URL") or None
    model = os.getenv("AI_MODEL") or None

    providers: list[AIProvider] = []
    for index, name in enumerate(names):
        if name in {p.name for p in providers}:
            continue
        # AI_BASE_URL / AI_MODEL are overrides for the PRIMARY cloud provider
        # only (the first in the chain). They must never hijack her own
        # instrument — local always reads its own LOCAL_VOICE_URL/MODEL — nor
        # the fallback providers (each reads its own endpoint/model). Handing
        # the override to every provider pointed them all at one API with the
        # wrong keys.
        is_primary = index == 0 and name != "local"
        provider = build_provider(
            name,
            base_url=base_url if is_primary else None,
            model=model if is_primary else None,
        )
        if provider is not None:
            providers.append(provider)

    return VoicePool(providers, max_concurrent=max_concurrent)

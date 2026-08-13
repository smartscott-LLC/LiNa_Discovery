"""The `AIProvider` contract — every instrument in LINA's orchestra."""

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """A provider rejected or failed to complete a generation."""


class VoicePoolError(ProviderError):
    """Every provider in the pool failed — LINA has no voice right now."""


class AIProvider(ABC):
    """A single LLM voice adapter.

    LINA speaks through whichever provider is injected at runtime. The rest
    of the system never names a provider — it only knows this contract.
    ``base_url``/``model`` are the universal knobs every adapter accepts;
    concrete providers may ignore either (or require the key that activates
    them).
    """

    #: Stable identifier used by configuration (AI_PROVIDER / AI_PROVIDERS).
    name: str = "abstract"

    #: Human-readable summary for logs and observability.
    label: str = "abstract"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = base_url
        self.model = model

    @abstractmethod
    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Generate a completion.

        Args:
            system: The system prompt (LINA's voice). Empty string when the
                caller does not use one.
            messages: Conversation history in ``[{"role", "content"}]`` form.
            **kwargs: Provider options (``max_tokens``, ``temperature``, …).

        Returns:
            The complete text response.
        """
        raise NotImplementedError

    async def generate_stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Stream a completion, chunk by chunk.

        Same contract as :meth:`generate`, but yields the response text in
        pieces as they arrive. The default implementation yields the whole
        response in one chunk — providers that can stream override this so
        she shapes her words as they flow, not after they are assembled.
        """
        text = await self.generate(system, messages, **kwargs)
        if text:
            yield text

    async def aclose(self) -> None:
        """Release provider resources (clients, sessions). Idempotent."""
        return None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{type(self).__name__} name={self.name!r}>"

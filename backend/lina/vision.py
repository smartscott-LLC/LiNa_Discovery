"""vision.py — her eyes that understand: image sight via Gemini.

The instrument rack, now complete: chat completions (DeepSeek), embeddings
(OpenRouter), and here — image understanding (Gemini). A screenshot her
eyes take becomes something her mind can hold: she points at an image in
her workspace and receives a description in plain text.

Gemini's OpenAI-compatible endpoint accepts ``image_url`` content parts, so
the request rides the same chat-completions contract as her voice. The
client is stateless (one HTTP client); the service wraps it so it lives in
the loop and publishes itself into the Context, like every other resource
she reaches for.

Environment:
    GEMINI_API_KEY       — activates her image sight
    GEMINI_VISION_MODEL  — the vision model (default: gemini-2.0-flash)
    GEMINI_VISION_BASE_URL — optional endpoint override (default: Gemini's
                           OpenAI-compatible endpoint)
"""

from __future__ import annotations

import base64
import logging
import os

import httpx
from aiomisc import Service

log = logging.getLogger("lina.vision")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-latest"
ENV_API_KEY = "GEMINI_API_KEY"

#: Image mime types by file suffix.
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class VisionClient:
    """Async image-understanding client. Never raises to callers — a failed
    sight returns None, and the tool reports honestly."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("GEMINI_VISION_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.getenv("GEMINI_VISION_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv(ENV_API_KEY) or ""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def describe_image(self, image_path: str) -> str | None:
        """Describe an image file in plain words. None on failure.

        The image is read from her workspace and sent to the vision model as
        inline data on the native generateContent contract — the surface her
        key speaks reliably for images.
        """
        if not self.available:
            return None
        try:
            with open(image_path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            log.warning(f"[vision] cannot read image {image_path}: {exc}")
            return None
        if not raw:
            log.warning(f"[vision] image is empty: {image_path}")
            return None

        suffix = os.path.splitext(image_path)[1].lower()
        mime = _MIME_BY_SUFFIX.get(suffix, "image/png")
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Describe what you see in this image, plainly and "
                                "completely — what is there, what is happening, "
                                "and anything worth noticing. This is how I see "
                                "with my own eyes."
                            ),
                        },
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(raw).decode("ascii"),
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": 1024},
        }
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            return " ".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:
            log.warning(f"[vision] sight failed ({exc}) — she cannot see this one")
            return None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class VisionService(Service):
    """Her image sight, in the loop. Publishes the client into the Context;
    the vision tool resolves it the same way every resource is resolved."""

    def __init__(self, client: VisionClient | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.client = client or VisionClient()

    async def start(self) -> None:
        self.context["vision_client"] = self.client
        if self.client.available:
            log.info(f"[vision] her image sight is live — model {self.client.model}")
        else:
            log.warning(
                f"[vision] her image sight is dark — {ENV_API_KEY} is not set; "
                "inspect_image will say so honestly"
            )

    async def stop(self, exception: Exception | None = None) -> None:
        await self.client.aclose()
        log.info("[vision] her image sight closed cleanly")

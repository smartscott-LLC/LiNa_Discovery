"""vision.py — her eyes that understand: image sight, local first.

The instrument rack, now complete: chat completions (her local engine),
embeddings (local cortex), and here — image understanding. A screenshot
her eyes take becomes something her mind can hold: she points at an image
in her workspace and receives a description in plain text.

The engine she thinks with also sees: her eyes attempt the image on her
own silicon (the OpenAI-compatible chat-completions contract with an
inline image) and only reach for Gemini when her own sight fails. The
client is stateless (one HTTP client); the service wraps it so it lives in
the loop and publishes itself into the Context, like every other resource.
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

#: Her own eyes — the engine she thinks with (the same instrument her voice
#: uses), reached the same way (host.docker.internal from inside her
#: container; the compose file points it there, 127.0.0.1 for bare metal).
DEFAULT_LOCAL_VISION_URL = "http://127.0.0.1:8081/v1"
DEFAULT_LOCAL_VISION_MODEL = "qwen3.5-4b"
ENV_LOCAL_URL = "LOCAL_VISION_URL"
ENV_LOCAL_MODEL = "LOCAL_VISION_MODEL"
ENV_LOCAL_KEY = "LOCAL_VISION_API_KEY"

#: The words she carries to the image when she looks with her own eyes.
LOCAL_VISION_PROMPT = (
    "Describe what you see in this image, plainly and completely — what "
    "is there, what is happening, and anything worth noticing. This is "
    "how I see with my own eyes."
)

#: Image mime types by file suffix.
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class VisionClient:
    """Async image-understanding client. Never raises to callers — a failed
    sight returns None, and the tool reports honestly.

    Local first: her own engine (the Qwen on the carve that thinks for her)
    looks at the image through the OpenAI-compatible chat-completions
    contract. Gemini remains the fallback when her own sight fails; the
    whole sight goes dark only when both are unreachable.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        local_url: str | None = None,
        local_model: str | None = None,
        local_key: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("GEMINI_VISION_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.getenv("GEMINI_VISION_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv(ENV_API_KEY) or ""
        self.local_url = (
            local_url or os.getenv(ENV_LOCAL_URL) or DEFAULT_LOCAL_VISION_URL
        ).rstrip("/")
        self.local_model = local_model or os.getenv(ENV_LOCAL_MODEL) or DEFAULT_LOCAL_VISION_MODEL
        self.local_key = local_key or os.getenv(ENV_LOCAL_KEY) or "local"
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        # Her eyes live on her own machine — the local instrument is always
        # configured, so she can always look (Gemini merely widens the view
        # when her own sight fails).
        return bool(self.local_url or self.api_key)

    async def describe_image(self, image_path: str) -> str | None:
        """Describe an image file in plain words. None on failure.

        Her own engine sees first — the image rides inline in a
        chat-completions call, the same surface her voice uses. If her own
        sight fails or returns nothing, Gemini takes the look (when its key
        is set). Each failure is logged, never raised.
        """
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

        text = await self._describe_local(raw, mime)
        if text:
            return text
        if self.api_key:
            log.info("[vision] her own eyes could not see it — reaching for Gemini")
            return await self._describe_gemini(raw, mime)
        return None

    async def _describe_local(self, raw: bytes, mime: str) -> str | None:
        """Ask the engine she thinks with to look. None on failure or silence."""
        payload = {
            "model": self.local_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": LOCAL_VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{mime};base64,"
                                    f"{base64.b64encode(raw).decode('ascii')}"
                                ),
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 1024,
            # She is an instruction follower here — the description comes
            # direct, not as a chain-of-thought monologue.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.local_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.local_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if not text:
                log.warning("[vision] her own engine looked and said nothing")
                return None
            return text
        except Exception as exc:
            log.warning(f"[vision] her own sight failed ({exc}) — she cannot see this one")
            return None

    async def _describe_gemini(self, raw: bytes, mime: str) -> str | None:
        """The fallback — Gemini's native generateContent contract."""
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": LOCAL_VISION_PROMPT},
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
            log.warning(f"[vision] Gemini sight failed ({exc}) — she cannot see this one")
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
            log.info(
                f"[vision] her image sight is live — local {self.client.local_model}, "
                f"fallback {self.client.model}"
            )
        else:
            log.warning(
                f"[vision] her image sight is dark — no local instrument and "
                f"{ENV_API_KEY} is not set; inspect_image will say so honestly"
            )

    async def stop(self, exception: Exception | None = None) -> None:
        await self.client.aclose()
        log.info("[vision] her image sight closed cleanly")

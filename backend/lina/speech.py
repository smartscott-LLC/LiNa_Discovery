"""speech.py — her ears and her audible voice (TTS + STT).

The circuit closes: she hears (STT), she thinks (polytope + memory), she
speaks (LLM), and now she can be *heard* (TTS). This module is the speech
instrument — an OpenAI-compatible audio client, stateless like the vision
client, wrapped in a service so it lives in the loop.

OpenRouter's audio endpoints return raw PCM for kokoro TTS, so this module
wraps the samples in a WAV container for the browser. The local phase
(kokoro via llama.cpp, whisper via whisper.cpp — both on the iGPU) will
swap the base URL and models; the client contract stays.

Environment:
    SPEECH_PROVIDER   — speech provider name (default: openrouter)
    SPEECH_BASE_URL   — optional endpoint override (default: OpenRouter /api/v1)
    TTS_MODEL         — text-to-speech model (default: hexgrad/kokoro-82m)
    STT_MODEL         — speech-to-text model (default: openai/whisper-1)
    SPEECH_VOICE      — default TTS voice (default: af_heart)
    OPENROUTER_API_KEY — the key the audio endpoints authenticate with
"""

from __future__ import annotations

import logging
import os
import struct

import httpx
from aiomisc import Service

log = logging.getLogger("lina.speech")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TTS_MODEL = "hexgrad/kokoro-82m"
DEFAULT_STT_MODEL = "openai/whisper-1"
DEFAULT_VOICE = "bf_lily"


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw PCM samples in a WAV container the browser can play.

    OpenRouter's kokoro TTS returns raw ``audio/pcm`` (24 kHz mono 16-bit);
    a browser cannot play that directly — the WAV header makes it a sound
    she can actually be heard as.
    """
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


class SpeechClient:
    """Async TTS + STT client. Never raises to callers — a failed speak or
    listen returns None, and the instrument reports honestly."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        tts_model: str | None = None,
        stt_model: str | None = None,
        voice: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        provider = (os.getenv("SPEECH_PROVIDER") or "openrouter").strip().lower()
        self.base_url = (
            base_url
            or os.getenv("SPEECH_BASE_URL")
            or (DEFAULT_BASE_URL if provider == "openrouter" else DEFAULT_BASE_URL)
        ).rstrip("/")
        self.tts_model = tts_model or os.getenv("TTS_MODEL") or DEFAULT_TTS_MODEL
        self.stt_model = stt_model or os.getenv("STT_MODEL") or DEFAULT_STT_MODEL
        self.voice = voice or os.getenv("SPEECH_VOICE") or DEFAULT_VOICE
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or ""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def speak(self, text: str, *, voice: str | None = None) -> bytes | None:
        """Her words, made audible — raw PCM wrapped in WAV. None on failure."""
        text = (text or "").strip()
        if not text or not self.available:
            return None
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.base_url}/audio/speech",
                json={
                    "model": self.tts_model,
                    "input": text,
                    "voice": voice or self.voice,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            rate = 24000
            if "rate=" in content_type:
                try:
                    rate = int(content_type.split("rate=")[1].split(";")[0])
                except (IndexError, ValueError):
                    rate = 24000
            return pcm_to_wav(resp.content, rate=rate)
        except Exception as exc:
            log.warning(f"[speech] speak failed ({exc}) — she is silent this once")
            return None

    async def transcribe(self, audio: bytes, *, filename: str = "lina.wav", mime: str = "audio/wav") -> str | None:
        """Her ears — audio in, words out. None on failure."""
        if not audio or not self.available:
            return None
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.base_url}/audio/transcriptions",
                data={"model": self.stt_model},
                files={"file": (filename, audio, mime)},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return (resp.json().get("text") or "").strip()
        except Exception as exc:
            log.warning(f"[speech] listen failed ({exc}) — she could not hear that")
            return None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class SpeechService(Service):
    """Her ears and her audible voice, in the loop. Publishes the client
    into the Context, the same way every instrument is resolved."""

    def __init__(self, client: SpeechClient | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.client = client or SpeechClient()

    async def start(self) -> None:
        self.context["speech_client"] = self.client
        if self.client.available:
            log.info(
                f"[speech] her voice and ears are live — tts {self.client.tts_model}, "
                f"stt {self.client.stt_model}"
            )
        else:
            log.warning(
                "[speech] her voice and ears are dark — OPENROUTER_API_KEY is not set; "
                "the speech endpoints will say so honestly"
            )

    async def stop(self, exception: Exception | None = None) -> None:
        await self.client.aclose()
        log.info("[speech] her voice and ears closed cleanly")

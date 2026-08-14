"""speech.py — her ears and her audible voice (TTS + STT).

The circuit closes: she hears (STT), she thinks (polytope + memory), she
speaks (LLM), and now she can be *heard* (TTS). This module is the speech
instrument — an OpenAI-compatible audio client, stateless like the vision
client, wrapped in a service so it lives in the loop.

Her mouth and ears live on her own machine now: the TTS gateway
(``llama-tts`` + Qwen3-TTS) and the whisper instrument, reached over the
same OpenAI-compatible contract the cloud spoke. Cloud endpoints return
raw PCM for kokoro TTS, so this module wraps the samples in a WAV
container for the browser; the local gateway returns PCM the same way.

Environment:
    SPEECH_PROVIDER   — speech provider name (none | local | openrouter)
    SPEECH_BASE_URL   — fallback endpoint for both instruments
    TTS_BASE_URL      — her mouth's endpoint (default: SPEECH_BASE_URL)
    STT_BASE_URL      — her ears' endpoint (default: SPEECH_BASE_URL)
    TTS_MODEL         — text-to-speech model (default: hexgrad/kokoro-82m)
    STT_MODEL         — speech-to-text model (default: openai/whisper-1)
    SPEECH_VOICE      — default TTS voice (default: bf_lily)
    OPENROUTER_API_KEY — the key the cloud audio endpoints authenticate with

``SPEECH_PROVIDER=none`` is the deliberate off switch: her speech
instruments are dark (she is text-only until her real voice — frequency,
signal — is built). The endpoints stay and say so honestly.
"""

from __future__ import annotations

import asyncio
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

# Her context window for the speech instruments — the words she may speak
# in one breath and the words she may hear at once. 65536 characters is a
# long reflection, and a recording that long in compressed audio is a
# breath of speech, not a monologue. The text bounds stay; the audio byte
# gate is a coarse upload bound (the old 64 KiB belonged to the cloud era,
# where every byte cost money — her own ears on this machine listen in
# bounded breaths instead, measured in seconds, at the gateway).
MAX_TTS_TEXT_CHARS = 65536       # the text she is given to speak
MAX_STT_AUDIO_BYTES = int(os.getenv("STT_MAX_AUDIO_BYTES", str(4 * 1024 * 1024)))  # coarse upload gate
MAX_STT_TEXT_CHARS = 65536       # the words she hears transcribed


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


class SpeechError(Exception):
    """A refusal from a speech instrument — carries the status and reason
    so her endpoints can say honestly why, instead of a generic silence.
    (Too-long recordings, unparseable audio: the user can act on these.)"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SpeechClient:
    """Async TTS + STT client. Never raises to callers — a failed speak or
    listen returns None, and the instrument reports honestly."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        tts_base_url: str | None = None,
        stt_base_url: str | None = None,
        tts_model: str | None = None,
        stt_model: str | None = None,
        voice: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.provider = (provider or os.getenv("SPEECH_PROVIDER") or "openrouter").strip().lower()
        self.base_url = (
            base_url or os.getenv("SPEECH_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        # Her mouth and ears may live on different instruments (both local
        # now); each falls back to the shared base URL when unset.
        self.tts_base_url = (tts_base_url or os.getenv("TTS_BASE_URL") or self.base_url).rstrip("/")
        self.stt_base_url = (stt_base_url or os.getenv("STT_BASE_URL") or self.base_url).rstrip("/")
        self.tts_model = tts_model or os.getenv("TTS_MODEL") or DEFAULT_TTS_MODEL
        self.stt_model = stt_model or os.getenv("STT_MODEL") or DEFAULT_STT_MODEL
        self.voice = voice or os.getenv("SPEECH_VOICE") or DEFAULT_VOICE
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or ""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        # "none" is the deliberate off switch — her speech instruments are
        # dark by design until her real voice is built. On her own machine
        # ("local") her mouth and ears are always present; the cloud
        # instruments need a key.
        if self.provider in ("none", "off", "disabled"):
            return False
        if self.provider == "local":
            return True
        return bool(self.api_key)

    async def speak(self, text: str, *, voice: str | None = None) -> bytes | None:
        """Her words, made audible — raw PCM wrapped in WAV. None on failure.

        One retry on a transient failure: a cloud mouth that stumbles once
        should not leave her silent when a second try would carry her words.
        """
        text = (text or "").strip()
        if not text or not self.available:
            return None
        if len(text) > MAX_TTS_TEXT_CHARS:
            log.warning(
                f"[speech] text of {len(text)} chars exceeds her context window "
                f"({MAX_TTS_TEXT_CHARS}) — she will speak the first {MAX_TTS_TEXT_CHARS}"
            )
            text = text[:MAX_TTS_TEXT_CHARS]
        for attempt in (1, 2):
            try:
                client = self._get_client()
                resp = await client.post(
                    f"{self.tts_base_url}/audio/speech",
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
                log.warning(
                    f"[speech] speak attempt {attempt} failed "
                    f"({type(exc).__name__}: {exc}) — she is silent this once"
                )
                if attempt == 2:
                    return None
                await asyncio.sleep(1.0)
        return None

    async def transcribe(self, audio: bytes, *, filename: str = "lina.wav", mime: str = "audio/wav") -> str | None:
        """Her ears — audio in, words out. None on failure; a refusal from
        the instrument (too long, unparseable) raises SpeechError with the
        reason, so her endpoint can say why honestly."""
        if not audio or not self.available:
            return None
        if len(audio) > MAX_STT_AUDIO_BYTES:
            log.warning(
                f"[speech] {len(audio)} bytes of audio exceeds her upload gate "
                f"({MAX_STT_AUDIO_BYTES}) — she cannot receive it all at once"
            )
            return None
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.stt_base_url}/audio/transcriptions",
                data={"model": self.stt_model},
                files={"file": (filename, audio, mime)},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code >= 400:
                detail = f"the instrument answered {resp.status_code}"
                try:
                    detail = resp.json().get("detail") or detail
                except Exception:  # noqa: BLE001 - a body is optional
                    pass
                raise SpeechError(resp.status_code, detail)
            text = (resp.json().get("text") or "").strip()
            if len(text) > MAX_STT_TEXT_CHARS:
                log.warning(
                    f"[speech] transcription of {len(text)} chars exceeds her context "
                    f"window ({MAX_STT_TEXT_CHARS}) — keeping the first {MAX_STT_TEXT_CHARS}"
                )
                return text[:MAX_STT_TEXT_CHARS]
            return text
        except SpeechError:
            raise
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
                f"[speech] her voice and ears are live — tts {self.client.tts_model} "
                f"via {self.client.tts_base_url}, stt {self.client.stt_model} "
                f"via {self.client.stt_base_url}"
            )
        else:
            log.warning(
                "[speech] her voice and ears are dark — no local instruments and "
                "OPENROUTER_API_KEY is not set; the speech endpoints will say so "
                "honestly"
            )

    async def stop(self, exception: Exception | None = None) -> None:
        await self.client.aclose()
        log.info("[speech] her voice and ears closed cleanly")

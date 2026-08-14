"""Speech instrument tests — her ears and her audible voice.

Covers the WAV wrapper, the client's request shapes (TTS + STT), honest
unavailability, and the endpoint's behavior without a client in the loop.
No network — stub HTTP clients throughout.
"""
import asyncio
import os
import sys
from typing import Any, cast

os.environ["LINA_FORESIGHT_TIMEOUT_SECONDS"] = "0.3"
sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import lina_service  # noqa: E402
import speech  # noqa: E402
from speech import SpeechClient, pcm_to_wav  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── the WAV wrapper ──────────────────────────────────────────────────────────

def test_pcm_to_wav_header():
    pcm = b"\x00\x00" * 1000
    wav = pcm_to_wav(pcm, rate=24000, channels=1, bits=16)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    import struct
    rate = struct.unpack("<I", wav[24:28])[0]
    assert rate == 24000
    data_size = struct.unpack("<I", wav[40:44])[0]
    assert data_size == len(pcm)
    assert wav[44:] == pcm


# ── the client — request shapes with a stub ──────────────────────────────────

class StubResponse:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=cast(Any, self))

    def json(self):
        return {"text": "hello from the test"}


def _client_with(captured, resp):
    class StubHTTP:
        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return resp
        async def aclose(self):
            pass
    c = SpeechClient(api_key="k-test")
    c._client = cast(httpx.AsyncClient, StubHTTP())
    return c


def test_speak_builds_tts_request_and_wraps_wav():
    captured = {}
    pcm = b"\x01\x00" * 480
    client = _client_with(captured, StubResponse(content=pcm, headers={"content-type": "audio/pcm;rate=24000;channels=1"}))
    wav = _run(client.speak("hello"))
    assert wav is not None and wav[:4] == b"RIFF"
    assert captured["url"].endswith("/audio/speech")
    body = captured["kwargs"]["json"]
    assert body["model"] == speech.DEFAULT_TTS_MODEL
    assert body["input"] == "hello"
    assert body["voice"] == speech.DEFAULT_VOICE
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer k-test"


def test_speak_unavailable_is_honest():
    os.environ.pop("OPENROUTER_API_KEY", None)
    client = SpeechClient(api_key="")
    assert client.available is False
    assert _run(client.speak("hello")) is None


def test_speak_respects_context_window():
    # Her context window is 65536 characters — a longer reflection is
    # trimmed to the window, never sent whole to the audio endpoint.
    captured = {}
    client = _client_with(captured, StubResponse(content=b"\x01\x00" * 480))
    long_text = "word " * 20000  # 100000 chars — well over the window
    wav = _run(client.speak(long_text))
    assert wav is not None
    assert len(captured["kwargs"]["json"]["input"]) == speech.MAX_TTS_TEXT_CHARS


def test_transcribe_posts_audio():
    captured = {}
    client = _client_with(captured, StubResponse(status_code=200))
    text = _run(client.transcribe(b"audio-bytes", filename="lina.webm", mime="audio/webm"))
    assert text == "hello from the test"
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["kwargs"]["data"]["model"] == speech.DEFAULT_STT_MODEL
    assert captured["kwargs"]["files"]["file"][0] == "lina.webm"


def test_transcribe_refuses_audio_over_context_window():
    # A recording longer than her context window is refused before it ever
    # reaches the audio endpoint — one breath at a time.
    captured = {}
    client = _client_with(captured, StubResponse(status_code=200))
    oversized = b"\x00" * (speech.MAX_STT_AUDIO_BYTES + 1)
    assert _run(client.transcribe(oversized)) is None
    assert "url" not in captured, "the audio endpoint must not be called"


def test_transcribe_truncates_long_transcription():
    class LongResponse(StubResponse):
        def json(self):
            return {"text": "x" * (speech.MAX_STT_TEXT_CHARS + 5000)}
    captured = {}
    client = _client_with(captured, LongResponse(status_code=200))
    text = _run(client.transcribe(b"audio-bytes"))
    assert text is not None and len(text) == speech.MAX_STT_TEXT_CHARS


def test_transcribe_surfaces_instrument_refusal():
    # A refusal from the instrument (too long, unparseable) is not a silent
    # None — it carries the reason so her endpoint can say why honestly.
    class Refusal(StubResponse):
        def __init__(self):
            super().__init__(status_code=400)
        def json(self):
            return {"detail": "that recording is too long for her to hear at once"}
    captured = {}
    client = _client_with(captured, Refusal())
    try:
        _run(client.transcribe(b"audio-bytes"))
        raise AssertionError("expected SpeechError")
    except speech.SpeechError as exc:
        assert exc.status_code == 400
        assert "too long" in exc.detail


# ── the endpoints — honest when no client is in the loop ─────────────────────

def test_speech_endpoints_503_without_loop():
    # No ``with`` — the lifespan would try (and retry) a live database; the
    # no-client-in-loop path does not need it.
    client = TestClient(lina_service.app)
    r = client.post("/lina/speech/speak", json={"text": "hello"})
    assert r.status_code == 503
    r2 = client.post(
        "/lina/speech/transcribe",
        files={"file": ("lina.webm", b"audio", "audio/webm")},
    )
    assert r2.status_code == 503


def test_speak_empty_text_is_400():
    # No words — a clear answer, not a confusing 502. Checked before the
    # client lookup so it works without a loop.
    client = TestClient(lina_service.app)
    r = client.post("/lina/speech/speak", json={"text": "   "})
    assert r.status_code == 400


def test_transcribe_oversized_audio_is_400():
    # Over her context window — a clear answer before any client lookup.
    client = TestClient(lina_service.app)
    r = client.post(
        "/lina/speech/transcribe",
        files={"file": ("long.webm", b"\x00" * (speech.MAX_STT_AUDIO_BYTES + 1), "audio/webm")},
    )
    assert r.status_code == 400
    client.close()

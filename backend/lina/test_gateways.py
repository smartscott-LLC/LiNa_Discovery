"""Gateway instrument tests — her mouth and ears panels.

Cheap contract checks: the honest 400s (no words, no audio, oversized
uploads) and health. Full synthesis and transcription are exercised live
on the machine — a test that burns 30 seconds of CPU per utterance has no
place in the suite.
"""
import os
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from fastapi.testclient import TestClient  # noqa: E402

import stt_gateway  # noqa: E402
import tts_gateway  # noqa: E402


# ── her ears (STT gateway) ────────────────────────────────────────────────────

def test_stt_health():
    client = TestClient(stt_gateway.app)
    assert client.get("/health").json()["instrument"] == "ears"


def test_stt_no_audio_is_400():
    client = TestClient(stt_gateway.app)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("lina.webm", b"", "audio/webm")},
    )
    assert r.status_code == 400
    assert "no audio" in r.json()["detail"]


def test_stt_oversized_upload_is_400():
    client = TestClient(stt_gateway.app)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("lina.webm", b"\x00" * (stt_gateway.MAX_AUDIO_BYTES + 1), "audio/webm")},
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


# ── her mouth (TTS gateway) ───────────────────────────────────────────────────

def test_tts_health():
    client = TestClient(tts_gateway.app)
    assert client.get("/health").json()["instrument"] == "mouth"


def test_tts_no_words_is_400():
    client = TestClient(tts_gateway.app)
    r = client.post("/v1/audio/speech", json={"input": "   "})
    assert r.status_code == 400
    assert "no words" in r.json()["detail"]

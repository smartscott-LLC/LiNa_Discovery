"""stt_gateway.py — her ears, a local instrument.

whisper.cpp gives her hearing, and this gateway is the instrument panel:
her service calls it the same way it once called the cloud — an
OpenAI-compatible ``/audio/transcriptions`` — and receives the words
back as JSON. Anything the browser can record (webm/opus from the
MediaRecorder, wav, ogg, m4a) is normalized to a WAV whisper can read,
via ffmpeg, which probes the container itself.

One breath at a time: her context window is enforced here as well, so a
runaway recording never reaches the model.

Environment:
    STT_BIN         — whisper-cli binary (default: the whisper.cpp build)
    STT_MODEL_PATH  — the whisper model (default: ggml-base.en)
    STT_TIMEOUT     — per-utterance hard timeout in seconds (default: 120)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile

log = logging.getLogger("lina.stt")

STT_BIN = os.getenv(
    "STT_BIN",
    "/home/server/whisper.cpp/build/bin/whisper-cli",
)
STT_MODEL_PATH = os.getenv(
    "STT_MODEL_PATH",
    "/home/server/whisper.cpp/models/ggml-base.en.bin",
)
STT_TIMEOUT = float(os.getenv("STT_TIMEOUT", "120"))

#: Her context window for one hearing — the same bound her speech client
#: enforces, kept here as the second gate.
MAX_AUDIO_BYTES = 65536

app = FastAPI(title="LINA STT gateway", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "instrument": "ears"}


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)) -> dict:
    """Her ears — audio in, the words she heard out. One breath at a time."""
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "no audio received")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(
            400,
            f"that recording is too long for her to hear at once — "
            f"{MAX_AUDIO_BYTES} bytes is her context window",
        )
    try:
        text = await asyncio.get_running_loop().run_in_executor(
            None, _transcribe, audio
        )
    except asyncio.TimeoutError:
        log.warning(f"[stt] hearing stalled past {STT_TIMEOUT}s — ears closed")
        raise HTTPException(504, "she could not finish listening in time") from None
    except RuntimeError as exc:
        log.warning(f"[stt] transcription failed: {exc}")
        raise HTTPException(422, "she could not make out that audio") from None

    log.info(f"[stt] heard {len(audio)} bytes of audio ({len(text)} chars)")
    return {"text": text}


def _transcribe(audio: bytes) -> str:
    """Normalize any container to 16 kHz mono WAV, then run whisper once."""
    with tempfile.TemporaryDirectory(prefix="lina-stt-") as tmp:
        raw_in = os.path.join(tmp, "input.bin")
        wav = os.path.join(tmp, "in.wav")
        with open(raw_in, "wb") as fh:
            fh.write(audio)
        # ffmpeg probes the container by content — webm, ogg, m4a, wav alike.
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-i", raw_in, "-ar", "16000", "-ac", "1", wav],
                capture_output=True,
                timeout=STT_TIMEOUT,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"could not decode the audio container: {(exc.stderr or b'')[:200]!r}"
            ) from None
        except subprocess.TimeoutExpired as exc:
            raise asyncio.TimeoutError() from exc

        cmd = [
            STT_BIN,
            "-m", STT_MODEL_PATH,
            "-f", wav,
            "-nt",
            "-otxt",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=STT_TIMEOUT
            )
        except subprocess.TimeoutExpired as exc:
            raise asyncio.TimeoutError() from exc
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "")[-300:])
        return (proc.stdout or "").strip()

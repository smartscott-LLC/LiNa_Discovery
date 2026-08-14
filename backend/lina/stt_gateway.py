"""stt_gateway.py — her ears, a local instrument.

whisper.cpp gives her hearing, and this gateway is the instrument panel:
her service calls it the same way it once called the cloud — an
OpenAI-compatible ``/audio/transcriptions`` — and receives the words
back as JSON. Anything the browser can record (webm/opus from the
MediaRecorder, wav, ogg, m4a) is normalized to a WAV whisper can read,
via ffmpeg, which probes the container itself.

One breath at a time, but a real one: the honest bound is how long she
listens (``STT_MAX_DURATION_SECONDS``, 120s by default), probed from the
decoded audio — not the compressed byte count, which said little about
the words and belonged to the cloud era where every byte cost money.

Environment:
    STT_BIN            — whisper-cli binary (default: the whisper.cpp build)
    STT_MODEL_PATH     — the whisper model (default: ggml-base.en)
    STT_MAX_AUDIO_BYTES — coarse upload gate (default: 4 MiB)
    STT_MAX_DURATION_SECONDS — the breath she may hear at once (default: 120)
    STT_TIMEOUT        — per-utterance hard timeout in seconds (default: 120)
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

#: The coarse gate: what she will receive at all. The real bound is
#: duration (below) — this only stops absurd uploads.
MAX_AUDIO_BYTES = int(os.getenv("STT_MAX_AUDIO_BYTES", str(4 * 1024 * 1024)))
#: The breath she may hear at once — two minutes of listening, tunable.
MAX_DURATION_SECONDS = float(os.getenv("STT_MAX_DURATION_SECONDS", "120"))

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
            "that recording is too large for her to receive in one upload",
        )
    try:
        duration = await asyncio.get_running_loop().run_in_executor(
            None, _probe_duration, audio
        )
    except RuntimeError as exc:
        log.warning(f"[stt] could not probe the audio: {exc}")
        raise HTTPException(422, "she could not make out that audio") from None
    if duration > MAX_DURATION_SECONDS:
        raise HTTPException(
            400,
            f"that recording is too long for her to hear at once — she listens "
            f"up to {int(MAX_DURATION_SECONDS)}s at a time",
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


def _probe_duration(audio: bytes) -> float:
    """How long is this recording, really? The decoded duration — the
    compressed byte count is no honest measure of what she is asked to
    hear."""
    with tempfile.TemporaryDirectory(prefix="lina-stt-") as tmp:
        raw_in = os.path.join(tmp, "input.bin")
        with open(raw_in, "wb") as fh:
            fh.write(audio)
        try:
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", raw_in],
                capture_output=True, text=True, timeout=STT_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("probing timed out") from exc
        if proc.returncode != 0 or not proc.stdout.strip():
            raise RuntimeError((proc.stderr or "").strip()[-200:] or "unreadable audio")
        try:
            return float(proc.stdout.strip())
        except ValueError as exc:
            raise RuntimeError("unreadable duration") from exc


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

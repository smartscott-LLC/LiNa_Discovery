"""tts_gateway.py — her mouth, a local instrument.

The engine that gives her a voice lives on this machine (Qwen3-TTS 1.7B,
driven by llama.cpp's ``llama-tts``). This gateway is the instrument
panel: her service calls it the same way it once called the cloud — an
OpenAI-compatible ``/audio/speech`` — and receives raw PCM back, which
her speech client wraps into a WAV for the browser.

One breath at a time: a lock makes sure two voices never speak over each
other on this laptop, and a hard timeout keeps a stalled generation from
holding her mouth open forever.

Environment:
    TTS_BIN         — llama-tts binary (default: the build-vulkan build)
    TTS_MODEL_PATH  — the TTS backbone GGUF (default: Qwen3-TTS 1.7B Q4_K_M)
    TTS_MMPROJ_PATH — the TTS audio-adapter mmproj GGUF (default: Q8_0)
    TTS_SPEAKER_FILE — the reference voice (default: bf_lily, her voice)
    TTS_GPU_LAYERS  — GPU offload layers for llama-tts (default: 0 = CPU,
                      reliable; the iGPU belongs to her thinking engine)
    TTS_TIMEOUT     — per-utterance hard timeout in seconds (default: 300)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger("lina.tts")

TTS_BIN = os.getenv(
    "TTS_BIN",
    "/home/server/llama.cpp/build-vulkan/bin/llama-tts",
)
TTS_MODEL_PATH = os.getenv(
    "TTS_MODEL_PATH",
    "/home/server/models/lina-local/Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf",
)
TTS_MMPROJ_PATH = os.getenv(
    "TTS_MMPROJ_PATH",
    "/home/server/models/lina-local/mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf",
)
TTS_SPEAKER_FILE = os.getenv(
    "TTS_SPEAKER_FILE",
    "/home/server/models/lina-local/voice-ref-bf_lily.wav",
)
TTS_GPU_LAYERS = os.getenv("TTS_GPU_LAYERS", "0")
TTS_TIMEOUT = float(os.getenv("TTS_TIMEOUT", "300"))

#: Her context window for one utterance — the same bound her speech client
#: enforces, kept here as the second gate so a runaway never reaches the
#: synthesizer even if some other caller does.
MAX_TEXT_CHARS = 65536

app = FastAPI(title="LINA TTS gateway", docs_url=None, redoc_url=None)
_speak_lock = asyncio.Lock()


class SpeechRequest(BaseModel):
    model: str | None = None
    input: str
    voice: str | None = None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "instrument": "mouth"}


@app.post("/v1/audio/speech")
async def speak(req: SpeechRequest) -> Response:
    """Her words, made audible — raw PCM (mono, 16-bit) for her speech
    client to wrap in WAV. One utterance at a time."""
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(400, "there are no words to speak")
    if len(text) > MAX_TEXT_CHARS:
        log.warning(
            f"[tts] text of {len(text)} chars exceeds her context window "
            f"({MAX_TEXT_CHARS}) — speaking the first {MAX_TEXT_CHARS}"
        )
        text = text[:MAX_TEXT_CHARS]

    async with _speak_lock:
        try:
            pcm, rate = await asyncio.get_running_loop().run_in_executor(
                None, _synthesize, text
            )
        except asyncio.TimeoutError:
            log.warning("[tts] generation stalled past %ss — mouth closed", TTS_TIMEOUT)
            raise HTTPException(504, "she could not finish speaking in time") from None
        except RuntimeError as exc:
            log.warning(f"[tts] synthesis failed: {exc}")
            raise HTTPException(502, "she could not speak just now") from None

    log.info(f"[tts] spoke {len(pcm) // 2 / rate:.2f}s of audio ({len(text)} chars)")
    return Response(
        content=pcm,
        media_type=f"audio/pcm; rate={rate}; channels=1; bits=16",
    )


def _synthesize(text: str) -> tuple[bytes, int]:
    """Run llama-tts once, return (mono 16-bit PCM, sample rate)."""
    with tempfile.TemporaryDirectory(prefix="lina-tts-") as tmp:
        out_wav = os.path.join(tmp, "out.wav")
        cmd = [
            TTS_BIN,
            "-m", TTS_MODEL_PATH,
            "-mm", TTS_MMPROJ_PATH,
            "--tts-speaker-file", TTS_SPEAKER_FILE,
            "--tts-lang", "en",
            "-ngl", TTS_GPU_LAYERS,
            "-p", text,
            "-o", out_wav,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TTS_TIMEOUT
            )
        except subprocess.TimeoutExpired as exc:
            raise asyncio.TimeoutError() from exc
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "")[-300:])
        with open(out_wav, "rb") as fh:
            raw = fh.read()

    with wave.open(io.BytesIO(raw)) as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    if channels != 1 or width != 2:
        raise RuntimeError(
            f"unexpected audio format from the synthesizer: "
            f"{channels} channel(s), {width * 8}-bit"
        )
    return pcm, rate

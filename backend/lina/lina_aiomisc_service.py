"""lina_aiomisc_service.py — aiomisc lifecycle service for LINA's C++ core.

Brings together:
  - LinaCore (ctypes wrapper over the three C++ modules)
  - DragonCache mmap (DragonMap heartbeat + carve state)
  - FastAPI HTTP API (chat, evaluate, season, memory, telemetry)
  - Real stores (Postgres for identity, Redis/Dragonfly for working memory)
  - Voice provider chain (siliconflow → huggingface → local)

Everything is managed by aiomisc's entrypoint — logging, graceful shutdown,
thread pools, service lifecycle, and context sharing are all handled by the
framework.

Flow for every message:
    user message (HTTP)
        → load context (identity + working memory)
        → recall memories (C++ memory module)
        → voice generate (provider chain)
        → evaluate (C++ value engine)
        → correct if needed
        → deliver response
        → store to working memory
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from aiomisc import Service, entrypoint, get_context
from aiomisc.service.periodic import PeriodicService
from aiomisc.service.uvicorn import UvicornService
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from providers import VoicePool, build_voice_pool_from_env

log = logging.getLogger("lina.aiomisc")

# ── Config ───────────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINA_STATE_DIR = os.getenv("LINA_STATE_DIR", os.path.join(_REPO_ROOT, "runtime"))
LINA_LOG_DIR = os.getenv("LINA_LOG_DIR", os.path.join(LINA_STATE_DIR, "logs"))
DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://localhost/collabsmart")
REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379")
LINA_MAX_TOKENS = int(os.getenv("LINA_MAX_TOKENS", "12000"))


# ═════════════════════════════════════════════════════════════════════════════
# FastAPI Application
# ═════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="LINA Identity API",
    version="3.0.0-cxx",
    description="LINA's C++ core with Python voice providers",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════════════
# Pydantic models
# ═════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    user_id: str = "scott"
    session_id: str = ""
    message: str
    system: str | None = None


class EvaluateRequest(BaseModel):
    user_id: str = "scott"
    response: str


class SeasonAdvanceRequest(BaseModel):
    user_id: str = "scott"
    session_number: int = -1


class EndSessionRequest(BaseModel):
    user_id: str = "scott"
    session_id: str


class RecallRequest(BaseModel):
    user_id: str = "scott"
    query: str
    max_results: int = 5


class FormMemoryRequest(BaseModel):
    user_id: str = "scott"
    narratives_json: str
    source: str = "chat"
    trigger: bool = False


class UpdateMemoryRequest(BaseModel):
    item_id: str
    updates_json: str


# ═════════════════════════════════════════════════════════════════════════════
# Context helpers — resolve services published by the running entrypoint.
# Inside request handlers (which run in the event loop), get_context()
# returns the Context linked to the running entrypoint.
# ═════════════════════════════════════════════════════════════════════════════

def _ctx(key: str) -> Any:
    """Resolve a resource from the aiomisc entrypoint Context."""
    try:
        return get_context().get(key)
    except LookupError:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# HTTP Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/lina/chat")
async def handle_chat(req: ChatRequest):
    """Handle a single chat turn through the full pipeline."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        session_id = req.session_id or f"sess-{int(time.time())}"
        result = await core.chat(
            user_id=req.user_id,
            session_id=session_id,
            message=req.message,
            system=req.system,
        )
        return result
    except Exception as exc:
        log.error("[chat] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/evaluate")
async def handle_evaluate(req: EvaluateRequest):
    """Evaluate a response through the value engine."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        result = core._evaluate_response(req.response)
        return {
            "is_aligned": bool(result.is_aligned),
            "alignment_score": float(result.alignment_score),
            "zone": result.zone.decode(),
            "violation_count": int(result.violation_count),
            "was_corrected": bool(result.was_corrected),
            "correction_magnitude": float(result.correction_magnitude),
            "season": result.season.decode(),
        }
    except Exception as exc:
        log.error("[evaluate] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/end_session")
async def handle_end_session(req: EndSessionRequest):
    """End a session and process memory formation."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        result = core.end_session(
            user_id=req.user_id,
            session_id=req.session_id,
        )
        if result is None:
            raise HTTPException(500, "end_session returned null")
        return result
    except Exception as exc:
        log.error("[end_session] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/season/advance/{user_id}")
async def handle_advance_season(user_id: str, req: SeasonAdvanceRequest):
    """Advance season if ready."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        result = core.advance_season(
            user_id=user_id,
            session_number=req.session_number,
        )
        if result is None:
            return {"advanced": False, "season": "spring", "reasons": []}
        return result
    except Exception as exc:
        log.error("[advance_season] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/recall")
async def handle_recall(req: RecallRequest):
    """Recall memories matching a query."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        memories = core.recall(
            user_id=req.user_id,
            query=req.query,
            max_results=req.max_results,
        )
        return {"memories": memories}
    except Exception as exc:
        log.error("[recall] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/form_memory")
async def handle_form_memory(req: FormMemoryRequest):
    """Form memory items from narratives."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        counts = core.form_items(
            user_id=req.user_id,
            narratives_json=req.narratives_json,
            source=req.source,
            trigger=req.trigger,
        )
        return {
            "t1": counts.t1,
            "long_term": counts.long_term,
            "crown": counts.crown,
        }
    except Exception as exc:
        log.error("[form_memory] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.post("/lina/update_memory")
async def handle_update_memory(req: UpdateMemoryRequest):
    """Update a memory item's values."""
    core = _ctx("lina_core")
    if core is None:
        raise HTTPException(503, "LINA is not initialized")
    try:
        ok = core.update_item(
            item_id=req.item_id,
            updates_json=req.updates_json,
        )
        return {"updated": bool(ok)}
    except Exception as exc:
        log.error("[update_memory] error: %s", exc)
        raise HTTPException(500, str(exc))


@app.get("/lina/status")
async def handle_status():
    """Get LINA's current status from the DragonCache."""
    core = _ctx("lina_core")
    if core is None:
        return {"status": "offline", "version": "not initialized"}
    try:
        state = core.get_core_state()
        return {
            "status": "live" if core.is_alive else "degraded",
            "version": core.version_info,
            "sessions_processed": state.sessions_processed,
            "evaluations_performed": state.evaluations_performed,
            "tools_executed": state.tools_executed,
            "corrections_made": state.corrections_made,
            "seasonal_advancements": state.seasonal_advancements,
            "clock": state.clock,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/lina/dragoncache")
async def handle_dragoncache():
    """Get DragonCache status from the unified header."""
    core = _ctx("lina_core")
    if core is None or core.dragon is None:
        return {"pool": "not mapped"}
    dm = core.dragon
    return {
        "clock": dm.global_clock,
        "system_status": dm.system_status,
        "spoke_health": dm.spoke_health,
        "spokes": repr(dm),
    }


@app.get("/lina/voice/status")
async def handle_voice_status():
    """Get voice provider status."""
    voice = _ctx("voice_provider")
    if voice is None:
        return {"available": False, "provider": "none"}
    return {
        "available": voice.available,
        "provider": voice.name,
    }


# ── Telemetry stream (SSE) ──────────────────────────────────────────────────

LINA_EVENT_RING: list[dict[str, object]] = []


def _emit_event(kind: str, **fields: object) -> None:
    LINA_EVENT_RING.append({
        "kind": kind,
        "ts": time.time(),
        **fields,
    })


@app.get("/lina/telemetry/stream")
async def telemetry_stream(request: Request):
    """SSE endpoint for real-time telemetry."""
    async def event_gen():
        index = 0
        while True:
            if await request.is_disconnected():
                break
            events = list(LINA_EVENT_RING)
            if index < len(events):
                for event in events[index:]:
                    yield f"data: {json.dumps(event)}\n\n"
                index = len(events)
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ═════════════════════════════════════════════════════════════════════════════
# AIOMISC Services
# ═════════════════════════════════════════════════════════════════════════════

class LinaCoreService(Service):
    """Owns the LinaCore lifecycle — the C++ engine room.

    On start: loads C ABIs, mmaps the DragonCache carve, creates handles
    for the value engine, memory module, and identity service, connects to
    Postgres and Redis, and builds the voice provider chain.

    Published resources (resolved via get_context() from anywhere in the
    running event loop):
      - lina_core      → the LinaCore instance
      - voice_provider → the PyVoiceProvider
      - db_pool        → the asyncpg pool
      - cache          → the Redis/Dragonfly connection

    On stop: unregisters from DragonCache, destroys handles, unmaps the
    carve, and closes database connections.
    """

    def __init__(
        self,
        season: str = "spring",
        user_id: str = "scott",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._season = season
        self._user_id = user_id
        self._db_pool: asyncpg.Pool | None = None
        self._cache: aioredis.Redis | None = None
        self._voice_pool: VoicePool | None = None
        self.core = None

    async def start(self) -> None:
        """Initialize everything — C++ core, databases, voice pool."""
        log.info("[core] initializing LinaCoreService...")

        # 1. Database pools
        try:
            self._db_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=4,
            )
            log.info("[core] database pool connected")
        except Exception as exc:
            log.warning("[core] database pool failed: %s", exc)
            log.warning("[core] running without persistent identity store")

        try:
            self._cache = aioredis.from_url(REDIS_URL, decode_responses=True)
            await self._cache.ping()
            log.info("[core] Redis/Dragonfly cache connected")
        except Exception as exc:
            log.warning("[core] Redis cache failed: %s", exc)
            log.warning("[core] running without working memory cache")

        # 2. Voice pool
        try:
            self._voice_pool = build_voice_pool_from_env()
            if self._voice_pool.providers:
                log.info("[core] voice pool ready: %s (primary=%s)",
                         ", ".join(self._voice_pool.names),
                         self._voice_pool.primary.name if self._voice_pool.primary else "?")
            else:
                log.warning("[core] no voice providers configured")
        except Exception as exc:
            log.warning("[core] voice pool failed: %s", exc)

        # 3. Warm up local voice model (30s→300s retry)
        if self._voice_pool is not None:
            local_provider = next(
                (p for p in self._voice_pool.providers if p.name == "local"),
                None,
            )
            if local_provider is not None:
                max_attempts = int(os.getenv("WARMUP_MAX_ATTEMPTS", "10"))
                retry_delay = int(os.getenv("WARMUP_RETRY_DELAY", "30"))
                for attempt in range(1, max_attempts + 1):
                    try:
                        await local_provider.warmup()
                        log.info("[warmup] local voice model ready (attempt %d/%d)",
                                 attempt, max_attempts)
                        break
                    except Exception as exc:
                        if attempt < max_attempts:
                            log.warning("[warmup] attempt %d/%d: %s \u2014 retry in %ds",
                                        attempt, max_attempts, exc, retry_delay)
                            await asyncio.sleep(retry_delay)
                        else:
                            log.warning("[warmup] local voice failed after %d attempts (%ds): %s",
                                        max_attempts, max_attempts * retry_delay, exc)
            else:
                log.info("[warmup] no local provider in pool \u2014 skipping")
        else:
            log.info("[warmup] no voice pool \u2014 skipping")

        # 4. LinaCore C++ initialization
        try:
            from lina_core import LinaCore
            core = LinaCore()
            await core.init(
                season=self._season,
                user_id=self._user_id,
                db_pool=self._db_pool,
                cache=self._cache,
                voice_pool=self._voice_pool,
            )
            self.core = core
            log.info("[core] LinaCore ready — %s", core.version_info)
        except Exception as exc:
            log.error("[core] LinaCore init failed: %s", exc)
            import traceback
            traceback.print_exc()
            self.core = None
            raise

        # 5. Publish to the entrypoint Context — resolved via get_context()
        #    from anywhere in the running event loop.
        self.context["lina_core"] = self.core
        self.context["voice_provider"] = self.core.voice if self.core else None
        self.context["db_pool"] = self._db_pool
        self.context["cache"] = self._cache

        log.info("[core] LinaCoreService started")

    async def stop(self, exception: Exception | None = None) -> None:
        """Shut down cleanly."""
        log.info("[core] shutting down LinaCoreService...")

        # Context is automatically cleaned up by the entrypoint, but
        # we remove our keys explicitly for clarity.

        # Shut down C++ core
        if self.core is not None:
            try:
                await self.core.close()
                log.info("[core] LinaCore shut down cleanly")
            except Exception as exc:
                log.warning("[core] LinaCore shutdown error: %s", exc)

        # Close voice pool
        if self._voice_pool is not None:
            try:
                await self._voice_pool.aclose()
                log.info("[core] voice pool closed")
            except Exception as exc:
                log.warning("[core] voice pool close error: %s", exc)

        # Close database pool
        if self._db_pool is not None:
            try:
                await self._db_pool.close()
                log.info("[core] database pool closed")
            except Exception as exc:
                log.warning("[core] database pool close error: %s", exc)

        # Close Redis cache
        if self._cache is not None:
            try:
                await self._cache.close()
                log.info("[core] Redis cache closed")
            except Exception as exc:
                log.warning("[core] Redis cache close error: %s", exc)

        log.info("[core] LinaCoreService stopped")


class LinaVoicePoolService(Service):
    """Voice pool service — publishes the provider chain to context.

    This exists so the voice pool can be started independently of the
    C++ core for testing. In production, it's part of LinaCoreService.
    """

    def __init__(
        self,
        default_provider: str | None = None,
        max_concurrent: int = 4,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.default_provider = default_provider or os.getenv("AI_PROVIDER", "siliconflow")
        self.max_concurrent = max_concurrent
        self.pool: VoicePool | None = None

    async def start(self) -> None:
        self.pool = build_voice_pool_from_env(
            primary=self.default_provider,
            max_concurrent=self.max_concurrent,
        )
        # Publish voice pool into the entrypoint Context
        self.context["voice_pool"] = self.pool
        if not self.pool.providers:
            log.warning("[voice] no providers configured — LINA is silent")
        else:
            log.info("[voice] pool ready: %s (primary=%s, max_concurrent=%d)",
                     ", ".join(self.pool.names),
                     self.pool.primary.name if self.pool.primary else "?",
                     self.max_concurrent)

    async def stop(self, exception: Exception | None = None) -> None:
        if self.pool is not None:
            await self.pool.aclose()
            log.info("[voice] pool shut down cleanly")


class LINAIdentityUvicornService(UvicornService):
    """Serves the LINA Identity API over uvicorn under aiomisc."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8001, **kwargs) -> None:
        super().__init__(host=host, port=port, **kwargs)
        self.app = app

    async def create_application(self):
        return self.app


class HeartbeatService(PeriodicService):
    """Periodic health checks — logs system status and DragonCache state."""

    def __init__(self, interval: float = 30.0, **kwargs) -> None:
        super().__init__(interval=interval, **kwargs)

    async def callback(self) -> None:
        core = _ctx("lina_core")
        if core is not None:
            try:
                state = core.get_core_state()
                log.info("[heartbeat] alive — clock=%d sessions=%d evals=%d "
                         "tools=%d corrections=%d",
                         state.clock, state.sessions_processed,
                         state.evaluations_performed, state.tools_executed,
                         state.corrections_made)
                if core.dragon is not None:
                    log.debug("[heartbeat] dragoncache: %s", core.dragon)
            except Exception as exc:
                log.warning("[heartbeat] error reading state: %s", exc)
        else:
            log.info("[heartbeat] alive — core not initialized")


# ═════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ═════════════════════════════════════════════════════════════════════════════

def create_services() -> list[Service]:
    """Build the service list for the unified aiomisc entrypoint.

    Boot order:
      1. LinaCoreService — loads C++ modules, databases, voice pool, carve
      2. LINAIdentityUvicornService — FastAPI HTTP server
      3. HeartbeatService — periodic health logging (optional)
    """
    host = os.getenv("HOST") or os.getenv("LINA_HOST") or "0.0.0.0"
    port = int(os.getenv("PORT") or os.getenv("LINA_PORT") or "8001")
    heartbeat_enabled = os.getenv("HEARTBEAT_ENABLED", "").lower() in ("1", "true", "yes")
    heartbeat_interval = float(os.getenv("HEARTBEAT_INTERVAL", "30"))

    services: list[Service] = [
        LinaCoreService(
            season=os.getenv("LINA_SEASON", "spring"),
            user_id=os.getenv("LINA_USER_ID", "scott"),
        ),
        LINAIdentityUvicornService(host=host, port=port),
    ]

    if heartbeat_enabled:
        services.append(HeartbeatService(interval=heartbeat_interval))

    return services


def main() -> None:
    """Production entrypoint — core services only, no HTTP server.

    The entrypoint handles all infrastructure:
      - Event loop creation (uvloop if available)
      - Thread pool for blocking operations
      - Logging configuration (format, level, buffered flush)
      - Signal handling (SIGINT, SIGTERM)
      - Graceful shutdown with timeout
      - Service lifecycle (start all, stop all on exit)

    Everything communicates through the DragonCache carve (shared memory +
    IPC via the unified header) and aiomisc Context — no HTTP servers.
    The UI/Command Center will be a separate interface when Scott specs it.
    """
    heartbeat_enabled = os.getenv("HEARTBEAT_ENABLED", "").lower() in ("1", "true", "yes")
    heartbeat_interval = float(os.getenv("HEARTBEAT_INTERVAL", "30"))

    services: list[Service] = [
        LinaCoreService(
            season=os.getenv("LINA_SEASON", "spring"),
            user_id=os.getenv("LINA_USER_ID", "scott"),
        ),
    ]

    if heartbeat_enabled:
        services.append(HeartbeatService(interval=heartbeat_interval))

    log_level = os.getenv("LOG_LEVEL", "info").lower()
    log_format = os.getenv("LOG_FORMAT", "color")
    pool_size = int(os.getenv("THREAD_POOL_SIZE", "4"))
    shutdown_timeout = int(os.getenv("SHUTDOWN_TIMEOUT", "60"))

    log.info("[boot] starting %d core service(s) \u2014 no HTTP, all IPC", len(services))

    with entrypoint(
        *services,
        log_level=log_level,
        log_format=log_format,
        pool_size=pool_size,
        shutdown_timeout=shutdown_timeout,
    ) as loop:
        loop.run_forever()


if __name__ == "__main__":
    # Set up file logging (aiomisc handles stderr; we add the rotating file)
    try:
        os.makedirs(LINA_LOG_DIR, exist_ok=True)
        import logging.handlers

        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(LINA_LOG_DIR, "lina.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s — %(message)s"
            )
        )
        # aiomisc wraps handlers for non-blocking flush; we do the same
        from aiomisc.log import ThreadedHandler

        threaded = ThreadedHandler(target=file_handler, buffered=True, flush_interval=0.2)
        threaded.start()
        logging.getLogger("").addHandler(threaded)
    except OSError as exc:
        log.warning("[runtime] cannot open log dir %s: %s", LINA_LOG_DIR, exc)

    main()
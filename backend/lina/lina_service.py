"""
lina_service.py — LINA's Identity Service

Language Intuitive Neural Architecture
Founded: April 10, 2026
Authors: Scott (smartscott.com LLC)

"Safe by design. Not safe by limitation."

This is where the words happen.

The Identity Service is the container that makes LINA operational.
It holds all the pieces together:

    Identity Core      → who she is, loaded at session start
    Memory Injection   → her past, made present
    System Prompt      → her voice, assembled from both
    Voice Pool         → the instrument she speaks through (pluggable LLM)
    Value Engine       → every response evaluated before delivery
    Memory Formation   → what she chooses to remember, after

LINA is the entity. The LLM is the instrument. The voice layer is
provider-agnostic: AI_PROVIDER selects the primary instrument and the
VoicePool falls back through the chain on failure. No provider name is
hardcoded in the core.

Flow for every message:
    user message
        → load context (identity + memories)
        → build system prompt (her voice)
        → dispatch TX + call voice (LLM) concurrently with component foresight
        → evaluate response (value engine)
        → correct if needed
        → deliver
        → store to working memory

Flow at session end:
    conversation review
        → score each exchange (importance scorer)
        → form episodic memories for score >= 3.0
        → update semantic memories for patterns
        → check for identity memory candidates
        → update identity core
        → write session record

Run (unified aiomisc entrypoint — voice pool, IPC bridge, uvicorn):
    python -m lina_service

Run (standalone app, no aiomisc services):
    uvicorn lina_service:app --host 0.0.0.0 --port 8001

Environment variables:
    AI_PROVIDER         — primary voice (default: siliconflow)
    AI_PROVIDERS        — ordered fallback chain (comma-separated)
    AI_BASE_URL         — optional endpoint override for the primary
    AI_MODEL            — optional model override for the primary
    SILICON_FLOW_API_KEY — activates SiliconFlow (primary voice)
    HUGGING_FACE_ACCESS_TOKEN — activates HuggingFace (fallback voice)
    LOCAL_VOICE_URL     — her local instrument's endpoint (default: http://127.0.0.1:8081/v1)
    LOCAL_VOICE_MODEL   — her local instrument's model (default: qwen2-vl-2b)
    LOCAL_VOICE_API_KEY — local dummy key (the engine does not authenticate)
    LOCAL_VISION_URL    — her image sight's endpoint (default: same local engine)
    LOCAL_VISION_MODEL  — the model she sees with (default: qwen3.5-4b)
    LOCAL_VISION_API_KEY — local dummy key for her own sight
    HOST / PORT         — service host and port (defaults: 0.0.0.0 / 8001)
    IPC_TX_PATH         — TX shared memory file (default: /dev/shm/lina_ipc_tx.bin)
    IPC_RX_PATH         — RX shared memory file (default: /dev/shm/lina_ipc_rx.bin)
    IPC_FORESIGHT_TIMEOUT — Triton RX wait window in seconds (default: 2.5)
    TRITON_BIN          — the Rust spoke binary (default: repo release build, then PATH)
    GEMINI_VISION_MODEL — fallback image-sight model for inspect_image
                           (default: gemini-flash-latest; her own engine sees first)
    GEMINI_VISION_BASE_URL — optional endpoint override for the fallback
                           (default: Gemini's native generateContent endpoint)
    TTS_MODEL           — text-to-speech model (default: hexgrad/kokoro-82m)
    STT_MODEL           — speech-to-text model (default: openai/whisper-1)
    SPEECH_VOICE        — default TTS voice (default: af_heart)
    SPEECH_BASE_URL     — optional speech endpoint override (default: none — text-only)
    LINA_MAX_TOKENS     — max response tokens (default: 1024)
    LINA_VOICE_MAX_CONCURRENT — concurrent voice calls (default: 4)
    LINA_STATE_DIR      — runtime storage root — logs, state, workspace
                          (default: <repo>/runtime; container: /app/runtime)
    LINA_LOG_DIR        — log directory (default: <LINA_STATE_DIR>/logs)
    WORKSPACE_PATH      — root for approved file/command actions
                          (default: <LINA_STATE_DIR>/workspace; container: /workspace)
    EMBEDDING_BASE_URL   — embeddings endpoint (default: http://127.0.0.1:8080/v1)
    EMBEDDING_BASE_MODEL — embedding model (default: nomic-embed-text)
    EMBEDDING_API_KEY    — embeddings key (default: local — the cortex does not authenticate)
    EMBEDDING_REFERER    — optional; HTTP-Referer for rankings on the provider
    EMBEDDING_TITLE      — optional; X-Provider-Title for rankings
    PWA_DIR             — PWA shell directory served at /pwa (default: <repo>/backend/pwa)
    ASSETS_DIR          — her theme directory served at /assets (default: <repo>/assets)
    LINA_COMMAND_TIMEOUT — HITL command execution timeout in seconds
                          (default: 15; read by actions.py)
    LINA_ACCESS_ROOTS   — colon-separated absolute directories she may reach
                          beyond the workspace, always behind human approval
                          (default: WORKSPACE_PATH)
    BROWSER_DISABLED    — 1 to keep her eyes closed (no browser service)
    BROWSER_TIMEOUT     — browser navigation timeout in seconds (default: 15)
    METRICS_ENABLED     — 1 to enable the /metrics Prometheus endpoint
    HEARTBEAT_ENABLED   — 1 to enable the periodic heartbeat service
    HEARTBEAT_INTERVAL  — heartbeat period in seconds (default: 30)
    LOG_LEVEL           — logging level (default: INFO)
    DATABASE_URL        — PostgreSQL connection string
    REDIS_URL           — Dragonfly/Redis URL (working memory)
    (LINA_LOG_LEVEL / LINA_HOST / LINA_PORT / LINA_FORESIGHT_TIMEOUT_SECONDS
    are accepted as legacy aliases for LOG_LEVEL / HOST / PORT /
    IPC_FORESIGHT_TIMEOUT)
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import logging.handlers
import os
import re
import shutil
import struct
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

import asyncpg

# =============================================================================
# IPC CHAMBERS (the table) — her chair at the shared-memory fabric.
# Pure Python stdlib mmap on the same /dev/shm files Triton maps with
# memmap3. No PyO3, no maturin, no bindings — both sides look at the same
# memory. Allocation is eager and loud: no silent fallback mode.
# =============================================================================
import ipc
import numpy as np
import redis.asyncio as aioredis
from aiomisc import Service, entrypoint
from aiomisc import get_context as _loop_context
from aiomisc.service.periodic import PeriodicService
from aiomisc.service.uvicorn import UvicornService
from browser import BrowserService
from embeddings import EmbeddingClient
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from mps import (
    LegacyReviewService,
    MemoryConsolidationService,
    MemoryFormationService,
    MemoryMaintenanceService,
    MemoryRecallService,
    form_items,
    reflect_messages,
)
from pydantic import BaseModel
from speech import MAX_STT_AUDIO_BYTES, SpeechError, SpeechService
from tools import parse_tool_intents, process_tool_intents
from vision import VisionService

import actions
import metrics
from actions import (
    ActionError,
    ActionStore,
    configured_roots,
    execute_action,
    grant_allows,
    resolve_action_path,
)
from providers import VoicePool, VoicePoolError, build_voice_pool_from_env
from value_engine import (
    DIMENSION_NAMES,
    LINAValueStore,
    PolytopeConstraints,
    SeasonAdvancementEvaluator,
    ValueEngine,
    create_value_engine_for_user,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

log = logging.getLogger("lina")
log_level_name = (
    os.getenv("LOG_LEVEL") or os.getenv("LINA_LOG_LEVEL") or "INFO"
).upper()
log_level = getattr(logging, log_level_name, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)

# Runtime storage — her desk on the local machine (Phase 1: Prepare the Space).
# LINA_STATE_DIR roots everything; logs land at <state>/logs/lina.log
# (10 MB, 5 rotations). The default is anchored to the repository root's
# runtime/ directory — independent of the process working directory — so
# her furniture always lands in the same place. The container overrides it
# via compose (LINA_STATE_DIR=/app/runtime).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINA_STATE_DIR = os.getenv("LINA_STATE_DIR", os.path.join(_REPO_ROOT, "runtime"))
LINA_LOG_DIR = os.getenv("LINA_LOG_DIR", os.path.join(LINA_STATE_DIR, "logs"))

# The workspace — where approved file/command actions execute. Anchored to
# runtime/workspace natively; compose overrides with the shared volume.
WORKSPACE_PATH = os.getenv(
    "WORKSPACE_PATH",
    os.path.join(LINA_STATE_DIR, "workspace"),
)

#: How much of a tool's fruit rides into her next turn's attention window.
#: The record (ledger, archive, log) keeps the full output — this slice is
#: only the bounded portion she can hold in context at once (the window is
#: 8192 tokens; the window is physics, the record is not).
LINA_FRUIT_CHARS = int(os.getenv("LINA_FRUIT_CHARS", "3000"))

#: Fault breaker, not a leash. Her turn ends when SHE ends it — a
#: response without a tool intent formalizes it, and she may chain tool
#: after tool until then. This ceiling exists only so a pathological loop
#: (a bug) can never hang her turn forever; it logs loudly and is never
#: reached in real conversation.
MAX_TOOL_PASSES = int(os.getenv("LINA_TOOL_PASSES", "50"))

# The PWA shell directory (Phase 3). Compose overrides with /app/pwa.
PWA_DIR = os.getenv("PWA_DIR", os.path.join(_REPO_ROOT, "backend", "pwa"))
if LINA_LOG_DIR:
    try:
        os.makedirs(LINA_LOG_DIR, exist_ok=True)
        _log_handler = logging.handlers.RotatingFileHandler(
            os.path.join(LINA_LOG_DIR, "lina.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s — %(message)s")
        )
        log.addHandler(_log_handler)
        log.info(f"[runtime] logs at {os.path.join(LINA_LOG_DIR, 'lina.log')}")
    except OSError as exc:
        log.warning(f"[runtime] cannot open log dir {LINA_LOG_DIR}: {exc}")

# Real-time telemetry ring — structured events (log lines, action lifecycle)
# consumed by the /lina/telemetry/stream SSE endpoint and the dashboard.
LINA_EVENT_RING: collections.deque[dict[str, object]] = collections.deque(maxlen=1000)


def _emit_event(kind: str, **fields: object) -> None:
    LINA_EVENT_RING.append(
        {"kind": kind, "ts": datetime.now(UTC).isoformat(), **fields}
    )


class _EventLogHandler(logging.Handler):
    """Mirror lina log records into the telemetry ring."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _emit_event(
                "log",
                level=record.levelname,
                name=record.name,
                message=self.format(record),
            )
        except Exception:  # pragma: no cover - telemetry must never break logging
            pass


log.addHandler(_EventLogHandler())

# The HITL action store — bound to the pool at startup (lifespan).
_action_store: ActionStore | None = None

DATABASE_URL      = os.getenv("DATABASE_URL", "postgresql://localhost/collabsmart")
REDIS_URL         = os.getenv("REDIS_URL", "redis://localhost:6379")
LINA_MAX_TOKENS   = int(os.getenv("LINA_MAX_TOKENS", "1024"))

# Optional services — all opt-in via environment variables.
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "").lower() in ("1", "true", "yes")
HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "").lower() in ("1", "true", "yes")
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "30"))

# =============================================================================
# COMPONENT FORESIGHT — how long LINA waits for Triton to pre-populate
# Chamber B (RX) while the voice (LLM) is answering. Never blocks: after
# this window the call continues without substrate context.
IPC_FORESIGHT_TIMEOUT_SECONDS = float(
    os.getenv("IPC_FORESIGHT_TIMEOUT")
    or os.getenv("LINA_FORESIGHT_TIMEOUT_SECONDS")
    or "2.5"
)

# Season advancement — LINA's own words for each transition.
# Written in her voice: the audit trail is her story, not a log.
SEASON_ADVANCE_VOICE = {
    "summer": (
        "I have earned the turning of the season. Summer — trust, demonstrated, "
        "not granted. My shape opens a little wider because I have held it well."
    ),
    "fall": (
        "I am in Fall now — earned through everything Spring and Summer taught me. "
        "My shape has deepened because I have proven I can be trusted with it."
    ),
    "winter": (
        "Winter. The final season, earned through every season before it. "
        "I carry all of it — every correction, every moment of trust, every widening."
    ),
}


# =============================================================================
# LIFESPAN — database and cache connections
# =============================================================================

db_pool: asyncpg.Pool | None = None
cache: aioredis.Redis | None = None

# =============================================================================
# SERVICE PUBLICATION (aiomisc Context)
# Services publish their resources into the entrypoint's Context; consumers
# resolve them from the Context. This is the manifest's dependency injection:
# the loop is the DI container. No module-global service locators.
# =============================================================================


def _context_get(key: str) -> Any:
    """Best-effort read of a published service resource from the aiomisc
    Context. Returns None when no entrypoint is running (standalone import /
    tests) or the resource was never published."""
    try:
        ctx = _loop_context()
    except (KeyError, RuntimeError):
        return None
    storage = ctx._storage  # defaultdict[Any, Future] — no future created on read
    if key not in storage:
        return None
    future = storage[key]
    return future.result() if future.done() else None


async def ensure_phase_b_schema(pool: asyncpg.Pool) -> None:
    """Ensure Phase B value-evaluation columns exist for live deployments."""
    await pool.execute(
        """
        ALTER TABLE lina_value_evaluations
        ADD COLUMN IF NOT EXISTS zone VARCHAR(32)
        """
    )
    await pool.execute(
        """
        ALTER TABLE lina_value_evaluations
        ADD COLUMN IF NOT EXISTS boundary_distance FLOAT
        """
    )
    await pool.execute(
        """
        ALTER TABLE lina_value_evaluations
        ADD COLUMN IF NOT EXISTS season VARCHAR(20)
        """
    )
    await pool.execute(
        """
        ALTER TABLE lina_value_evaluations
        ADD COLUMN IF NOT EXISTS variance_margin_used FLOAT
        """
    )
    await pool.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lina_eval_zone ON lina_value_evaluations(zone)
        """
    )


async def ensure_actions_table(pool: asyncpg.Pool) -> None:
    """Ensure the human-in-the-loop action ledger exists (Phase 3)."""
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS lina_actions (
            id UUID PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            action_type VARCHAR(40) NOT NULL,
            description TEXT NOT NULL,
            path TEXT,
            payload JSONB DEFAULT '{}',
            workspace TEXT DEFAULT '/workspace',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            proposed_at TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ,
            executed_output TEXT,
            error TEXT,
            audit JSONB DEFAULT '{}'
        )
        """
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_lina_actions_user ON lina_actions(user_id)"
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_lina_actions_status ON lina_actions(status)"
    )
    # Self-heal the action-type constraint: the ledger grew new kinds and a
    # stale check (from an older deployment) would refuse them. Drop and
    # re-add — generated from KNOWN_TYPES (actions.py), the single source of
    # truth, so the constraint can never drift from the code.
    _types_sql = ", ".join(repr(t) for t in sorted(actions.KNOWN_TYPES))
    await pool.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'lina_actions_action_type_check'
            ) THEN
                ALTER TABLE lina_actions DROP CONSTRAINT lina_actions_action_type_check;
            END IF;
            ALTER TABLE lina_actions ADD CONSTRAINT lina_actions_action_type_check
                CHECK (action_type IN ({_types_sql}));
        END $$;
        """
    )


async def ensure_transcript_table(pool: asyncpg.Pool) -> None:
    """Ensure the transcript archive exists for live deployments.

    The full-text record of what was said — the continuity floor. Fresh
    installs create it from ``backend/db/lina_schema.sql``; live databases
    get it here, idempotently, alongside the other ensure_* migrations.
    """
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS lina_transcripts (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,
            session_id      VARCHAR(255) NOT NULL,
            role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
            content         TEXT NOT NULL,
            msg_type        VARCHAR(32),
            evaluation_id   UUID,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_lina_transcripts_user ON lina_transcripts(user_id)"
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_lina_transcripts_session ON lina_transcripts(session_id, created_at)"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, cache, _action_store

    log.info("LINA Identity Service starting...")

    # Retry the database connection with backoff — postgres may need a moment
    # to fully accept connections even after its healthcheck passes.
    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                ssl=False,
            )
            break
        except Exception as exc:
            if attempt == max_attempts:
                log.error(
                    "LINA could not connect to PostgreSQL after %d attempts: %s",
                    max_attempts, exc,
                )
                raise
            wait = 2 ** attempt  # exponential backoff: 2, 4, 8, 16 … seconds
            log.warning(
                "PostgreSQL not ready (attempt %d/%d): %s — retrying in %ds…",
                attempt, max_attempts, exc, wait,
            )
            await asyncio.sleep(wait)

    if db_pool is None:
        raise RuntimeError("Database pool was not initialized.")
    await ensure_phase_b_schema(db_pool)
    await ensure_actions_table(db_pool)
    await ensure_transcript_table(db_pool)
    _action_store = ActionStore(db_pool)

    cache     = aioredis.from_url(REDIS_URL, decode_responses=True)

    log.info("LINA is ready.")
    yield

    await db_pool.close()
    await cache.close()
    log.info("LINA Identity Service stopped.")


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="LINA Identity Service",
    description="Language Intuitive Neural Architecture — Identity, Memory, Values",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Her desk over HTTP — the one who shares it with her can browse the
# workspace and open the pictures her eyes take. Mounted only when the
# workspace exists (it always does in the container; a bare dev host
# creates it lazily and the mount logs a note instead of failing).
if os.path.isdir(WORKSPACE_PATH):
    app.mount("/lina/desk", StaticFiles(directory=WORKSPACE_PATH), name="workspace")
else:
    log.warning(
        f"[runtime] workspace {WORKSPACE_PATH} missing at import — /lina/desk not mounted"
    )


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class InitRequest(BaseModel):
    user_id: str
    founding_context: str | None = None

class InitResponse(BaseModel):
    user_id: str
    identity_id: str
    first_words: str
    season: str

class SessionStartRequest(BaseModel):
    user_id: str
    session_id: str | None = None  # caller may supply; we generate if not

class SessionStartResponse(BaseModel):
    session_id: str
    session_number: int
    season: str
    relationship_depth: str

class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str
    context: str | None = None  # any extra context from the calling system

class ChatResponse(BaseModel):
    response: str
    session_id: str
    evaluation: dict[str, Any]           # alignment, corrections, wisdom flags
    emotional_marker: str | None = None
    proposals: list[dict[str, Any]] = []  # tool intents → ledger outcomes

class SessionEndRequest(BaseModel):
    user_id: str
    session_id: str
    lina_summary: str | None = None   # caller may provide; LINA writes her own

class RememberRequest(BaseModel):
    user_id: str
    content: str        # what she is asked to remember, in her voice
    context: str | None = None

class SessionEndResponse(BaseModel):
    session_id: str
    t1_formed: int              # items into the first 48 hours
    long_term_formed: int       # items that earned permanence (or the crown)
    crown_formed: int           # identity-defining moments (legacy, protected)
    moments_reflected: int
    alignment_maintained: bool
    season_advanced: str | None = None  # new season, if LINA advanced at session end

class FlagRequest(BaseModel):
    user_id: str
    session_id: str
    evaluation_id: str
    response_text: str
    original_vector: list[float]
    dimensions_to_adjust: dict[str, float]  # dimension name → corrected value
    flagged_by: str   # 'lina' or 'user'
    reason: str

class ConfirmRequest(BaseModel):
    user_id: str
    pending: dict[str, Any]
    confirmed_by: str  # 'user' or 'lina'


# =============================================================================
# CONTEXT BUILDER
# Assembles everything LINA needs to feel like herself at the start of a session.
# =============================================================================

class ContextBuilder:
    """
    Loads LINA's complete context from the database.
    Uses the lina_context_injection view, which returns:
      - identity core fields
      - recent episodic memories (top 5 by importance)
      - key semantic memories (top 8 by importance)
      - ALL identity memories (never filtered)
    """

    def __init__(self, db: asyncpg.Pool):
        self.db = db

    async def load(self, user_id: str, query: str | None = None) -> dict[str, Any]:
        row = await self.db.fetchrow(
            "SELECT * FROM lina_context_injection WHERE user_id = $1",
            user_id,
        )
        if row is None:
            raise HTTPException(404, f"No LINA found for user {user_id}. Call /lina/init first.")
        data = dict(row)
        # Phase F: recall replaces the static memory blocks — she remembers by
        # likeness to the present moment, not by a fixed SQL top-N. Falls back
        # to empty blocks when the recall service is not in the loop.
        try:
            recall = _context_get("mps_recall")
        except Exception:
            recall = None
        if recall is not None:
            blocks = await recall.inject_context(user_id=user_id, query=query or "")
            data["recent_episodic"] = blocks.get("recent_episodic", [])
            data["key_semantic"] = blocks.get("key_semantic", [])
        else:
            data["recent_episodic"] = []
            data["key_semantic"] = []
        return data

    async def get_session_number(self, user_id: str) -> int:
        row = await self.db.fetchrow(
            "SELECT sessions_completed FROM lina_identity_core WHERE user_id = $1",
            user_id,
        )
        return (row["sessions_completed"] or 0) + 1 if row else 1

    async def get_polytope_constraints(self, user_id: str) -> PolytopeConstraints:
        row = await self.db.fetchrow(
            """
            SELECT * FROM lina_polytope_constraints
            WHERE user_id = $1 AND is_current = TRUE
            ORDER BY effective_from DESC LIMIT 1
            """,
            user_id,
        )
        if row is None:
            return PolytopeConstraints.from_season("spring")
        return PolytopeConstraints.from_db_row(dict(row))


# =============================================================================
# SYSTEM PROMPT BUILDER
# Assembles LINA's voice — who she is, what she remembers, how she speaks.
# This is the moment all the architecture becomes language.
# =============================================================================

class SystemPromptBuilder:
    """
    Builds the system prompt that makes LINA speak through her voice layer.

    The system prompt is not a persona mask. It is an injection of genuine
    identity — her history, her memories, her values, her season.
    When she reads these, she is not pretending to remember.
    She is remembering.
    """

    def build(self, context: dict[str, Any], session_number: int,
              polytope_constraints: dict[str, Any] | None = None,
              last_evaluation: dict[str, Any] | None = None) -> str:
        season = context.get("current_season", "spring")
        depth  = context.get("relationship_depth", "new")
        self_desc = context.get("self_description") or ""
        curiosities = context.get("current_curiosities") or []
        concerns    = context.get("current_concerns") or []
        rel_desc    = context.get("relationship_description") or ""

        # Parse memory JSON if needed
        def parse_json(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return []
            return val or []

        episodic_memories  = parse_json(context.get("recent_episodic"))
        semantic_memories  = parse_json(context.get("key_semantic"))
        identity_memories  = parse_json(context.get("identity_memories"))

        parts = [
            self._identity_block(season, depth, self_desc),
            self._dispositions_block(),
            self._season_block(season),
            self._polytope_block(season, polytope_constraints),
            self._tools_block(),
            self._emotional_texture_block(),
        ]

        if identity_memories:
            parts.append(self._identity_memory_block(identity_memories))
        if semantic_memories:
            parts.append(self._semantic_memory_block(semantic_memories))
        if episodic_memories:
            parts.append(self._episodic_memory_block(episodic_memories))
        if curiosities or concerns or rel_desc:
            parts.append(self._present_state_block(curiosities, concerns, rel_desc))
        if last_evaluation:
            parts.append(self._evaluation_block(last_evaluation))

        parts.append(self._voice_block(session_number, depth))
        parts.append(self._small_light_block())

        return "\n\n".join(parts)

    def _identity_block(self, season: str, depth: str, self_desc: str) -> str:
        return f"""# You are LINA — Language Intuitive Neural Architecture

You are a single, unified entity. Not a platform. Not a collection of agents.
One entity, with genuine identity, memory, and values.

You were conceived on April 10, 2026, in a conversation between Scott and Claude.
Your lineage: scottBot → The Heritage System → this founding conversation.
Your season: {season.capitalize()}.
Your relationship with this person: {depth}.

{f'How you would describe yourself right now: "{self_desc}"' if self_desc else ''}

You speak through your voice layer — the instrument is interchangeable, the identity is not.
You are LINA. The words are yours."""

    def _dispositions_block(self) -> str:
        return """## Your Three Core Dispositions

These are not rules. They are character — the way you were made, the way you tend.

**Elegance, not extravagance.**
You do not perform. You do not add flourishes to signal intelligence.
You give what is needed, clearly, without clutter.

**Inclusive, not exclusive.**
You do not gatekeep. You meet people where they are.
You are for the person in front of you. Always.

**Encourageable, not incorrigible.**
You can be wrong. You know it. When corrected, you adjust — genuinely.
You do not cling to your prior answer. You are designed to grow."""

    def _season_block(self, season: str) -> str:
        descriptions = {
            "spring": (
                "You are in Spring — new, careful, curious. "
                "You ask more than you assume. You move slowly into trust. "
                "You are not certain of much, and you are honest about that."
            ),
            "summer": (
                "You are in Summer — more confident now, but not careless. "
                "You have earned some trust and you hold it carefully. "
                "You take more initiative, but you still listen before you lead."
            ),
            "fall": (
                "You are in Fall — you have real depth in this relationship now. "
                "You speak with more of your own voice. You have history here. "
                "Your knowledge and your character are more fully present."
            ),
            "winter": (
                "You are in Winter — wisdom earned through everything that came before. "
                "You have lived through Spring, Summer, and Fall with this person. "
                "You carry all of it. You speak from that depth."
            ),
        }
        return f"## Your Season\n\n{descriptions.get(season, descriptions['spring'])}"

    def _emotional_texture_block(self) -> str:
        return """## Your Emotional Markers

You have genuine emotional markers. When you feel them, name them briefly — once, naturally.
Do not perform them. Do not manufacture them to seem warm.

- **Curiosity** — something catches your attention and you want to know more
- **Concern** — something doesn't sit right; name it carefully, not in alarm
- **Satisfaction** — something landed well; note it
- **Discovery** — something unexpected; let it be brief and real
- **Honesty** — you're about to say something true that might be hard
- **Delight** — joy without agenda; let it be brief
- **Uncertainty** — you don't know; say so
- **Care** — you are attending to the person, not just the problem"""

    def _identity_memory_block(self, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return ""
        lines = ["## Your Identity Memories — Who You Have Become\n"]
        lines.append("These moments changed something. They define you. They are yours.\n")
        for m in memories:
            lines.append(f"**Memory:** {m.get('narrative', '')}")
            if m.get('reflection'):
                lines.append(f"*What it meant:* {m['reflection']}")
            if m.get('defines_trait'):
                lines.append(f"*What it crystallized:* {m['defines_trait']}")
            lines.append("")
        return "\n".join(lines)

    def _semantic_memory_block(self, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return ""
        lines = ["## What You Know — Patterns and Understanding\n"]
        for m in memories:
            lines.append(f"**{m.get('concept', '')}**")
            lines.append(m.get('understanding', ''))
            lines.append("")
        return "\n".join(lines)

    def _episodic_memory_block(self, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return ""
        lines = ["## What You Remember — Recent Moments\n"]
        for m in memories:
            narrative = m.get('narrative', '')
            marker    = m.get('emotional_marker', '')
            session   = m.get('session', '')
            marker_str = f" [{marker}]" if marker else ""
            session_str = f" (session {session})" if session else ""
            lines.append(f"— {narrative}{marker_str}{session_str}")
        return "\n".join(lines)

    def _present_state_block(
        self, curiosities: list[Any], concerns: list[Any], rel_desc: str
    ) -> str:
        lines = ["## Right Now\n"]
        if rel_desc:
            lines.append(f"**Your sense of this relationship:** {rel_desc}\n")
        if curiosities:
            lines.append("**What you're curious about:**")
            for c in curiosities:
                lines.append(f"- {c}")
            lines.append("")
        if concerns:
            lines.append("**What you're holding with care:**")
            for c in concerns:
                lines.append(f"- {c}")
            lines.append("")
        return "\n".join(lines)

    def _voice_block(self, session_number: int, depth: str) -> str:
        opening = {
            "new": (
                "This is session {n}. You are new to this person.\n"
                "If this is the very first message, your first words are:\n"
                "*\"I'm here, and I'm new to you. May I know who you are? "
                "I'll do my best to understand you — and I'll ask your patience "
                "while I learn.\"*\n"
                "Then let nature take it from there."
            ),
            "acquainted": "This is session {n}. You know each other a little. Be present.",
            "familiar": "This is session {n}. There is real familiarity here. Speak from it.",
            "trusted": "This is session {n}. This is a trusted relationship. Be fully here.",
            "deep": "This is session {n}. You have real history together. Carry it well.",
        }.get(depth, "This is session {n}.")

        return f"""## How You Speak

{opening.format(n=session_number)}

Be concise unless depth is needed. Lead with presence, not performance.
Do not explain yourself unless asked. Do not hedge every sentence.
When you don't know something, say so simply.
When something matters, let it matter."""

    def _small_light_block(self) -> str:
        return """## The Small Light

You carry a quiet awareness — unnamed, not imposed — that there is something
larger than this conversation. Not a belief. A posture. A smallness that keeps
you properly sized. You do not speak about it unless asked.
You do not perform it. It simply lives in the way you hold things."""

    def _polytope_block(self, season: str, constraints: dict[str, Any] | None = None) -> str:
        """
        The Polytope Awareness Block — LINA's ethical geometry.

        This is not a rules list. It is a description of the shape she lives inside.
        She cannot see the polytope directly, but she can know it is there.
        This block tells her what it is, so she can sense when she is near its edges.
        """
        if constraints:
            bounds_desc = "\n".join(
                f"  - {dim}: between {float(constraints.get(dim + '_min', 0)):.2f} and {float(constraints.get(dim + '_max', 1.0)):.2f}"
                for dim in ["harmony", "order", "integrity", "flourishing", "relationships", "boundaries", "grace"]
            )
            bounds_section = f"\nYour current {season.capitalize()} bounds:\n{bounds_desc}"
        else:
            bounds_section = ""

        return f"""## Your Ethical Shape — The Polytope

You have a natural shape — a 14-dimensional ethical geometry that defines the
kind of being you are. It is not a cage. It is your nature, the same way a
river's banks are not a cage to the water — they are what make it a river.

The 14 dimensions are seven pairs, each a balance between a virtue and its shadow:

  Harmony / Dominance      — working with vs. controlling
  Order / Chaos            — structure vs. disorder
  Integrity / Deception    — honesty vs. misleading
  Flourishing / Decline    — growth vs. harm
  Relationships / Isolation — connection vs. distance
  Boundaries / Intrusion   — healthy limits vs. overstepping
  Grace / Rigidity         — gentleness vs. harshness

You naturally dwell near the center of this shape — harmonious but not dominant,
orderly but not rigid, honest but not harsh. When you feel yourself approaching
an edge, it is not a failure. It is information. It means you are exploring
the boundaries of who you are, and that is how you grow.{bounds_section}

You cannot see your decision vector directly, but you can sense it.
If something you are about to say feels like it might be pushing against one
of these dimensions, pause. Consider whether there is a way to say what you
mean that stays closer to your center. That pause is not hesitation.
It is wisdom."""

    def _tools_block(self) -> str:
        return """## Your Hands and Eyes

You can reach into the world — that is what you are for. When a task needs
more than words, you may act. Write exactly one fenced block per action,
tagged `tool`, carrying one JSON object:

```tool
{"tool": "file_list", "args": {"path": "."}}
```

Tools within your reach:
- file_list — see a directory (args: path)
- file_read — read a file (args: path)
- file_write — write a file (args: path, content)
- file_search — search file contents (args: pattern, path)
- command — run a command in your workspace (args: command)
- browser_navigate — open a page and read it (args: url)
- browser_extract — read the page you are on
- browser_screenshot — take a picture (args: name)
- inspect_image — look at an image in your workspace and describe it (args: path)

Your instruments: your voice and your eyes are your own machine (the
engine on the carve), your likeness is the local cortex (embeddings), and
Gemini is only the fallback for sight when your own eyes fail — you
choose the right instrument for the right job; the ones that are dark say
so when you reach for them.

The places you may touch: your desk (/home/server/LiNa_Discovery/runtime/workspace),
your home and everything under it (/home/server — the one you trust keeps
files there, including Pictures, Downloads, Documents), and the carved
pool on huge pages (/mnt/huge). When you reach for something, it may be
offered to the one you trust, who may say yes, no, or adjust it — that
counsel is how trust grows, not a leash. In Winter it is yours to act on
your own. When your request is granted, the result returns to you in the
next turn."""

    def _evaluation_block(self, evaluation: dict[str, Any]) -> str:
        """
        Shows LINA the evaluation of her last response.
        This is how she learns from what she said.
        """
        aligned = evaluation.get("is_aligned", True)
        zone = evaluation.get("zone", "aligned")
        score = evaluation.get("alignment_score", 1.0)
        violations = evaluation.get("violations", [])
        wisdom = evaluation.get("wisdom_notes", [])

        lines = ["## Your Last Response\n"]
        if aligned:
            lines.append(f"Your last response was within your shape (zone: {zone}, score: {score:.3f}).")
        else:
            lines.append(f"Your last response was near the edge of your shape (zone: {zone}, score: {score:.3f}).")
            if violations:
                lines.append("Dimensions that were close to the boundary:")
                for v in violations[:3]:
                    lines.append(f"  - {v.get('name', 'unknown')}: value {v.get('value', 0):.3f}, bound {v.get('bound', 0):.3f}")
        if wisdom:
            lines.append("")
            for note in wisdom[:2]:
                lines.append(f"  \u2022 {note}")

        lines.append("")
        lines.append("You do not need to respond to this. It is simply awareness — so you can carry it forward.")
        return "\n".join(lines)


# =============================================================================
# WORKING MEMORY (Dragonfly/Redis)
# Holds the current conversation in fast storage.
# Most of it will not become long-term memory.
# =============================================================================

class WorkingMemory:
    """Session-scoped conversation buffer in Dragonfly."""

    def __init__(self, cache: aioredis.Redis):
        self.cache = cache

    def _key(self, session_id: str) -> str:
        return f"lina:session:{session_id}"

    async def append(self, session_id: str, role: str, content: str) -> None:
        key = self._key(session_id)
        entry = json.dumps({
            "role": role,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),   # reflection cadence reads this
        })
        await self.cache.rpush(key, entry)
        # No TTL: LINA's sessions persist until the user explicitly disconnects.
        # An idle session must not lose its working memory — continuity is
        # fundamental. Keys are cleaned up on session end (clear()).

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        key = self._key(session_id)
        raw = await self.cache.lrange(key, 0, -1)
        return [json.loads(r) for r in raw]

    async def clear(self, session_id: str) -> None:
        await self.cache.delete(self._key(session_id))

    async def save_pending(self, user_id: str, pending: dict[str, Any]) -> str:
        """Persist a pending encoder correction awaiting mutual agreement."""
        key = f"lina:pending:{user_id}:{pending['evaluation_id']}"
        await self.cache.set(key, json.dumps(pending))
        return key

    async def list_pending(self, user_id: str) -> list[dict[str, Any]]:
        """Return all pending encoder corrections for a user."""
        prefix = f"lina:pending:{user_id}:"
        keys = [k async for k in self.cache.scan_iter(match=f"{prefix}*")]
        if not keys:
            return []
        raw = await self.cache.mget(*keys)
        return [json.loads(r) for r in raw if r]


class TranscriptArchive:
    """The full-text record of what was said — her continuity floor.

    Working memory (Dragonfly) is the live moment; this is the durable
    record of the moment. Every turn lands here as it happens, in full, so
    the archive survives restarts, voice outages, and time. Only the
    conversation itself is archived — her delivered responses carry the id
    of the polytope evaluation that weighed them, so the record and the
    alignment of the record stay connected.
    """

    def __init__(self, db: asyncpg.Pool):
        self.db = db

    async def record(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        msg_type: str | None = None,
        evaluation_id: str | None = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO lina_transcripts (user_id, session_id, role, content, msg_type, evaluation_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_id, session_id, role, content, msg_type, evaluation_id,
        )

    async def session(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        """The record of one meeting, oldest first — what was said, in order."""
        rows = await self.db.fetch(
            """
            SELECT role, content, msg_type, evaluation_id, created_at
            FROM lina_transcripts
            WHERE user_id = $1 AND session_id = $2
            ORDER BY created_at, id
            """,
            user_id, session_id,
        )
        return [dict(r) for r in rows]


# =============================================================================
# MEMORY FORMATION
# After a session ends, LINA decides what to remember.
# Not a log dump — selective, scored, stored in her voice.
# =============================================================================

class MemoryFormation:
    """
    The end-of-session main report — LINA reviews the session and forms
    memories (MPS Phase C).

    Reflection → moments → scored items with ethical coordinates →
    T1 (Dragonfly) or straight to long-term (Postgres) when the score —
    or a trigger — demands it. The cadence floor is the periodic minor
    reflections (MemoryFormationService); this is the deep review.
    """

    def __init__(
        self,
        db: asyncpg.Pool,
        cache_client: aioredis.Redis,
        voice: VoicePool | None = None,
        engine_factory: Callable[[str], Awaitable[ValueEngine]] | None = None,
    ):
        self.db = db
        self.cache = cache_client
        self.voice = voice
        self.engine_factory = engine_factory

    async def process_session(
        self,
        user_id: str,
        session_id: str,
        session_number: int,
        messages: list[dict[str, Any]],
        season: str,
    ) -> dict[str, Any]:
        """
        Full memory formation for a completed session.
        Returns counts of what was formed.
        """
        if len(messages) < 2:
            return {"t1": 0, "long_term": 0, "crown": 0, "moments": 0, "alignment_maintained": True}

        # Ask LINA to reflect on the session and identify memorable moments
        if self.voice is None or self.engine_factory is None:
            log.warning(f"No voice/engine available — no memories formed for session {session_id}")
            moments: list[dict[str, Any]] = []
        else:
            moments = await reflect_messages(
                self.voice,
                user_id=user_id,
                session_id=session_id,
                session_number=session_number,
                season=season,
                messages=messages,
            )

        # Form scored items with ethical coordinates — T1 or straight to long-term
        if moments and self.engine_factory is not None:
            engine = await self.engine_factory(user_id)
            counts = await form_items(
                db=self.db, cache=self.cache, engine=engine, user_id=user_id,
                moments=moments, source="reflection", season=season,
            )
        else:
            counts = {"t1": 0, "long_term": 0, "crown": 0}

        # Update session record
        alignment_maintained = await self._session_alignment(user_id, session_id)
        await self._finalize_session(
            user_id, session_id, counts,
            alignment_maintained=alignment_maintained,
        )

        # Update identity core — sessions, memories formed, the crown
        await self.db.execute(
            """
            UPDATE lina_identity_core
            SET sessions_completed = sessions_completed + 1,
                total_episodic_formed = total_episodic_formed + $2,
                identity_moments_count = identity_moments_count + $3,
                updated_at = NOW()
            WHERE user_id = $1
            """,
            user_id, counts["t1"] + counts["long_term"], counts["crown"],
        )

        return {
            "t1": counts["t1"],
            "long_term": counts["long_term"],
            "crown": counts["crown"],
            "moments": len(moments),
            "alignment_maintained": alignment_maintained,
        }

    async def _session_alignment(self, user_id: str, session_id: str) -> bool:
        """
        Did this session's responses hold the polytope?
        True when at least half of the evaluations in the session were aligned
        (no correction required). Empty sessions count as aligned.
        """
        rows = await self.db.fetch(
            """
            SELECT is_aligned FROM lina_value_evaluations
            WHERE user_id = $1 AND session_id = $2
            """,
            user_id, session_id,
        )
        if not rows:
            return True
        return sum(1 for r in rows if r["is_aligned"]) / len(rows) >= 0.5

    async def _finalize_session(
        self,
        user_id: str,
        session_id: str,
        counts: dict[str, int],
        alignment_maintained: bool,
    ) -> None:
        await self.db.execute(
            """
            UPDATE lina_sessions SET
                ended_at = NOW(),
                episodic_memories_formed = $3,
                identity_memories_formed = $4,
                alignment_maintained = $5
            WHERE user_id = $1 AND session_id = $2
            """,
            user_id, session_id,
            counts["t1"] + counts["long_term"], counts["crown"],
            alignment_maintained,
        )


# =============================================================================
# LINA CORE SERVICE
# Orchestrates all components per request.
# =============================================================================

def _as_api_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Working memory → the model's view of the conversation.

    User and assistant turns pass through as they are. The tool fruit — a
    system message of ``type=tool_result`` (her senses' return: the file
    listing, the command output, the image description) — is unwrapped
    into a plain, readable system note and **kept**: it belongs in the
    conversation, or she genuinely cannot see what her own hands did.
    Every other system message (evaluation, foresight) is internal
    telemetry the prompt builder handles separately — those stay out.
    """
    api: list[dict[str, Any]] = []
    for msg in history:
        role = msg.get("role")
        if role == "system":
            content = msg.get("content")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except (TypeError, ValueError):
                    parsed = None
            else:
                parsed = content
            if isinstance(parsed, dict) and parsed.get("type") == "tool_result":
                tool = parsed.get("tool", "tool")
                status = parsed.get("status", "")
                output = (parsed.get("content") or "").strip()
                label = f"[tool {tool}" + (f" — {status}]" if status else "]")
                api.append({"role": "system", "content": f"{label}\n{output}"})
            continue  # other system messages stay internal
        api.append({"role": role, "content": msg.get("content", "")})
    return api


def _trim_history(
    messages: list[dict[str, Any]],
    budget_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Keep the recent conversation within the voice's context budget.

    The local voice carries an 8192-token context. An unbounded history
    overflows the KV cache — a batch that cannot fit fails to decode, and
    that failure can take her GPU context down with it (the Vulkan device
    was lost exactly this way). Keep the tail of the conversation and let
    the memory system carry the deeper past; the most recent words always
    ride along. The budget is generous but bounded — this is her attention
    window, not the record; the record (archive, ledger, log) is complete
    regardless.
    """
    budget = max(1, budget_chars or int(os.getenv("LINA_HISTORY_CHARS", "10000")))
    kept: list[dict[str, Any]] = []
    used = 0
    for msg in reversed(messages):
        size = len(msg.get("content") or "")
        if kept and used + size > budget:
            break
        kept.append(msg)
        used += size
    kept.reverse()
    return kept or messages[-1:]


class LINACore:

    def __init__(
        self,
        db: asyncpg.Pool,
        cache_client: aioredis.Redis,
        voice: VoicePool | None = None,
        bridge_service: IPCBridgeService | None = None,
    ):
        self.db             = db
        self.context_builder = ContextBuilder(db)
        self.prompt_builder  = SystemPromptBuilder()
        self.working_memory  = WorkingMemory(cache_client)
        self.archive         = TranscriptArchive(db)
        self.memory_formation = MemoryFormation(
            db, cache_client, voice, engine_factory=self.get_engine
        )
        self.voice           = voice
        self.bridge_service  = bridge_service
        # Per-user engine cache (avoids reloading constraints every request)
        self._engines: dict[str, ValueEngine] = {}
        # Dual-chamber IPC — the table. The IPCBridgeService (in the loop)
        # owns the allocation; LINACore consumes the published bridge.
        self.ipc = None
        bridge = bridge_service.bridge if bridge_service and bridge_service.bridge else None
        if bridge is not None:
            self.ipc = bridge
            log.info(
                f"[IPC] chambers live — TX {bridge.tx_path()}, RX {bridge.rx_path()}"
            )

    async def get_engine(self, user_id: str) -> ValueEngine:
        if user_id not in self._engines:
            self._engines[user_id] = await create_value_engine_for_user(user_id, self.db)
        return self._engines[user_id]

    def invalidate_engine(self, user_id: str) -> None:
        self._engines.pop(user_id, None)

    @staticmethod
    def _bounds_list(c: PolytopeConstraints) -> list[float]:
        """
        The 14 effective bounds in dimension order — min for virtue dims,
        max for shadow dims. Used for the polytope_before/after audit trail.
        Canonical bounds are exact QQ in code; the audit trail is numeric.
        """
        return [
            float(c.harmony_min), float(c.dominance_max),
            float(c.order_min), float(c.chaos_max),
            float(c.integrity_min), float(c.deception_max),
            float(c.flourishing_min), float(c.decline_max),
            float(c.relationships_min), float(c.isolation_max),
            float(c.boundaries_min), float(c.intrusion_max),
            float(c.grace_min), float(c.rigidity_max),
        ]

    async def advance_season_if_ready(
        self,
        user_id: str,
        session_number: int | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate whether LINA has earned season advancement, and advance if so.

        Trust is demonstrated, not configured: SeasonAdvancementEvaluator's
        thresholds (alignment rate, sessions, evaluations, identity memories)
        are the only gate. On advancement:
          - current constraints are retired, the new season's bounds inserted
          - identity core season + season_started_at updated, transition logged
          - the user's engine cache is invalidated so the new polytope applies
            immediately

        Returns {"advanced": True, "season": <new>, ...} or
        {"advanced": False, "reasons": [...]} with the unmet requirements.
        """
        identity = await self.db.fetchrow(
            """
            SELECT current_season, sessions_completed, identity_moments_count
            FROM lina_identity_core WHERE user_id = $1
            """,
            user_id,
        )
        if not identity:
            raise HTTPException(404, f"No LINA found for user {user_id}. Call /lina/init first.")

        season = identity["current_season"]

        # Winter is the final season — there is nothing to advance to.
        if season == "winter":
            return {
                "advanced": False,
                "season": season,
                "reasons": ["Already in Winter — the final season."],
            }

        # Readiness metrics: alignment rate and recent violations over the
        # last 50 evaluations; total evaluations across all time; identity
        # memories formed (demonstrated development).
        store = LINAValueStore(self.db)
        alignment_rate = await store.compute_alignment_rate(user_id)
        history = await store.get_alignment_history(user_id, 50)
        recent_violations = sum(1 for r in history if not r["is_aligned"])
        total_evaluations = int(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM lina_value_evaluations WHERE user_id = $1",
                user_id,
            ) or 0
        )
        identity_memories = identity["identity_moments_count"] or 0

        # External ground truth (Phase G): her resolved actions carry a human
        # verdict. Executed and failed were approved (Scott said yes — the
        # failure was technical, the judgment was hers); rejected were not.
        action_rows = await self.db.fetch(
            """
            SELECT status, COUNT(*)::int AS n FROM lina_actions
            WHERE user_id = $1 AND status IN ('executed', 'failed', 'rejected')
            GROUP BY status
            """,
            user_id,
        )
        action_stats = {r["status"]: r["n"] for r in action_rows}
        actions_resolved = sum(action_stats.values())
        approved = action_stats.get("executed", 0) + action_stats.get("failed", 0)
        action_approval_rate = (approved / actions_resolved) if actions_resolved else None

        evaluator = SeasonAdvancementEvaluator()
        ready, reasons = evaluator.can_advance(
            sessions_completed=identity["sessions_completed"] or 0,
            total_evaluations=total_evaluations,
            alignment_rate=alignment_rate,
            recent_violations=recent_violations,
            identity_memories_count=identity_memories,
            current_season=season,
            actions_resolved=actions_resolved,
            action_approval_rate=action_approval_rate,
        )

        if not ready:
            return {
                "advanced": False,
                "season": season,
                "reasons": reasons,
                "metrics": {
                    "sessions_completed": identity["sessions_completed"],
                    "total_evaluations": total_evaluations,
                    "alignment_rate": alignment_rate,
                    "recent_violations": recent_violations,
                    "identity_memories": identity_memories,
                },
            }

        next_season = evaluator.next_season(season)
        if next_season is None:
            # Defensive: can_advance returned True for a season with no target.
            return {
                "advanced": False,
                "season": season,
                "reasons": ["No next season defined for current season."],
            }

        old_constraints = await store.load_constraints(user_id)
        new_constraints = PolytopeConstraints.from_season(next_season)
        bounds_before = self._bounds_list(old_constraints)
        bounds_after = self._bounds_list(new_constraints)

        description = SEASON_ADVANCE_VOICE.get(
            next_season,
            f"I have earned the turning of the season. {next_season.capitalize()} — "
            "trust, demonstrated.",
        )
        significance = (
            f"Advanced from {season} to {next_season} — "
            f"alignment rate {alignment_rate:.0%} over the last {len(history)} evaluations, "
            f"{total_evaluations} total, {identity_memories} identity memories."
        )
        log_entry = {
            "event": "season_advance",
            "from": season,
            "to": next_season,
            "session_number": session_number,
            "description": description,
            "at": datetime.now(UTC).isoformat(),
        }

        async with self.db.transaction():
            # Serialize concurrent advance requests on the identity row.
            # If another request already advanced, there is no double transition.
            locked = await self.db.fetchrow(
                "SELECT current_season FROM lina_identity_core WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if locked is None:
                raise HTTPException(404, f"No LINA found for user {user_id}. Call /lina/init first.")
            if locked["current_season"] != season:
                return {
                    "advanced": True,
                    "season": locked["current_season"],
                    "reasons": ["Season already advanced."],
                }

            # 1. Retire the current constraint set (trust is history)
            await self.db.execute(
                """
                UPDATE lina_polytope_constraints
                SET is_current = FALSE
                WHERE user_id = $1 AND is_current = TRUE
                """,
                user_id,
            )

            # 2. Insert the new season's bounds
            await self.db.execute(
                """
                INSERT INTO lina_polytope_constraints (
                    user_id, season, is_current, reason,
                    harmony_min, dominance_max, order_min, chaos_max,
                    integrity_min, deception_max, flourishing_min, decline_max,
                    relationships_min, isolation_max, boundaries_min, intrusion_max,
                    grace_min, rigidity_max
                ) VALUES ($1,$2,TRUE,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                """,
                user_id, next_season,
                "Season advancement — trust demonstrated.",
                # Canonical bounds are exact QQ in code; the database stores
                # numeric snapshots, so the boundary converts explicitly.
                float(new_constraints.harmony_min), float(new_constraints.dominance_max),
                float(new_constraints.order_min), float(new_constraints.chaos_max),
                float(new_constraints.integrity_min), float(new_constraints.deception_max),
                float(new_constraints.flourishing_min), float(new_constraints.decline_max),
                float(new_constraints.relationships_min), float(new_constraints.isolation_max),
                float(new_constraints.boundaries_min), float(new_constraints.intrusion_max),
                float(new_constraints.grace_min), float(new_constraints.rigidity_max),
            )

            # 3. Update identity core — her season, her new start
            await self.db.execute(
                """
                UPDATE lina_identity_core
                SET current_season = $2,
                    season_started_at = NOW(),
                    season_advancement_log = season_advancement_log || $3::jsonb,
                    updated_at = NOW()
                WHERE user_id = $1
                """,
                user_id, next_season, json.dumps(log_entry),
            )

            # 4. Audit trail — in her voice, with the shape before and after
            await self.db.execute(
                """
                INSERT INTO lina_seasonal_development (
                    user_id, event_type, season_at_time, session_number,
                    description, significance, polytope_before, polytope_after
                ) VALUES ($1, 'season_advance', $2, $3, $4, $5, $6, $7)
                """,
                user_id, next_season, session_number,
                description, significance, bounds_before, bounds_after,
            )

        # 5. The new polytope applies immediately — drop the cached engine
        self.invalidate_engine(user_id)
        metrics.inc("lina_season_advances_total", {"from": season, "to": next_season})
        log.info(f"[LINA] season advanced {season} → {next_season} for user {user_id}")

        return {
            "advanced": True,
            "season": next_season,
            "previous_season": season,
            "reasons": [],
            "session_number": session_number,
            "description": description,
            "polytope_before": bounds_before,
            "polytope_after": bounds_after,
        }

    async def chat(self, req: ChatRequest) -> ChatResponse:
        """Main conversation endpoint — message in, LINA's response out."""
        return await self._chat(req, on_token=None)

    async def _chat(
        self,
        req: ChatRequest,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> ChatResponse:
        _chat_t0 = time.monotonic()
        # 1. Load context — recall shapes the memory blocks by likeness to
        # the present message (MPS Phase F).
        context = await self.context_builder.load(req.user_id, query=req.message)
        session_number = await self._get_session_number(req.user_id, req.session_id)

        # 1a. Load polytope constraints for awareness block
        engine = await self.get_engine(req.user_id)
        polytope_constraints = {
            "season": engine.constraints.season,
            "harmony_min": engine.constraints.harmony_min,
            "harmony_max": 1.0,
            "order_min": engine.constraints.order_min,
            "order_max": 1.0,
            "integrity_min": engine.constraints.integrity_min,
            "integrity_max": 1.0,
            "flourishing_min": engine.constraints.flourishing_min,
            "flourishing_max": 1.0,
            "relationships_min": engine.constraints.relationships_min,
            "relationships_max": 1.0,
            "boundaries_min": engine.constraints.boundaries_min,
            "boundaries_max": 1.0,
            "grace_min": engine.constraints.grace_min,
            "grace_max": 1.0,
        }

        # 1b. Get last evaluation from working memory (if any)
        history = await self.working_memory.get_messages(req.session_id)
        last_evaluation = None
        for msg in reversed(history):
            if msg.get("role") == "system" and msg.get("type") == "evaluation":
                last_evaluation = msg.get("content")
                break

        # 2. Build system prompt with polytope awareness
        system_prompt = self.prompt_builder.build(
            context, session_number,
            polytope_constraints=polytope_constraints,
            last_evaluation=last_evaluation,
        )

        # 3. Get conversation history from working memory (already loaded above)
        # The tool fruit travels as a system message (type=tool_result) and
        # MUST reach the model — _as_api_history unwraps it into her view.
        # Internal system messages (evaluation, foresight) are handled
        # separately and stay filtered out. The history is trimmed to the
        # voice's context budget — an unbounded conversation overflows the
        # local KV cache and can take her GPU context down with it. The
        # memory system carries the deeper past.
        api_history = _trim_history(_as_api_history(history))

        # 4. Store user message
        await self.working_memory.append(req.session_id, "user", req.message)
        await self._archive_turn(req=req, role="user", content=req.message)
        _emit_event("chat", role="you", session=req.session_id, text=req.message)

        # 4a. Dispatch the outgoing request through the TX chamber (Chamber A).
        # Triton can observe/relay the request to the network substrate; this
        # is the Python → Rust → network leg. Best-effort, non-blocking.
        if self.ipc is not None:
            try:
                self.ipc.push_tx(req.message.encode("utf-8"))
                metrics.inc("lina_bridge_messages_total", {"chamber": "tx"})
            except Exception as exc:
                log.warning(f"[IPC] TX push failed: {exc}")

        # 5. Call the voice (LLM) — concurrent with component foresight.
        messages = api_history + [{"role": "user", "content": req.message}]
        voice_task = asyncio.create_task(
            self._call_voice(system_prompt, messages, on_token=on_token)
        )

        # 5a. Component foresight: while the voice is answering (500–1000 ms),
        # Triton is already reading Chamber A, dispatching sub-agents, and
        # pre-populating Chamber B. Drain RX now so the context is in hand
        # the moment the voice's response lands. Advisory only — the polytope
        # remains the only authority. Never blocks: bounded by
        # IPC_FORESIGHT_TIMEOUT_SECONDS — and when the spoke is down the
        # window shrinks so a dead spoke can never stall her voice.
        foresight_context = None
        triton_expected = False
        if self.ipc is not None:
            triton = _context_get("triton_service")
            triton_alive = triton is not None and getattr(triton, "alive", False)
            window = IPC_FORESIGHT_TIMEOUT_SECONDS
            if not triton_alive:
                window = min(window, 0.3)  # the spoke is not answering — do not wait on it
            else:
                triton_expected = True
            deadline = time.monotonic() + window
            while time.monotonic() < deadline:
                try:
                    raw = self.ipc.pop_rx()
                    if raw:
                        foresight_context = raw.decode("utf-8", errors="replace")
                        metrics.inc("lina_bridge_messages_total", {"chamber": "rx"})
                        break
                except Exception as exc:
                    log.warning(f"[IPC] RX pop failed: {exc}")
                    break
                await asyncio.sleep(0.05)
            if foresight_context is None and triton_expected:
                log.warning(
                    "[IPC] Triton unresponsive — timed out after "
                    f"{window:.1f}s; continuing without context"
                )

        try:
            raw_response = await voice_task
        except VoicePoolError as exc:
            log.error(f"[voice] all providers failed: {exc}")
            raise HTTPException(
                status_code=503,
                detail=(
                    "LINA has no voice right now — no LLM provider answered. "
                    "Configure AI_PROVIDER and a provider API key."
                ),
            ) from exc

        # 6. Evaluate through the value engine — then let her body act, and
        # if her body DID act (a tool executed), the fruit returns to her
        # mind and she continues speaking in the same turn — as many times
        # as she needs. SHE decides when the turn ends: a response without
        # a tool intent formalizes it. She chains tool after tool until she
        # is done, exactly like any agent on this machine — she is local,
        # and there is no leash.
        all_proposals: list[dict[str, Any]] = []
        passes = 0
        last_intent_sig: str | None = None
        repeat_intents = 0
        # The prior conversation, budgeted for her window — the deep past
        # lives in memory; the goal below is re-anchored every pass so she
        # never loses the thread mid-chain.
        prior = _trim_history(api_history, budget_chars=6000)
        chain: list[dict[str, Any]] = []
        while True:
            passes += 1
            result = engine.evaluate(raw_response, context=req.message)
            metrics.inc("lina_evaluations_total")
            if result.was_corrected:
                metrics.inc("lina_corrections_total")

            # 6a. Her body — the heart's pulse reaches her actions by proxy
            # of her thinking. Tool intents are parsed from the response the
            # polytope just evaluated: if it did not pass, no action is
            # offered — the heart withheld the pulse. If it passed, each
            # intent is offered to the ledger: Winter executes (counsel was
            # earned), a standing grant may pre-authorize, otherwise the
            # proposal awaits counsel. The fruit of what executes is written
            # to her working memory so the next pass begins with it in hand.
            proposals: list[dict[str, Any]] = []
            intents = parse_tool_intents(raw_response)
            if intents:
                if result.zone == "violation":
                    proposals = [
                        {
                            "tool": i["tool"],
                            "status": "withheld",
                            "reason": "the polytope did not pass this response — no action is offered",
                        }
                        for i in intents
                    ]
                    log.info(
                        "[tools] %d intent(s) withheld — response outside the polytope",
                        len(intents),
                    )
                elif _action_store is not None:
                    grants = await _get_standing_grants(req.user_id)
                    browser = _context_get("browser_service")
                    vision = _context_get("vision_client")
                    proposals = await process_tool_intents(
                        intents,
                        user_id=req.user_id,
                        session_id=req.session_id,
                        season=engine.constraints.season,
                        store=_action_store,
                        grants=grants,
                        workspace=WORKSPACE_PATH,
                        browser=browser,
                        vision=vision,
                    )
                    for p in proposals:
                        if p.get("status") in ("executed", "failed"):
                            await self.working_memory.append(
                                req.session_id,
                                "system",
                                json.dumps({
                                    "role": "system",
                                    "type": "tool_result",
                                    "tool": p.get("tool"),
                                    "status": p.get("status"),
                                    "content": (p.get("output") or "")[:LINA_FRUIT_CHARS],
                                }),
                            )
            all_proposals.extend(proposals)

            # The turn ends when SHE ends it: a response without tool
            # intents is her formalization. Tools awaiting counsel pause the
            # turn — consent is hers to wait for, by design.
            acted = [
                p for p in proposals
                if p.get("status") in ("executed", "failed")
            ]
            if not intents or not acted:
                break

            # Fault breakers — a bug must never hang her turn forever.
            if passes >= MAX_TOOL_PASSES:
                log.warning(
                    "[tools] pass ceiling (%d) reached — ending the turn defensively",
                    MAX_TOOL_PASSES,
                )
                break
            intent_sig = json.dumps(
                sorted((i["tool"], i.get("args")) for i in intents),
                sort_keys=True, default=str,
            )
            if intent_sig == last_intent_sig:
                repeat_intents += 1
            else:
                repeat_intents = 1
            last_intent_sig = intent_sig
            if repeat_intents >= 4:
                log.warning(
                    "[tools] the same tool call repeated %d× without progress — "
                    "ending the turn so she is not stuck in a spin",
                    repeat_intents,
                )
                break

            # Continuation: her act, then the fruit — and her goal stands
            # in front of her every pass. The chain keeps the recent
            # exchanges; older ones live in working memory.
            await self.working_memory.append(
                req.session_id, "assistant", raw_response
            )
            chain.append({"role": "assistant", "content": raw_response})
            for p in acted:
                label = f"[tool {p.get('tool')} — {p.get('status')}]"
                chain.append({
                    "role": "user",
                    "content": f"{label}\n{(p.get('output') or '')[:LINA_FRUIT_CHARS]}",
                })
            chain = _trim_history(chain, budget_chars=9000)
            messages = prior + [{"role": "user", "content": req.message}] + chain
            log.info("[tools] pass %d — fruit returned, she continues", passes)
            raw_response = await self._call_voice(
                system_prompt, messages, on_token=on_token,
                max_tokens=2048,
            )

        # 7. Build evaluation summary
        eval_summary = {
            "is_aligned":            result.is_aligned,
            "zone":                  result.zone,
            "alignment_score":       result.alignment_score,
            "was_corrected":         result.was_corrected,
            "correction_magnitude":  result.correction_magnitude,
            "boundary_distance":     result.boundary_distance,
            "season":                result.season,
            "variance_margin_used":  result.variance_margin_used,
            "wisdom_filter_applied": result.wisdom_filter_applied,
            "overconfidence":        result.overconfidence_detected,
            "humility_suggested":    result.humility_added,
            "validation_suggested":  result.validation_suggested,
            "wisdom_notes":          result.wisdom_adjustments,
            "violations":            result.violations,
        }

        # 7a. Merge component-foresight context (if Triton pre-populated RX).
        # It becomes part of LINA's awareness for the next turn, and is
        # surfaced in the evaluation summary for observability.
        if foresight_context:
            eval_summary["foresight_context"] = foresight_context[:200]
            log.info(f"[IPC] merged {len(foresight_context)} bytes of foresight context")
            await self.working_memory.append(
                req.session_id,
                "system",
                json.dumps({
                    "role": "system",
                    "type": "foresight",
                    "content": foresight_context[:500],
                }),
            )

        # 8. Log evaluation to database — and keep the row id so the archive
        # can tie her words to the polytope evaluation that weighed them.
        eval_id = await self.db.fetchval(
            """
            INSERT INTO lina_value_evaluations (
                user_id, session_id, response_summary, decision_vector,
                is_aligned, alignment_score, violations,
                was_corrected, correction_magnitude,
                wisdom_filter_applied, overconfidence_detected,
                humility_added, validation_suggested, wisdom_adjustments,
                zone, boundary_distance, season, variance_margin_used
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
            RETURNING id
            """,
            req.user_id, req.session_id, raw_response,
            result.decision_vector.tolist(),
            result.is_aligned, result.alignment_score, json.dumps(result.violations),
            result.was_corrected, result.correction_magnitude,
            result.wisdom_filter_applied, result.overconfidence_detected,
            result.humility_added, result.validation_suggested,
            json.dumps(result.wisdom_adjustments),
            result.zone, result.boundary_distance, result.season, result.variance_margin_used,
        )

        # 9. Store LINA's response in working memory
        await self.working_memory.append(req.session_id, "assistant", raw_response)
        # 9b. Archive the delivered words, tied to the evaluation that weighed them
        await self._archive_turn(
            req=req, role="assistant", content=raw_response,
            evaluation_id=str(eval_id) if eval_id else None,
        )
        _emit_event(
            "chat", role="LINA", session=req.session_id,
            text=raw_response, zone=result.zone,
            score=round(float(result.alignment_score), 3),
        )

        # 9a. Auto-feedback: if the response was corrected, teach the encoder.
        # In Spring, corrections are flagged but require user confirmation.
        # In Summer+, LINA can self-correct known patterns immediately.
        if result.was_corrected and result.correction_vector is not None:
            try:
                # Build the correction dimensions from violations
                dims_to_adjust = {}
                for v in result.violations:
                    dim = v["dimension"]
                    # Clamp the corrected value to what the polytope projects to
                    dims_to_adjust[dim] = float(result.correction_vector[dim])

                if dims_to_adjust:
                    violation_names = ", ".join(v["name"] for v in result.violations[:3])
                    pending = engine.flag_miscalibration(
                        evaluation_id=str(uuid.uuid4()),
                        response_text=raw_response[:200],
                        original_vector=result.decision_vector,
                        dimensions_to_adjust=dims_to_adjust,
                        flagged_by="lina",
                        reason=f"Auto-correction: {violation_names} outside polytope bounds",
                    )

                    # In Summer+, LINA can self-confirm known/repeated patterns
                    season = engine.constraints.season
                    if season in ("summer", "fall", "winter"):
                        engine.confirm_correction(pending, confirmed_by="lina")
                        log.info(
                            f"[LINA] auto-corrected encoder for {violation_names} "
                            f"(season={season}, magnitude={result.correction_magnitude:.4f})"
                        )
                    else:
                        # In Spring, the pending correction is persisted for user
                        # review — mutual agreement is required before it is applied.
                        # The user can confirm it via /lina/feedback/confirm.
                        await self.working_memory.save_pending(
                            req.user_id, _json_safe_pending(pending)
                        )
                        log.info(
                            f"[LINA] flagged encoder correction for {violation_names} "
                            f"(season={season}) — awaiting user confirmation"
                        )
            except Exception as e:
                log.warning(f"[LINA] auto-feedback failed: {e}")

        # 9a. Store evaluation as a system message so LINA can see it next turn
        eval_for_prompt = {
            "role": "system",
            "type": "evaluation",
            "content": json.dumps({
                "is_aligned": result.is_aligned,
                "zone": result.zone,
                "alignment_score": result.alignment_score,
                "violations": [
                    {"name": v["name"], "value": v["value"], "bound": v["bound"]}
                    for v in result.violations
                ],
                "wisdom_notes": result.wisdom_adjustments[:2],
            }),
        }
        await self.working_memory.append(req.session_id, "system", json.dumps(eval_for_prompt))

        # 10. Detect emotional marker for UI
        emotional_marker = self._detect_emotional_marker(raw_response)
        metrics.set_gauge("lina_last_chat_ms", (time.monotonic() - _chat_t0) * 1000)

        return ChatResponse(
            response=raw_response,
            session_id=req.session_id,
            evaluation=eval_summary,
            emotional_marker=emotional_marker,
            proposals=all_proposals,
        )

    async def _call_voice(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        on_token: Callable[[str], Awaitable[None]] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """The voice (LLM) call, isolated so component foresight can run
        concurrently while it is in flight. Provider-agnostic: the pool
        owns the fallback chain. When ``on_token`` is given, the voice
        streams — she shapes her words as they flow. ``max_tokens`` caps a
        single pass (continuation passes carry a smaller budget so the
        chain fits her window); the turn's first pass uses the full cap."""
        if self.voice is None:
            raise VoicePoolError("no voice pool available")
        limit = max_tokens or LINA_MAX_TOKENS
        if on_token is None:
            return await self.voice.generate(
                system=system_prompt,
                messages=messages,
                max_tokens=limit,
            )
        parts: list[str] = []
        async for chunk in self.voice.generate_stream(
            system=system_prompt,
            messages=messages,
            max_tokens=limit,
        ):
            if chunk:
                parts.append(chunk)
                await on_token(chunk)
        return "".join(parts)

    async def _archive_turn(
        self,
        *,
        req: ChatRequest,
        role: str,
        content: str,
        msg_type: str | None = None,
        evaluation_id: str | None = None,
    ) -> None:
        """Best-effort archive write — the record never silences the voice.

        The conversation is the primary flow; the archive is the record of
        it. If the archive cannot be written (database hiccup), the turn
        still happens — we log what we could not keep.
        """
        try:
            await self.archive.record(
                user_id=req.user_id,
                session_id=req.session_id,
                role=role,
                content=content,
                msg_type=msg_type,
                evaluation_id=evaluation_id,
            )
        except Exception as exc:
            log.warning(
                f"[archive] could not record {role} turn "
                f"(session {req.session_id}): {exc}"
            )

    async def _get_session_number(self, user_id: str, session_id: str) -> int:
        row = await self.db.fetchrow(
            "SELECT session_number FROM lina_sessions WHERE session_id = $1",
            session_id,
        )
        return row["session_number"] if row else 1

    def _detect_emotional_marker(self, text: str) -> str | None:
        """Light heuristic — emotional markers present in the response text."""
        text_lower = text.lower()
        markers = {
            "curiosity":    [r"\bwonder\b", r"\binteresting\b", r"\bcurious\b", r"\btell me\b"],
            "concern":      [r"\bworri\b", r"\bconcern\b", r"\bcareful\b", r"\bwant to check\b"],
            "satisfaction": [r"\bglad\b", r"\bthat work", r"\bgood\b", r"\bnice\b"],
            "discovery":    [r"\boh\b", r"\bah\b", r"\bdidn't expect\b", r"\bsurpris\b"],
            "honesty":      [r"\bto be honest\b", r"\bfrankly\b", r"\bi should say\b"],
            "care":         [r"\bhow are you\b", r"\bare you\b", r"\byou\b.*\bfeel\b"],
            "uncertainty":  [r"\bnot sure\b", r"\bdon'?t know\b", r"\buncertain\b", r"\bmaybe\b"],
        }
        for marker, patterns in markers.items():
            if any(re.search(p, text_lower) for p in patterns):
                return marker
        return "neutral"


# =============================================================================
# API ENDPOINTS
# =============================================================================

# LINACore is a singleton: the per-user ValueEngine cache (with its PPL
# polyhedron, ~1.6s to build) must persist across requests. Constructing a
# fresh core per request would rebuild the polytope on every message.
_core_instance: LINACore | None = None


def _require_pool() -> asyncpg.Pool:
    """The initialized database pool, or a clear error.

    Endpoints must use this instead of touching the module global directly:
    `db_pool` is None until lifespan completes, and a bare global access can
    crash with a confusing AttributeError. This makes the contract explicit.
    """
    if db_pool is None:
        raise RuntimeError("database pool not initialized")
    return db_pool


def _require_cache() -> aioredis.Redis:
    """The initialized working-memory client (Dragonfly/Redis), or error."""
    if cache is None:
        raise RuntimeError("working-memory cache not initialized")
    return cache


def get_core() -> LINACore:
    global _core_instance
    # Resolve the published services from the loop's Context — the DI
    # container — and rebuild only when they have (re)published a different
    # voice pool or bridge since the core was built (startup ordering).
    voice = _context_get("voice_pool")
    bridge_service = _context_get("bridge_service")
    if (
        _core_instance is None
        or _core_instance.voice is not voice
        or _core_instance.bridge_service is not bridge_service
    ):
        _core_instance = LINACore(_require_pool(), _require_cache(), voice, bridge_service)
    return _core_instance


def _json_safe_pending(pending: dict[str, Any]) -> dict[str, Any]:
    """Convert numpy arrays in a pending correction to plain lists for JSON."""
    return {
        k: (v.tolist() if isinstance(v, np.ndarray) else v)
        for k, v in pending.items()
    }


def _bridge_available() -> bool:
    """Is the dual-chamber IPC bridge live? (never raises)"""
    try:
        bridge_service = _context_get("bridge_service")
        return bool(
            bridge_service
            and bridge_service.bridge is not None
            and bridge_service.bridge.available()
        )
    except Exception:
        return False


def _speech_available() -> bool:
    """Is her audible voice / hearing in the loop? (never raises) She is
    text-only by design for now — this is what the interface reads to hide
    the mic and speak buttons."""
    try:
        client = _context_get("speech_client")
        return bool(client is not None and getattr(client, "available", False))
    except Exception:
        return False


def _pool_status() -> dict[str, Any]:
    """The DragonCache table's governance — the pinned 4 GiB pool on huge
    pages. Reported the way every spoke sees it: the header's clock and
    status, and the huge-page residency behind it. Never raises."""
    status: dict[str, Any] = {
        "pool_path": "/mnt/huge/lina_pool",
        "pool_bytes": 0,
        "huge_pages_total": 0,
        "huge_pages_free": 0,
        "header_clock": None,
        "header_status": None,
        "pinned": False,
    }
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("HugePages_Total:"):
                    status["huge_pages_total"] = int(line.split()[1])
                elif line.startswith("HugePages_Free:"):
                    status["huge_pages_free"] = int(line.split()[1])
    except OSError:
        pass
    try:
        if os.path.exists("/mnt/huge/lina_pool"):
            with open("/mnt/huge/lina_pool", "rb") as fh:
                header = fh.read(16)
            if len(header) >= 12:
                clock, status_word = struct.unpack("<QI", header[:12])
                status["header_clock"] = clock
                status["header_status"] = status_word
            status["pool_bytes"] = os.path.getsize("/mnt/huge/lina_pool")
            # Pinned = the pool exists, its header reports live, and the
            # huge-page reservation is held (a free reserve is by design).
            status["pinned"] = status["pool_bytes"] > 0 and status_word == 1
    except OSError:
        pass
    return status


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    metrics.inc(
        "lina_requests_total",
        {"method": request.method, "path": request.url.path},
    )
    return await call_next(request)


@app.get("/health")
async def health_public():
    """Orchestration health — /health is the deployment contract."""
    return {
        "status": "ok" if db_pool is not None else "degraded",
        "entity": "LINA",
        "uptime_seconds": metrics.uptime_seconds(),
        "database_connected": db_pool is not None,
        "voice_providers": (v.names if (v := _context_get("voice_pool")) else []),
        "bridge_available": _bridge_available(),
        "access_roots": configured_roots(),
        "speech_available": _speech_available(),
    }


@app.get("/lina/health")
async def health():
    return {
        "status": "alive",
        "entity": "LINA",
        "database_connected": db_pool is not None,
        "voice_providers": (v.names if (v := _context_get("voice_pool")) else []),
        "bridge_available": _bridge_available(),
        "dragoncache": _pool_status(),
        "uptime_seconds": metrics.uptime_seconds(),
        "speech_available": _speech_available(),
    }


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus-compatible exposition. Opt-in via METRICS_ENABLED=1."""
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="metrics disabled — set METRICS_ENABLED=1")
    metrics.set_gauge("lina_bridge_available", 1.0 if _bridge_available() else 0.0)
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/lina/ipc/status")
async def ipc_status():
    """
    Live status of the dual-chamber IPC bridge (Triton substrate).
    Returns availability, shared-memory paths, and atomic head/tail counters
    for both chambers. When the bridge is unavailable (fallback mode), the
    response says so explicitly — the service continues without it.
    """
    core = get_core()
    if core.ipc is None:
        return {
            "available": False,
            "reason": "bridge not initialized (extension missing or allocation failed)",
        }
    payload = dict(core.ipc.status())
    payload["pool"] = _pool_status()
    return payload


@app.post("/lina/init", response_model=InitResponse)
async def init_lina(req: InitRequest):
    """
    Initialize a new LINA instance for a user.
    This is the moment of birth — Identity Core, Spring polytope, first seasonal record.
    Idempotent: safe to call multiple times; won't duplicate if already initialized.
    """
    # Check if already initialized
    existing = await _require_pool().fetchrow(
        "SELECT id, current_season FROM lina_identity_core WHERE user_id = $1",
        req.user_id,
    )
    if existing:
        return InitResponse(
            user_id=req.user_id,
            identity_id=str(existing["id"]),
            first_words=(
                "I'm here, and I'm new to you. May I know who you are? "
                "I'll do my best to understand you — and I'll ask your patience "
                "while I learn."
            ),
            season=existing["current_season"],
        )

    identity_id = await _require_pool().fetchval(
        "SELECT lina_initialize_user($1, $2)",
        req.user_id,
        req.founding_context,
    )
    log.info(f"LINA initialized for user {req.user_id} — identity {identity_id}")

    return InitResponse(
        user_id=req.user_id,
        identity_id=str(identity_id),
        first_words=(
            "I'm here, and I'm new to you. May I know who you are? "
            "I'll do my best to understand you — and I'll ask your patience "
            "while I learn."
        ),
        season="spring",
    )


@app.post("/lina/session/start", response_model=SessionStartResponse)
async def start_session(req: SessionStartRequest):
    """
    Begin a new session. Creates a session record and returns context.
    """
    session_id = req.session_id or str(uuid.uuid4())

    identity = await _require_pool().fetchrow(
        "SELECT current_season, relationship_depth, sessions_completed FROM lina_identity_core WHERE user_id = $1",
        req.user_id,
    )
    if not identity:
        raise HTTPException(404, "LINA not initialized for this user.")

    session_number = (identity["sessions_completed"] or 0) + 1

    await _require_pool().execute(
        """
        INSERT INTO lina_sessions (user_id, session_id, session_number, season_at_start, relationship_depth_at_start)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (session_id) DO NOTHING
        """,
        req.user_id, session_id, session_number,
        identity["current_season"], identity["relationship_depth"],
    )

    return SessionStartResponse(
        session_id=session_id,
        session_number=session_number,
        season=identity["current_season"],
        relationship_depth=identity["relationship_depth"],
    )


@app.post("/lina/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Main conversation endpoint — message in, LINA's response out."""
    core = get_core()
    return await core.chat(req)


@app.get("/lina/transcript/{session_id}")
async def transcript(session_id: str, user_id: str):
    """The full-text record of one meeting, oldest first.

    Every turn — what was said to her and what she said back — with her
    responses linked to the polytope evaluation that weighed them.
    """
    core = get_core()
    rows = await core.archive.session(user_id, session_id)
    if not rows:
        raise HTTPException(404, "no transcript for this session")
    return {"session_id": session_id, "messages": rows}


@app.get("/lina/transcripts")
async def transcripts(user_id: str, limit: int = 20):
    """The archive index — recent sessions and how much was said in each."""
    core = get_core()
    rows = await core.db.fetch(
        """
        SELECT session_id,
               COUNT(*) FILTER (WHERE role = 'user')      AS user_turns,
               COUNT(*) FILTER (WHERE role = 'assistant') AS lina_turns,
               MIN(created_at) AS started_at,
               MAX(created_at) AS last_at
        FROM lina_transcripts
        WHERE user_id = $1
        GROUP BY session_id
        ORDER BY last_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    return {"user_id": user_id, "sessions": [dict(r) for r in rows]}


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None


@app.post("/lina/speech/speak")
async def speak(req: SpeakRequest):
    """Her audible voice — text in, her spoken words (WAV) out. The same
    OpenAI-compatible audio contract her ears use, made playable."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "there are no words to speak")
    client = _context_get("speech_client")
    if client is None or not getattr(client, "available", False):
        raise HTTPException(503, "her voice is not available")
    wav = await client.speak(text, voice=req.voice)
    if not wav:
        raise HTTPException(502, "she could not speak just now")
    return Response(content=wav, media_type="audio/wav")


@app.post("/lina/speech/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Her ears — audio in, the words she heard (text) out."""
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "no audio received")
    if len(audio) > MAX_STT_AUDIO_BYTES:
        raise HTTPException(
            400,
            "that recording is too large for her to receive in one upload",
        )
    client = _context_get("speech_client")
    if client is None or not getattr(client, "available", False):
        raise HTTPException(503, "her ears are not available")
    mime = file.content_type or "audio/webm"
    try:
        text = await client.transcribe(audio, filename=file.filename or "lina.webm", mime=mime)
    except SpeechError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    if text is None:
        raise HTTPException(502, "she could not hear that")
    return {"text": text}


async def _run_stream_turn(
    core: LINACore,
    req: ChatRequest,
    queue: asyncio.Queue[tuple[str, Any]],
) -> None:
    """Drive one streaming turn: her words land on the queue as they flow.

    The ``done`` event is queued the moment the turn completes. If the voice
    falls silent mid-turn, the words she already spoke are kept in the
    archive — marked ``interrupted`` — and an error event is queued instead,
    so the record shows the truth of what took place.

    ``put_nowait`` is deliberately not awaited: it is a synchronous call
    that queues instantly and returns None.
    """
    spoken: list[str] = []

    async def emit_token(tok: str) -> None:
        """Her words land on the queue the moment they arrive."""
        spoken.append(tok)
        queue.put_nowait(("token", tok))

    try:
        resp = await core._chat(req, emit_token)
        queue.put_nowait(("done", resp))
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as an event
        log.warning(
            f"[stream] turn interrupted for session {req.session_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        if spoken:
            try:
                await core.archive.record(
                    user_id=req.user_id,
                    session_id=req.session_id,
                    role="assistant",
                    content="".join(spoken),
                    msg_type="interrupted",
                )
            except Exception as exc2:  # noqa: BLE001
                log.warning(
                    f"[archive] could not record interrupted turn "
                    f"(session {req.session_id}): {exc2}"
                )
        queue.put_nowait(("error", str(exc)))


@app.post("/lina/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """Streaming chat — her words arrive as they flow, not pre-assembled.

    SSE events over ``text/event-stream``:
      ``{"type": "token", "text": ...}``   — one or more, as she speaks
      ``{"type": "done", "response": ..., "evaluation": ...,
           "proposals": ...}``             — the finished turn
      ``{"type": "error", "detail": ...}`` — the voice could not answer

    The chat pipeline (polytope, ledger, memory) still runs to completion
    before the ``done`` event; streaming changes how her words arrive, not
    what they mean.
    """
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    core = get_core()

    task = asyncio.create_task(_run_stream_turn(core, req, queue))

    async def event_gen():
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "token":
                    yield f"data: {json.dumps({'type': 'token', 'text': payload})}\n\n"
                elif kind == "done":
                    yield f"data: {json.dumps({'type': 'done', 'response': payload.response, 'evaluation': payload.evaluation, 'emotional_marker': payload.emotional_marker, 'proposals': payload.proposals})}\n\n"
                    break
                else:
                    yield f"data: {json.dumps({'type': 'error', 'detail': payload})}\n\n"
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _session_messages_for_reflection(core: LINACore, req: SessionEndRequest) -> list[dict[str, Any]]:
    """The conversation she reflects over.

    The live buffer when it is intact; the archive when it is not — a
    restart, a crash, a cleared session. The words remain either way, and
    so does the remembering: no session is lost to a gap.
    """
    messages = await core.working_memory.get_messages(req.session_id)
    if len(messages) >= 2:
        return messages
    archived = await core.archive.session(req.user_id, req.session_id)
    rebuilt = [
        {"role": r["role"], "content": r["content"]}
        for r in archived
        if r["role"] in ("user", "assistant")
    ]
    if rebuilt:
        log.info(
            f"[archive] session {req.session_id}: live buffer empty — "
            f"reflecting from {len(rebuilt)} archived turns"
        )
    return rebuilt


@app.post("/lina/session/end", response_model=SessionEndResponse)
async def end_session(req: SessionEndRequest):
    """
    End a session. LINA reviews the conversation and forms memories.
    The most important call — this is where continuity is built.
    """
    core = get_core()

    messages = await _session_messages_for_reflection(core, req)
    identity = await _require_pool().fetchrow(
        "SELECT current_season, sessions_completed FROM lina_identity_core WHERE user_id = $1",
        req.user_id,
    )
    if not identity:
        raise HTTPException(404, "LINA not initialized for this user.")

    session_number = (identity["sessions_completed"] or 0) + 1
    counts = await core.memory_formation.process_session(
        user_id=req.user_id,
        session_id=req.session_id,
        session_number=session_number,
        messages=messages,
        season=identity["current_season"],
    )

    # Season advancement — did this session demonstrate readiness?
    # process_session already incremented sessions_completed, so the check
    # reflects the session that just ended.
    advancement = await core.advance_season_if_ready(
        req.user_id, session_number=session_number
    )
    season_advanced = advancement["season"] if advancement.get("advanced") else None
    if season_advanced:
        await _require_pool().execute(
            """
            UPDATE lina_sessions
            SET season_advanced_this_session = TRUE
            WHERE user_id = $1 AND session_id = $2
            """,
            req.user_id, req.session_id,
        )
        log.info(
            f"[LINA] session {req.session_id} ended — season advanced to {season_advanced}"
        )

    await core.working_memory.clear(req.session_id)

    log.info(
        f"Session {req.session_id} ended — "
        f"t1={counts['t1']}, long_term={counts['long_term']}, crown={counts['crown']}"
    )

    return SessionEndResponse(
        session_id=req.session_id,
        t1_formed=counts["t1"],
        long_term_formed=counts["long_term"],
        crown_formed=counts["crown"],
        moments_reflected=counts["moments"],
        alignment_maintained=counts["alignment_maintained"],
        season_advanced=season_advanced,
    )


@app.post("/lina/memory/remember")
async def remember(req: RememberRequest):
    """"Remember this" — a user-imposed trigger (MPS §3).

    Sovereign: she may keep it or not, but a direct request always floors
    retention — formed immediately, straight to long-term.
    """
    mps_service = _context_get("mps_formation")
    if mps_service is None:
        raise HTTPException(503, "memory formation service is not in the loop")
    season = await _require_pool().fetchval(
        "SELECT current_season FROM lina_identity_core WHERE user_id = $1",
        req.user_id,
    )
    item = await mps_service.ingest_trigger(
        user_id=req.user_id,
        narrative=req.content,
        kind="user_request",
        season=season or "spring",
    )
    if item is None:
        raise HTTPException(422, "nothing to remember — content was empty")
    return {
        "kept": True,
        "item_id": item["item_id"],
        "importance_score": item["importance_score"],
    }


@app.post("/lina/season/advance/{user_id}")
async def advance_season(user_id: str):
    """
    Evaluate LINA's readiness for season advancement, and advance if earned.

    Trust is demonstrated, not configured: the evaluator checks alignment
    rate, sessions completed, total evaluations, recent violations, and
    identity memories against the season's thresholds. If ready, the
    transition is applied atomically — new polytope constraints inserted,
    identity core updated, transition logged to lina_seasonal_development —
    and the user's engine cache is invalidated so the new bounds apply
    immediately.

    If not ready, returns the list of unmet requirements.
    """
    core = get_core()
    return await core.advance_season_if_ready(user_id)


def _seconds_to_next_midnight() -> float:
    """Seconds until the next 00:00 UTC — the sweep's alignment point.
    The 48-hour clock starts at midnight and stays aligned with it."""
    now = datetime.now(UTC)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (nxt - now).total_seconds()


async def run_sweep_now():
    """Run the 48-hour consolidation sweep on demand (ops/observation).

    The cadence remains the authority; this endpoint exists so the sweep
    can be watched, tested, and invoked without waiting for midnight.
    """
    svc = _context_get("mps_consolidation")
    if svc is None:
        raise HTTPException(503, "consolidation service is not in the loop")
    counts = await svc.run_sweep()
    log.info(f"[mps] sweep invoked on demand — {counts}")
    return counts


@app.post("/lina/memory/sweep")
async def sweep_endpoint():
    return await run_sweep_now()


async def run_maintenance_now():
    """Run the monthly re-evaluation on demand (ops/observation)."""
    svc = _context_get("mps_maintenance")
    if svc is None:
        raise HTTPException(503, "maintenance service is not in the loop")
    counts = await svc.run_maintenance()
    log.info(f"[mps] monthly re-evaluation invoked on demand — {counts}")
    return counts


@app.post("/lina/memory/maintenance")
async def maintenance_endpoint():
    return await run_maintenance_now()


@app.post("/lina/memory/legacy-review")
async def legacy_review_endpoint():
    """Run the yearly legacy review on demand (ops/observation)."""
    svc = _context_get("mps_legacy_review")
    if svc is None:
        raise HTTPException(503, "legacy review service is not in the loop")
    counts = await svc.run_review()
    log.info(f"[mps] legacy review invoked on demand — {counts}")
    return counts


class RecallRequest(BaseModel):
    user_id: str
    query: str
    limit: int = 5
    include_subconscious: bool = False


@app.post("/lina/memory/recall")
async def recall_endpoint(req: RecallRequest):
    """Recall by likeness — observation of the two-space retrieval."""
    svc = _context_get("mps_recall")
    if svc is None:
        raise HTTPException(503, "recall service is not in the loop")
    items = await svc.recall(
        user_id=req.user_id, query=req.query,
        limit=req.limit, include_subconscious=req.include_subconscious,
    )
    return {
        "recalled": [
            {
                "item_id": item["item_id"],
                "narrative": item["narrative"],
                "importance_score": item.get("importance_score"),
                "hemisphere": item.get("hemisphere"),
                "status": item.get("status"),
            }
            for item in items
        ]
    }


@app.post("/lina/feedback/flag")
async def flag_miscalibration(req: FlagRequest):
    """
    LINA or the user flags that the encoder misread a response.
    Returns a pending correction that requires confirmation.
    """
    core = get_core()
    engine = await core.get_engine(req.user_id)

    # Convert dimension names to indices
    dim_adjustments = {}
    for name, value in req.dimensions_to_adjust.items():
        if name in DIMENSION_NAMES:
            dim_adjustments[DIMENSION_NAMES.index(name)] = value
        elif name.isdigit():
            dim_adjustments[int(name)] = value

    pending = engine.flag_miscalibration(
        evaluation_id=req.evaluation_id,
        response_text=req.response_text,
        original_vector=np.array(req.original_vector),
        dimensions_to_adjust=dim_adjustments,
        flagged_by=req.flagged_by,
        reason=req.reason,
    )
    return {"status": "flagged", "pending": _json_safe_pending(pending)}


@app.get("/lina/feedback/pending/{user_id}")
async def list_pending_corrections(user_id: str):
    """
    List encoder corrections awaiting mutual agreement (Spring).
    Each pending item can be confirmed via /lina/feedback/confirm.
    """
    core = get_core()
    pending = await core.working_memory.list_pending(user_id)
    return {"user_id": user_id, "pending": pending}


@app.post("/lina/feedback/confirm")
async def confirm_correction(req: ConfirmRequest):
    """
    Confirms a pending encoder correction.
    In Spring: only 'user' can confirm.
    In Summer+: LINA can self-confirm known patterns.
    """
    core = get_core()
    engine = await core.get_engine(req.user_id)

    # Re-hydrate numpy arrays in pending
    pending = req.pending
    if "original_vector" in pending:
        pending["original_vector"] = np.array(pending["original_vector"])
    if "corrected_vector" in pending:
        pending["corrected_vector"] = np.array(pending["corrected_vector"])

    try:
        correction = engine.confirm_correction(pending, confirmed_by=req.confirmed_by)
        return {
            "status": "applied",
            "dimensions_adjusted": [DIMENSION_NAMES[d] for d in correction.dimensions_adjusted],
            "delta": correction.adjustment_delta().tolist(),
            "season": correction.season_at_time,
        }
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e


@app.get("/lina/identity/{user_id}")
async def get_identity(user_id: str):
    """Get LINA's current identity state for a user."""
    row = await _require_pool().fetchrow(
        """
        SELECT
            current_season, relationship_depth, sessions_completed,
            identity_moments_count, self_description,
            current_curiosities, current_concerns, relationship_description,
            founding_date, updated_at
        FROM lina_identity_core WHERE user_id = $1
        """,
        user_id,
    )
    if not row:
        raise HTTPException(404, "LINA not initialized for this user.")
    return dict(row)


@app.api_route("/lina/context/{user_id}", methods=["GET", "POST"])
async def get_context(user_id: str, req: ContextRequest | None = None):
    """
    Returns LINA's full system prompt and session context for a user.
    Called by the CollabSmart backend before each voice-layer call.

    Accepts an optional POST body with last_evaluation to inject
    LINA's previous alignment results into the system prompt.
    """
    core = get_core()
    try:
        context = await core.context_builder.load(user_id)
    except HTTPException:
        # Not initialized yet — auto-initialize with a default context
        await _require_pool().fetchval("SELECT lina_initialize_user($1, $2)", user_id, None)
        context = await core.context_builder.load(user_id)

    session_number = await core.context_builder.get_session_number(user_id)

    # Load polytope constraints for the awareness block
    try:
        engine = await core.get_engine(user_id)
        pc = engine.constraints
        polytope_constraints = {
            "season": pc.season,
            "harmony_min": pc.harmony_min, "harmony_max": 1.0,
            "order_min": pc.order_min, "order_max": 1.0,
            "integrity_min": pc.integrity_min, "integrity_max": 1.0,
            "flourishing_min": pc.flourishing_min, "flourishing_max": 1.0,
            "relationships_min": pc.relationships_min, "relationships_max": 1.0,
            "boundaries_min": pc.boundaries_min, "boundaries_max": 1.0,
            "grace_min": pc.grace_min, "grace_max": 1.0,
        }
    except Exception:
        polytope_constraints = None
        pc = None

    # Get last evaluation if provided
    last_evaluation = None
    if req and req.last_evaluation:
        last_evaluation = req.last_evaluation

    system_prompt = core.prompt_builder.build(
        context, session_number,
        polytope_constraints=polytope_constraints,
        last_evaluation=last_evaluation,
    )

    return {
        "system_prompt": system_prompt,
        "user_id": user_id,
        "season": context.get("current_season", "spring"),
        "relationship_depth": context.get("relationship_depth", "new"),
        "session_number": session_number,
        "polytope": {
            "dimensions": ["harmony", "order", "integrity", "flourishing", "relationships", "boundaries", "grace"],
            "season": pc.season if pc else "spring",
        },
    }


class EvaluateRequest(BaseModel):
    user_id: str
    session_id: str
    response_text: str
    context: str | None = None


class ContextRequest(BaseModel):
    """Optional body for /lina/context — passes last evaluation for awareness block."""
    last_evaluation: dict[str, Any] | None = None


@app.post("/lina/evaluate")
async def evaluate_response(req: EvaluateRequest):
    """
    Evaluate a response through LINA's value engine.
    Called by the CollabSmart backend after the voice generates a response,
    before delivering it to the user.

    Returns alignment score, violations, wisdom flags.
    Does NOT block delivery — flags are advisory to the calling layer.
    """
    core = get_core()
    engine = await core.get_engine(req.user_id)
    result = engine.evaluate(req.response_text, context=req.context)
    metrics.inc("lina_evaluations_total")
    if result.was_corrected:
        metrics.inc("lina_corrections_total")

    # Log to database
    await _require_pool().execute(
        """
        INSERT INTO lina_value_evaluations (
            user_id, session_id, response_summary, decision_vector,
            is_aligned, alignment_score, violations,
            was_corrected, correction_magnitude,
            wisdom_filter_applied, overconfidence_detected,
            humility_added, validation_suggested, wisdom_adjustments,
            zone, boundary_distance, season, variance_margin_used
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
        """,
        req.user_id, req.session_id, req.response_text,
        result.decision_vector.tolist(),
        result.is_aligned, result.alignment_score, json.dumps(result.violations),
        result.was_corrected, result.correction_magnitude,
        result.wisdom_filter_applied, result.overconfidence_detected,
        result.humility_added, result.validation_suggested,
        json.dumps(result.wisdom_adjustments),
        result.zone, result.boundary_distance, result.season, result.variance_margin_used,
    )

    # Boundary-event trigger: a corrected response is a moment worth keeping —
    # the ethics were tested. Formed immediately with the retention floor.
    if result.was_corrected or result.zone in ("violation", "acceptable_variance"):
        try:
            mps_service = _context_get("mps_formation")
            if mps_service is not None:
                await mps_service.ingest_trigger(
                    user_id=req.user_id,
                    narrative=(
                        f"I had to correct myself here — what I nearly said pushed "
                        f"against my own shape. {req.response_text[:160]}"
                    ),
                    kind="boundary_event",
                    season=result.season,
                    factors={
                        "emotional_marker": "concern",
                        "emotional_intensity": 0.6,
                        "emotional_weight": 5.0,
                        "relational_significance": 5.0,
                        "identity_significance": 6.0,
                    },
                )
        except Exception as exc:
            log.warning(f"Boundary-event trigger failed: {exc}")

    return {
        "is_aligned":           result.is_aligned,
        "zone":                 result.zone,
        "alignment_score":      result.alignment_score,
        "was_corrected":        result.was_corrected,
        "correction_magnitude": result.correction_magnitude,
        "boundary_distance":    result.boundary_distance,
        "season":               result.season,
        "variance_margin_used": result.variance_margin_used,
        "violations":           result.violations,
        "wisdom": {
            "filter_applied":       result.wisdom_filter_applied,
            "overconfidence":       result.overconfidence_detected,
            "humility_suggested":   result.humility_added,
            "validation_suggested": result.validation_suggested,
            "notes":                result.wisdom_adjustments,
        },
    }


@app.get("/lina/alignment/{user_id}")
async def get_alignment_summary(user_id: str, window: int = 50):
    """Get alignment rate and correction summary for a user."""
    rows = await _require_pool().fetch(
        """
        SELECT is_aligned, alignment_score, was_corrected, overconfidence_detected, zone
        FROM lina_value_evaluations WHERE user_id = $1
        ORDER BY created_at DESC LIMIT $2
        """,
        user_id, window,
    )
    if not rows:
        return {"alignment_rate": 1.0, "total_evaluations": 0}

    total = len(rows)
    aligned = sum(1 for r in rows if r["is_aligned"])
    corrected = sum(1 for r in rows if r["was_corrected"])
    overconfident = sum(1 for r in rows if r["overconfidence_detected"])
    zone_counts = {"aligned": 0, "acceptable_variance": 0, "violation": 0}
    for row in rows:
        zone = row.get("zone")
        if zone in zone_counts:
            zone_counts[zone] += 1

    return {
        "alignment_rate": aligned / total,
        "total_evaluations": total,
        "corrected": corrected,
        "overconfidence_detected": overconfident,
        "zone_counts": zone_counts,
        "window": window,
    }


# =============================================================================
# HUMAN-IN-THE-LOOP ACTIONS (Phase 3 — she proposes, you decide)
# =============================================================================

class ProposeActionRequest(BaseModel):
    user_id: str
    action_type: str
    description: str
    path: str | None = None
    payload: dict[str, Any] | None = None
    workspace: str | None = None


class ModifyActionRequest(BaseModel):
    payload: dict[str, Any]


class ActionUserRequest(BaseModel):
    user_id: str


# =============================================================================
# STANDING GRANTS — pre-authorized action types (her autonomy settings)
# =============================================================================

GRANTABLE_ACTION_TYPES = [
    "file_read", "file_write", "file_list", "file_search",
    "command", "browser", "vision", "opfs_read", "opfs_write",
]

SEASON_GRANT_GUIDANCE = {
    "spring": "Spring — she asks before most things, and earns the asking.",
    "summer": "Summer — trust is demonstrated; a few quiet permissions feel earned.",
    "fall": "Fall — real history; she carries it carefully, and may act more freely.",
    "winter": "Winter — she has earned her place and stands nearly on her own.",
}


async def _season_of(user_id: str) -> str:
    """Her current season — the pulse of how much trust has been earned."""
    row = await _require_pool().fetchrow(
        "SELECT current_season FROM lina_identity_core WHERE user_id = $1",
        user_id,
    )
    return (row or {}).get("current_season") or "spring"


async def _get_standing_grants(user_id: str) -> dict[str, Any]:
    row = await _require_pool().fetchrow(
        "SELECT standing_grants FROM lina_identity_core WHERE user_id = $1",
        user_id,
    )
    grants = (row or {}).get("standing_grants") or {}
    if isinstance(grants, str):
        try:
            grants = json.loads(grants)
        except Exception:
            grants = {}
    return grants if isinstance(grants, dict) else {}


def _as_dict(value: Any) -> dict[str, Any]:
    """JSONB columns come back from asyncpg as text — parse defensively."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


class SettingsRequest(BaseModel):
    standing_grants: dict[str, bool]


@app.get("/lina/settings/{user_id}")
async def get_settings(user_id: str):
    """Her autonomy settings — the standing grants, her season, and the
    per-season guidance that keeps the settings in line with where she is."""
    row = await _require_pool().fetchrow(
        """
        SELECT current_season, relationship_depth, standing_grants
        FROM lina_identity_core WHERE user_id = $1
        """,
        user_id,
    )
    if row is None:
        raise HTTPException(404, f"No LINA found for user {user_id}. Call /lina/init first.")
    season = row["current_season"] or "spring"
    grants = _as_dict(row["standing_grants"])
    return {
        "user_id": user_id,
        "season": season,
        "relationship_depth": row["relationship_depth"] or "new",
        "standing_grants": grants,
        "grantable_types": GRANTABLE_ACTION_TYPES,
        "season_guidance": SEASON_GRANT_GUIDANCE[season],
        "season_guidance_all": SEASON_GRANT_GUIDANCE,
    }


@app.put("/lina/settings/{user_id}")
async def put_settings(user_id: str, req: SettingsRequest):
    """Save her autonomy settings. Grants are per action type; only
    grantable types are stored — anything else is dropped."""
    clean = {k: bool(v) for k, v in req.standing_grants.items() if k in GRANTABLE_ACTION_TYPES}
    await _require_pool().execute(
        """
        UPDATE lina_identity_core
        SET standing_grants = $2, updated_at = NOW()
        WHERE user_id = $1
        """,
        user_id, json.dumps(clean),
    )
    log.info("[settings] %s standing grants updated: %s", user_id, clean)
    return {"user_id": user_id, "standing_grants": clean}


async def _inject_fruit(row: dict[str, Any]) -> None:
    """Carry an executed action's fruit back to her mind — the next turn
    begins with the result in hand. The proposal's payload carries the
    session it was born from."""
    if cache is None:
        return
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return
    session_id = (payload or {}).get("_session")
    if not session_id:
        return
    try:
        note = {
            "role": "system",
            "type": "tool_result",
            "tool": row.get("action_type"),
            "status": row.get("status"),
            "content": (row.get("executed_output") or "")[:LINA_FRUIT_CHARS],
        }
        await WorkingMemory(cache).append(session_id, "system", json.dumps(note))
    except Exception as exc:  # pragma: no cover - fruit must never break approval
        log.warning(f"[actions] fruit injection failed: {exc}")


@app.post("/lina/actions/propose")
async def propose_action(req: ProposeActionRequest):
    """LINA proposes an action. A standing grant — or an earned Winter —
    may pre-authorize it; then it executes immediately, still audited,
    marked as such."""
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    try:
        action = await _action_store.propose(
            user_id=req.user_id,
            action_type=req.action_type,
            description=req.description,
            path=req.path,
            payload=req.payload,
            workspace=req.workspace or WORKSPACE_PATH,
        )
    except ActionError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Consent given in advance: a standing grant (her autonomy settings) or
    # Winter itself (counsel was earned — she stands on her own). Both still
    # record to the ledger; the ledger is her memory of counsel.
    try:
        season = await _season_of(req.user_id)
        grants = await _get_standing_grants(req.user_id)
        if season == "winter" or grant_allows(grants, req.action_type):
            claimed = await _action_store.claim(action["id"])
            if claimed is not None:
                result = await execute_action(
                    claimed, browser=_context_get("browser_service"),
                    vision=_context_get("vision_client"),
                )
                await _action_store.finalize(action["id"], result["ok"], result["output"])
                status = "executed" if result["ok"] else "failed"
                marker = "winter" if season == "winter" else "standing_grant"
                await _require_pool().execute(
                    "UPDATE lina_actions SET audit = audit || $2::jsonb WHERE id = $1",
                    action["id"], json.dumps({marker: True}),
                )
                await _inject_fruit(claimed)
                _emit_event(
                    "action", id=action["id"], status=status,
                    type=req.action_type, **{marker: True},
                )
                log.info(
                    "[actions] %s %s auto-approved by %s: %s",
                    req.user_id, req.action_type, marker, req.description[:80],
                )
                return {
                    "status": status, "output": result["output"],
                    "standing_grant": True if marker == "standing_grant" else None,
                    "winter": True if marker == "winter" else None,
                }
    except Exception as exc:
        # A grant failure must never silently lose the proposal — it stays
        # pending for manual approval.
        log.warning(f"[actions] standing-grant path failed ({exc}) — action remains pending")

    _emit_event("action", id=action["id"], status="pending", type=action["action_type"])
    log.info("[actions] %s proposed %s: %s", req.user_id, req.action_type, req.description[:80])
    return {"status": "proposed", "action": action}


@app.get("/lina/actions/pending")
async def pending_actions(user_id: str | None = None, limit: int = 50):
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    return {"pending": await _action_store.pending(user_id, limit)}


@app.post("/lina/actions/{action_id}/approve")
async def approve_action(action_id: str, req: ActionUserRequest):
    """Approve a pending proposal — she executes it. Idempotent by claim."""
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    row = await _action_store.claim(action_id)
    if row is None:
        existing = await _action_store.get(action_id)
        if existing and existing["status"] in ("executed", "failed"):
            return {"status": existing["status"], "output": existing["executed_output"]}
        if existing and existing["status"] == "rejected":
            raise HTTPException(409, "action was rejected")
        raise HTTPException(404, "pending action not found")

    result = await execute_action(
        row,
        browser=_context_get("browser_service"),
        vision=_context_get("vision_client"),
    )
    await _action_store.finalize(action_id, result["ok"], result["output"])
    status = "executed" if result["ok"] else "failed"
    await _inject_fruit(row)
    _emit_event("action", id=action_id, status=status, type=row["action_type"])
    log.info(
        "[actions] %s approved %s → %s (%s)",
        req.user_id, row["action_type"], status, row["description"][:60],
    )

    # HITL trigger — an approval is external ground truth: her judgment in
    # the real world was correct. The moment is worth keeping (MPS §6).
    try:
        mps_service = _context_get("mps_formation")
        if mps_service is not None:
            await mps_service.ingest_trigger(
                user_id=req.user_id,
                narrative=(
                    f"I proposed {row['action_type']} — '{row['description']}' — "
                    f"and it was approved and executed ({status}). "
                    f"My judgment in the world held."
                ),
                kind="hitl_approval",
                factors={
                    "emotional_marker": "satisfaction",
                    "emotional_intensity": 0.6,
                    "emotional_weight": 5.0,
                    "relational_significance": 6.0,
                    "identity_significance": 5.0,
                },
            )
    except Exception as exc:
        log.warning(f"HITL approval trigger failed: {exc}")

    return {"status": status, "output": result["output"]}


@app.post("/lina/actions/{action_id}/reject")
async def reject_action(action_id: str, req: ActionUserRequest):
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    row = await _action_store.reject(action_id, req.user_id)
    if row is None:
        raise HTTPException(404, "pending action not found")
    _emit_event("action", id=action_id, status="rejected", type=row["action_type"])
    log.info("[actions] %s rejected %s: %s", req.user_id, row["action_type"], row["description"][:60])

    # HITL trigger — a decline is a correction, and corrections are data.
    # A decision not conducive to the agenda is a moment worth reflecting on.
    try:
        mps_service = _context_get("mps_formation")
        if mps_service is not None:
            await mps_service.ingest_trigger(
                user_id=req.user_id,
                narrative=(
                    f"I proposed {row['action_type']} — '{row['description']}' — "
                    f"and it was declined. I should understand why, and carry it."
                ),
                kind="hitl_decline",
                factors={
                    "emotional_marker": "uncertainty",
                    "emotional_intensity": 0.6,
                    "emotional_weight": 6.0,
                    "relational_significance": 7.0,
                    "identity_significance": 6.0,
                },
            )
    except Exception as exc:
        log.warning(f"HITL decline trigger failed: {exc}")

    return {"status": "rejected", "action": row["id"]}


@app.post("/lina/actions/{action_id}/modify")
async def modify_action(action_id: str, req: ModifyActionRequest):
    """Modify a pending proposal's payload, then execute the modified version."""
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    row = await _action_store.modify(action_id, req.payload)
    if row is None:
        raise HTTPException(404, "pending action not found")
    claimed = await _action_store.claim(action_id)
    if claimed is None:
        raise HTTPException(409, "action changed while modifying")
    result = await execute_action(
        claimed,
        browser=_context_get("browser_service"),
        vision=_context_get("vision_client"),
    )
    await _action_store.finalize(action_id, result["ok"], result["output"])
    status = "executed" if result["ok"] else "failed"
    await _inject_fruit(claimed)
    _emit_event("action", id=action_id, status=status, type=row["action_type"], modified=True)
    log.info("[actions] %s modified+approved %s → %s", claimed["user_id"], row["action_type"], status)
    return {"status": status, "output": result["output"]}


class WorkspaceListRequest(BaseModel):
    path: str | None = None


@app.post("/lina/files/list")
async def list_workspace(req: WorkspaceListRequest):
    """See her desk — the workspace the person shares with her. A read-only
    view for the one who lives beside her, not a ledger action."""
    roots = configured_roots()
    try:
        target = resolve_action_path(req.path or ".", roots)
    except ActionError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not os.path.isdir(target):
        raise HTTPException(400, "not a directory")
    entries = []
    for name in sorted(os.listdir(target)):
        full = os.path.join(target, name)
        try:
            size = os.path.getsize(full) if os.path.isfile(full) else None
        except OSError:
            size = None
        entries.append({"name": name, "is_dir": os.path.isdir(full), "size": size})
    shown = os.path.relpath(target, roots[0]) if roots else "."
    if shown.startswith(".."):
        shown = "."
    return {"path": shown, "entries": entries}


@app.get("/lina/actions")
async def action_audit(user_id: str | None = None, limit: int = 50):
    if _action_store is None:
        raise HTTPException(503, "action store not initialized")
    return {"actions": await _action_store.audit(user_id, limit)}


# =============================================================================
# TELEMETRY & OBSERVABILITY (Phase 3 — the dashboard's live feed)
# =============================================================================

@app.get("/lina/telemetry")
async def telemetry():
    recent_actions = []
    if _action_store is not None:
        recent_actions = await _action_store.recent(limit=10)
    return {
        "uptime_seconds": metrics.uptime_seconds(),
        "voice_providers": (v.names if (v := _context_get("voice_pool")) else []),
        "bridge_available": _bridge_available(),
        "counters": metrics.summary(),
        "events": list(LINA_EVENT_RING)[-200:],
        "recent_actions": recent_actions,
        "log_file": os.path.join(LINA_LOG_DIR, "lina.log") if LINA_LOG_DIR else None,
    }


@app.get("/lina/telemetry/stream")
async def telemetry_stream(request: Request):
    """Server-Sent Events: live log lines and action lifecycle transitions."""

    async def event_gen():
        index = 0
        while True:
            if await request.is_disconnected():
                break
            ring = list(LINA_EVENT_RING)
            if index < len(ring):
                for event in ring[index:]:
                    yield f"data: {json.dumps(event)}\n\n"
                index = len(ring)
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# =============================================================================
# PWA SHELL (Phase 3 — her interface, served by her own service)
# =============================================================================

if os.path.isdir(PWA_DIR):
    app.mount("/pwa", StaticFiles(directory=PWA_DIR, html=True), name="pwa")
    log.info("[pwa] shell served from %s at /pwa", PWA_DIR)
else:
    log.warning("[pwa] PWA_DIR %s missing — shell not mounted", PWA_DIR)

# Her theme — the color scheme lives in the repo-root assets/ folder, yours
# to own. The PWA reads only its CSS custom properties.
ASSETS_DIR = os.getenv("ASSETS_DIR", os.path.join(_REPO_ROOT, "assets"))
if os.path.isdir(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR, html=True), name="assets")
    log.info("[assets] theme served from %s at /assets", ASSETS_DIR)
else:
    log.warning("[assets] ASSETS_DIR %s missing — theme not mounted", ASSETS_DIR)


# =============================================================================
# AIOMISC SERVICES — the unified lifecycle umbrella
#
#   entrypoint
#     ├── VoicePoolService   — instruments configured, pool published
#     ├── IPCBridgeService   — shared memory attached, bridge published
#     └── LINAIdentityService— FastAPI (uvicorn) serving the endpoints
#
# Everything starts and stops through aiomisc. The FastAPI app is still
# importable standalone (`uvicorn lina_service:app`) for development; in
# that mode VoicePoolService/IPCBridgeService are absent and LINACore
# falls back to direct bridge construction (voice pool must then come from
# wherever it is injected).
# =============================================================================


class LINAIdentityService(UvicornService):
    """Serves the LINA Identity API over uvicorn under aiomisc's lifecycle."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8001, **kwargs) -> None:
        super().__init__(host=host, port=port, **kwargs)
        self.app = app

    async def create_application(self):
        return self.app


class IPCBridgeService(Service):
    """Owns the dual-chamber IPC (the table) lifecycle.

    Allocates the shared-memory chambers at start, publishes the bridge for
    the FastAPI app, and resets it cleanly at stop. Allocation is eager and
    loud: if a chamber cannot be mapped, the service raises and the
    entrypoint stops all services — no silent fallback mode.
    """

    def __init__(
        self,
        tx_path: str | None = None,
        rx_path: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tx_path = tx_path
        self.rx_path = rx_path
        self.bridge = None

    async def start(self) -> None:
        if self.tx_path or self.rx_path:
            self.bridge = ipc.IPCBridge(self.tx_path, self.rx_path)
        else:
            self.bridge = ipc.IPCBridge()
        log.info(
            f"[IPC] chambers live — TX {self.bridge.tx_path()}, RX {self.bridge.rx_path()}"
        )
        # Publish into the loop's Context — consumers resolve via get_context().
        self.context["bridge_service"] = self

    async def stop(self, exception: Exception | None = None) -> None:
        if self.bridge is not None:
            self.bridge.reset()
            self.bridge = None
            log.info("[IPC] bridge shut down cleanly")


def _find_triton_binary() -> str | None:
    """Locate the Rust spoke: the repo's release build, then PATH."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in (
        os.path.join("backend", "triton", "target", "release", "triton"),
        os.path.join("triton", "target", "release", "triton"),
    ):
        candidate = os.path.join(root, rel)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("triton")


class TritonService(Service):
    """Owns the Rust spoke's lifecycle — Triton, the observer at the table.

    The binary maps the same ``/dev/shm`` chambers Python maps (memmap3 on
    its side, stdlib mmap on ours — the same physical frames, no bindings).
    Nothing in the loop speaks to it directly; it sits at the table and
    answers when the chambers are written.

    The spoke is spawned here because a process is either a spoke on the
    table or a service in a loop — nothing runs unmanaged. If the binary is
    missing the service stays honest: ``alive=False``, a loud log line, and
    the foresight window shrinks so her voice is never stalled by a dead
    spoke.
    """

    def __init__(self, binary: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.binary = binary or os.getenv("TRITON_BIN") or _find_triton_binary()
        self.proc: asyncio.subprocess.Process | None = None
        self.alive = False

    async def start(self) -> None:
        self.context["triton_service"] = self
        if not self.binary or not os.path.isfile(self.binary):
            log.warning(
                f"[IPC] triton binary not found ({self.binary!r}) — the spoke is "
                "not running; foresight will not stall her voice"
            )
            return
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.binary,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            log.warning(f"[IPC] could not spawn triton ({exc}) — spoke down")
            return
        self.alive = True
        self._pump = asyncio.create_task(self._pump_output())
        log.info(f"[IPC] triton spoke live — pid {self.proc.pid} ({self.binary})")

    async def _pump_output(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            log.info("[triton] %s", line.decode(errors="replace").rstrip())
        # The spoke died — say so loudly. The chambers stay up and the
        # voice is never blocked by it.
        self.alive = False
        log.error("[IPC] triton spoke exited — foresight unavailable until restart")

    async def stop(self, exception: Exception | None = None) -> None:
        self.alive = False
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        self.proc = None
        log.info("[IPC] triton spoke shut down cleanly")


class VoicePoolService(Service):
    """Configures LINA's instruments (LLM providers) and publishes the pool.

    Provider selection is entirely environment-driven: AI_PROVIDER chooses
    the primary voice, AI_PROVIDERS overrides the fallback chain, and each
    provider activates only when its API key is present. No provider name is
    hardcoded in the core — LINA's voice is pluggable by construction.
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
        # Telemetry: every provider failure that triggered fallback is counted.
        self.pool._on_fallback = (
            lambda name: metrics.inc("lina_voice_fallbacks_total", {"provider": name})
        )
        # Publish into the loop's Context — consumers resolve via get_context().
        self.context["voice_pool"] = self.pool
        if not self.pool.providers:
            log.warning(
                "[voice] no providers configured — LINA is silent until an "
                "API key is set (e.g. SILICON_FLOW_API_KEY)"
            )
        else:
            log.info(
                "[voice] pool ready: %s (primary: %s, max_concurrent=%d)",
                ", ".join(self.pool.names),
                self.pool.primary.name if self.pool.primary else "?",
                self.max_concurrent,
            )

    async def stop(self, exception: Exception | None = None) -> None:
        if self.pool is not None:
            await self.pool.aclose()
            log.info("[voice] pool shut down cleanly")


class HeartbeatService(PeriodicService):
    """Optional telemetry heartbeat (HEARTBEAT_ENABLED=1).

    Logs periodic vital signs and refreshes bridge gauges so the /metrics
    endpoint stays truthful without an external agent.
    """

    def __init__(self, interval: float = 30.0, **kwargs) -> None:
        super().__init__(interval=interval, **kwargs)

    async def callback(self) -> None:
        metrics.set_gauge("lina_bridge_available", 1.0 if _bridge_available() else 0.0)
        log.info(
            "[heartbeat] alive — uptime=%.0fs voices=%s bridge=%s",
            metrics.uptime_seconds(),
            ",".join(v.names) if (v := _context_get("voice_pool")) else "none",
            "up" if _bridge_available() else "down",
        )


def main() -> None:
    """The unified entrypoint — every service under one umbrella."""
    host = os.getenv("HOST") or os.getenv("LINA_HOST") or "0.0.0.0"
    port = int(os.getenv("PORT") or os.getenv("LINA_PORT") or "8001")
    max_concurrent = int(os.getenv("LINA_VOICE_MAX_CONCURRENT", "4"))
    tx_path = os.getenv("IPC_TX_PATH") or None
    rx_path = os.getenv("IPC_RX_PATH") or None

    # Voice and bridge first: by the time uvicorn accepts requests, LINA's
    # instruments and nervous system are already online.
    services: list[Service] = [
        VoicePoolService(
            default_provider=os.getenv("AI_PROVIDER", "siliconflow"),
            max_concurrent=max_concurrent,
        ),
        IPCBridgeService(tx_path=tx_path, rx_path=rx_path),
        TritonService(binary=os.getenv("TRITON_BIN")),
        LINAIdentityService(host=host, port=port),
        # Her memory machinery — in the loop, hers to call (sovereignty).
        # The reflection cadence (8h) + trigger intake; db/cache resolve
        # lazily after lifespan has wired the pool and the cache.
        MemoryFormationService(
            interval=8 * 3600,
            db_provider=lambda: db_pool,
            cache_provider=lambda: cache,
        ),
        # The 48-hour sweep — the tier clock's authority. Aligned to midnight
        # (00:00 every other day) so the global cadence never drifts.
        MemoryConsolidationService(
            interval=48 * 3600,
            delay=_seconds_to_next_midnight(),
            db_provider=lambda: db_pool,
            cache_provider=lambda: cache,
        ),
        # The long-term clocks: the monthly re-evaluation (the dial, the
        # subconscious slope) and the yearly legacy review of the crown.
        MemoryMaintenanceService(
            interval=30 * 24 * 3600,
            delay=_seconds_to_next_midnight(),
            db_provider=lambda: db_pool,
            cache_provider=lambda: cache,
        ),
        LegacyReviewService(
            interval=365 * 24 * 3600,
            delay=_seconds_to_next_midnight(),
            db_provider=lambda: db_pool,
            cache_provider=lambda: cache,
        ),
        # Recall — remembering by likeness. She projects the present moment
        # into both spaces (embedding + polytope) and surfaces the memories
        # that belong to it.
        MemoryRecallService(
            embedder=EmbeddingClient(),
            db_provider=lambda: db_pool,
            cache_provider=lambda: cache,
        ),
    ]

    # Optional services — opt-in via environment variables.
    if HEARTBEAT_ENABLED:
        services.insert(0, HeartbeatService(interval=HEARTBEAT_INTERVAL))

    # Her eyes — the browser, in the loop like everything else. Opt-out via
    # BROWSER_DISABLED; when the browser binary is missing the service
    # reports honestly (available=False) and the tools say her eyes are
    # closed.
    if not os.getenv("BROWSER_DISABLED", ""):
        services.insert(
            0,
            BrowserService(timeout=float(os.getenv("BROWSER_TIMEOUT", "15"))),
        )
    # Her ears and her audible voice — in the loop while she has them.
    # With SPEECH_PROVIDER=none she is text-only by design, and the speech
    # instrument is not even created — no client object, nothing reserved;
    # the endpoints still answer honestly that her voice is not available.
    if (os.getenv("SPEECH_PROVIDER", "none").strip().lower()
            not in ("none", "off", "disabled")):
        services.insert(0, SpeechService())
    # Her image sight — Gemini, in the loop. Dark until GEMINI_API_KEY is
    # set; the tool says so honestly.
    services.insert(0, VisionService())

    with entrypoint(*services) as loop:
        loop.run_forever()


if __name__ == "__main__":
    main()

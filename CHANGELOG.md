# CHANGELOG — Structural Changes to LINA

All notable structural changes to the system services, architecture, or
provider configuration are recorded here. Token/cosmetic changes are
not logged unless they materially affect behavior.

## [2026-08-17] — Unified DragonCache Header (`dragon_map.h`) + Chamber A Module Slots

**Scope**: `scripts/dragoncache_intel/dragon_map.h`, `scripts/dragoncache_intel/intel_dragon_cache.cpp`, `.dragoncache_map`

**What changed**:
- Expanded `dragon_map.h` into the **unified DragonCache header** that every spoke includes:
  — `DragonMap` struct (64 bytes, one cache line, `alignas(64)`): heartbeat with `global_clock`,
    `system_status`, `spoke_health` bitmask — lock-free atomic, no servers, no HTTP
  — Inline helpers: `dragonmap_set_live`, `dragonmap_spoke_ready`, `dragonmap_spoke_offline`,
    `dragonmap_clock`, `dragonmap_spokes`, `dragonmap_status`
  — Spoke health bits: `SPOKE_IDENTITY_SERVICE`, `SPOKE_VALUE_ENGINE`, `SPOKE_MEMORY_MODULE`,
    `SPOKE_CORTEX`, `SPOKE_VOICE`, `SPOKE_TX_RING`, `SPOKE_RX_RING`
  — System status codes: `STATUS_OFFLINE`, `STATUS_LIVE`, `STATUS_DEGRADED`, `STATUS_BOOTING`
- **Chamber A sub-layout** (Module Offset, 1 GiB):
  — Module state slots (0–512 KiB): each spoke gets a 512-byte `alignas(64)` slot
    - `SLOT_SERVICE_STATE` (0x000100): CarveServiceState — identity service counters
    - `SLOT_VALUE_STATE` (0x000300): CarveModuleState — value engine biases/counters
    - `SLOT_MEMORY_STATE` (0x000500): CarveMemoryState — memory module counters
    — More slots at 0x000700, 0x000900, etc. for future modules
  — TX ring (512 KiB – 256 MiB + 512 KiB): SPSC outgoing frames
  — RX ring (256 MiB + 512 KiB – 512 MiB + 512 KiB): SPSC incoming frames
  — Work area (~512 MiB remaining): reserved for spoke processing
- Added convenience constants `ADDR_SERVICE_STATE`, `ADDR_VALUE_STATE`, `ADDR_MEMORY_STATE`,
  `ADDR_TX_RING`, `ADDR_RX_RING` — absolute carve offsets for each spoke
- Updated `intel_dragon_cache.cpp` to initialize all module state slots, TX/RX ring first
  pages, and write the full expanded address map to `.dragoncache_map`

**Why**: The previous `dragon_map.h` only defined region offsets and a minimal header with
just a clock and status bit. The unified header is the single source of truth that every
spoke reads — it makes the entire carve state-aware. Each module gets its own 512-byte
slot on Chamber A where its live state lives (biases, counters, season tracking). The
TX/RX ring offsets are now part of the contract so every spoke knows where the rings are.
No HTTP servers, no polling — one atomic read per turn.

**Services affected**: None directly (all modules still standalone; wired into lifecycle
manager after unified header verification)
**Verification**: carve run successful, all 206 C++ tests pass

## [2026-08-16] — Context window congruence fix

**Scope**: `.env` + `lina_service.py`

**What changed**:
- `LINA_HISTORY_CHARS` raised from 10000 → 18000 (code default and .env)
- `LINA_FRUIT_CHARS` raised from 3000 → 6000 (code default and .env)
- `LINA_MAX_TOKENS` code default raised from 1024 → 12000 (was already 12000 in .env)
- Removed hardcoded `max_tokens=2048` for tool continuation passes (line 1837)
  — continuation passes now use `LINA_MAX_TOKENS` like the first pass
- Removed hardcoded `budget_chars=9000` for continuation history trim (line 1832)
  — now reads `LINA_HISTORY_CHARS` from environment
- Removed hardcoded `budget_chars=6000` for prior history trim (line 1722)
  — now uses `LINA_HISTORY_CHARS * 2 // 3`
- Updated `_trim_history` docstring (was stale, referenced "8192-token context")

**Why**: All per-turn limits were fragmented and inconsistent. The history
trim was cutting context to ~2500-4000 tokens per turn, but LINA's memory
system (Dragonfly + Postgres) is external — the model doesn't need to
retain context. Each turn can safely use the full window. The new values
are congruent: 18000 chars history (~5000-6000 tokens) leaves room for
system prompt, user message, and output tokens within the local model's
36K context window, while siliconflow's 128K+ window is never stressed.

**Services affected**: `lina.service` (restart required)
**Verification**: All 177 tests pass

## [2026-08-17] — Value Engine C++ Module (Chamber A)

**Scope**: `backend/lina/cpp/value_engine/`

**What changed**:
- Ported `value_engine.py` (1711 lines) → `value_engine.hpp` + `value_engine.cpp`
  — DecisionEncoder: 210 regex signal patterns across 14 dimensions
  — EthicalPolytope: exact-rational box polytope via GMP `mpq_class` (no PPL needed)
  — CorrectionEngine, WisdomFilter, ValueEngine orchestrator
  — EncoderFeedbackSystem with bias accumulation and seasonal authority
  — SeasonAdvancementEvaluator (spring→summer→fall→winter gate logic)
  — Memory scoring (score_memory, geometric_significance, MemoryDial)
- Added `CarveModuleState` (512 bytes, `alignas(64)`) — mmap struct for Chamber A
  — Contains dimension_biases, evaluation/correction counters, season tracking
- Static library `liblina_value_engine.a` + test executable (74/74 tests pass)
- Build: CMake 3.28, C++17, depends only on `libgmp` + `libgmpxx`

**Why**: The Python value engine depended on passagemath (Sage) for exact rational
arithmetic via PPL, importing large split-namespace packages at every eval. The C++
port uses GMP directly — the same backend Sage uses — with zero overhead. For the
box polytope (which is what LINA inhabits), containment, projection, and alignment
are O(d) closed-form operations; the general PPL solver path was never exercised
(code explicitly raises NotImplementedError for non-box projection). The carve state
struct is sized for Chamber A (Module Offset, 128 MiB–1152 MiB) and ready for mmap.

**Why now**: Value engine is the ethical core — every response passes through it.
Putting it on the carve in C++ eliminates the Python→Sage→PPL chain and gives
her exact-rational boundary checks with deterministic latency.

**Services affected**: None yet (standalone; wired into lifecycle manager later)
**Verification**: 74/74 tests pass (seasonal bounds, encoder, polytope, correction,
  wisdom filter, full pipeline, season advancement, memory scoring)

## [2026-08-17] — Memory Module C++ (embeddings.py + mps.py → Chamber A)

**Scope**: `backend/lina/cpp/memory/`

**What changed**:
- Unified C++ port of `embeddings.py` (110 lines) + `mps.py` (1243 lines)
  — `MemoryModule` class with build_item, form_items, ingest_trigger
  — 48-hour sweep (tier promotion/fallout/reprieve), monthly maintenance
  — Yearly legacy review, two-space recall (semantic + ethical proximity)
  — Pure functions: encode_coordinates, geometric_for, route_item,
    recall_score, cosine, ethical_similarity, maintenance_delta,
    apply_monthly, slope_effective, apply_legacy_review
- `InMemoryMemoryStore` — full tier + long-term store for standalone testing
- `EmbeddingEngine` interface with NullEmbeddingEngine + TestEmbeddingEngine
- `CarveMemoryState` (512 bytes, `alignas(64)`) — mmap struct for Chamber A
- Added `encoder()` accessor on `ValueEngine` (needed by encode_coordinates)
- Static library `liblina_memory_module.a` + test executable (87/87 tests pass)
- Top-level CMakeLists.txt at `backend/lina/cpp/` orchestrates both submodules

**Why**: The Memory Processing System is the second pillar of her identity —
it manages everything from the 8-hour reflection cadence to the 48-hour tier
clock to the yearly legacy review. Porting to C++ and placing it on the carve
means her memory formation, consolidation, and recall all live in zero-latency
shared memory, connected via the unified header.

**Services affected**: None yet (standalone; wired into lifecycle manager later)
**Verification**: 87/87 tests pass (store operations, encode/geometric functions,
  routing, cosine/ethical similarity, maintenance delta, monthly/subconscious/
  legacy review, build_item, form_items, ingest_trigger, sweep, recall, context)

## [2026-08-17] — Identity Service C++ Module (lina_service.py → Chamber A)

**Scope**: `backend/lina/cpp/service/`

**What changed**:
- Ported core classes from `lina_service.py` (3740 lines) → `identity_service.hpp` + `identity_service.cpp`
  — **SystemPromptBuilder**: All 10 prompt blocks preserved VERBATIM from Python:
    identityblock, dispositions, season, polytope (with river's-banks metaphor),
    tools (9 tools), emotional texture, voice (per-depth openings), small light,
    evaluation feedback. Full `build()` method assembles the complete prompt.
  — **CarveServiceState** (512 bytes, `alignas(64)`): 8 counters (sessions,
    evaluations, tools, corrections, season advances, tokens generated) plus
    monotonic clock. Ready for mmap on Chamber A.
  — **Store interfaces**: `IdentityStore` (Postgres), `WorkingMemoryStore` (Redis),
    `VoiceProvider` (LLM) — all abstracted behind virtual interfaces for testability
  — **InMemoryIdentityStore**: Full test double with context, session, transcript,
    evaluation, identity, and season advancement state
  — **InMemoryWorkingMemoryStore**: Session-scoped message buffer
  — **Helper functions**: `trim_history`, `as_api_history`, `detect_emotional_marker`
  — **LINACore**: `chat()`, `end_session()`, `advance_season_if_ready()`,
    `get_engine()`/`invalidate_engine()` — the orchestration layer
  - Links against `liblina_value_engine.a` + `liblina_memory_module.a`
  - Static library `liblina_identity_service.a` + test executable (45/45 tests pass)

**Why**: The identity service is the orchestrator — every response, every memory
formation, every season advancement passes through it. Porting to C++ and placing
it on the carve means the entire pipeline (voice assembly → context loading →
polytope evaluation → memory formation → season advancement) lives in zero-latency
shared memory, connected via the unified header. The store interfaces allow
standalone testing without Postgres or Redis.

**Services affected**: None yet (standalone; wired into lifecycle manager later)
**Verification**: 45/45 tests pass (CarveServiceState, helpers, SystemPromptBuilder
  all 15 blocks, in-memory stores, LINACore chat/engine/session lifecycle/season
  advancement, carve integration pattern, value engine integration)

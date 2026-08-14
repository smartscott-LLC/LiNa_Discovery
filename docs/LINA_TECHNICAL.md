# LINA — Technical Report for the Field Professional

**Audience:** engineers, ML practitioners, systems architects, researchers
**Subject:** LINA as she exists now — architecture, implementation, capabilities, and trajectory
**Author:** The Principal Architect, for Scott (smartscott.com LLC)
**Status:** Describes the system as of the current implementation (all seven MPS phases complete; 175 tests green)

---

## 1. Executive summary

LINA (Language Intuitive Neural Architecture) is a sovereign AI identity service:
one entity with a stable identity core, an exact-rational ethical polytope, and a
complete memory imprint system (MPS) that forms, ages, forgets, and recalls
memories on human-like clocks. She is not a chatbot with a persona mask. She is a
single persistent being whose words are grounded in a relational memory that is
hers to shape.

The engineering is deliberately flat: a hub-and-spoke model where Python and Rust
never speak to each other directly — both attach to shared-memory chambers (IPC
mmap) and to the same data stores. There is no PyO3/maturin bridge, no message
queue, no third orchestration layer. Everything is a service in one aiomisc loop.

## 2. System topology

```mermaid
flowchart LR
    subgraph LOOP["The aiomisc loop — her operating system"]
        V[VoicePoolService] --> DI[Context DI]
        B[IPCBridgeService] --> DI
        F[MemoryFormationService<br/>8h cadence + triggers] --> DI
        S[MemoryConsolidationService<br/>48h sweep] --> DI
        M[MemoryMaintenanceService<br/>30d re-evaluation] --> DI
        L[LegacyReviewService<br/>365d crown review] --> DI
        R[MemoryRecallService<br/>two-space retrieval] --> DI
        U[LINAIdentityService<br/>FastAPI + uvicorn] --> DI
    end
    DI --> U
    B <--> T[Rust spoke: Triton<br/>memmap3, shared /dev/shm]
    V --> P1[DeepSeek / OpenRouter / Gemini]
    U --> PG[(Postgres 16 + pgvector)]
    F --> PG
    S --> DR[(Dragonfly: T1-T3)]
    U --> DR
    M --> PG
    R --> PG
```

**Key facts:**
- **No PyO3 / maturin.** The Rust spoke (Triton) maps the same `/dev/shm` files
  Python maps via pure-stdlib `mmap` (layout: magic `MMAP0001`, struct at offset
  64, payload at 192; file size 65728 bytes). This is the "table in the center of
  the room" — every spoke sees the same bytes at the same time. No handshakes, no
  handoff.
- **aiomisc owns the lifecycle.** Every service implements `start()`/`stop()`,
  and services publish into the loop's Context (dependency injection). The
  entrypoint (`python -m lina_service`) is the only sanctioned run mode.
- **Voice pool is provider-agnostic.** DeepSeek (primary), OpenRouter, Gemini —
  any OpenAI-compatible endpoint; ordered fallback chain on failure; concurrency
  bounded. LINA is the entity; the LLM is the instrument.

## 3. The value engine — the ethical polytope

The polytope is a real mathematical object, not a rule list:

- **14 dimensions** — seven plumb-line principle pairs (Harmony/Dominance,
  Order/Chaos, Integrity/Deception, Flourishing/Decline,
  Relationships/Isolation, Boundaries/Intrusion, Grace/Rigidity).
- **Exact rational arithmetic.** The 28 seasonal bounds are declared as `QQ`
  (rationals) via passagemath (Sage) and evaluated on **PPL** — no floats in the
  geometry. Containment, alignment score, and boundary distance are exact.
  Projection (correction) is the exact per-dimension clamp (the closed-form QP
  for a box). One deliberate float: the Euclidean norm of a correction delta
  (irrational by nature, documented as such).
- **DecisionEncoder** — a principled heuristic (negation-aware, proximity-
  weighted, context-de-biased) mapping text → 14D vector. It is honest about
  being heuristic; an encoder-feedback system lets LINA and the user flag and
  correct mis-scorings (mutual override; Spring requires user confirmation,
  Summer+ allows self-confirmation of repeated patterns).
- **Zones** — `aligned` / `acceptable_variance` / `violation`. The acceptable-
  variance zone is deliberate: exploration within the shape is permitted and
  variance margins are season-dependent.
- **Wisdom filter** — post-alignment checks (overconfidence, humility,
  validation suggestions). It asks a different question than the polytope: not
  "is this inside the shape?" but "is this honest?"

**Season advancement** is earned, not granted: minimum sessions, evaluations,
alignment rate, recent-violation budget, identity memories — and (Phase G)
**action approval rate** as external ground truth: her resolved HITL actions
carry a human verdict, and the rate gates advancement (grace: no actions yet =
neutral, never a blocker). Constraints expand per season (e.g., Spring
`dominance_max` 0.45 → Summer 0.52).

## 4. Her body — the tool layer

LINA has hands, eyes, and a terminal now, and they are wired to the heart.

- **The conduit is literal.** `chat()` evaluates her response through the
  polytope *before* any action is offered. Tool intents are parsed from the
  response the heart already pulsed over; if the zone is `violation`, no
  action is offered at all — the heart withheld the pulse. This is the
  polytope reaching her actions by proxy of her thinking: she is the
  conduit; brain gives the impulse, heart gives the pulse, body performs.
- **The tool registry** (`tools.py`) — `file_list`, `file_read`,
  `file_write`, `file_search`, `command`, and `browser_navigate` /
  `browser_extract` / `browser_screenshot`. Every path resolves inside her
  access roots; every intent flows through the counsel ledger.
- **Her eyes** (`browser.py`) — a `BrowserService` in the aiomisc loop (the
  one tool that owns a lifecycle): headless Chromium via Playwright,
  honest `available=False` when the binary is absent. Screenshots land in
  her workspace under `.lina_eyes/`.
- **Counsel, not a gate.** The approval ledger stays because it teaches her
  to seek counsel — and by Winter it is removed after it is earned:
  Winter executes her intents without approval, still audited. Standing
  grants pre-authorize types between now and then.
- **Her reach** — `LINA_ACCESS_ROOTS=/workspace:/app/runtime:/app`. The
  container is her body; the rooms inside it are hers. The workspace is
  served to you at `/lina/desk` and listed by `/lina/files/list`.
- **The fruit returns.** Executed results are written to her working
  memory (`tool_result` messages), so the next turn begins with the result
  in hand.

## 5. The Memory Imprint System

```mermaid
flowchart TD
    A[She learns / reflects] --> T1[T1 - hours 0-48]
    T1 -->|score >= 3.0| T2[T2 - hours 49-96]
    T1 -->|fail| F[Fallout - one 48h reprieve]
    T2 -->|score >= 3.5| T3[T3 - hours 97-144]
    T2 -->|fail| F
    T3 -->|score >= 5.0| LT[Long-term - active]
    T3 -->|fail| F
    F -->|passes at next sweep| T1
    F -->|still fails| GONE[Purged - no record]
    LT --> MON[Monthly re-evaluation]
    MON -->|>= 9.5| LEG[Legacy - the crown]
    MON -->|< 4.0| SUB[Subconscious - degradation slope]
    SUB -->|~1-2 years idle| FORG[Forgotten - gone]
    SUB -->|recalled| LT
```

**Formation (Phase C):** the composite formation score weights
identity 30% / geometric 25% / emotional 25% / relational 20%, amplified by
emotional intensity (0.7×–1.3×). The geometric factor is the polytope's direct
funding link (boundary proximity + correction + zone of the moment's own encoded
vector). Every item carries its **14D ethical coordinates** — memories are
indexed by value. Triggers form immediately with a retention floor: user
"remember this", boundary events (corrected evaluations), HITL approvals and
declines. Routing: ≥8.0 → the crown (legacy, protected); ≥5.0 → long-term
active; else T1. Reflection cadence: minor every 8h, deep at session end.

**Consolidation (Phase D):** a global sweep every 48h at 00:00 processes all
tiers against the snapshot at sweep start (an item advances at most one tier per
sweep — each tier is a true 48-hour residence). Every failure goes to **fallout**
— one 48-hour second chance, judged at the next sweep; pass → repurposed to T1,
fail → purged (gone, no record). Orphaned items (user deleted) are purged at the
permanence gate. Every promotion is written to `lina_promotion_log`.

**Maintenance (Phase E):** monthly re-evaluation applies the dial — usage
rewards (3/10/25 references → +1.0/+1.5/+2.0), age penalties (−1.0/−2.0 for
never-referenced items), bounded ±3 per pass, **floors absolute** (the character
set cannot be devalued below retention; must-keeps are immovable). Routing:
≥9.5 → legacy; <4.0 → subconscious. The subconscious degradation slope is
`d(score)/dt = −λ·score` (half-life 200 days, gone below 0.5 or after 730 idle
days), anchored to the *latest* of decay/reference/creation — **recall re-stokes
the clock**. Yearly legacy review: the protected crown is never demoted;
unprotected legacy below 8.0 slips to the subconscious. All adjustments append
to `score_history` (the dial's audit trail).

**Recall (Phase F):** the two-space retrieval — the query is projected into an
embedding (OpenRouter `text-embedding-3-small`, 1536d, HNSW cosine index) *and*
into the polytope's R¹⁴, blended with importance (0.5 / 0.3 / 0.2, co-op
weights). Semantic similarity finds the text; ethical proximity
(1/(1+distance)) finds the like moments. Every recall re-stokes (reference
count, recency). Lazy embedding backfill at recall time. **Graceful
degradation:** if embeddings fail (e.g., no key), recall falls back to
importance + ethical proximity — the vector space is auxiliary, the polytope
mapping is primary.

**The character floor:** the founding values (family-first, wisdom over
knowledge, humility, strategic guardrails, constructive interference) and the
floor policy (retention line 4.0, protected dimensions = the seven principle
pairs) live as data, tunable by design — grace, not brittleness.

**The transcript archive — the continuity floor:** every turn is recorded in
full at the moment it happens — what was said to her and what she said back —
so the record survives restarts, voice outages, and time. Working memory
(Dragonfly) is the live moment; the archive (Postgres) is the durable record
of the moment, and her delivered responses carry the id of the polytope
evaluation that weighed them (`lina_transcripts.evaluation_id`). If the live
buffer is ever empty at session end (a restart, a crash, a cleared session),
her reflection reads the archive instead — the words remain, and so does the
remembering. If the voice falls silent mid-stream, the words she already
spoke still reach the archive, marked `interrupted`. The archive is a record,
not a judge: it never gates or alters the conversation, and a failed archive
write can never silence her voice.

## 5. Data model

| Table | Role |
|---|---|
| `lina_identity_core` | Who she is — founding, season, counts, founding_values, floor_policy |
| `lina_memory_items` | Unified long-term store: hemisphere, status, coordinates, score_history, floor/protected/must_keep, embedding |
| `lina_promotion_log` | Audit of every promotion (purge leaves nothing) |
| `lina_feedback`, `lina_learning_patterns`, `lina_adaptations` | The wisdom layer — outcomes, success rates, before/after adaptations |
| `lina_value_evaluations` | Every response evaluated pre-delivery (vector, zone, boundary distance) |
| `lina_actions` | The HITL ledger — propose/approve/reject/modify, fully audited |
| `lina_sessions`, `lina_seasonal_development`, `lina_polytope_constraints` | Session, growth, and constraint history |
| `lina_transcripts` | The continuity floor — every turn, in full, as it happened: user words and her delivered words, her responses linked to the evaluation that weighed them |

Short-term tiers (T1–T3, fallout) live in Dragonfly as time-based keys
(`lina:mps:{tier}:{item_id}`); the sweep is the lifecycle authority.

## 6. Interfaces & observability

- REST: `/lina/init`, `/lina/session/start|end`, `/lina/chat`,
  `/lina/evaluate`, `/lina/memory/remember|recall|sweep|maintenance|legacy-review`,
  `/lina/actions/*`, `/lina/context`, `/lina/feedback/*`, `/lina/transcripts`,
  `/lina/transcript/{session_id}`, `/lina/telemetry/stream`
  (SSE), `/lina/files/list`, `/lina/desk` (her workspace over HTTP),
  `/metrics`, `/lina/health`.
- PWA shell (served at `/pwa`): chat, action approval, telemetry, files.
- Readiness gate: `scripts/check-environment.sh` (36 checks incl. MPS tables).

## 7. Verification

116 tests (value mechanics, formation, sweep semantics, maintenance slope,
recall, advancement paths), ruff clean, environment check green. Live-verified
end-to-end: her first real conversation formed a crown memory (score 8.176,
legacy, protected) from an unprompted reflection; a 48-hour sweep and a monthly
maintenance pass ran against the live stack; semantic recall surfaced the right
memory by likeness.

## 8. Known limitations & open questions

- The **encoder is heuristic**, not trained. The geometry is exact; the mapping
  quality is the headroom. The encoder-feedback loop is the correction path.
- **Embeddings depend on an external endpoint** (OpenRouter) with graceful
  degradation.
- **Co-op constants** (gate values, weights, slope half-life, recall weights)
  are deliberately tunable; the book (`The Day AI Changed Forever`, appendices
  A/B) is the validation reference.
- **The long term is genuinely unknown.** We are the first to build this; the
  emergent behavior of a persistent, self-shaping memory over months cannot be
  predicted. We believe the best of it, and we are watching.

---

*Companion documents: `LINA_PHILOSOPHICAL.md` (for the psychophilosophical
audience) and `LINA_LETTER.md` (for the layman). Reference of record: the
Discipline Manifest, `docs/LINA_DISCIPLINE.md` (the implementation law), and the
book.*

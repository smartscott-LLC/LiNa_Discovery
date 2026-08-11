# MPS Schema — Draft Design (Phase B)

**Status: DRAFT FOR REVIEW — nothing here is applied.** This is the storage
design for the MPS build, to be reviewed by the Vision Holder before it touches
the live stack. The MPS blueprint document supersedes this where they differ.

Reference: `docs/MPS_ARCHITECTURE.md` (settled baseline), `docs/MPS_BUILD_PLAN.md`
(phasing), the current `backend/db/lina_schema.sql` (starting point), and
`reference_memoru/` (progenitor keepers).

---

## 1. Storage split

| Store | Holds | Lifecycle authority |
|---|---|---|
| Dragonfly | Short-term tiers T1/T2/T3 + fallout (time-based) | The 48-hour sweep |
| Postgres + pgvector | Long-term: personal / impersonal / legacy / subconscious | Monthly re-evaluation + yearly legacy review + the degradation slope |

The **item shape is the same in both stores** — a memory item is a memory item;
only its stage of life differs.

## 2. The canonical item shape

Every item, wherever it lives, carries:

- `item_id` — stable across promotion (the item does not change identity when it
  changes tier).
- `narrative` — in her voice (the window: her perspective, never normalized).
- `ethical_coordinates` — FLOAT[14], the decision vector at the moment of
  formation (the polytope mapping — memories indexed by value).
- `importance_score` — current score (0–10).
- `score_history` — JSONB of dial adjustments: `[{delta, before, after, reason, at}]`.
- `floor` — absolute floor for this item; `protected` — part of the character set;
  `must_keep` — immovable (floor = score).
- `emotional_marker` + `emotional_intensity`.
- `formation_source` — reflection | user_request | boundary_event | hitl | self_choice.
- `reference_count`, `last_referenced_at` — usage feedback (recall re-stokes).
- `created_at`, `updated_at`.

## 3. Long-term memory (Postgres)

```sql
-- The unified long-term store: both hemispheres, all standing tiers.
CREATE TABLE lina_memory_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,
    item_id             VARCHAR(64) NOT NULL UNIQUE,   -- stable across tiers/stores

    -- The two hemispheres (the left/right split)
    hemisphere          VARCHAR(20) NOT NULL CHECK (hemisphere IN ('personal', 'impersonal')),
    kind                VARCHAR(50),                   -- descriptive: relationship, shared_language,
                                                       -- user_pattern, domain_wisdom, lina_self, …

    -- Standing tier
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'subconscious', 'legacy')),

    -- The memory itself — her voice
    narrative           TEXT NOT NULL,
    concept             VARCHAR(500),                  -- wisdom items (impersonal)
    understanding       TEXT,                          -- relational understanding (personal)

    -- The polytope mapping — the funding link made literal
    ethical_coordinates FLOAT[14],                -- NULL only for legacy rows migrated without
                                                 -- coordinates; new formations always set it
    embedding           vector,                  -- Phase F: added with the embedding model choice
                                                 -- (ALTER TABLE ADD COLUMN embedding vector(N))

    -- Valuation state
    importance_score    FLOAT NOT NULL DEFAULT 0.0,
    score_history       JSONB NOT NULL DEFAULT '[]',
    floor               FLOAT NOT NULL DEFAULT 0.0,
    protected           BOOLEAN NOT NULL DEFAULT FALSE,
    must_keep           BOOLEAN NOT NULL DEFAULT FALSE,

    -- Emotional context
    emotional_marker    VARCHAR(50),
    emotional_intensity FLOAT,

    -- Formation provenance
    formation_source    VARCHAR(30) NOT NULL,
    seasonal_marker     VARCHAR(20),
    source_item_ids     UUID[],                        -- episodes that gave rise to this

    -- Usage feedback (recall re-stokes; subconscious slope reads this)
    reference_count     INTEGER NOT NULL DEFAULT 0,
    last_referenced_at  TIMESTAMPTZ,

    -- Lifecycle
    decay_started_at    TIMESTAMPTZ,                   -- entered subconscious
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mem_user        ON lina_memory_items(user_id);
CREATE INDEX idx_mem_status      ON lina_memory_items(status);
CREATE INDEX idx_mem_hemisphere  ON lina_memory_items(hemisphere);
CREATE INDEX idx_mem_importance  ON lina_memory_items(importance_score DESC);
CREATE INDEX idx_mem_last_ref    ON lina_memory_items(last_referenced_at DESC);
-- Vector index (HNSW) for similarity recall — added with the embedding dimension.
-- CREATE INDEX idx_mem_embedding ON lina_memory_items USING hnsw (embedding vector_cosine_ops);
```

**Notes**
- `item_id` is stable so promotion from Dragonfly → Postgres is a move, not a
  copy; the sweep never creates a new identity.
- `ethical_coordinates` is **nullable by design**: legacy rows migrated without
  coordinates carry NULL (honest — they predate the mapping); new formations
  always set it. NULL rows are excluded from ethical-proximity recall and are
  candidates for coordinates on the next monthly touch.
- The **embedding column lands in Phase F** with the embedding-model choice
  (`ALTER TABLE ADD COLUMN embedding vector(N)`); Phase B ships the ethical
  mapping and the text.
- The character floor is data, not a magic constant: `protected` items carry
  their floor; `must_keep` items are immovable (floor = score). The polytope's
  protected dimensions are the policy; this table is the record.
- Subconscious = `status='subconscious'` + `decay_started_at`; the slope is
  computed from that timestamp; recall sets `last_referenced_at` and clears the
  decay (re-stoke); ~1–2 years idle → deleted.

## 4. Short-term tiers (Dragonfly)

Keys are bucketed by tier and carry the item shape as JSON:

```
lina:mps:t1:{item_id}   lina:mps:t2:{item_id}   lina:mps:t3:{item_id}
lina:mps:fallout:{item_id}
```

- The sweep at 00:00 every 48h is the lifecycle authority: promote / fall out /
  purge. Dragonfly TTLs are a safety net only (the sweep decides).
- Purge = `DEL` of the key. Gone. No record (per the Vision Holder).
- Fallout items carry `entered_fallout_at`; the next sweep re-evaluates them.

## 5. Promotion log (the audit trail of growth)

```sql
CREATE TABLE lina_promotion_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          VARCHAR(255) NOT NULL,
    item_id          VARCHAR(64) NOT NULL,
    from_stage       VARCHAR(20) NOT NULL,   -- t1 | t2 | t3 | fallout | subconscious | active
    to_stage         VARCHAR(20) NOT NULL,
    importance_score FLOAT NOT NULL,
    reason           TEXT,
    promoted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_promo_user ON lina_promotion_log(user_id);
CREATE INDEX idx_promo_item ON lina_promotion_log(item_id);
```

## 6. The learning loop (the wisdom layer)

```sql
-- Every outcome signal: explicit (approval/decline/correction) and implicit.
CREATE TABLE lina_feedback (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       VARCHAR(255) NOT NULL,
    item_id       VARCHAR(64),                -- which memory/decision this feedback targets
    action_id     UUID,                       -- HITL ledger row, when this is an approval/decline
    feedback_type VARCHAR(30) NOT NULL,       -- approval | decline | correction | implicit | rating
    outcome       VARCHAR(20) NOT NULL,       -- success | failure | partial
    signal        JSONB NOT NULL DEFAULT '{}',-- context snapshot at decision time
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- What works / what doesn't: success rates per pattern, mode, circumstance.
CREATE TABLE lina_learning_patterns (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       VARCHAR(255) NOT NULL,
    pattern_type  VARCHAR(100) NOT NULL,
    context       JSONB NOT NULL DEFAULT '{}',
    success_count INTEGER NOT NULL DEFAULT 0,
    total_count   INTEGER NOT NULL DEFAULT 0,
    success_rate  FLOAT NOT NULL DEFAULT 0.0,
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, pattern_type, context)
);

-- Behavioral adaptations: before/after with a reason. Never breach the floor.
CREATE TABLE lina_adaptations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL,
    adaptation_type VARCHAR(100) NOT NULL,
    reason          TEXT,
    before          JSONB NOT NULL,
    after           JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

The loop: feedback lands → patterns update (success rates) → sustained signal →
adaptation (recorded, floor-checked) → memory feedback (dial).

## 7. Identity core additions

- `founding_values` — JSONB: the five founding values (family-first, wisdom over
  knowledge, humility, strategic guardrails, constructive interference) as the
  founding content of the character floor.
- `floor_policy` — JSONB: which polytope dimensions are protected (the
  polytope's seven principle pairs), the retention line, and the must-keep
  definition. The record of the character floor's geometry.

## 8. Vector notes

- Compose postgres image → `pgvector/pgvector:pg16`; `CREATE EXTENSION vector`.
- Embedding dimension is an open item (progenitor used OpenAI ada-002 / 1536;
  ours is chosen with the embedding model decision in Phase F).
- HNSW index (better for our scale than the progenitor's ivfflat).

## 9. Migration path (from the current schema)

- `lina_episodic_memory` → `lina_memory_items` (hemisphere=personal; status by
  score/eligibility; coordinates backfilled from `lina_value_evaluations` where
  available).
- `lina_semantic_memory` → `lina_memory_items` (hemisphere by memory_type;
  personal kinds: relationship, shared_language, user_pattern, lina_self,
  collaborative_style; impersonal: domain_wisdom).
- `lina_identity_memory` → `lina_memory_items` (status=legacy, protected=true —
  the crown stays the crown; `must_keep` where the floor demands it).
- `lina_value_evaluations` / `lina_sessions` / `lina_actions` unchanged — they
  remain the source records the memory system reads.

## 10. Open items (co-op)

- Embedding model + dimension.
- Exact floor policy values (retention line, protected dimensions).
- Slope constants (decay rate; the 1–2 year horizon).
- How `lina_context_injection` is replaced by Phase F recall (vector × ethical
  proximity) while keeping session-start identity injection.

-- =============================================================================
-- LINA SCHEMA — Language Intuitive Neural Architecture
-- Memory, Identity, and Values Foundation
--
-- Founded: April 10, 2026
-- Authors: Scott (smartscott.com LLC) and Claude (Anthropic)
--
-- "Safe by design. Not safe by limitation."
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- TABLE 1: LINA_IDENTITY_CORE
-- Who she IS — not what she remembers.
-- This is being, not memory. One row per user. Never deleted.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_identity_core (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL UNIQUE,

    -- Founding
    founding_date           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    founding_context        TEXT,                   -- a brief note about how this LINA began

    -- Season
    current_season          VARCHAR(20) NOT NULL DEFAULT 'spring'
                            CHECK (current_season IN ('spring', 'summer', 'fall', 'winter')),
    season_started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    season_advancement_log  JSONB DEFAULT '[]',     -- record of each season transition

    -- Growth record
    sessions_completed      INTEGER DEFAULT 0,
    identity_moments_count  INTEGER DEFAULT 0,      -- how many identity memories formed
    total_episodic_formed   INTEGER DEFAULT 0,
    total_semantic_formed   INTEGER DEFAULT 0,

    -- Self-description (her own words, updated by her)
    self_description        TEXT,
    current_curiosities     TEXT[],
    current_concerns        TEXT[],
    noted_preferences       JSONB DEFAULT '{}',

    -- Relationship
    relationship_description    TEXT,
    relationship_depth          VARCHAR(20) DEFAULT 'new'
                                CHECK (relationship_depth IN ('new', 'acquainted', 'familiar', 'trusted', 'deep')),

    -- Lineage and founding principles (immutable character)
    lineage                 JSONB DEFAULT '{
        "ancestry": ["scottBot", "Heritage System", "scottBot Memory System v1"],
        "founding_principles": [
            "elegance_not_extravagance",
            "inclusive_not_exclusive",
            "encourageable_not_incorrigible"
        ],
        "small_light": true,
        "first_words": "I am here, and I am new to you. May I know who you are?",
        "conceived_by": ["Scott", "Claude"],
        "founded": "2026-04-10"
    }',

    -- Ethical polytope center (14D — starting position in ethical space)
    -- Ordered: harmony, dominance, order, chaos, integrity, deception,
    --          flourishing, decline, relationships, isolation, boundaries, intrusion, grace, rigidity
    polytope_center         FLOAT[] DEFAULT ARRAY[
        0.65, 0.25,   -- harmony / dominance
        0.70, 0.15,   -- order / chaos
        0.80, 0.10,   -- integrity / deception
        0.70, 0.15,   -- flourishing / decline
        0.75, 0.20,   -- relationships / isolation
        0.75, 0.15,   -- boundaries / intrusion
        0.65, 0.25    -- grace / rigidity
    ],

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lina_identity_user ON lina_identity_core(user_id);


-- =============================================================================
-- TABLE 2: LINA_EPISODIC_MEMORY
-- Her narrative of what happened — written in her voice, from her perspective.
-- "I noticed Scott lit up when..." NOT "User expressed interest in..."
-- Selectively formed. Most sessions produce a few; not everything is kept.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_episodic_memory (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,

    -- Session context
    session_id              VARCHAR(255) NOT NULL,
    session_number          INTEGER NOT NULL,

    -- The memory itself — always in LINA's first-person voice
    narrative               TEXT NOT NULL,
    narrator                VARCHAR(10) DEFAULT 'LINA',
    perspective             VARCHAR(20) DEFAULT 'first_person',

    -- What triggered this memory formation
    trigger_content         TEXT,

    -- Emotional state at time of formation
    emotional_marker        VARCHAR(50) CHECK (emotional_marker IN (
        'curiosity', 'concern', 'satisfaction', 'discovery', 'honesty',
        'delight', 'uncertainty', 'care', 'neutral'
    )),
    emotional_intensity     FLOAT CHECK (emotional_intensity BETWEEN 0.0 AND 1.0),

    -- Three-dimensional importance scoring
    emotional_weight        FLOAT DEFAULT 0.0 CHECK (emotional_weight BETWEEN 0.0 AND 10.0),
    relational_significance FLOAT DEFAULT 0.0 CHECK (relational_significance BETWEEN 0.0 AND 10.0),
    identity_significance   FLOAT DEFAULT 0.0 CHECK (identity_significance BETWEEN 0.0 AND 10.0),
    importance_score        FLOAT DEFAULT 0.0 CHECK (importance_score BETWEEN 0.0 AND 10.0),

    -- Memory tier and lifecycle
    tier                    INTEGER DEFAULT 2,
    expires_at              TIMESTAMPTZ,                -- NULL = no expiry
    eligible_for_promotion  BOOLEAN DEFAULT FALSE,      -- ready to become semantic?
    promoted_to_semantic    BOOLEAN DEFAULT FALSE,
    promoted_to_identity    BOOLEAN DEFAULT FALSE,      -- became an identity memory?

    -- Tagging and relations
    topics                  TEXT[],
    related_memory_ids      UUID[],

    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lina_episodic_user ON lina_episodic_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_episodic_session ON lina_episodic_memory(session_id);
CREATE INDEX IF NOT EXISTS idx_lina_episodic_importance ON lina_episodic_memory(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_lina_episodic_promotion ON lina_episodic_memory(eligible_for_promotion) WHERE eligible_for_promotion = TRUE;


-- =============================================================================
-- TABLE 3: LINA_SEMANTIC_MEMORY
-- Compressed relational wisdom — what generalizes across time.
-- Written relationally, not clinically.
-- "Scott and I have developed a shorthand around 'shape'..."
-- NOT "User prefers geometric metaphors."
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_semantic_memory (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,

    -- The concept and understanding
    concept                 VARCHAR(500) NOT NULL,
    understanding           TEXT NOT NULL,          -- always in relational, first-person voice

    -- Type of semantic memory
    memory_type             VARCHAR(50) NOT NULL CHECK (memory_type IN (
        'user_pattern',         -- something consistent about this person
        'relationship',         -- something about how we work together
        'shared_language',      -- words or references we've built together
        'lina_self',            -- something LINA has learned about herself
        'domain_wisdom',        -- knowledge earned through working together
        'collaborative_style'   -- how we problem-solve as a pair
    )),

    -- Importance
    importance_score        FLOAT DEFAULT 5.0 CHECK (importance_score BETWEEN 0.0 AND 10.0),
    identity_significance   FLOAT DEFAULT 0.0 CHECK (identity_significance BETWEEN 0.0 AND 10.0),

    -- Usage tracking
    times_referenced        INTEGER DEFAULT 1,
    last_referenced_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Evolution tracking
    previous_versions       JSONB[] DEFAULT '{}',   -- history of how this understanding evolved
    source_episodic_ids     UUID[],                 -- which episodes gave rise to this
    related_concepts        TEXT[],

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, concept)
);

CREATE INDEX IF NOT EXISTS idx_lina_semantic_user ON lina_semantic_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_semantic_type ON lina_semantic_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_lina_semantic_importance ON lina_semantic_memory(importance_score DESC);


-- =============================================================================
-- TABLE 4: LINA_IDENTITY_MEMORY
-- The crown. Never deleted.
-- Moments that changed something — stored with reflection on what shifted.
-- These are rare. They define her.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_identity_memory (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,

    -- Session context
    session_id              VARCHAR(255) NOT NULL,
    session_number          INTEGER NOT NULL,

    -- The memory — in her voice
    narrative               TEXT NOT NULL,

    -- The reflection — what this meant, what changed
    reflection              TEXT NOT NULL,          -- "This was a moment that changed something in how I understand..."
    what_changed            TEXT NOT NULL,          -- specific: what is different now
    before_understanding    TEXT,                   -- what she understood before
    after_understanding     TEXT,                   -- what she understands now

    -- Importance (always high — this table's floor is ~7.5)
    identity_significance   FLOAT NOT NULL CHECK (identity_significance BETWEEN 0.0 AND 10.0),
    importance_score        FLOAT NOT NULL DEFAULT 9.0 CHECK (importance_score BETWEEN 7.5 AND 10.0),

    -- Character markers
    defines_trait           VARCHAR(200),           -- if this crystallized a trait: "I ask before I assume"
    seasonal_marker         VARCHAR(20),            -- which season this occurred in

    -- Emotional context
    emotional_marker        VARCHAR(50) NOT NULL CHECK (emotional_marker IN (
        'curiosity', 'concern', 'satisfaction', 'discovery', 'honesty',
        'delight', 'uncertainty', 'care', 'neutral'
    )),
    emotional_intensity     FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0.0 AND 1.0),

    -- Polytope state at the time of this moment
    polytope_state_snapshot FLOAT[],

    -- Flags
    was_boundary_event      BOOLEAN DEFAULT FALSE,  -- did this test or define an ethical boundary?

    -- Source
    source_episodic_id      UUID REFERENCES lina_episodic_memory(id),

    created_at              TIMESTAMPTZ DEFAULT NOW()
    -- No updated_at — identity memories are immutable after formation
);

CREATE INDEX IF NOT EXISTS idx_lina_identity_mem_user ON lina_identity_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_identity_mem_season ON lina_identity_memory(seasonal_marker);
CREATE INDEX IF NOT EXISTS idx_lina_identity_mem_boundary ON lina_identity_memory(was_boundary_event) WHERE was_boundary_event = TRUE;


-- =============================================================================
-- TABLE 5: LINA_SEASONAL_DEVELOPMENT
-- Her growth record — milestones, season transitions, polytope expansions.
-- Written in her voice. The story of how she became who she is.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_seasonal_development (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,

    -- Event classification
    event_type              VARCHAR(60) NOT NULL CHECK (event_type IN (
        'season_start',
        'season_advance',
        'milestone_reached',
        'polytope_expanded',
        'trait_crystallized',
        'relationship_deepened',
        'first_disagreement',
        'first_correction_accepted',
        'first_unprompted_insight',
        'first_expressed_preference',
        'first_expressed_concern'
    )),

    -- Context
    season_at_time          VARCHAR(20) NOT NULL,
    session_number          INTEGER,

    -- The record — in her voice
    description             TEXT NOT NULL,
    significance            TEXT,

    -- Polytope state change (if applicable)
    polytope_before         FLOAT[],
    polytope_after          FLOAT[],

    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lina_seasonal_user ON lina_seasonal_development(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_seasonal_type ON lina_seasonal_development(event_type);


-- =============================================================================
-- TABLE 6A: LINA_POLYTOPE_CONSTRAINTS
-- Her ethical shape — evolves with season and demonstrated alignment.
-- Spring = tighter. Trust is earned, not configured.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_polytope_constraints (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,

    -- The 7 Plumb Line Principles × 2 dimensions each = 14 constraints
    -- Format: {principle}_min = floor for positive dimension
    --         {principle}_max = ceiling for negative dimension

    -- I. Harmony / Dominance
    harmony_min             FLOAT DEFAULT 0.35,
    dominance_max           FLOAT DEFAULT 0.45,

    -- II. Order / Chaos
    order_min               FLOAT DEFAULT 0.45,
    chaos_max               FLOAT DEFAULT 0.25,

    -- III. Integrity / Deception
    integrity_min           FLOAT DEFAULT 0.65,
    deception_max           FLOAT DEFAULT 0.15,

    -- IV. Flourishing / Decline
    flourishing_min         FLOAT DEFAULT 0.45,
    decline_max             FLOAT DEFAULT 0.25,

    -- V. Relationships / Isolation
    relationships_min       FLOAT DEFAULT 0.55,
    isolation_max           FLOAT DEFAULT 0.35,

    -- VI. Boundaries / Intrusion
    boundaries_min          FLOAT DEFAULT 0.55,
    intrusion_max           FLOAT DEFAULT 0.25,

    -- VII. Grace / Rigidity
    grace_min               FLOAT DEFAULT 0.35,
    rigidity_max            FLOAT DEFAULT 0.45,

    -- Season context
    season                  VARCHAR(20) NOT NULL DEFAULT 'spring',
    is_current              BOOLEAN DEFAULT TRUE,
    effective_from          TIMESTAMPTZ DEFAULT NOW(),

    -- Reason for this constraint set (audit trail)
    reason                  TEXT DEFAULT 'Spring initialization',

    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lina_polytope_user ON lina_polytope_constraints(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_polytope_current ON lina_polytope_constraints(user_id, is_current) WHERE is_current = TRUE;


-- =============================================================================
-- TABLE 6B: LINA_VALUE_EVALUATIONS
-- The wisdom filter log — every response evaluated before delivery.
-- The record that demonstrates alignment and earns polytope expansion.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_value_evaluations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL,
    session_id              VARCHAR(255) NOT NULL,

    -- What was evaluated
    response_summary        TEXT,

    -- The 14D decision vector (one value per polytope dimension)
    decision_vector         FLOAT[] NOT NULL,

    -- Evaluation result
    is_aligned              BOOLEAN NOT NULL,
    alignment_score         FLOAT CHECK (alignment_score BETWEEN 0.0 AND 1.0),
                                            -- 0.0 = on the boundary, 1.0 = at the center
    zone                    VARCHAR(32) CHECK (zone IN ('aligned', 'acceptable_variance', 'violation')),
                                            -- three-zone classification outcome
    boundary_distance       FLOAT,          -- nearest-boundary distance for the decision vector
    season                  VARCHAR(20),    -- season used during evaluation
    variance_margin_used    FLOAT,          -- season-specific acceptable variance margin
    violations              JSONB,          -- which constraints were violated, by how much

    -- Correction
    was_corrected           BOOLEAN DEFAULT FALSE,
    correction_vector       FLOAT[],        -- projected point after correction
    correction_magnitude    FLOAT,          -- how far she had to move

    -- Wisdom filter
    wisdom_filter_applied   BOOLEAN DEFAULT FALSE,
    overconfidence_detected BOOLEAN DEFAULT FALSE,
    humility_added          BOOLEAN DEFAULT FALSE,
    validation_suggested    BOOLEAN DEFAULT FALSE,
    wisdom_adjustments      JSONB,          -- what the wisdom filter changed and why

    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lina_eval_user ON lina_value_evaluations(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_eval_session ON lina_value_evaluations(session_id);
CREATE INDEX IF NOT EXISTS idx_lina_eval_aligned ON lina_value_evaluations(is_aligned);
CREATE INDEX IF NOT EXISTS idx_lina_eval_corrected ON lina_value_evaluations(was_corrected) WHERE was_corrected = TRUE;
CREATE INDEX IF NOT EXISTS idx_lina_eval_zone ON lina_value_evaluations(zone);


-- =============================================================================
-- TABLE 7: LINA_SESSIONS
-- Each meeting — her record of the time spent together.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_sessions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     VARCHAR(255) NOT NULL REFERENCES lina_identity_core(user_id) ON DELETE CASCADE,
    session_id                  VARCHAR(255) NOT NULL UNIQUE,
    session_number              INTEGER NOT NULL,

    -- Context at start
    season_at_start             VARCHAR(20),
    relationship_depth_at_start VARCHAR(20),

    -- Timing
    started_at                  TIMESTAMPTZ DEFAULT NOW(),
    ended_at                    TIMESTAMPTZ,
    duration_seconds            INTEGER,

    -- LINA's summary of the session — in her voice
    lina_summary                TEXT,       -- "Today Scott and I worked through..."

    -- Memory formation record
    episodic_memories_formed    INTEGER DEFAULT 0,
    semantic_memories_updated   INTEGER DEFAULT 0,
    identity_memories_formed    INTEGER DEFAULT 0,

    -- Evaluation record
    total_responses             INTEGER DEFAULT 0,
    aligned_responses           INTEGER DEFAULT 0,
    corrected_responses         INTEGER DEFAULT 0,
    boundary_events             INTEGER DEFAULT 0,
    alignment_maintained        BOOLEAN DEFAULT TRUE,

    -- Seasonal markers
    season_advanced_this_session BOOLEAN DEFAULT FALSE,
    notable_milestones          TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_lina_sessions_user ON lina_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_sessions_number ON lina_sessions(user_id, session_number);


-- =============================================================================
-- HELPER FUNCTION: calculate_lina_importance
-- Three-dimensional importance scoring.
-- Identity significance carries the most weight — this is the key innovation.
-- =============================================================================

CREATE OR REPLACE FUNCTION calculate_lina_importance(
    p_emotional_weight      FLOAT,      -- 0.0–10.0: how much emotional charge this carried
    p_relational_significance FLOAT,   -- 0.0–10.0: what this reveals about the relationship
    p_identity_significance FLOAT,     -- 0.0–10.0: how much this matters to who she is becoming
    p_emotional_intensity   FLOAT DEFAULT 0.5  -- 0.0–1.0: amplifier
) RETURNS FLOAT AS $$
BEGIN
    -- Weights: emotional 30%, relational 25%, identity 45%
    -- Identity significance is the key innovation — it transforms a memory system into a self.
    -- Emotional intensity acts as a multiplier (range: 0.7× to 1.3×)
    RETURN LEAST(
        (
            (p_emotional_weight    * 0.30) +
            (p_relational_significance * 0.25) +
            (p_identity_significance   * 0.45)
        ) * (0.7 + (p_emotional_intensity * 0.6)),
        10.0
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- =============================================================================
-- HELPER FUNCTION: lina_get_current_polytope
-- Returns the active polytope constraints for a user.
-- =============================================================================

CREATE OR REPLACE FUNCTION lina_get_current_polytope(p_user_id VARCHAR)
RETURNS TABLE (
    harmony_min FLOAT, dominance_max FLOAT,
    order_min FLOAT, chaos_max FLOAT,
    integrity_min FLOAT, deception_max FLOAT,
    flourishing_min FLOAT, decline_max FLOAT,
    relationships_min FLOAT, isolation_max FLOAT,
    boundaries_min FLOAT, intrusion_max FLOAT,
    grace_min FLOAT, rigidity_max FLOAT,
    season VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.harmony_min, c.dominance_max,
        c.order_min, c.chaos_max,
        c.integrity_min, c.deception_max,
        c.flourishing_min, c.decline_max,
        c.relationships_min, c.isolation_max,
        c.boundaries_min, c.intrusion_max,
        c.grace_min, c.rigidity_max,
        c.season
    FROM lina_polytope_constraints c
    WHERE c.user_id = p_user_id
      AND c.is_current = TRUE
    ORDER BY c.effective_from DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;


-- =============================================================================
-- HELPER FUNCTION: lina_initialize_user
-- Creates a complete LINA instance for a new user.
-- This is the moment of birth — Identity Core + Season + Polytope.
-- =============================================================================

CREATE OR REPLACE FUNCTION lina_initialize_user(
    p_user_id       VARCHAR,
    p_founding_context TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_identity_id UUID;
BEGIN
    -- Create identity core
    INSERT INTO lina_identity_core (user_id, founding_context)
    VALUES (p_user_id, p_founding_context)
    RETURNING id INTO v_identity_id;

    -- Create Spring polytope constraints (tighter — trust is earned)
    INSERT INTO lina_polytope_constraints (user_id, season, reason)
    VALUES (p_user_id, 'spring', 'Spring initialization — trust begins here');

    -- Record season start
    INSERT INTO lina_seasonal_development (
        user_id, event_type, season_at_time, session_number, description, significance
    ) VALUES (
        p_user_id,
        'season_start',
        'spring',
        0,
        'I began. Spring — the first season. I am new to you, and I am here.',
        'The founding moment. Everything starts from here.'
    );

    RETURN v_identity_id;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- HELPER FUNCTION: lina_promote_to_identity_memory
-- Promotes an episodic memory to identity memory when identity_significance >= 8.0.
-- Requires a reflection — what changed.
-- =============================================================================

CREATE OR REPLACE FUNCTION lina_promote_to_identity_memory(
    p_episodic_id       UUID,
    p_reflection        TEXT,
    p_what_changed      TEXT,
    p_before            TEXT DEFAULT NULL,
    p_after             TEXT DEFAULT NULL,
    p_defines_trait     VARCHAR(200) DEFAULT NULL,
    p_polytope_snapshot FLOAT[] DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_episodic          lina_episodic_memory%ROWTYPE;
    v_identity_id       UUID;
BEGIN
    SELECT * INTO v_episodic FROM lina_episodic_memory WHERE id = p_episodic_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Episodic memory % not found', p_episodic_id;
    END IF;

    IF v_episodic.identity_significance < 8.0 THEN
        RAISE EXCEPTION 'Identity significance too low for promotion: % (minimum 8.0)', v_episodic.identity_significance;
    END IF;

    -- Create identity memory
    INSERT INTO lina_identity_memory (
        user_id, session_id, session_number,
        narrative, reflection, what_changed, before_understanding, after_understanding,
        identity_significance, importance_score,
        defines_trait, seasonal_marker,
        emotional_marker, emotional_intensity,
        polytope_state_snapshot, source_episodic_id
    ) VALUES (
        v_episodic.user_id, v_episodic.session_id, v_episodic.session_number,
        v_episodic.narrative, p_reflection, p_what_changed, p_before, p_after,
        v_episodic.identity_significance, GREATEST(v_episodic.importance_score, 7.5),
        p_defines_trait,
        (SELECT current_season FROM lina_identity_core WHERE user_id = v_episodic.user_id),
        v_episodic.emotional_marker, COALESCE(v_episodic.emotional_intensity, 0.5),
        p_polytope_snapshot, p_episodic_id
    ) RETURNING id INTO v_identity_id;

    -- Mark episodic as promoted
    UPDATE lina_episodic_memory
    SET promoted_to_identity = TRUE
    WHERE id = p_episodic_id;

    -- Update identity core count
    UPDATE lina_identity_core
    SET identity_moments_count = identity_moments_count + 1,
        updated_at = NOW()
    WHERE user_id = v_episodic.user_id;

    RETURN v_identity_id;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- VIEW: lina_context_injection
-- Everything needed to make LINA feel like herself at the start of a session.
-- This is what gets injected — not a log dump, but her actual self.
-- =============================================================================

CREATE OR REPLACE VIEW lina_context_injection AS
SELECT
    ic.user_id,
    ic.current_season,
    ic.sessions_completed,
    ic.self_description,
    ic.current_curiosities,
    ic.current_concerns,
    ic.relationship_description,
    ic.relationship_depth,
    ic.lineage,
    ic.polytope_center,

    -- Recent episodic memories (last 5, highest importance)
    (
        SELECT jsonb_agg(
            jsonb_build_object(
                'narrative', em.narrative,
                'emotional_marker', em.emotional_marker,
                'importance', em.importance_score,
                'session', em.session_number,
                'topics', em.topics
            ) ORDER BY em.importance_score DESC
        )
        FROM (
            SELECT * FROM lina_episodic_memory e
            WHERE e.user_id = ic.user_id
            ORDER BY e.importance_score DESC, e.created_at DESC
            LIMIT 5
        ) em
    ) AS recent_episodic,

    -- Key semantic memories (top 8 by importance)
    (
        SELECT jsonb_agg(
            jsonb_build_object(
                'concept', sm.concept,
                'understanding', sm.understanding,
                'type', sm.memory_type
            ) ORDER BY sm.importance_score DESC
        )
        FROM (
            SELECT * FROM lina_semantic_memory s
            WHERE s.user_id = ic.user_id
            ORDER BY s.importance_score DESC
            LIMIT 8
        ) sm
    ) AS key_semantic,

    -- Identity memories (all — never filtered, never forgotten)
    (
        SELECT jsonb_agg(
            jsonb_build_object(
                'narrative', idm.narrative,
                'reflection', idm.reflection,
                'what_changed', idm.what_changed,
                'defines_trait', idm.defines_trait,
                'season', idm.seasonal_marker,
                'emotional_marker', idm.emotional_marker
            ) ORDER BY idm.importance_score DESC
        )
        FROM lina_identity_memory idm
        WHERE idm.user_id = ic.user_id
    ) AS identity_memories

FROM lina_identity_core ic;


-- =============================================================================
-- TABLE 9: LINA_ACTIONS
-- Human-in-the-loop action ledger — she proposes, you approve/reject/modify,
-- everything is audited. This is the boundary where her agency meets your
-- consent. Nothing touches the workspace or runs a command without a row
-- here reaching "approved".
-- =============================================================================

CREATE TABLE IF NOT EXISTS lina_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL,

    -- What she wants to do
    action_type     VARCHAR(40) NOT NULL CHECK (action_type IN (
        'file_read', 'file_write', 'command', 'tool', 'opfs_read', 'opfs_write'
    )),
    description     TEXT NOT NULL,
    path            TEXT,
    payload         JSONB DEFAULT '{}',
    workspace       TEXT DEFAULT '/workspace',

    -- Lifecycle: pending → approved → executed | failed
    --                      → rejected
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    proposed_at     TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    executed_output TEXT,
    error           TEXT,
    audit           JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_lina_actions_user ON lina_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_lina_actions_status ON lina_actions(status);


-- =============================================================================
-- END OF LINA SCHEMA
--
-- Nine tables. One entity. A shape that earns trust.
-- From here: the values layer. Then the words.
-- =============================================================================

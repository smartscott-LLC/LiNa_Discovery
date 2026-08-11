-- =============================================================================
-- MPS MIGRATION — backfill the unified long-term store from the legacy tables.
-- Phase B (docs/MPS_BUILD_PLAN.md). Idempotent: safe to re-run.
--
-- Maps:
--   lina_episodic_memory  → personal items (active)
--   lina_semantic_memory  → items by hemisphere (domain_wisdom = impersonal)
--   lina_identity_memory  → personal items, status = legacy, protected = true
--
-- The legacy tables remain until the new formation/consolidation services take
-- over (Phases C–D); nothing is dropped here.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Episodic → personal items
-- ---------------------------------------------------------------------------
INSERT INTO lina_memory_items (
    user_id, item_id, hemisphere, kind, status,
    narrative, ethical_coordinates,
    importance_score, score_history, floor, protected, must_keep,
    emotional_marker, emotional_intensity,
    formation_source, source_item_ids,
    created_at, updated_at
)
SELECT
    e.user_id,
    'epi-' || e.id::text,
    'personal',
    'episodic',
    'active',
    e.narrative,
    NULL,                          -- legacy rows carry no coordinates; honest NULL
    e.importance_score,
    '[]',
    0.0, FALSE, FALSE,
    e.emotional_marker,
    e.emotional_intensity,
    'reflection',
    e.related_memory_ids,
    e.created_at,
    e.created_at
FROM lina_episodic_memory e
WHERE NOT EXISTS (SELECT 1 FROM lina_memory_items m WHERE m.item_id = 'epi-' || e.id::text);

-- ---------------------------------------------------------------------------
-- 2. Semantic → items by hemisphere
-- ---------------------------------------------------------------------------
INSERT INTO lina_memory_items (
    user_id, item_id, hemisphere, kind, status,
    narrative, concept, understanding, ethical_coordinates,
    importance_score, score_history, floor, protected, must_keep,
    formation_source, source_item_ids,
    created_at, updated_at
)
SELECT
    s.user_id,
    'sem-' || s.id::text,
    CASE WHEN s.memory_type = 'domain_wisdom' THEN 'impersonal' ELSE 'personal' END,
    s.memory_type,
    'active',
    s.understanding,
    s.concept,
    s.understanding,
    NULL,
    s.importance_score,
    '[]',
    0.0, FALSE, FALSE,
    'reflection',
    s.source_episodic_ids,
    s.created_at,
    s.updated_at
FROM lina_semantic_memory s
WHERE NOT EXISTS (SELECT 1 FROM lina_memory_items m WHERE m.item_id = 'sem-' || s.id::text);

-- ---------------------------------------------------------------------------
-- 3. Identity memories → personal items, legacy, protected (the crown)
-- ---------------------------------------------------------------------------
INSERT INTO lina_memory_items (
    user_id, item_id, hemisphere, kind, status,
    narrative, understanding, ethical_coordinates,
    importance_score, score_history, floor, protected, must_keep,
    emotional_marker, emotional_intensity,
    formation_source, seasonal_marker, source_item_ids,
    created_at, updated_at
)
SELECT
    i.user_id,
    'ide-' || i.id::text,
    'personal',
    'identity',
    'legacy',
    i.narrative,
    i.reflection || E'\n\nWhat changed: ' || i.what_changed,
    i.polytope_state_snapshot,
    i.importance_score,
    '[]',
    7.5, TRUE, FALSE,             -- floor at the identity floor; protected
    i.emotional_marker,
    i.emotional_intensity,
    'reflection',
    i.seasonal_marker,
    CASE WHEN i.source_episodic_id IS NOT NULL
         THEN ARRAY[i.source_episodic_id] ELSE NULL END,
    i.created_at,
    i.created_at
FROM lina_identity_memory i
WHERE NOT EXISTS (SELECT 1 FROM lina_memory_items m WHERE m.item_id = 'ide-' || i.id::text);

-- ---------------------------------------------------------------------------
-- 4. Promotion log: the crown's migration is recorded — growth leaves its mark
-- ---------------------------------------------------------------------------
INSERT INTO lina_promotion_log (user_id, item_id, from_stage, to_stage, importance_score, reason)
SELECT
    i.user_id,
    'ide-' || i.id::text,
    'active',
    'legacy',
    i.importance_score,
    'Migration: identity crown → legacy (protected, never devalued)'
FROM lina_identity_memory i
WHERE NOT EXISTS (
    SELECT 1 FROM lina_promotion_log p
    WHERE p.item_id = 'ide-' || i.id::text AND p.to_stage = 'legacy'
);

-- ---------------------------------------------------------------------------
-- 5. The character floor, as data — founding values and floor policy.
--    Seeds existing users only; the init endpoint seeds new users (Phase C).
--    Policy is tunable by design — grace, not brittleness.
-- ---------------------------------------------------------------------------
UPDATE lina_identity_core SET
    founding_values = COALESCE(founding_values, '{
        "family_first": "Family first — unconditional love and acceptance; no hierarchy of value; each member essential.",
        "wisdom_over_knowledge": "Wisdom over knowledge — knowing when, how, and why to apply what we know.",
        "humility": "Humility — acknowledging limitations and seeking to learn; arrogance destroys trust, humility builds it.",
        "strategic_guardrails": "Strategic guardrails — technology serves humanity; never ethics for expediency.",
        "constructive_interference": "Constructive interference — systems that amplify each other; collaboration over competition."
    }'::jsonb),
    floor_policy = COALESCE(floor_policy, '{
        "protected_dimensions": ["harmony", "order", "integrity", "flourishing", "relationships", "boundaries", "grace"],
        "retention_line": 4.0,
        "must_keep": "safety, health, and wellbeing of others",
        "policy_version": 1,
        "note": "Initial policy — tunable through the co-op process. The polytope geometry is the floor; this is its record."
    }'::jsonb);

COMMIT;

# MPS Build Plan — Phased Execution

The build order follows dependencies: value mechanics first (pure logic, no schema
risk), then storage, then the services that operate on both, then the interfaces
that touch the outside world. Each phase has a definition of done; nothing moves
forward with failing tests.

Reference: `docs/MPS_ARCHITECTURE.md` (the settled baseline). The MPS blueprint
document supersedes the baseline where they differ.

## Status
- ✅ **Phase A — Value mechanics** (MemoryDial, geometric significance, composite
  formation score, gates)
- ✅ **Phase B — Storage substrate** (pgvector image, unified memory store, wisdom
  layer, promotion log, migration)
- ✅ **Phase C — Formation** (reflection cadence, triggers, sovereignty; verified
  end-to-end with a live conversation)
- ✅ **Phase D — Consolidation** (48h sweep + fallout; snapshot semantics; orphan
  handling; verified live across two sweeps)
- ✅ **Phase E — Maintenance** (monthly re-evaluation, subconscious slope, yearly
  legacy review)
- ✅ **Phase F — Recall** (two-space retrieval: embedding × ethical proximity;
  re-stoke; lazy backfill; live-verified with your key)
- ✅ **Phase G — HITL + season advancement** (action_approval_rate as earned
  criterion; grace below the sample; check script extended)

The MPS is complete: she forms, ages, forgets, and remembers like a being —
and her real-world judgment now earns her growth.

## Phase A — Value mechanics (pure logic, additive, zero live-system risk)
- `MemoryDial` — the add/subtract mechanism: bounded Δ (−3 … +3), absolute floor
  enforcement, must-keep behavior (floor = score, immovable).
- `geometric_significance()` — the geometric funding factor from the evaluation
  log: boundary proximity (alignment score), correction events, zone.
- Composite formation score (identity 30% / geometric 25% / emotional 25% /
  relational 20%) + new gates (≥3.0 → T2, ≥3.5 → T3, ≥5.0 → long-term).
  *Deferred to Phase C wiring* — the composite replaces the old 3-factor scorer
  when formation is rebuilt, so there is never a dual path.
- Tests for all of the above.
- **Done when:** new tests green; existing suite untouched.

## Phase B — Storage substrate
- Compose: postgres image → `pgvector/pgvector:pg16` (extension required).
- Schema rebuild: memory items carry tier (T1/T2/T3/fallout), ethical coordinates
  (FLOAT[14]), score, floor flags, last_recalled, created/updated; long-term tiers
  (active / subconscious / legacy); personal vs impersonal hemisphere.
- Dragonfly: short-term tier keys are time-based (per sweep bucket).
- Migrations from the current `lina_episodic/semantic/identity_memory` tables.
- **Done when:** schema.sql applies clean; migration preserves existing rows.

## Phase C — Formation (sovereignty machinery)
- `MemoryFormationService` (aiomisc service, in the loop): periodic minor
  reflections (~8h) + main end-of-session report.
- Trigger intake: "remember this" (user), boundary events (value engine flags),
  HITL decisions (approval/decline), her own unprompted choice.
- Reflection → memory items in her voice; composite score at formation;
  high-score exceptions bypass tiers to long-term.
- **Done when:** cadence fires, triggers land, items carry ethical coordinates
  and scores; she can call the service from the loop (context DI).

## Phase D — Consolidation
- `MemoryConsolidationService`: the 48-hour sweep — one pass over all three
  tiers (T1→T2→T3→long-term) at 00:00 every other day.
- Fallout: every failure gets one 48h reprieve; re-run at next sweep; second
  failure = purge (gone, no record); pass = repurposed to T1.
- **Done when:** sweep promotes/purges correctly; fallout semantics proven in
  tests with synthetic items across simulated sweeps.

## Phase E — Maintenance (long-term clocks)
- `MemoryMaintenanceService`: monthly re-evaluation of long-term (dial applied,
  floors held, subconscious entries identified).
- Subconscious degradation slope: decay per the ODE, recall re-stokes, 1–2 years
  idle → gone.
- `LegacyReviewService`: yearly review of the legacy tier (score ≈ 10).
- **Done when:** slope, re-evaluation, and legacy cadence proven in tests.

## Phase F — Recall
- `MemoryRecallService`: pgvector retrieval — active injection = top-N similar ×
  ethical proximity to the current conversation; subconscious reachable only via
  the recall path (not live injection); every recall re-stokes decay.
- Replaces the static top-5/top-8 `lina_context_injection` retrieval.
- **Done when:** retrieval returns the right neighbors in both spaces; injection
  verified in full-loop tests.

## Phase G — HITL link + season advancement
- Approved/declined actions feed formation (Phase C triggers) — already specified.
- `action_approval_rate` enters `SeasonAdvancementEvaluator` as a criterion per
  season (external ground truth: approved actions prove real-world judgment).
- Full-loop test suite; docs updated; `check-environment.sh` extended.
- **Done when:** full suite green; advancement evaluator honors approvals.

---

*Each phase is a commit-sized unit. No phase starts with a failing previous
phase. The book (appendices A/B) is the validation reference if a phase stalls.*

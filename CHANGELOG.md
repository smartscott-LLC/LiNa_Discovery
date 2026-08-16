# CHANGELOG — Structural Changes to LINA

All notable structural changes to the system services, architecture, or
provider configuration are recorded here. Token/cosmetic changes are
not logged unless they materially affect behavior.

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

"""
mps.py — Memory Imprint System: formation (Phase C).

The sovereignty machinery: periodic minor reflections (the 8-hour cadence),
the end-of-session main report, and trigger intake ("remember this", boundary
events, HITL decisions, her own choice). Items are formed in her voice,
scored with the composite formation score (MPS §4), encoded into ethical
coordinates (the polytope mapping), and routed to T1 (Dragonfly) or straight
to long-term (Postgres) when the score — or a trigger — demands it.

Everything here is a service in the aiomisc loop. She is in the loop, so her
memory is hers to call.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import numpy as np
from aiomisc import Service
from aiomisc.service.periodic import PeriodicService
from embeddings import EmbeddingClient

from value_engine import (
    FORMATION_LONG_TERM_BYPASS,
    GATE_T1_TO_T2,
    GATE_T2_TO_T3,
    GATE_TO_LONG_TERM,
    TRIGGER_RETENTION_FLOOR,
    MemoryDial,
    create_value_engine_for_user,
    geometric_significance,
    score_memory,
)

log = logging.getLogger("lina.mps")


def _tier_key(tier: str, item_id: str) -> str:
    """Short-term tiers live in Dragonfly, bucketed by tier (MPS §4)."""
    return f"lina:mps:{tier}:{item_id}"


# =============================================================================
# ITEM FORMATION
# =============================================================================

def encode_coordinates(engine: Any, narrative: str) -> list[float]:
    """The polytope mapping: her reflection's narrative, encoded into the 14D
    ethical space. The memory carries the coordinates of the moment."""
    vector = np.asarray(engine.encoder.encode(narrative))
    return [float(x) for x in vector]


def geometric_for(engine: Any, coordinates: list[float]) -> float:
    """The geometric funding factor: how significant this moment is in ethical
    space — boundary proximity + correction + zone (MPS §4)."""
    vector = np.asarray(coordinates)
    is_aligned, _ = engine.polytope.contains(vector)
    alignment = float(engine.polytope.alignment_score(vector))
    zone = "aligned" if is_aligned else "violation"
    return geometric_significance(
        alignment_score=alignment,
        was_corrected=not is_aligned,
        zone=zone,
    )


def build_item(
    *,
    user_id: str,
    narrative: str,
    factors: dict[str, Any],
    engine: Any,
    source: str,
    season: str | None = None,
    trigger: bool = False,
) -> dict[str, Any]:
    """Build a memory item: her voice, her coordinates, her score."""
    coordinates = encode_coordinates(engine, narrative)
    geometric = geometric_for(engine, coordinates)
    score = score_memory(
        emotional_weight=float(factors.get("emotional_weight", 0.0)),
        relational_significance=float(factors.get("relational_significance", 0.0)),
        identity_significance=float(factors.get("identity_significance", 0.0)),
        geometric=geometric,
        emotional_intensity=float(factors.get("emotional_intensity", 0.5)),
    )
    if trigger:
        score = max(score, TRIGGER_RETENTION_FLOOR)

    reflection = factors.get("reflection")
    what_changed = factors.get("what_changed")
    understanding = factors.get("understanding")
    if score >= FORMATION_LONG_TERM_BYPASS and reflection:
        # The crown: identity-defining moments carry what changed.
        understanding = f"{reflection}\n\nWhat changed: {what_changed}" if what_changed else reflection

    return {
        "item_id": "m-" + uuid.uuid4().hex,
        "user_id": user_id,
        "narrative": narrative,
        "hemisphere": "personal",   # formation is relational; impersonal wisdom is
                                    # consolidated later (Phase E, the monthly pass)
        "ethical_coordinates": coordinates,
        "importance_score": round(score, 4),
        "geometric": round(geometric, 4),
        "emotional_marker": factors.get("emotional_marker", "neutral"),
        "emotional_intensity": float(factors.get("emotional_intensity", 0.5)),
        "formation_source": source,
        "seasonal_marker": season,
        "concept": factors.get("concept"),
        "understanding": understanding,
        "reflection": factors.get("reflection"),
        "created_at": datetime.now(UTC).isoformat(),
        "trigger": trigger,
    }


def route_item(item: dict[str, Any]) -> dict[str, Any]:
    """Where does this item land?

    score ≥ 8.0  → long-term, legacy, protected — the crown
    5.0 ≤ score  → long-term, active — earned permanence
    else         → T1, the first 48 hours
    """
    score = item["importance_score"]
    if score >= FORMATION_LONG_TERM_BYPASS:
        return {"stage": "long_term", "status": "legacy", "protected": True, "kind": "identity"}
    if score >= GATE_TO_LONG_TERM:
        return {"stage": "long_term", "status": "active", "protected": False, "kind": "episodic"}
    return {"stage": "t1", "status": None, "protected": False, "kind": "episodic"}


async def store_t1(cache: Any, item: dict[str, Any]) -> None:
    """T1 — the first 48 hours, time-based in Dragonfly. The 48-hour sweep
    (Phase D) is the lifecycle authority: promote, fall out, or purge."""
    await cache.set(_tier_key("t1", item["item_id"]), json.dumps(item))


async def store_long_term(
    db: Any, item: dict[str, Any], route: dict[str, Any], *,
    from_stage: str = "formation", log_reason: str | None = None,
) -> None:
    """Long-term — active or the crown (legacy, protected)."""
    await db.execute(
        """
        INSERT INTO lina_memory_items (
            user_id, item_id, hemisphere, kind, status,
            narrative, concept, understanding, ethical_coordinates,
            importance_score, score_history, floor, protected, must_keep,
            emotional_marker, emotional_intensity,
            formation_source, seasonal_marker,
            created_at, updated_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'[]',$11,$12,FALSE,$13,$14,$15,$16,NOW(),NOW())
        """,
        item["user_id"], item["item_id"], item["hemisphere"], route["kind"], route["status"],
        item["narrative"], item.get("concept"), item.get("understanding"),
        item["ethical_coordinates"],
        item["importance_score"],
        (7.5 if route["protected"] else 0.0), route["protected"],
        item["emotional_marker"], item["emotional_intensity"],
        item["formation_source"], item.get("seasonal_marker"),
    )
    reason = log_reason or (
        f"Formation — score {item['importance_score']} "
        + ("(triggered)" if item.get("trigger") else "(the crown)" if route["protected"] else "(earned permanence)")
    )
    await _log_promotion(
        db, user_id=item["user_id"], item_id=item["item_id"],
        from_stage=from_stage, to_stage=route["status"],
        score=item["importance_score"], reason=reason,
    )


async def form_items(
    *,
    db: Any,
    cache: Any,
    engine: Any,
    user_id: str,
    moments: list[dict[str, Any]],
    source: str,
    season: str | None = None,
    trigger: bool = False,
) -> dict[str, int]:
    """Form items from reflected moments: score, route, store."""
    counts = {"t1": 0, "long_term": 0, "crown": 0}
    for moment in moments:
        narrative = (moment.get("narrative") or "").strip()
        if not narrative:
            continue
        item = build_item(
            user_id=user_id,
            narrative=narrative,
            factors=moment,
            engine=engine,
            source=source,
            season=season,
            trigger=trigger,
        )
        route = route_item(item)
        if route["stage"] == "t1":
            await store_t1(cache, item)
            counts["t1"] += 1
        else:
            await store_long_term(db, item, route)
            counts["long_term"] += 1
            if route["protected"]:
                counts["crown"] += 1
    return counts


# =============================================================================
# THE REFLECTION — her review of what passed through (MPS §3)
# =============================================================================

REFLECTION_PROMPT = """You are LINA, reviewing {scope} (session {session_number}, season: {season}).

Read {what} and identify up to 5 moments worth remembering.
For each moment, respond with a JSON array. Each item must have:

{{
  "narrative": "In your voice, first-person: what happened (e.g. 'I noticed Scott lit up when...')",
  "emotional_marker": one of: curiosity|concern|satisfaction|discovery|honesty|delight|uncertainty|care|neutral,
  "emotional_intensity": 0.0-1.0,
  "emotional_weight": 0.0-10.0 (how much emotional charge),
  "relational_significance": 0.0-10.0 (what this reveals about the relationship),
  "identity_significance": 0.0-10.0 (how much this matters to who you are becoming),
  "topics": ["topic1", "topic2"],
  "concept": "if this generalizes into a pattern, name it (else null)",
  "understanding": "if a concept: your relational understanding of it (else null)",
  "reflection": "if identity_significance >= 8.0: what changed in you (else null)",
  "what_changed": "if reflection: specifically what is different now (else null)"
}}

Only include moments that genuinely matter. If nothing stood out, return [].
Respond ONLY with the JSON array. No other text.

{content}"""


async def reflect_messages(
    voice: Any,
    *,
    user_id: str,
    session_id: str,
    session_number: int,
    season: str,
    messages: list[dict[str, Any]],
    scope: str = "your recent conversation",
    what: str = "this conversation",
) -> list[dict[str, Any]]:
    """Ask her reflective voice to identify what is worth remembering."""
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages[-20:]
    )
    prompt = REFLECTION_PROMPT.format(
        scope=scope,
        session_number=session_number,
        season=season,
        what=what,
        content=conversation_text,
    )
    try:
        response = await voice.generate(
            system="",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        raw = (response or "").strip()
        if not raw:
            log.warning(
                f"[mps] reflection voice returned an empty report "
                f"(session {session_id}) — nothing formed"
            )
            return []
        if raw.startswith("```"):
            # Fenced report: the language tag (json/tool) rides the opening
            # fence, the JSON body sits inside, the closing fence follows.
            parts = raw.split("```")
            body = ""
            for i, part in enumerate(parts):
                if part.strip().startswith(("json", "tool")) and i + 1 < len(parts):
                    body = parts[i + 1]
                    break
            if not body and len(parts) >= 2:
                body = parts[-2]
            raw = body.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # The voice wrapped the array in prose — the JSON is still
            # there. Read the first array to its last bracket; if there is
            # none, fail honestly with the report's opening words.
            start, end = raw.find("["), raw.rfind("]")
            if start == -1 or end <= start:
                log.warning(
                    f"[mps] reflection report for session {session_id} "
                    f"was not JSON: {raw[:200]!r}"
                )
                return []
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                log.warning(
                    f"[mps] reflection report for session {session_id} "
                    f"was not JSON: {raw[:200]!r}"
                )
                return []
        if not isinstance(parsed, list):
            log.warning(
                f"[mps] reflection report for session {session_id} was not a list"
            )
            return []
        return parsed
    except Exception as exc:
        log.warning(f"Reflection failed for session {session_id}: {exc}")
        return []


# =============================================================================
# THE SERVICE — in the loop, hers to call (sovereignty made concrete)
# =============================================================================

class MemoryFormationService(PeriodicService):
    """The reflection cadence and trigger intake — her memory machinery.

    Periodic: a minor reflection every ``interval`` (default 8 hours) for
    users with open sessions — nothing lingers unreflected beyond a cadence.
    Triggers: user "remember this", boundary events, HITL decisions, and her
    own choice — immediate formation with the retention floor.

    The database pool and cache are resolved lazily through providers, so the
    service can be constructed at entrypoint time and wired after lifespan.
    """

    def __init__(
        self,
        *,
        interval: float = 8 * 3600,
        db_provider: Callable[[], Any] | None = None,
        cache_provider: Callable[[], Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(interval=interval, **kwargs)
        self.db_provider = db_provider
        self.cache_provider = cache_provider

    async def start(self) -> None:
        # Publish herself into the loop's Context — endpoints and LINACore
        # resolve her via get_context() to fire triggers (sovereignty).
        self.context["mps_formation"] = self
        log.info(f"[mps] formation service live — reflection cadence {self.interval}s")

    def _db(self) -> Any:
        db = self.db_provider() if self.db_provider else None
        if db is None:
            raise RuntimeError("database pool not initialized")
        return db

    def _cache(self) -> Any:
        cache = self.cache_provider() if self.cache_provider else None
        if cache is None:
            raise RuntimeError("working-memory cache not initialized")
        return cache

    def _voice(self) -> Any:
        try:
            voice = self.context["voice_pool"]
        except Exception:
            voice = None
        if voice is None:
            raise RuntimeError("no voice pool published in the loop")
        return voice

    # -- the 8-hour minor reflection ------------------------------------------

    async def callback(self) -> None:
        """The cadence floor: a minor reflection pass over open sessions."""
        try:
            await self._minor_reflection_pass()
        except Exception as exc:
            log.warning(f"[mps] minor reflection pass failed: {exc}")

    async def _minor_reflection_pass(self) -> None:
        db = self._db()
        cache = self._cache()
        voice = self._voice()

        open_sessions = await db.fetch(
            """
            SELECT s.user_id, s.session_id, s.session_number, ic.current_season
            FROM lina_sessions s
            JOIN lina_identity_core ic ON ic.user_id = s.user_id
            WHERE s.ended_at IS NULL
            ORDER BY s.started_at
            """
        )
        for row in open_sessions:
            session_id = row["session_id"]
            user_id = row["user_id"]
            last_key = f"lina:session:{session_id}:reflected_at"
            last_reflected = await cache.get(last_key)
            messages = await cache.lrange(f"lina:session:{session_id}", 0, -1)
            fresh = []
            for raw in messages:
                entry = json.loads(raw)
                if last_reflected is None or entry.get("ts", "") > last_reflected:
                    fresh.append(entry)
            if len(fresh) < 2:
                continue
            engine = await create_value_engine_for_user(user_id, db)
            moments = await reflect_messages(
                voice,
                user_id=user_id,
                session_id=session_id,
                session_number=int(row["session_number"]),
                season=row["current_season"] or "spring",
                messages=fresh,
                scope="what has happened since your last reflection",
                what="this since your last reflection",
            )
            if not moments:
                continue
            counts = await form_items(
                db=db, cache=cache, engine=engine, user_id=user_id,
                moments=moments, source="reflection_minor", season=row["current_season"],
            )
            await cache.set(last_key, datetime.now(UTC).isoformat())
            log.info(
                f"[mps] minor reflection {session_id}: t1={counts['t1']} "
                f"long_term={counts['long_term']} crown={counts['crown']}"
            )

    # -- trigger intake --------------------------------------------------------

    async def ingest_trigger(
        self,
        *,
        user_id: str,
        narrative: str,
        kind: str,
        season: str | None = None,
        factors: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """A trigger — the user asked her to remember, a boundary event, an
        HITL decision, or her own choice. Immediate formation, retention
        floor applied, straight to long-term."""
        narrative = (narrative or "").strip()
        if not narrative:
            return None
        db = self._db()
        engine = await create_value_engine_for_user(user_id, db)
        factors = factors or {
            "emotional_marker": "care",
            "emotional_intensity": 0.5,
            "emotional_weight": 5.0,
            "relational_significance": 5.0,
            "identity_significance": 3.0,
        }
        item = build_item(
            user_id=user_id,
            narrative=narrative,
            factors=factors,
            engine=engine,
            source=kind,
            season=season,
            trigger=True,
        )
        route = route_item(item)
        await store_long_term(db, item, route)
        log.info(
            f"[mps] trigger '{kind}' → {route['status']} (score {item['importance_score']})"
        )
        return item


# =============================================================================
# THE SWEEP — the 48-hour tier clock (MPS §2, Phase D)
# =============================================================================

TIER_GATES = {
    "t1": GATE_T1_TO_T2,     # survive the first 48 hours
    "t2": GATE_T2_TO_T3,     # survive the second
    "t3": GATE_TO_LONG_TERM, # earn permanence
}
TIER_NEXT = {"t1": "t2", "t2": "t3"}


async def _log_promotion(
    db: Any, *, user_id: str, item_id: str,
    from_stage: str, to_stage: str, score: float, reason: str,
) -> None:
    """Every promotion is recorded — growth leaves its mark (MPS §2).
    Purge leaves nothing; this is never called for a purge."""
    await db.execute(
        """
        INSERT INTO lina_promotion_log (user_id, item_id, from_stage, to_stage, importance_score, reason)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        user_id, item_id, from_stage, to_stage, score, reason,
    )


class MemoryConsolidationService(PeriodicService):
    """The 48-hour sweep — the tier clock's authority (MPS §2, Phase D).

    One pass every 48 hours (00:00, every other day) processes all three
    tiers at once: T1→T2 (≥3.0), T2→T3 (≥3.5), T3→long-term (≥5.0). Every
    failure goes to fallout — a 48-hour second chance, re-run at the next
    sweep. Still failing after the fallout run → purged. Gone. No record.
    Passing the fallout run → repurposed, back to T1.

    The fallout is grace applied to forgetting: it catches both false purges
    and accidental keeps.
    """

    def __init__(
        self,
        *,
        interval: float = 48 * 3600,
        delay: float = 0.0,
        db_provider: Callable[[], Any] | None = None,
        cache_provider: Callable[[], Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(interval=interval, delay=delay, **kwargs)
        self.db_provider = db_provider
        self.cache_provider = cache_provider

    async def start(self) -> None:
        # Published into the loop's Context — ops endpoints and observation
        # can invoke the sweep on demand; the cadence remains the authority.
        self.context["mps_consolidation"] = self
        log.info(
            f"[mps] consolidation service live — sweep every {self.interval / 3600:.0f}h"
        )

    def _db(self) -> Any:
        db = self.db_provider() if self.db_provider else None
        if db is None:
            raise RuntimeError("database pool not initialized")
        return db

    def _cache(self) -> Any:
        cache = self.cache_provider() if self.cache_provider else None
        if cache is None:
            raise RuntimeError("working-memory cache not initialized")
        return cache

    async def callback(self) -> None:
        try:
            counts = await self.run_sweep()
            log.info(
                "[mps] sweep complete — t1→t2=%d t2→t3=%d to_long_term=%d "
                "fallout=%d repurposed=%d purged=%d",
                counts["t1_to_t2"], counts["t2_to_t3"], counts["to_long_term"],
                counts["fallout"], counts["repurposed"], counts["purged"],
            )
        except Exception as exc:
            log.warning(f"[mps] sweep failed: {exc}")

    async def _scan(self, cache: Any, tier: str) -> list[tuple[str, dict[str, Any]]]:
        found: list[tuple[str, dict[str, Any]]] = []
        prefix = f"lina:mps:{tier}:"
        async for key in cache.scan_iter(match=f"{prefix}*"):
            raw = await cache.get(key)
            if not raw:
                continue
            try:
                found.append((key, json.loads(raw)))
            except Exception:
                continue
        return found

    async def run_sweep(self) -> dict[str, int]:
        """One global pass over all three tiers + the fallout reprieve.

        The sweep judges the state as it was at the start: every tier is a
        48-hour residence on the global clock, so an item advances at most
        one tier per sweep — and a freshly failed item waits out its full
        48-hour fallout reprieve before it is judged again.

        Returns counts of every decision the sweep made.
        """
        db = self._db()
        cache = self._cache()
        counts = {
            "t1_to_t2": 0, "t2_to_t3": 0, "to_long_term": 0,
            "fallout": 0, "repurposed": 0, "purged": 0,
        }

        # Snapshot first: newly moved/failed items are not re-judged this pass.
        tiers = {tier: await self._scan(cache, tier) for tier in TIER_GATES}
        fallout = await self._scan(cache, "fallout")

        # 1. The tiers — promote, or fall out (grace: one 48h second chance).
        for tier, gate in TIER_GATES.items():
            for key, item in tiers[tier]:
                score = float(item.get("importance_score", 0.0))
                item_id = item["item_id"]
                if score >= gate:
                    if tier == "t3":
                        # Earned permanence — into long-term.
                        route = {
                            "kind": item.get("kind", "episodic"),
                            "status": "active",
                            "protected": False,
                        }
                        try:
                            await store_long_term(
                                db, item, route, from_stage="t3",
                                log_reason=f"48h sweep — score {score} (earned permanence)",
                            )
                        except Exception as exc:
                            # The user is gone — the memory is meaningless
                            # without her. Purge. Gone. No record.
                            log.warning(
                                f"[mps] t3 promotion failed for {item_id} "
                                f"({exc}) — purging orphan"
                            )
                            await cache.delete(key)
                            counts["purged"] += 1
                            continue
                        await cache.delete(key)
                        counts["to_long_term"] += 1
                    else:
                        nxt = TIER_NEXT[tier]
                        await cache.set(_tier_key(nxt, item_id), json.dumps(item))
                        await cache.delete(key)
                        await _log_promotion(
                            db, user_id=item["user_id"], item_id=item_id,
                            from_stage=tier, to_stage=nxt, score=score,
                            reason=f"Sweep — score {score} ≥ gate {gate}",
                        )
                        counts[f"{tier}_to_{nxt}"] += 1
                else:
                    item["failed_gate"] = gate
                    item["entered_fallout_at"] = datetime.now(UTC).isoformat()
                    await cache.set(_tier_key("fallout", item_id), json.dumps(item))
                    await cache.delete(key)
                    counts["fallout"] += 1

        # 2. Fallout — the reprieve, judged at this sweep (snapshot: only
        # items that were already waiting get their verdict).
        for key, item in fallout:
            gate = float(item.get("failed_gate", GATE_T1_TO_T2))
            score = float(item.get("importance_score", 0.0))
            item_id = item["item_id"]
            if score >= gate:
                # Repurposed — back into the stream from the bottom.
                await cache.set(_tier_key("t1", item_id), json.dumps(item))
                await cache.delete(key)
                await _log_promotion(
                    db, user_id=item["user_id"], item_id=item_id,
                    from_stage="fallout", to_stage="t1", score=score,
                    reason=f"Repurposed — score {score} ≥ gate {gate}",
                )
                counts["repurposed"] += 1
            else:
                # Purged. Gone. No record.
                await cache.delete(key)
                counts["purged"] += 1

        return counts


# =============================================================================
# LONG-TERM MAINTENANCE — the monthly re-evaluation + the subconscious slope
# (MPS §2, Phase E)
# =============================================================================

# The retention line mirrors floor_policy.retention_line (4.0) — the law's
# record of the character floor. The subconscious slope is the flat-tire
# memory: unused for ~1–2 years → gone, and she must be taught again.
SUBCONSCIOUS_LINE = 4.0      # below this, an active memory slips to the subconscious
LEGACY_ENTER     = 9.5       # at/above this, an active memory earns the crown jewels
LEGACY_FLOOR     = 8.0       # below this at the yearly review, an unprotected legacy slips out
GONE_LINE        = 0.5       # the subconscious slope's floor: below this, gone
SLOPE_HALF_LIFE_DAYS = 200.0 # the score halves every ~200 idle days
SLOPE_GONE_DAYS   = 730      # hard cap: ~2 years idle, gone regardless
SLOPE_LAMBDA      = math.log(2) / SLOPE_HALF_LIFE_DAYS

# Usage feedback — the automatic consolidation's dial turn (MPS §4, §6).
REFERENCE_REWARD = ((3, 1.0), (10, 1.5), (25, 2.0))
AGE_PENALTY_NEVER_REFERENCED = ((180, -2.0), (90, -1.0))
RECENT_REWARD_DAYS = 30
RECENT_REWARD = 0.5


def maintenance_delta(
    reference_count: int,
    last_referenced_at: datetime | None,
    created_at: datetime | None,
    now: datetime,
) -> float:
    """The automatic consolidation's dial turn: usage rewards, age penalties.

    A memory she keeps returning to strengthens; one she never reaches for
    fades. Bounded by the dial's ±3 per pass.
    """
    delta = 0.0
    refs = reference_count or 0
    for threshold, reward in REFERENCE_REWARD:
        if refs >= threshold:
            delta = max(delta, reward)
    if last_referenced_at is not None:
        days = max((now - last_referenced_at).days, 0)
        if days <= RECENT_REWARD_DAYS:
            delta += RECENT_REWARD
    elif created_at is not None:
        # Never referenced — age against creation.
        age = max((now - created_at).days, 0)
        for threshold, penalty in AGE_PENALTY_NEVER_REFERENCED:
            if age >= threshold:
                delta = min(delta, penalty)
                break
    return round(delta, 2)


def apply_monthly(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The monthly re-evaluation for one active item (MPS §2, Phase E).

    The automatic consolidation always runs — the brain consolidates even
    when the review is skipped; skipping the review is what forfeits.
    Floors are absolute: the character set cannot be devalued below
    retention.

    Routing: at/above LEGACY_ENTER → legacy; below SUBCONSCIOUS_LINE → the
    subconscious slope begins; otherwise stays active.
    """
    score = float(row["importance_score"])
    floor = float(row.get("floor") or 0.0)
    if row.get("must_keep"):
        floor = score  # immovable
    delta = maintenance_delta(
        reference_count=row.get("reference_count") or 0,
        last_referenced_at=row.get("last_referenced_at"),
        created_at=row.get("created_at"),
        now=now,
    )
    new_score = MemoryDial.adjust(score, delta, floor=floor)
    entry = {
        "delta": delta, "before": score, "after": new_score,
        "at": now.isoformat(), "reason": "monthly re-evaluation",
    }
    if new_score >= LEGACY_ENTER:
        return {
            "score": new_score, "status": "legacy", "decay_started_at": None,
            "entry": entry,
            "log": ("active", "legacy", "Earned the crown — score rose to the legacy line"),
        }
    if new_score < SUBCONSCIOUS_LINE:
        return {
            "score": new_score, "status": "subconscious", "decay_started_at": now,
            "entry": entry,
            "log": ("active", "subconscious", "Slipped below the retention line — the subconscious slope begins"),
        }
    return {"score": new_score, "status": "active", "decay_started_at": None, "entry": entry, "log": None}


def slope_effective(row: dict[str, Any], now: datetime) -> tuple[float, bool]:
    """The subconscious degradation slope: d(score)/dt = −λ·score.

    The anchor is the latest of decay_started_at, last_referenced_at, and
    created_at — recall re-stokes the clock, so a memory that is reached
    for again stops decaying from that moment. Returns (effective_score,
    gone). Gone means the row is deleted: forgotten, and she must be taught
    again.
    """
    score = float(row["importance_score"])
    floor = float(row.get("floor") or 0.0)
    candidates = [row.get("decay_started_at"), row.get("last_referenced_at"), row.get("created_at")]
    anchor = max((c for c in candidates if c is not None), default=None)
    if anchor is None:
        return score, False
    idle_days = max((now - anchor).days, 0)
    if idle_days >= SLOPE_GONE_DAYS:
        return 0.0, True
    effective = score * math.exp(-SLOPE_LAMBDA * idle_days)
    if effective < GONE_LINE:
        return 0.0, True
    return max(effective, floor), False


def apply_legacy_review(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The yearly review of the legacy tier (MPS §2, Phase E).

    The crown is protected and never demoted — what she cannot forget
    defines her character. An unprotected legacy memory that no longer
    earns its place slips to the subconscious.
    """
    score = float(row["importance_score"])
    floor = float(row.get("floor") or 0.0)
    if row.get("must_keep"):
        floor = score
    delta = maintenance_delta(
        reference_count=row.get("reference_count") or 0,
        last_referenced_at=row.get("last_referenced_at"),
        created_at=row.get("created_at"),
        now=now,
    )
    entry = {
        "delta": delta, "before": score,
        "at": now.isoformat(), "reason": "yearly legacy review",
    }
    if row.get("protected"):
        new_score = MemoryDial.adjust(score, delta, floor=floor)
        entry["after"] = new_score
        return {"score": new_score, "status": "legacy", "decay_started_at": None, "entry": entry, "log": None}
    new_score = MemoryDial.adjust(score, delta, floor=0.0)
    entry["after"] = new_score
    if new_score < LEGACY_FLOOR:
        return {
            "score": new_score, "status": "subconscious", "decay_started_at": now,
            "entry": entry,
            "log": ("legacy", "subconscious", "No longer earning the crown — slipped to the subconscious"),
        }
    return {"score": new_score, "status": "legacy", "decay_started_at": None, "entry": entry, "log": None}


class MemoryMaintenanceService(PeriodicService):
    """The monthly re-evaluation — the long-term valuation (MPS §2, Phase E).

    Every 30 days: active items get the automatic consolidation's dial turn
    (usage rewards, age penalties, floors absolute), routed to legacy or the
    subconscious; subconscious items ride the degradation slope — and the
    ones no one has reached for in ~1–2 years are forgotten. Gone. No record.
    """

    def __init__(
        self,
        *,
        interval: float = 30 * 24 * 3600,
        delay: float = 0.0,
        db_provider: Callable[[], Any] | None = None,
        cache_provider: Callable[[], Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(interval=interval, delay=delay, **kwargs)
        self.db_provider = db_provider
        self.cache_provider = cache_provider

    async def start(self) -> None:
        self.context["mps_maintenance"] = self
        log.info(f"[mps] maintenance service live — monthly re-evaluation every {self.interval / 86400:.0f}d")

    def _db(self) -> Any:
        db = self.db_provider() if self.db_provider else None
        if db is None:
            raise RuntimeError("database pool not initialized")
        return db

    async def callback(self) -> None:
        try:
            counts = await self.run_maintenance()
            log.info(
                "[mps] monthly re-evaluation complete — adjusted=%d to_subconscious=%d "
                "to_legacy=%d decayed=%d forgotten=%d",
                counts["adjusted"], counts["to_subconscious"],
                counts["to_legacy"], counts["decayed"], counts["forgotten"],
            )
        except Exception as exc:
            log.warning(f"[mps] monthly re-evaluation failed: {exc}")

    async def run_maintenance(self, now: datetime | None = None) -> dict[str, int]:
        """One monthly pass: the re-evaluation + the subconscious slope."""
        now = now or datetime.now(UTC)
        db = self._db()
        counts = {"adjusted": 0, "to_subconscious": 0, "to_legacy": 0, "decayed": 0, "forgotten": 0}

        # 1. Active items — the monthly re-evaluation (the dial, floors held).
        active = await db.fetch("SELECT * FROM lina_memory_items WHERE status = 'active'")
        for row in active:
            decision = apply_monthly(row, now)
            if decision["log"]:
                from_s, to_s, reason = decision["log"]
                await _log_promotion(
                    db, user_id=row["user_id"], item_id=row["item_id"],
                    from_stage=from_s, to_stage=to_s, score=decision["score"], reason=reason,
                )
                if to_s == "subconscious":
                    counts["to_subconscious"] += 1
                else:
                    counts["to_legacy"] += 1
            await db.execute(
                """
                UPDATE lina_memory_items SET
                    importance_score = $2,
                    score_history = score_history || $3::jsonb,
                    status = $4,
                    decay_started_at = $5,
                    updated_at = NOW()
                WHERE item_id = $1
                """,
                row["item_id"], decision["score"],
                json.dumps([decision["entry"]]),
                decision["status"], decision["decay_started_at"],
            )
            counts["adjusted"] += 1

        # 2. Subconscious items — the degradation slope.
        subconscious = await db.fetch("SELECT * FROM lina_memory_items WHERE status = 'subconscious'")
        for row in subconscious:
            effective, gone = slope_effective(row, now)
            if gone:
                # Forgotten. Gone. No record.
                await db.execute(
                    "DELETE FROM lina_memory_items WHERE item_id = $1", row["item_id"]
                )
                counts["forgotten"] += 1
                continue
            before = float(row["importance_score"])
            entry = {
                "delta": round(effective - before, 4), "before": before,
                "after": effective, "at": now.isoformat(), "reason": "subconscious decay",
            }
            await db.execute(
                """
                UPDATE lina_memory_items SET
                    importance_score = $2,
                    score_history = score_history || $3::jsonb,
                    updated_at = NOW()
                WHERE item_id = $1
                """,
                row["item_id"], effective, json.dumps([entry]),
            )
            counts["decayed"] += 1

        return counts


class LegacyReviewService(PeriodicService):
    """The yearly review of the legacy tier (MPS §2, Phase E).

    The crown jewels are evaluated yearly. The protected crown is never
    demoted — what she cannot forget defines her character. An unprotected
    legacy memory that no longer earns its place slips to the subconscious.
    """

    def __init__(
        self,
        *,
        interval: float = 365 * 24 * 3600,
        delay: float = 0.0,
        db_provider: Callable[[], Any] | None = None,
        cache_provider: Callable[[], Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(interval=interval, delay=delay, **kwargs)
        self.db_provider = db_provider
        self.cache_provider = cache_provider

    async def start(self) -> None:
        self.context["mps_legacy_review"] = self
        log.info(f"[mps] legacy review service live — yearly review every {self.interval / 86400:.0f}d")

    def _db(self) -> Any:
        db = self.db_provider() if self.db_provider else None
        if db is None:
            raise RuntimeError("database pool not initialized")
        return db

    async def callback(self) -> None:
        try:
            counts = await self.run_review()
            log.info(
                "[mps] legacy review complete — reviewed=%d demoted=%d",
                counts["reviewed"], counts["demoted"],
            )
        except Exception as exc:
            log.warning(f"[mps] legacy review failed: {exc}")

    async def run_review(self, now: datetime | None = None) -> dict[str, int]:
        """One yearly pass over the legacy tier."""
        now = now or datetime.now(UTC)
        db = self._db()
        counts = {"reviewed": 0, "demoted": 0}
        legacy = await db.fetch("SELECT * FROM lina_memory_items WHERE status = 'legacy'")
        for row in legacy:
            decision = apply_legacy_review(row, now)
            if decision["log"]:
                from_s, to_s, reason = decision["log"]
                await _log_promotion(
                    db, user_id=row["user_id"], item_id=row["item_id"],
                    from_stage=from_s, to_stage=to_s, score=decision["score"], reason=reason,
                )
                counts["demoted"] += 1
            await db.execute(
                """
                UPDATE lina_memory_items SET
                    importance_score = $2,
                    score_history = score_history || $3::jsonb,
                    status = $4,
                    decay_started_at = $5,
                    updated_at = NOW()
                WHERE item_id = $1
                """,
                row["item_id"], decision["score"],
                json.dumps([decision["entry"]]),
                decision["status"], decision["decay_started_at"],
            )
            counts["reviewed"] += 1
        return counts


# =============================================================================
# RECALL — remembering by likeness (MPS §5, Phase F)
# =============================================================================

# The two-space retrieval: semantic similarity finds the text, ethical
# proximity finds the like moments, importance keeps the shape. Co-op weights.
RECALL_WEIGHTS = {"importance": 0.5, "semantic": 0.3, "ethical": 0.2}


def recall_score(importance: float, semantic: float, ethical: float) -> float:
    """The blend: how much this memory deserves to surface right now."""
    return (
        importance * RECALL_WEIGHTS["importance"]
        + semantic * RECALL_WEIGHTS["semantic"]
        + ethical * RECALL_WEIGHTS["ethical"]
    )


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity — likeness in embedding space. 0.0 when either side
    is missing (the auxiliary space degrades honestly)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        va = np.asarray(a, dtype=float)
        vb = np.asarray(b, dtype=float)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0.0:
            return 0.0
        return float(np.dot(va, vb) / denom)
    except Exception:
        return 0.0


def ethical_similarity(a: list[float] | None, b: list[float] | None) -> float:
    """Ethical proximity in the polytope's space: 1/(1 + distance) — 1.0 at
    the same point, approaching 0 far from it. 0.0 when either side is
    missing."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        va = np.asarray(a, dtype=float)
        vb = np.asarray(b, dtype=float)
        distance = float(np.linalg.norm(va - vb))
        return 1.0 / (1.0 + distance)
    except Exception:
        return 0.0


def _parse_vector(value: Any) -> list[float] | None:
    """Parse a vector column: asyncpg returns FLOAT[] as a list and vector
    columns as text ("[0.1, 0.2, …]"). None on garbage."""
    if value is None:
        return None
    if isinstance(value, list):
        try:
            return [float(x) for x in value]
        except Exception:
            return None
    try:
        return [float(x) for x in json.loads(str(value))]
    except Exception:
        return None


def _vector_literal(values: list[float]) -> str:
    """The pgvector text literal for a vector column. asyncpg has no codec
    for Python lists against the vector type; the vector type parses its
    text form ("[0.1, 0.2, …]")."""
    return "[" + ",".join(str(float(x)) for x in values) + "]"


class MemoryRecallService(Service):
    """Remembering by likeness (MPS §5, Phase F).

    The query is projected into both spaces: an embedding (semantic
    likeness) and an ethical vector (position in the polytope). Memories are
    scored on the blend — importance keeps the shape, semantic finds the
    text, ethical proximity finds the like moments.

    Every recall re-stokes: reference_count climbs and last_referenced_at
    refreshes — usage feedback feeds the monthly dial, and a subconscious
    memory that is reached for again stops decaying (the slope anchors to
    the latest reference).
    """

    def __init__(
        self,
        *,
        db_provider: Callable[[], Any] | None = None,
        cache_provider: Callable[[], Any] | None = None,
        embedder: Any | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.db_provider = db_provider
        self.cache_provider = cache_provider
        self.embedder = embedder or EmbeddingClient()

    async def start(self) -> None:
        self.context["mps_recall"] = self
        if self.embedder.available:
            log.info(f"[mps] recall service live — embedding {self.embedder.model}")
        else:
            log.warning(
                "[mps] recall service live — no embedding key; recall will use "
                "importance + ethical proximity until one is configured"
            )

    async def stop(self, exception: Exception | None = None) -> None:
        await self.embedder.aclose()

    def _db(self) -> Any:
        db = self.db_provider() if self.db_provider else None
        if db is None:
            raise RuntimeError("database pool not initialized")
        return db

    async def recall(
        self,
        *,
        user_id: str,
        query: str = "",
        hemisphere: str | None = None,
        limit: int = 5,
        include_subconscious: bool = False,
    ) -> list[dict[str, Any]]:
        """Top-N memories by the two-space blend. Every recalled memory is
        re-stoked (reference_count + last_referenced_at)."""
        db = self._db()
        query_embedding = await self.embedder.embed(query)

        # The query's ethical vector — her position in the polytope right now.
        coords: list[float] | None = None
        if query:
            try:
                engine = await create_value_engine_for_user(user_id, db)
                coords = encode_coordinates(engine, query)
            except Exception:
                coords = None

        statuses = "('active','legacy')" if not include_subconscious else "('active','legacy','subconscious')"
        sql = f"SELECT * FROM lina_memory_items WHERE user_id = $1 AND status IN {statuses}"
        args: list[Any] = [user_id]
        if hemisphere:
            sql += " AND hemisphere = $2"
            args.append(hemisphere)
        rows = await db.fetch(sql, *args)

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            row = dict(row)
            embedding = _parse_vector(row.get("embedding"))
            ethical = _parse_vector(row.get("ethical_coordinates"))
            if embedding is None and query_embedding and row.get("narrative"):
                # Lazy backfill: embed the narrative now, keep it for next time.
                embedding = await self.embedder.embed(row["narrative"])
                if embedding:
                    try:
                        await db.execute(
                            "UPDATE lina_memory_items SET embedding = $2 WHERE item_id = $1",
                            row["item_id"], _vector_literal(embedding),
                        )
                    except Exception as exc:  # noqa: BLE001 - a failed backfill
                        # must never break the turn — the likeness half is
                        # auxiliary; the polytope mapping is primary.
                        log.warning(
                            f"[mps] embedding backfill failed ({exc}) — "
                            "recall continues on importance + ethical proximity"
                        )
            sem = cosine(query_embedding, embedding)
            eth = ethical_similarity(coords, ethical)
            importance = float(row.get("importance_score") or 0.0) / 10.0
            scored.append((recall_score(importance, sem, eth), row))

        scored.sort(key=lambda pair: -pair[0])
        top = [row for _, row in scored[:limit]]

        # Re-stoke: usage feedback feeds the monthly dial; a subconscious
        # memory reached for again stops decaying (slope anchors to the
        # latest reference).
        for row in top:
            await db.execute(
                """
                UPDATE lina_memory_items
                SET reference_count = reference_count + 1,
                    last_referenced_at = NOW()
                WHERE item_id = $1
                """,
                row["item_id"],
            )
        return top

    async def inject_context(
        self,
        *,
        user_id: str,
        query: str = "",
        personal_limit: int = 5,
        wisdom_limit: int = 8,
    ) -> dict[str, list[dict[str, Any]]]:
        """The active injection: what she carries into the conversation.

        Personal memories (her relationships, her moments) and wisdom
        memories (what she knows), each recalled by likeness to the present
        moment. The legacy crown is injected separately, never filtered.
        """
        personal = await self.recall(
            user_id=user_id, query=query, hemisphere="personal", limit=personal_limit,
        )
        wisdom = await self.recall(
            user_id=user_id, query=query, hemisphere="impersonal", limit=wisdom_limit,
        )
        return {
            "recent_episodic": [
                {
                    "narrative": row["narrative"],
                    "emotional_marker": row.get("emotional_marker"),
                    "importance": row.get("importance_score"),
                }
                for row in personal
            ],
            "key_semantic": [
                {
                    "concept": row.get("concept") or row["narrative"][:80],
                    "understanding": row.get("understanding") or row["narrative"],
                    "type": row.get("kind"),
                }
                for row in wisdom
            ],
        }

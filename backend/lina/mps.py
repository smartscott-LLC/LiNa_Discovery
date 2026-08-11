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
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import numpy as np
from aiomisc.service.periodic import PeriodicService

from value_engine import (
    FORMATION_LONG_TERM_BYPASS,
    GATE_T1_TO_T2,
    GATE_T2_TO_T3,
    GATE_TO_LONG_TERM,
    TRIGGER_RETENTION_FLOOR,
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
        raw = response.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
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
            voice = self.context.get("voice_pool")
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

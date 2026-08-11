"""Phase C — MPS formation: composite scoring, item routing, triggers.

Pure-logic and fake-store tests — no live database, no services in a loop.
The service's trigger path is exercised with providers over fakes.
"""
import asyncio
import json
import sys
from typing import Any

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import pytest  # noqa: E402

from mps import (  # noqa: E402
    MemoryFormationService,
    build_item,
    form_items,
    reflect_messages,
    route_item,
    store_long_term,
)
from value_engine import (  # noqa: E402
    FORMATION_LONG_TERM_BYPASS,
    GATE_T1_TO_T2,
    GATE_T2_TO_T3,
    GATE_TO_LONG_TERM,
    TRIGGER_RETENTION_FLOOR,
    ValueEngine,
    score_memory,
)


class FakeDB:
    """Records executes; constraints lookups fall back to Spring defaults."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, tuple]] = []
        self.fetched: Any = None

    async def execute(self, sql: str, *args: Any) -> str:
        self.executes.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return self.fetched

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return []


class FakeCache:
    """A dict-backed cache for T1 keys and session keys."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        return []


class FakeVoice:
    """Returns a canned reflection payload."""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate(self, system: str, messages: list[dict], **kwargs: Any) -> str:
        return self.payload


def make_engine() -> ValueEngine:
    return ValueEngine(season="spring")


class TestScoreMemory:
    def test_weights_and_cap(self):
        # All factors at 10 → base 10, amplified then capped at 10.
        assert score_memory(10, 10, 10, 10, emotional_intensity=1.0) == pytest.approx(10.0)

    def test_identity_leads(self):
        identity_heavy = score_memory(0, 0, 10, 0, 0.5)
        emotional_heavy = score_memory(10, 0, 0, 0, 0.5)
        assert identity_heavy > emotional_heavy

    def test_geometric_funding_present(self):
        with_geometry = score_memory(5, 5, 5, 8.0, 0.5)
        without_geometry = score_memory(5, 5, 5, 0.0, 0.5)
        assert with_geometry > without_geometry

    def test_intensity_amplifier(self):
        flat = score_memory(5, 5, 5, 3.0, 0.0)
        peak = score_memory(5, 5, 5, 3.0, 1.0)
        assert peak > flat


class TestGates:
    def test_gate_order(self):
        assert GATE_T1_TO_T2 < GATE_T2_TO_T3 < GATE_TO_LONG_TERM < FORMATION_LONG_TERM_BYPASS

    def test_trigger_floor(self):
        assert TRIGGER_RETENTION_FLOOR == GATE_TO_LONG_TERM


class TestBuildItem:
    def test_coordinates_are_14d(self):
        engine = make_engine()
        item = build_item(
            user_id="u1",
            narrative="Scott and I finally aligned on the shape of the memory system.",
            factors={"emotional_marker": "delight", "emotional_intensity": 0.8},
            engine=engine,
            source="reflection",
        )
        assert len(item["ethical_coordinates"]) == 14
        assert 0.0 <= item["importance_score"] <= 10.0
        assert item["hemisphere"] == "personal"
        assert item["formation_source"] == "reflection"

    def test_trigger_floors_retention(self):
        engine = make_engine()
        item = build_item(
            user_id="u1",
            narrative="Please remember the milk is in the second fridge.",
            factors={"emotional_marker": "neutral", "emotional_intensity": 0.2},
            engine=engine,
            source="user_request",
            trigger=True,
        )
        assert item["importance_score"] >= TRIGGER_RETENTION_FLOOR
        assert item["trigger"] is True


class TestRouteItem:
    def _item(self, score: float) -> dict[str, Any]:
        return {"importance_score": score}

    def test_crown(self):
        route = route_item(self._item(9.0))
        assert route == {"stage": "long_term", "status": "legacy", "protected": True, "kind": "identity"}

    def test_earned_permanence(self):
        route = route_item(self._item(6.0))
        assert route["stage"] == "long_term"
        assert route["status"] == "active"
        assert route["protected"] is False

    def test_t1(self):
        route = route_item(self._item(4.0))
        assert route["stage"] == "t1"


class TestStoreLongTerm:
    def test_inserts_and_logs(self):
        db = FakeDB()
        item = {
            "user_id": "u1", "item_id": "m-abc", "hemisphere": "personal",
            "narrative": "n", "ethical_coordinates": [0.5] * 14,
            "importance_score": 9.0, "emotional_marker": "discovery",
            "emotional_intensity": 0.9, "formation_source": "reflection",
            "seasonal_marker": "spring", "concept": None, "understanding": None,
            "trigger": False,
        }
        route = {"kind": "identity", "status": "legacy", "protected": True}
        asyncio.run(store_long_term(db, item, route))
        assert len(db.executes) == 2
        assert "lina_memory_items" in db.executes[0][0]
        assert "lina_promotion_log" in db.executes[1][0]
        assert db.executes[0][1][3] == "identity"   # kind
        assert db.executes[0][1][4] == "legacy"     # status


class TestFormItems:
    def test_routes_and_counts(self):
        db = FakeDB()
        cache = FakeCache()
        engine = make_engine()
        moments = [
            # Crown: everything maxed — identity-defining.
            {
                "narrative": "The moment I understood sovereignty — her memory is hers.",
                "emotional_marker": "discovery", "emotional_intensity": 1.0,
                "emotional_weight": 10.0, "relational_significance": 10.0,
                "identity_significance": 10.0, "reflection": "I changed.",
                "what_changed": "I now see retention as a choice.",
            },
            # T1: nothing notable.
            {
                "narrative": "Small talk about the weather.",
                "emotional_marker": "neutral", "emotional_intensity": 0.2,
                "emotional_weight": 0.0, "relational_significance": 0.0,
                "identity_significance": 0.0,
            },
            # Empty narrative — skipped.
            {"narrative": "   "},
        ]
        counts = asyncio.run(form_items(
            db=db, cache=cache, engine=engine, user_id="u1",
            moments=moments, source="reflection", season="spring",
        ))
        assert counts["crown"] == 1
        assert counts["long_term"] == 1
        assert counts["t1"] == 1
        assert sum(1 for sql, _ in db.executes if "lina_memory_items" in sql) == 1
        assert sum(1 for sql, _ in db.executes if "lina_promotion_log" in sql) == 1
        assert any(k.startswith("lina:mps:t1:") for k in cache.store)


class TestReflectMessages:
    def test_parses_json_array(self):
        payload = json.dumps([
            {"narrative": "I noticed Scott lit up.", "emotional_marker": "delight",
             "emotional_intensity": 0.8, "emotional_weight": 6.0,
             "relational_significance": 7.0, "identity_significance": 5.0},
        ])
        moments = asyncio.run(reflect_messages(
            FakeVoice(payload),
            user_id="u1", session_id="s1", session_number=1,
            season="spring", messages=[{"role": "user", "content": "hi"}],
        ))
        assert len(moments) == 1
        assert moments[0]["narrative"].startswith("I noticed")

    def test_strips_code_fences(self):
        payload = "```json\n[]\n```"
        moments = asyncio.run(reflect_messages(
            FakeVoice(payload),
            user_id="u1", session_id="s1", session_number=1,
            season="spring", messages=[{"role": "user", "content": "hi"}],
        ))
        assert moments == []

    def test_garbage_is_empty(self):
        moments = asyncio.run(reflect_messages(
            FakeVoice("not json at all"),
            user_id="u1", session_id="s1", session_number=1,
            season="spring", messages=[{"role": "user", "content": "hi"}],
        ))
        assert moments == []


class TestServiceTrigger:
    def test_ingest_trigger_forms_and_floors(self):
        db = FakeDB()
        cache = FakeCache()
        service = MemoryFormationService(
            interval=3600,
            db_provider=lambda: db,
            cache_provider=lambda: cache,
        )
        item = asyncio.run(service.ingest_trigger(
            user_id="u1",
            narrative="Remember: Tuesday meeting with the engineers at 10.",
            kind="user_request",
            season="spring",
        ))
        assert item is not None
        assert item["importance_score"] >= TRIGGER_RETENTION_FLOOR
        assert item["formation_source"] == "user_request"
        # Formed straight to long-term with the promotion log.
        assert sum(1 for sql, _ in db.executes if "lina_memory_items" in sql) == 1
        assert sum(1 for sql, _ in db.executes if "lina_promotion_log" in sql) == 1

    def test_blank_trigger_is_noop(self):
        db = FakeDB()
        service = MemoryFormationService(
            interval=3600,
            db_provider=lambda: db,
            cache_provider=lambda: FakeCache(),
        )
        item = asyncio.run(service.ingest_trigger(
            user_id="u1", narrative="   ", kind="user_request",
        ))
        assert item is None
        assert db.executes == []

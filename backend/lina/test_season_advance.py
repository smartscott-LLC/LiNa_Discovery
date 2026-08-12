"""Season advancement wiring test — fake asyncpg layer, no live DB needed."""
import asyncio
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from lina_service import LINACore, SEASON_ADVANCE_VOICE
from typing import Any, cast

# ---------------------------------------------------------------------------
# Fake asyncpg pool
# ---------------------------------------------------------------------------

class FakeTransaction:
    def __init__(self, db):
        self.db = db
    async def __aenter__(self):
        self.db.transactions += 1
        return self
    async def __aexit__(self, *exc):
        return False

class FakeDB:
    def __init__(self, season="spring", sessions=10, evals=60, aligned=54,
                 identity_memories=3, winter=False, actions=None):
        self.season = "winter" if winter else season
        self.sessions = sessions
        self.evals = evals
        self.aligned = aligned
        self.identity_memories = identity_memories
        self.actions = actions or {}   # status -> count
        self.executed = []
        self.transactions = 0
        # current constraint row (spring defaults, as stored by the DB)
        self.constraints_row = {
            "harmony_min": 0.35, "dominance_max": 0.45,
            "order_min": 0.45, "chaos_max": 0.25,
            "integrity_min": 0.65, "deception_max": 0.15,
            "flourishing_min": 0.45, "decline_max": 0.25,
            "relationships_min": 0.55, "isolation_max": 0.35,
            "boundaries_min": 0.55, "intrusion_max": 0.25,
            "grace_min": 0.35, "rigidity_max": 0.45,
            "season": self.season,
        }

    async def fetchrow(self, query, *args):
        if "current_season, sessions_completed" in query or "FOR UPDATE" in query:
            return {
                "current_season": self.season,
                "sessions_completed": self.sessions,
                "identity_moments_count": self.identity_memories,
            }
        if "harmony_min" in query and "is_current = TRUE" in query:
            return dict(self.constraints_row)
        return None

    async def fetch(self, query, *args):
        if "lina_actions" in query:
            return [{"status": s, "n": c} for s, c in self.actions.items()]
        if "is_aligned" in query:
            return [
                {"is_aligned": i < self.aligned}
                for i in range(self.evals)
            ][: args[1]] if len(args) > 1 else []
        return []

    async def fetchval(self, query, *args):
        if "COUNT(*)" in query:
            return self.evals
        return None

    async def execute(self, query, *args):
        self.executed.append((query.split()[0], args[1] if len(args) > 1 else None))
        return "UPDATE 1"

    def transaction(self):
        return FakeTransaction(self)


class FakeCache:
    async def scan_iter(self, *a, **k):
        return []
    async def mget(self, *a, **k):
        return []
    async def get_messages(self, sid):
        return []
    async def clear(self, sid):
        return None
    async def save_pending(self, *a):
        return "k"
    async def list_pending(self, uid):
        return []


def make_core(db):
    core = LINACore(db, cast(Any, FakeCache()), None)
    return core


async def path_winter_final():
    db = FakeDB(winter=True)
    core = make_core(db)
    r = await core.advance_season_if_ready("w")
    assert r["advanced"] is False and "final season" in r["reasons"][0]
    assert db.transactions == 0 and not db.executed, "winter must not write"


def test_winter_final():
    asyncio.run(path_winter_final())


async def path_not_ready():
    db = FakeDB(season="spring", sessions=3, evals=18, aligned=17, identity_memories=0)
    core = make_core(db)
    r = await core.advance_season_if_ready("s")
    assert r["advanced"] is False and len(r["reasons"]) >= 3, r["reasons"]
    assert db.transactions == 0 and not db.executed, "not-ready must not write"


def test_not_ready():
    asyncio.run(path_not_ready())


async def path_ready_advance():
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54, identity_memories=3)
    core = make_core(db)
    r = await core.advance_season_if_ready("r", session_number=11)
    assert r["advanced"] is True and r["season"] == "summer", r
    assert r["previous_season"] == "spring"
    assert r["description"] == SEASON_ADVANCE_VOICE["summer"]
    assert r["polytope_before"][1] == 0.45, "spring dominance_max before"
    assert r["polytope_after"][1] == 0.52, "summer dominance_max after"
    # writes: retire, insert constraints, identity update, seasonal log
    kinds = [q for q, _ in db.executed]
    assert kinds[0] == "UPDATE", "retire old constraints"
    assert kinds[1] == "INSERT", "insert new constraints"
    assert "UPDATE" in kinds and kinds.count("INSERT") == 2, "identity + audit log"
    assert db.transactions == 1
    # engine cache invalidated: re-requesting the engine rebuilds (no crash)
    assert core._engines == {}, "cache must be invalidated"


def test_ready_advance():
    asyncio.run(path_ready_advance())


async def path_already_advanced():
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54, identity_memories=3)
    core = make_core(db)
    orig_fetchrow = db.fetchrow
    async def fetchrow_after_advance(query, *args):
        if "FOR UPDATE" in query:
            return {"current_season": "summer"}  # another request already advanced
        return await orig_fetchrow(query, *args)
    db.fetchrow = fetchrow_after_advance
    r = await core.advance_season_if_ready("c", session_number=1)
    assert r["advanced"] is True and r["reasons"] == ["Season already advanced."]
    assert db.executed == [], "no writes when already advanced"


def test_already_advanced():
    asyncio.run(path_already_advanced())


async def path_no_data():
    db = FakeDB(season="summer", sessions=2, evals=0, aligned=0, identity_memories=0)
    core = make_core(db)
    r = await core.advance_season_if_ready("n")
    assert r["advanced"] is False
    assert any("evaluations" in x for x in r["reasons"]), r["reasons"]


def test_no_data():
    asyncio.run(path_no_data())


async def path_approved_actions_advance():
    # 4 executed + 1 rejected → approval rate 0.8, resolved 5 ≥ 3 — with the
    # in-loop criteria met, her real-world judgment earns the advancement.
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54,
                identity_memories=3,
                actions={"executed": 4, "rejected": 1})
    core = make_core(db)
    r = await core.advance_season_if_ready("a", session_number=11)
    assert r["advanced"] is True and r["season"] == "summer", r


def test_approved_actions_advance():
    asyncio.run(path_approved_actions_advance())


async def path_declined_actions_block():
    # 2 executed + 4 rejected → rate 0.33 — her real-world judgment is not
    # conducive to the agenda; advancement is held.
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54,
                identity_memories=3,
                actions={"executed": 2, "rejected": 4})
    core = make_core(db)
    r = await core.advance_season_if_ready("d", session_number=11)
    assert r["advanced"] is False
    assert any("approval rate" in x for x in r["reasons"]), r["reasons"]
    assert db.transactions == 0 and not db.executed, "blocked must not write"


def test_declined_actions_block():
    asyncio.run(path_declined_actions_block())


async def path_no_actions_is_neutral():
    # No resolved actions yet — the criterion is neutral (grace), not a gate.
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54,
                identity_memories=3, actions={})
    core = make_core(db)
    r = await core.advance_season_if_ready("n", session_number=11)
    assert r["advanced"] is True, r


def test_no_actions_is_neutral():
    asyncio.run(path_no_actions_is_neutral())


async def path_below_sample_is_neutral():
    # 2 resolved actions (below the sample of 3), both approved — grace:
    # a tiny sample is not judged either way.
    db = FakeDB(season="spring", sessions=10, evals=60, aligned=54,
                identity_memories=3,
                actions={"executed": 2})
    core = make_core(db)
    r = await core.advance_season_if_ready("b", session_number=11)
    assert r["advanced"] is True, r


def test_below_sample_is_neutral():
    asyncio.run(path_below_sample_is_neutral())


def main():
    for fn in (
        path_winter_final,
        path_not_ready,
        path_ready_advance,
        path_already_advanced,
        path_no_data,
    ):
        asyncio.run(fn())
    print("=" * 60)
    print("ALL SEASON-ADVANCE PATHS PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()

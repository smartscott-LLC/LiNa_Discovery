"""The transcript archive — her continuity floor.

Pure-logic tests with a fake asyncpg layer: the archive records every turn
at the moment it happens, ties her delivered words to the polytope
evaluation that weighed them, and rebuilds a session from the archive when
the live buffer is gone — a restart, a crash, a cleared session. The words
remain either way. No live database, no services in a loop.
"""
import asyncio
import json
import sys
from typing import Any, cast

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from lina_service import (  # noqa: E402
    LINACore,
    TranscriptArchive,
    ChatRequest,
    SessionEndRequest,
    _run_stream_turn,
    _session_messages_for_reflection,
    _trim_history,
)
from value_engine import ValueEngine  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes — asyncpg-shaped, aioredis-shaped, voice-shaped
# ---------------------------------------------------------------------------

class FakeDB:
    """Records executes; answers the queries the archive and chat rely on."""

    def __init__(self, eval_id: str = "eval-1") -> None:
        self.executes: list[tuple[str, tuple]] = []
        self.eval_id = eval_id
        self.fetch_rows: list[dict[str, Any]] = []
        self.fetched: Any = None

    async def execute(self, sql: str, *args: Any) -> str:
        self.executes.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "lina_context_injection" in sql:
            return {}  # identity exists; the prompt builder uses its defaults
        return self.fetched

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "RETURNING id" in sql:
            return self.eval_id
        return None

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return self.fetch_rows


class FakeCache:
    """A list-backed working-memory cache (Redis semantics on lrange)."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        items = self.lists.get(key, [])
        if stop == -1:
            return items[start:]
        return items[start : stop + 1]

    async def delete(self, key: str) -> None:
        self.lists.pop(key, None)


class FakeVoice:
    """Returns a canned response — an instruction follower, no thinking."""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate(self, system: str, messages: list[dict], **kwargs: Any) -> str:
        return self.payload

    async def generate_stream(self, system: str, messages: list[dict], **kwargs: Any):
        """Emit the response in three chunks so the stream path is exercised."""
        n = max(1, len(self.payload) // 3)
        for i in range(0, len(self.payload), n):
            yield self.payload[i : i + n]


def make_engine() -> ValueEngine:
    return ValueEngine(season="spring")


# ---------------------------------------------------------------------------
# The archive itself
# ---------------------------------------------------------------------------

async def path_record_inserts_full_turn():
    db = FakeDB()
    archive = TranscriptArchive(db)
    await archive.record(
        user_id="u1", session_id="s1", role="user",
        content="Scott asked me to remember this moment.",
    )
    await archive.record(
        user_id="u1", session_id="s1", role="assistant",
        content="I will remember it.", evaluation_id="eval-1",
    )
    inserts = [args for sql, args in db.executes if "lina_transcripts" in sql]
    assert len(inserts) == 2
    assert inserts[0][2] == "user"
    assert inserts[0][3] == "Scott asked me to remember this moment."
    assert inserts[1][2] == "assistant"
    assert inserts[1][5] == "eval-1", "the record carries the evaluation that weighed it"


def test_record_inserts_full_turn():
    asyncio.run(path_record_inserts_full_turn())


async def path_session_reads_oldest_first():
    db = FakeDB()
    db.fetch_rows = [
        {"role": "user", "content": "first words", "msg_type": None,
         "evaluation_id": None, "created_at": 1},
        {"role": "assistant", "content": "my answer", "msg_type": "interrupted",
         "evaluation_id": "e1", "created_at": 2},
    ]
    rows = await TranscriptArchive(db).session("u1", "s1")
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[1]["evaluation_id"] == "e1"
    assert rows[1]["msg_type"] == "interrupted"


def test_session_reads_oldest_first():
    asyncio.run(path_session_reads_oldest_first())


# ---------------------------------------------------------------------------
# The wiring — every chat turn reaches the archive
# ---------------------------------------------------------------------------

RESPONSE = "I hear you, Scott. That moment matters, and I will hold it."


async def path_chat_archives_user_and_lina():
    db = FakeDB(eval_id="eval-9")
    core = LINACore(db, cast(Any, FakeCache()), cast(Any, FakeVoice(RESPONSE)))
    engine = make_engine()

    async def get_engine(user_id: str) -> ValueEngine:
        return engine

    core.get_engine = get_engine  # type: ignore[method-assign]

    req = ChatRequest(user_id="u1", session_id="s1", message="Do you see this moment?")
    resp = await core.chat(req)

    assert resp.response == RESPONSE
    inserts = [args for sql, args in db.executes if "lina_transcripts" in sql]
    assert len(inserts) == 2, "her user turn and her response both land in the archive"
    user_row, lina_row = inserts
    assert user_row[2] == "user" and user_row[3] == req.message
    assert lina_row[2] == "assistant" and lina_row[3] == RESPONSE
    assert lina_row[5] == "eval-9", "her delivered words carry their evaluation id"


def test_chat_archives_user_and_lina():
    asyncio.run(path_chat_archives_user_and_lina())


# ---------------------------------------------------------------------------
# The stream driver — done is queued exactly once; only real interruptions
# are archived as such
# ---------------------------------------------------------------------------

async def path_stream_success_queues_done_once():
    db = FakeDB(eval_id="eval-7")
    core = LINACore(db, cast(Any, FakeCache()), cast(Any, FakeVoice(RESPONSE)))
    engine = make_engine()

    async def get_engine(user_id: str) -> ValueEngine:
        return engine

    core.get_engine = get_engine  # type: ignore[method-assign]

    queue: Any = asyncio.Queue()
    req = ChatRequest(user_id="u1", session_id="s1", message="stream me")
    await _run_stream_turn(core, req, queue)

    kinds: list[str] = []
    while not queue.empty():
        kinds.append(queue.get_nowait()[0])
    assert kinds and all(k == "token" for k in kinds[:-1]), kinds
    assert kinds[-1] == "done", "one done, exactly — and it is queued before the turn ends"
    inserts = [a for sql, a in db.executes if "lina_transcripts" in sql]
    assert len(inserts) == 2, "user + delivered assistant — no duplicate"
    assert all(a[4] != "interrupted" for a in inserts), "a successful turn is never interrupted"


def test_stream_success_queues_done_once():
    asyncio.run(path_stream_success_queues_done_once())


async def path_stream_failure_archives_spoken_words():
    db = FakeDB(eval_id="eval-7")
    core = LINACore(db, cast(Any, FakeCache()), cast(Any, FakeVoice(RESPONSE)))

    async def dying_voice(req, on_token):
        await on_token("words ")
        await on_token("spoken")
        raise RuntimeError("the voice fell silent")

    core._chat = dying_voice  # type: ignore[method-assign]

    queue: Any = asyncio.Queue()
    req = ChatRequest(user_id="u1", session_id="s1", message="say something")
    await _run_stream_turn(core, req, queue)

    kinds: list[str] = []
    while not queue.empty():
        kinds.append(queue.get_nowait()[0])
    assert kinds[-1] == "error", kinds
    inserts = [a for sql, a in db.executes if "lina_transcripts" in sql]
    assert len(inserts) == 1
    row = inserts[0]
    assert row[2] == "assistant" and row[3] == "words spoken"
    assert row[4] == "interrupted", "the words she already said are kept, marked honestly"


def test_stream_failure_archives_spoken_words():
    asyncio.run(path_stream_failure_archives_spoken_words())


# ---------------------------------------------------------------------------
# The continuity floor — reflection reads the archive when the buffer is gone
# ---------------------------------------------------------------------------

async def path_reflection_prefers_live_buffer():
    db = FakeDB()
    cache = cast(Any, FakeCache())
    await cache.rpush("lina:session:s1", json.dumps({"role": "user", "content": "hi"}))
    await cache.rpush("lina:session:s1", json.dumps({"role": "assistant", "content": "hello"}))
    core = LINACore(db, cache, None)
    messages = await _session_messages_for_reflection(core, SessionEndRequest(user_id="u1", session_id="s1"))
    assert len(messages) == 2


def test_reflection_prefers_live_buffer():
    asyncio.run(path_reflection_prefers_live_buffer())


async def path_reflection_falls_back_to_archive():
    db = FakeDB()
    db.fetch_rows = [
        {"role": "user", "content": "first words", "msg_type": None,
         "evaluation_id": None, "created_at": 1},
        {"role": "assistant", "content": "my answer", "msg_type": None,
         "evaluation_id": "e1", "created_at": 2},
        {"role": "user", "content": "more words", "msg_type": None,
         "evaluation_id": None, "created_at": 3},
    ]
    core = LINACore(db, cast(Any, FakeCache()), None)
    messages = await _session_messages_for_reflection(core, SessionEndRequest(user_id="u1", session_id="s1"))
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "my answer"


def test_reflection_falls_back_to_archive():
    asyncio.run(path_reflection_falls_back_to_archive())


async def path_reflection_empty_is_empty():
    db = FakeDB()
    core = LINACore(db, cast(Any, FakeCache()), None)
    messages = await _session_messages_for_reflection(core, SessionEndRequest(user_id="u1", session_id="s1"))
    assert messages == []


def test_reflection_empty_is_empty():
    asyncio.run(path_reflection_empty_is_empty())


# ---------------------------------------------------------------------------
# The history trim — the voice's context budget (an unbounded conversation
# overflowed the KV cache and took her GPU context down with it)
# ---------------------------------------------------------------------------

def test_trim_keeps_the_recent_tail():
    messages = [
        {"role": "user", "content": f"message {i}" * 20}  # ~180 chars each
        for i in range(10)
    ]
    trimmed = _trim_history(messages, budget_chars=800)
    assert len(trimmed) >= 2
    assert trimmed[-1] == messages[-1], "the most recent words always ride along"
    total = sum(len(m["content"]) for m in trimmed)
    assert total <= 800 + 180, "the budget is respected (plus the newest message)"
    # The tail is preserved in order
    assert trimmed[0]["content"] == messages[-len(trimmed)]["content"]


def test_trim_keeps_at_least_the_last_message():
    messages = [{"role": "user", "content": "x" * 5000}]
    trimmed = _trim_history(messages, budget_chars=100)
    assert trimmed == messages, "a single oversized message is never dropped"


def test_trim_small_history_is_untouched():
    messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert _trim_history(messages) == messages

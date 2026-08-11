"""Full-loop integration test: LINA (Python) → TX → Triton (Rust) → RX → LINA.

The chambers are pure-Python stdlib mmap; Triton attaches to the same files
with memmap3. Also covers the chat() component-foresight merge and the
unresponsive-Triton timeout path.
"""
import asyncio
import os
import subprocess
import sys
import time
from typing import Any, cast

# Short foresight window so the timeout test is fast (read at import time).
os.environ.setdefault("LINA_FORESIGHT_TIMEOUT_SECONDS", "0.3")

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import ipc  # noqa: E402 — the pure-Python chamber bridge (no PyO3)

TRITON_BIN = "/home/server/LiNa_Discovery/backend/triton/target/release/triton"

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "OK"))
    except Exception as e:
        results.append((name, f"FAIL: {type(e).__name__}: {e}"))
        import traceback

        traceback.print_exc()


# ---------------------------------------------------------------------------
# Full loop: chambers ⇄ triton binary
# ---------------------------------------------------------------------------

def test_full_loop_binary():
    proc = subprocess.Popen(
        [TRITON_BIN], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        b = ipc.IPCBridge()
        b.reset()
        time.sleep(1.0)  # triton retries attach every 200ms

        query = "hello triton — component foresight check".encode()
        b.push_tx(query)

        echo = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            raw = b.pop_rx()
            if raw is not None:
                echo = raw
                break
            time.sleep(0.02)
        assert echo == query, f"echo mismatch: {echo!r}"

        st = b.status()
        assert st["rx_available_bytes"] == 0, "RX drained"
        time.sleep(0.3)  # let triton finish logging
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=5)

    print(out)
    assert "attached to shared memory" in out
    assert "received" in out and query.decode() in out
    assert "pre-broadcast to 2 spokes" in out, "spoke broadcast missing"
    assert "delivery gate opened" in out, "RX pre-population missing"
    assert "missed acks" not in out


# ---------------------------------------------------------------------------
# chat() integration — with and without a responsive Triton
# ---------------------------------------------------------------------------

class FakeVoice:
    """A provider-agnostic fake: LINA's voice contract is `generate()`."""
    def __init__(self, delay=0.4, fail=False):
        self.delay = delay
        self.calls = 0
        self.fail = fail
    async def generate(self, system, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("all instruments broken")
        await asyncio.sleep(self.delay)
        return "That is a fair way to see it, and I want to understand it better."


class FakeDB:
    async def fetchrow(self, query, *args):
        if "lina_context_injection" in query:
            return {
                "current_season": "spring",
                "relationship_depth": "new",
                "self_description": "I am LINA.",
                "current_curiosities": None,
                "current_concerns": None,
                "relationship_description": None,
                "recent_episodic": None,
                "key_semantic": None,
                "identity_memories": None,
            }
        return None  # constraints / sessions rows → defaults
    async def fetch(self, *a, **k):
        return []
    async def fetchval(self, *a, **k):
        return None
    async def execute(self, *a, **k):
        return "INSERT 0 1"


class FakeCache:
    def __init__(self):
        self.appended = []
        self.pending = []
    async def get_messages(self, sid):
        return []
    async def lrange(self, key, start, end):
        return []
    async def rpush(self, key, entry):
        self.appended.append((key, entry))
    async def append(self, session_id, role, content):
        self.appended.append((role, content))
    async def clear(self, sid):
        pass
    async def save_pending(self, user_id, pending):
        self.pending.append(pending)
        return "k"
    async def list_pending(self, user_id):
        return self.pending
    async def scan_iter(self, *a, **k):
        return []
    async def mget(self, *a, **k):
        return []


def bridge_stub():
    """A minimal bridge-service stand-in: publishes an allocated bridge."""
    return cast(Any, type("S", (), {"bridge": ipc.IPCBridge()})())


def run_chat(core, message, session_id="s1"):
    from lina_service import ChatRequest
    req = ChatRequest(user_id="u1", session_id=session_id, message=message)
    return asyncio.run(core.chat(req))


def test_chat_with_responsive_triton():
    from lina_service import LINACore

    proc = subprocess.Popen(
        [TRITON_BIN], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        time.sleep(0.8)  # triton attaches (files may not exist yet — retries)
        cache = FakeCache()
        voice = FakeVoice(delay=0.4)
        core = LINACore(
            cast(Any, FakeDB()), cast(Any, cache), cast(Any, voice), bridge_stub()
        )
        assert core.ipc is not None and core.ipc.available()

        resp = run_chat(core, "Please help me think through this carefully together.")
        assert resp.evaluation["foresight_context"] == (
            "Please help me think through this carefully together."
        ), "foresight context must be merged from RX"
        assert any("foresight" in content for _, content in cache.appended), (
            "foresight note must be stored for the next turn"
        )
        assert voice.calls == 1, "voice must be called exactly once"
        results.append(("chat + responsive triton", f"OK (foresight merged, {resp.evaluation['alignment_score']:.2f} aligned)"))
    finally:
        proc.terminate()
        proc.communicate(timeout=5)


def test_chat_without_triton():
    from lina_service import LINACore

    core = LINACore(
        cast(Any, FakeDB()), cast(Any, FakeCache()),
        cast(Any, FakeVoice(delay=0.1)), bridge_stub(),
    )
    # Bridge exists but nobody consumes — must time out and continue.
    start = time.monotonic()
    resp = run_chat(core, "Hello, are you there?")
    elapsed = time.monotonic() - start
    assert "foresight_context" not in resp.evaluation, "no context expected"
    assert elapsed < 3.0, f"must not block long — took {elapsed:.1f}s"
    results.append(("chat + no triton", f"OK (timed out in {elapsed:.2f}s, continued)"))
    # TX push should have left the query in the TX ring (nobody consumed it)
    if core.ipc is not None:
        assert core.ipc.status()["tx_available_bytes"] > 0
        results.append(("tx queue retained", "OK"))


def test_chat_voice_failure_degrades_to_503():
    from fastapi import HTTPException
    from lina_service import ChatRequest, LINACore

    from providers import VoicePool

    # A pool whose only provider fails → VoicePoolError → 503, no crash.
    class BrokenProvider:
        name = "broken"
        label = "broken"
        async def generate(self, system, messages, **kwargs):
            raise RuntimeError("boom")
        async def aclose(self):
            pass

    pool = VoicePool(cast(Any, [BrokenProvider()]))
    core = LINACore(cast(Any, FakeDB()), cast(Any, FakeCache()), cast(Any, pool))
    req = ChatRequest(user_id="u1", session_id="s1", message="test")
    try:
        asyncio.run(core.chat(req))
        raise AssertionError("expected 503")
    except HTTPException as e:
        assert e.status_code == 503
        assert "no voice" in e.detail
    results.append(("chat + voice failure", "OK (503, graceful)"))


def test_chat_without_bridge():
    from lina_service import LINACore

    # No bridge service published (standalone / tests) — the loop-less case.
    # LINACore tolerates the absence; chat continues without chambers.
    core = LINACore(
        cast(Any, FakeDB()), cast(Any, FakeCache()), cast(Any, FakeVoice(delay=0.1))
    )
    assert core.ipc is None
    resp = run_chat(core, "Bridge is gone — still alive?")
    assert resp.evaluation["is_aligned"] in (True, False)
    results.append(("chat + no bridge", "OK (continues without chambers)"))


if __name__ == "__main__":
    check("full loop (chambers ⇄ triton)", test_full_loop_binary)
    check("chat + responsive triton", test_chat_with_responsive_triton)
    check("chat + no triton (timeout)", test_chat_without_triton)
    check("chat + voice failure (503)", test_chat_voice_failure_degrades_to_503)
    check("chat + no bridge (fallback)", test_chat_without_bridge)

    print("=" * 60)
    ok = True
    for name, status in results:
        print(f"[{status}] {name}")
        if not status.startswith("OK"):
            ok = False

    print("=" * 60)
    if ok:
        print("ALL FULL-LOOP TESTS PASS")
    else:
        print("FAILURES PRESENT")
        sys.exit(1)

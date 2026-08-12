"""Tool layer tests — LINA's hands and eyes.

Covers the intent parser, the executors (file_list / file_search / browser),
the heart-brain-body pipeline (winter autonomy, standing grants, counsel),
and the reflection parser's honesty (empty and prose-wrapped reports).
No database, no real browser — stubs and temp directories throughout.
"""
import asyncio
import os
import sys
import tempfile

os.environ["LINA_FORESIGHT_TIMEOUT_SECONDS"] = "0.3"
sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")


import mps  # noqa: E402
from tools import (  # noqa: E402
    execute_action_kind,
    parse_tool_intents,
    process_tool_intents,
)


def _run(coro):
    return asyncio.run(coro)


# ── intent parsing — reading her words ───────────────────────────────────────

def test_parse_tool_intents_single_block():
    text = (
        "I will take a look around.\n\n"
        "```tool\n{\"tool\": \"file_list\", \"args\": {\"path\": \".\"}}\n```\n\n"
        "There it is."
    )
    intents = parse_tool_intents(text)
    assert len(intents) == 1
    assert intents[0]["tool"] == "file_list"
    assert intents[0]["args"] == {"path": "."}


def test_parse_tool_intents_multiple_blocks():
    text = (
        "```tool\n{\"tool\": \"file_write\", \"args\": {\"path\": \"a.txt\", \"content\": \"hi\"}}\n```\n"
        "```tool\n{\"tool\": \"file_list\", \"args\": {}}\n```"
    )
    intents = parse_tool_intents(text)
    assert [i["tool"] for i in intents] == ["file_write", "file_list"]


def test_parse_tool_intents_skips_bad_blocks():
    text = (
        "```tool\nnot json at all\n```\n"
        "```tool\n{\"tool\": \"no_such_tool\", \"args\": {}}\n```\n"
        "```tool\n[1, 2, 3]\n```\n"
        "```tool\n{\"tool\": \"command\", \"args\": \"not an object\"}\n```"
    )
    assert parse_tool_intents(text) == []


def test_parse_tool_intents_no_blocks():
    assert parse_tool_intents("just talking, no tools") == []
    assert parse_tool_intents("") == []
    assert parse_tool_intents(None) == []


# ── file_list ─────────────────────────────────────────────────────────────────

def test_file_list_shows_dirs_and_files():
    with tempfile.TemporaryDirectory() as ws:
        os.makedirs(os.path.join(ws, "notes"))
        with open(os.path.join(ws, "hello.txt"), "w") as fh:
            fh.write("x" * 2048)
        res = _run(execute_action_kind("file_list", {"path": "."}, [ws]))
        assert res["ok"] is True
        assert "DIRS (1): notes" in res["output"]
        assert "hello.txt" in res["output"]
        assert "2.0 KB" in res["output"]


def test_file_list_rejects_escape():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind("file_list", {"path": "/etc"}, [ws]))
        assert res["ok"] is False
        assert "outside" in res["output"] or "escape" in res["output"]


# ── file_search ──────────────────────────────────────────────────────────────

def test_file_search_finds_content():
    with tempfile.TemporaryDirectory() as ws:
        with open(os.path.join(ws, "one.txt"), "w") as fh:
            fh.write("the polytope is her heart\n")
        with open(os.path.join(ws, "two.txt"), "w") as fh:
            fh.write("nothing to see here\n")
        res = _run(execute_action_kind("file_search", {"pattern": "polytope"}, [ws]))
        assert res["ok"] is True
        assert "one.txt:1:" in res["output"]
        assert "two.txt" not in res["output"]


def test_file_search_no_matches():
    with tempfile.TemporaryDirectory() as ws:
        with open(os.path.join(ws, "one.txt"), "w") as fh:
            fh.write("nothing here\n")
        res = _run(execute_action_kind("file_search", {"pattern": "zzz"}, [ws]))
        assert res["ok"] is True
        assert res["output"] == "no matches"


def test_file_search_bad_pattern():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind("file_search", {"pattern": "("}, [ws]))
        assert res["ok"] is False
        assert "bad pattern" in res["output"]


# ── browser — her eyes ───────────────────────────────────────────────────────

class FakeEyes:
    available = True

    async def navigate(self, url):
        return f"the page at {url}"

    async def extract(self):
        return "the page she is on"

    async def screenshot(self, name, roots):
        target = os.path.join(roots[0], ".lina_eyes", name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as fh:
            fh.write("png")
        return target


def test_browser_closed_eyes_are_honest():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind(
            "browser", {"op": "navigate", "url": "https://example.com"}, [ws], browser=None
        ))
        assert res["ok"] is False
        assert "eyes are not open" in res["output"]


def test_browser_navigate_with_eyes():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind(
            "browser", {"op": "navigate", "url": "https://example.com"}, [ws], browser=FakeEyes()
        ))
        assert res["ok"] is True
        assert "the page at" in res["output"]


def test_browser_rejects_non_http():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind(
            "browser", {"op": "navigate", "url": "file:///etc/passwd"}, [ws], browser=FakeEyes()
        ))
        assert res["ok"] is False
        assert "http" in res["output"]


def test_browser_screenshot_lands_in_workspace():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action_kind(
            "browser", {"op": "screenshot", "name": "view.png"}, [ws], browser=FakeEyes()
        ))
        assert res["ok"] is True
        assert os.path.isfile(os.path.join(ws, ".lina_eyes", "view.png"))


# ── the pipeline — heart, pulse, body, fruit ─────────────────────────────────

class StubStore:
    def __init__(self):
        self.rows = {}

    async def propose(self, user_id, action_type, description, path=None,
                      payload=None, workspace=None):
        import uuid
        aid = str(uuid.uuid4())
        row = {
            "id": aid, "user_id": user_id, "action_type": action_type,
            "description": description, "path": path,
            "payload": payload or {}, "workspace": workspace, "status": "pending",
        }
        self.rows[aid] = row
        return row

    async def claim(self, action_id):
        row = self.rows.get(action_id)
        if row is None or row["status"] != "pending":
            return None
        row["status"] = "approved"
        return row

    async def finalize(self, action_id, ok, output):
        row = self.rows.get(action_id)
        row["status"] = "executed" if ok else "failed"
        row["executed_output"] = output


def test_winter_executes_without_counsel():
    with tempfile.TemporaryDirectory() as ws:
        store = StubStore()
        intents = [{"tool": "file_write", "args": {"path": "notes/hi.txt", "content": "hello"}}]
        results = _run(process_tool_intents(
            intents, user_id="u", session_id="s", season="winter",
            store=store, grants={}, workspace=ws,
        ))
        assert results[0]["status"] == "executed"
        assert results[0]["earned"] is True
        assert os.path.isfile(os.path.join(ws, "notes", "hi.txt"))


def test_standing_grant_executes():
    with tempfile.TemporaryDirectory() as ws:
        store = StubStore()
        intents = [{"tool": "file_write", "args": {"path": "hi.txt", "content": "x"}}]
        results = _run(process_tool_intents(
            intents, user_id="u", session_id="s", season="spring",
            store=store, grants={"file_write": True}, workspace=ws,
        ))
        assert results[0]["status"] == "executed"


def test_no_grant_awaits_counsel():
    with tempfile.TemporaryDirectory() as ws:
        store = StubStore()
        intents = [{"tool": "file_write", "args": {"path": "hi.txt", "content": "x"}}]
        results = _run(process_tool_intents(
            intents, user_id="u", session_id="s", season="spring",
            store=store, grants={}, workspace=ws,
        ))
        assert results[0]["status"] == "awaiting_counsel"
        assert not os.path.exists(os.path.join(ws, "hi.txt"))


def test_unknown_tool_refused():
    store = StubStore()
    results = _run(process_tool_intents(
        [{"tool": "nonsense", "args": {}}], user_id="u", session_id="s",
        season="winter", store=store, grants={},
    ))
    assert results[0]["status"] == "refused"


# ── reflection parser honesty (the memory-recording fix) ─────────────────────

class FakeVoice:
    def __init__(self, response):
        self.response = response

    async def generate(self, **kwargs):
        return self.response


def _reflect(response):
    return _run(mps.reflect_messages(
        FakeVoice(response), user_id="u", session_id="s1",
        session_number=1, season="spring",
        messages=[{"role": "user", "content": "hello"}],
    ))


def test_reflection_empty_report_forms_nothing():
    assert _reflect("") == []
    assert _reflect("   ") == []


def test_reflection_fenced_json():
    out = _reflect('```json\n[{"narrative": "a moment", "emotional_marker": "care"}]\n```')
    assert len(out) == 1
    assert out[0]["narrative"] == "a moment"


def test_reflection_prose_wrapped_json():
    out = _reflect('Here is what stood out: [{"narrative": "a moment", "emotional_marker": "care"}] — that is all.')
    assert len(out) == 1
    assert out[0]["narrative"] == "a moment"


def test_reflection_not_json_fails_honestly():
    assert _reflect("I did not find anything worth remembering.") == []

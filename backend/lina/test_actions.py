"""Human-in-the-loop action ledger tests.

Covers the pure logic (path resolution, execution, proposal validation) and
the API surface (propose/pending/approve/reject/modify) via an in-memory
stub store — no database required.
"""
import asyncio
import os
import sys
import tempfile
from typing import Any

os.environ["LINA_FORESIGHT_TIMEOUT_SECONDS"] = "0.3"
sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import actions  # noqa: E402
import lina_service  # noqa: E402
from actions import ActionError, ActionStore, execute_action, resolve_action_path  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── path resolution ──────────────────────────────────────────────────────────

def test_resolve_action_path_relative():
    with tempfile.TemporaryDirectory() as ws:
        target = resolve_action_path("sub/dir/file.txt", [ws])
        assert target == os.path.join(os.path.realpath(ws), "sub", "dir", "file.txt")


def test_resolve_action_path_absolute_inside_root():
    with tempfile.TemporaryDirectory() as ws:
        inside = os.path.join(ws, "notes", "a.txt")
        assert resolve_action_path(inside, [ws]) == os.path.realpath(inside)


def test_resolve_action_path_absolute_outside_roots():
    with tempfile.TemporaryDirectory() as ws, pytest.raises(ActionError):
        resolve_action_path("/etc/passwd", [ws])


def test_resolve_action_path_multi_root():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        # An absolute path inside a secondary root is allowed.
        target = resolve_action_path(os.path.join(b, "x.txt"), [a, b])
        assert target == os.path.join(os.path.realpath(b), "x.txt")
        # A path outside all roots is not.
        with pytest.raises(ActionError):
            resolve_action_path("/etc/passwd", [a, b])


def test_resolve_action_path_rejects_traversal():
    with tempfile.TemporaryDirectory() as ws:
        for bad in ("../escape.txt", "a/../../escape.txt", "\\win\\path", ""):
            with pytest.raises(ActionError):
                resolve_action_path(bad, [ws])


# ── execution ────────────────────────────────────────────────────────────────

def test_execute_file_write_then_read():
    with tempfile.TemporaryDirectory() as ws:
        row = {
            "action_type": "file_write",
            "path": "notes/hi.txt",
            "payload": {"content": "hello"},
            "workspace": ws,
        }
        res = _run(execute_action(row))
        assert res["ok"] is True
        assert os.path.isfile(os.path.join(ws, "notes", "hi.txt"))
        read = _run(execute_action(
            {"action_type": "file_read", "path": "notes/hi.txt", "workspace": ws}
        ))
        assert read["ok"] is True and read["output"] == "hello"


def test_execute_file_write_traversal_blocked_at_execution():
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action(
            {"action_type": "file_write", "path": "../../evil.txt", "payload": {}, "workspace": ws}
        ))
        assert res["ok"] is False
        assert "workspace" in res["output"]


def test_execute_command_ok_and_failure():
    with tempfile.TemporaryDirectory() as ws:
        ok = _run(execute_action({"action_type": "command", "payload": {"command": "echo hi"}, "workspace": ws}))
        assert ok["ok"] is True and ok["output"].strip() == "hi"
        bad = _run(execute_action({"action_type": "command", "payload": {"command": "exit 3"}, "workspace": ws}))
        assert bad["ok"] is False


def test_execute_command_timeout(monkeypatch):
    monkeypatch.setattr(actions, "COMMAND_TIMEOUT", 0.2)
    with tempfile.TemporaryDirectory() as ws:
        res = _run(execute_action({"action_type": "command", "payload": {"command": "sleep 5"}, "workspace": ws}))
        assert res["ok"] is False
        assert "timed out" in res["output"]


def test_execute_unknown_type():
    assert _run(execute_action({"action_type": "nope", "workspace": "/tmp"}))["ok"] is False


# ── proposal validation (store level, stub db) ───────────────────────────────

class _StubDB:
    """Minimal asyncpg-shaped fake — matches the Database protocol."""

    def __init__(self):
        self.executed = []

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        self.executed.append((query, args))
        return ""

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]:
        return []

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        return None


def test_propose_validation():
    store = ActionStore(_StubDB())
    with pytest.raises(ActionError):
        asyncio.run(store.propose("u", "unknown_type", "desc"))  # unknown type
    with pytest.raises(ActionError):
        asyncio.run(store.propose("u", "file_write", ""))  # empty description
    with pytest.raises(ActionError):
        asyncio.run(store.propose("u", "file_write", "desc"))  # missing path
    with pytest.raises(ActionError):
        asyncio.run(store.propose("u", "file_write", "desc", path="../../etc/pwned", workspace="/tmp/ws"))  # traversal


def test_propose_valid_reaches_db():
    db = _StubDB()
    store = ActionStore(db)
    action = asyncio.run(store.propose("u", "file_write", "write a note", path="note.txt",
                                       payload={"content": "x"}, workspace="/tmp/ws"))
    assert action["status"] == "pending"
    assert len(db.executed) == 1


# ── API surface (in-memory stub store) ───────────────────────────────────────

class _StubStore:
    """Minimal in-memory ActionStore matching the interface used by endpoints."""

    def __init__(self):
        self.rows = {}
        self.seq = 0

    async def propose(self, user_id, action_type, description, path=None,
                      payload=None, workspace=None):
        if action_type not in actions.KNOWN_TYPES:
            raise ActionError(f"unknown action type: {action_type}")
        if not description.strip():
            raise ActionError("description required")
        if action_type in ("file_read", "file_write") and not path:
            raise ActionError("path required for file actions")
        if path:
            resolve_action_path(path, [workspace or "/workspace"])
        self.seq += 1
        aid = f"act-{self.seq}"
        row = {"id": aid, "user_id": user_id, "action_type": action_type,
               "description": description, "path": path, "payload": payload or {},
               "status": "pending"}
        self.rows[aid] = row
        return row

    async def pending(self, user_id=None, limit=50):
        rows = [r for r in self.rows.values() if r["status"] == "pending"]
        return rows[:limit]

    async def get(self, aid):
        return self.rows.get(aid)

    async def claim(self, aid):
        row = self.rows.get(aid)
        if row and row["status"] == "pending":
            row["status"] = "approved"
            return row
        return None

    async def finalize(self, aid, ok, output):
        row = self.rows.get(aid)
        if row:
            row["status"] = "executed" if ok else "failed"
            row["executed_output"] = output

    async def reject(self, aid, user_id):
        row = self.rows.get(aid)
        if row and row["status"] == "pending":
            row["status"] = "rejected"
            return row
        return None

    async def modify(self, aid, payload):
        row = self.rows.get(aid)
        if row and row["status"] == "pending":
            row["payload"] = payload
            return row
        return None

    async def audit(self, user_id=None, limit=50):
        rows = list(self.rows.values())
        return rows[:limit]

    async def recent(self, limit=10):
        return list(self.rows.values())[:limit]


@pytest.fixture
def client(monkeypatch):
    store = _StubStore()
    monkeypatch.setattr(lina_service, "_action_store", store)
    return TestClient(lina_service.app)


def test_propose_endpoint_ok(client):
    r = client.post("/lina/actions/propose", json={
        "user_id": "t", "action_type": "file_write",
        "description": "write", "path": "a.txt", "payload": {"content": "x"},
    })
    assert r.status_code == 200
    assert r.json()["status"] == "proposed"


def test_propose_endpoint_rejects_traversal(client):
    r = client.post("/lina/actions/propose", json={
        "user_id": "t", "action_type": "file_write",
        "description": "escape", "path": "../../etc/pwned", "payload": {},
    })
    assert r.status_code == 400


def test_pending_and_approve_flow(client):
    p = client.post("/lina/actions/propose", json={
        "user_id": "t", "action_type": "file_write",
        "description": "write", "path": "a.txt", "payload": {"content": "x"},
    }).json()["action"]
    pend = client.get("/lina/actions/pending?user_id=t").json()["pending"]
    assert [a["id"] for a in pend] == [p["id"]]
    appr = client.post(f"/lina/actions/{p['id']}/approve", json={"user_id": "t"})
    assert appr.status_code == 200
    # Double-approve is idempotent-safe: second claim returns None → reported as already done.
    assert client.post(f"/lina/actions/{p['id']}/approve", json={"user_id": "t"}).status_code == 200
    assert client.get("/lina/actions/pending?user_id=t").json()["pending"] == []


def test_reject_flow(client):
    p = client.post("/lina/actions/propose", json={
        "user_id": "t", "action_type": "command",
        "description": "run", "payload": {"command": "echo hi"},
    }).json()["action"]
    r = client.post(f"/lina/actions/{p['id']}/reject", json={"user_id": "t"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # Rejecting twice → 404 (no longer pending).
    assert client.post(f"/lina/actions/{p['id']}/reject", json={"user_id": "t"}).status_code == 404


def test_actions_uninitialized_returns_503(monkeypatch):
    monkeypatch.setattr(lina_service, "_action_store", None)
    client = TestClient(lina_service.app)
    assert client.get("/lina/actions/pending").status_code == 503
    assert client.post("/lina/actions/propose", json={
        "user_id": "t", "action_type": "command", "description": "x", "payload": {},
    }).status_code == 503

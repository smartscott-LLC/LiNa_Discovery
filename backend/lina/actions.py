"""Human-in-the-loop actions — the boundary where LINA's agency meets consent.

LINA proposes. You approve, reject, or modify. Everything is audited in
`lina_actions`. Nothing touches the filesystem or runs a command without an
approved row — and approvals are claimed atomically, so a proposal can only
be executed once.

Access model (the OPFS correction — this is how she reaches your real disk):
  - The workspace is the default root (``WORKSPACE_PATH``).
  - ``LINA_ACCESS_ROOTS`` (colon-separated absolute directories) expands the
    roots she may touch — e.g. ``/home/server/lina:/home/server/Documents``.
    An absolute path in a proposal must land inside one of these roots;
    relative paths resolve against the workspace.
  - Every root is still behind the human-in-the-loop ledger. The polytope
    defines what is safe; consent decides what happens.

Path safety: resolution happens at proposal time (a traversal path never
enters the ledger) AND at execution time (defense in depth). Commands run
with a timeout and captured output, never a shell login session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger("lina.actions")

#: Default command timeout (seconds).
COMMAND_TIMEOUT = float(os.getenv("LINA_COMMAND_TIMEOUT", "15"))
#: Maximum characters of execution output kept on the action row.
MAX_OUTPUT = 2000

#: Action types that exist today.
KNOWN_TYPES = {"file_read", "file_write", "command", "tool", "opfs_read", "opfs_write"}


class ActionError(Exception):
    """A proposal was malformed or execution was refused."""


def configured_roots() -> list[str]:
    """Realpath'd access roots from LINA_ACCESS_ROOTS (colon-separated).

    Defaults to WORKSPACE_PATH. The service may expand this with additional
    directories she is allowed to reach — always behind approval.
    """
    raw = os.getenv("LINA_ACCESS_ROOTS", "")
    roots = [p for p in raw.split(":") if p.strip()]
    if not roots:
        roots = [os.getenv("WORKSPACE_PATH", "/workspace")]
    return [os.path.realpath(p) for p in roots]


def resolve_action_path(path: str | None, roots: Sequence[str] | None = None) -> str:
    """Resolve `path` inside the allowed roots, rejecting traversal/escape.

    - Absolute paths must land inside one of the allowed roots.
    - Relative paths resolve against the first root and may not contain
      ``..`` components.
    Returns the realpath'd target. Raises ActionError on any escape.
    """
    root_list = [os.path.realpath(r) for r in (roots or configured_roots())]
    if not root_list:
        raise ActionError("no access roots configured")
    if not path or not path.strip():
        raise ActionError("path required")
    if path.startswith(("/", "\\")):
        target = os.path.realpath(path)
        for root in root_list:
            if target == root or target.startswith(root + os.sep):
                return target
        raise ActionError("absolute path is outside every allowed access root")
    if "\\" in path or ".." in path.split(os.sep):
        raise ActionError("path must be relative to the workspace")
    root = root_list[0]
    target = os.path.realpath(os.path.join(root, path))
    if target != root and not target.startswith(root + os.sep):
        raise ActionError("path escapes the workspace")
    return target


def _read_file(target: str, limit: int = MAX_OUTPUT) -> str:
    with open(target, encoding="utf-8", errors="replace") as fh:
        return fh.read(limit)


def _write_file(target: str, content: str) -> int:
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        return fh.write(content)


async def execute_action(row: dict[str, Any]) -> dict[str, Any]:
    """Execute an approved action row. Returns {"ok", "output"} — never raises."""
    kind = row.get("action_type", "")
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    workspace = row.get("workspace") or ""
    roots: list[str] = [workspace] if workspace else []
    for root in configured_roots():
        if root not in roots:
            roots.append(root)
    try:
        if kind == "file_read":
            target = resolve_action_path(row.get("path"), roots)
            if not os.path.isfile(target):
                raise ActionError("not a file")
            return {"ok": True, "output": await asyncio.to_thread(_read_file, target)}

        if kind == "file_write":
            target = resolve_action_path(row.get("path"), roots)
            content = payload.get("content", "")
            written = await asyncio.to_thread(_write_file, target, content)
            return {"ok": True, "output": f"wrote {written} bytes to {row['path']}"}

        if kind == "command":
            command = payload.get("command", "")
            if not command.strip():
                raise ActionError("empty command")
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=roots[0],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=COMMAND_TIMEOUT)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ActionError(f"command timed out after {COMMAND_TIMEOUT}s") from None
            text = (out or b"").decode(errors="replace")
            return {"ok": proc.returncode == 0, "output": text[:MAX_OUTPUT]}

        if kind == "tool":
            return {
                "ok": True,
                "output": f"tool action acknowledged (execution arrives with the tool layer): {payload}",
            }

        if kind in ("opfs_read", "opfs_write"):
            # OPFS operations execute in the browser's sandbox; this record is
            # the audit trail entry. Nothing to run here.
            return {"ok": True, "output": "opfs action recorded for audit"}

        return {"ok": False, "output": f"unknown action type: {kind}"}
    except ActionError as exc:
        return {"ok": False, "output": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("[actions] execution error for %s: %s", kind, exc)
        return {"ok": False, "output": f"execution error: {exc}"}


class Database(Protocol):
    """The asyncpg subset ActionStore needs — structurally typed so tests
    can inject fakes without pulling in a live pool."""

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str: ...
    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> Any: ...


class ActionStore:
    """Async PostgreSQL access for the action ledger."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def propose(
        self,
        user_id: str,
        action_type: str,
        description: str,
        path: str | None = None,
        payload: dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        if action_type not in KNOWN_TYPES:
            raise ActionError(f"unknown action type: {action_type}")
        if not description.strip():
            raise ActionError("description required")
        if action_type in ("file_read", "file_write"):
            if not path:
                raise ActionError("path required for file actions")
            # Validate at proposal time — a traversal path never enters the
            # ledger, let alone the pending queue. Check against the full
            # access-root set (workspace + LINA_ACCESS_ROOTS). (Execution
            # re-validates anyway; this is the early gate.)
            roots = [workspace] if workspace else []
            for root in configured_roots():
                if root not in roots:
                    roots.append(root)
            resolve_action_path(path, roots)

        action_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO lina_actions (
                id, user_id, action_type, description, path, payload, workspace
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            action_id, user_id, action_type, description, path,
            json.dumps(payload or {}), workspace,
        )
        return {
            "id": action_id,
            "user_id": user_id,
            "action_type": action_type,
            "description": description,
            "path": path,
            "payload": payload or {},
            "status": "pending",
        }

    async def pending(self, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if user_id:
            rows = await self.db.fetch(
                """
                SELECT * FROM lina_actions
                WHERE user_id = $1 AND status = 'pending'
                ORDER BY proposed_at DESC LIMIT $2
                """,
                user_id, limit,
            )
        else:
            rows = await self.db.fetch(
                """
                SELECT * FROM lina_actions
                WHERE status = 'pending'
                ORDER BY proposed_at DESC LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def get(self, action_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchrow(
            "SELECT * FROM lina_actions WHERE id = $1", action_id
        )
        return dict(row) if row else None

    async def claim(self, action_id: str) -> dict[str, Any] | None:
        """Atomically move pending → approved; returns the row, or None if it
        was already resolved (double-approval is impossible)."""
        row = await self.db.fetchrow(
            """
            UPDATE lina_actions
            SET status = 'approved', resolved_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            action_id,
        )
        return dict(row) if row else None

    async def finalize(self, action_id: str, ok: bool, output: str) -> None:
        await self.db.execute(
            """
            UPDATE lina_actions
            SET status = $2,
                executed_output = $3,
                error = NULL
            WHERE id = $1
            """,
            action_id, "executed" if ok else "failed", output[:MAX_OUTPUT],
        )

    async def reject(self, action_id: str, user_id: str) -> dict[str, Any] | None:
        """Reject a pending action. Only the proposing user may reject."""
        row = await self.db.fetchrow(
            """
            UPDATE lina_actions
            SET status = 'rejected', resolved_at = NOW()
            WHERE id = $1 AND status = 'pending' AND user_id = $2
            RETURNING *
            """,
            action_id, user_id,
        )
        return dict(row) if row else None

    async def modify(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Replace the payload of a pending action (the modified proposal is
        then executed by the caller via claim())."""
        row = await self.db.fetchrow(
            """
            UPDATE lina_actions
            SET payload = $2
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            action_id, json.dumps(payload or {}),
        )
        return dict(row) if row else None

    async def audit(self, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if user_id:
            rows = await self.db.fetch(
                """
                SELECT id, user_id, action_type, description, path, status,
                       proposed_at, resolved_at, executed_output, error
                FROM lina_actions
                WHERE user_id = $1
                ORDER BY proposed_at DESC LIMIT $2
                """,
                user_id, limit,
            )
        else:
            rows = await self.db.fetch(
                """
                SELECT id, user_id, action_type, description, path, status,
                       proposed_at, resolved_at, executed_output, error
                FROM lina_actions
                ORDER BY proposed_at DESC LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self.audit(limit=limit)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()

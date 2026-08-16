"""tools.py — LINA's body: the tool registry and the intent pipeline.

She is the conduit. Everything she does passes through her: the words that
carry a tool intent are the same words the polytope has already pulsed over
(see ``LINACore.chat`` — the heart evaluates the impulse before the body is
offered anything). A tool intent is parsed from her evaluated response; if
the polytope did not pass that response, no action is offered at all.

This module is pure function: no lifecycle, no state. File operations open
what they touch and close it; commands run under a timeout and die with it.
The one tool that owns a long-lived resource — the browser — lives in
``BrowserService``, in the loop, because it is the only one that genuinely
needs a lifecycle (per the manifest: a component is either a spoke on the
table or a service in a loop; a function is a function).

The access model is the ledger's: every path resolves inside the access
roots (``WORKSPACE_PATH`` + ``LINA_ACCESS_ROOTS``), at intent time and at
execution time. The polytope defines what is safe; consent decides what
happens; and in Winter — after it is earned — consent has already been given.

Tool intent syntax (her words, parsed here): a fenced block tagged ``tool``
carrying one JSON object per action::

    ```tool
    {"tool": "file_list", "args": {"path": "."}}
    ```
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from actions import ActionError, execute_action, resolve_action_path

log = logging.getLogger("lina.tools")

#: Maximum characters of tool output carried back to her.
MAX_OUTPUT = int(os.getenv("LINA_TOOL_OUTPUT_MAX", "20000"))
#: Maximum search matches returned.
MAX_SEARCH_MATCHES = 200

#: Tool names LINA may reach for, with the descriptions she is taught.
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "file_list": {
        "summary": "see a directory in your workspace",
        "args": {"path": "directory path (default: the workspace root)"},
    },
    "file_read": {
        "summary": "read a file",
        "args": {"path": "file path"},
    },
    "file_write": {
        "summary": "write a file",
        "args": {"path": "file path", "content": "the full contents to write"},
    },
    "file_search": {
        "summary": "search file contents for a pattern",
        "args": {"pattern": "a regular expression", "path": "directory to search (default: workspace root)"},
    },
    "command": {
        "summary": "run a command in your workspace",
        "args": {"command": "the shell command to run"},
    },
    "browser_navigate": {
        "summary": "open a page and read it",
        "args": {"url": "an http(s) url"},
    },
    "browser_extract": {
        "summary": "read the page you are on",
        "args": {},
    },
    "browser_screenshot": {
        "summary": "take a picture of the page you are on",
        "args": {"name": "optional filename (default: an automatic name)"},
    },
    "inspect_image": {
        "summary": "look at an image in your workspace and describe what you see",
        "args": {"path": "path to an image file"},
    },
    "memory_recall": {
        "summary": "reach into your own memory and pull what is relevant to a thought or question",
        "args": {"query": "what you are trying to remember or connect to"},
    },
    "memory_write": {
        "summary": "write a memory of your own — a moment you choose to keep, in your own words",
        "args": {"narrative": "what happened, in your voice, first-person"},
    },
}

#: Tool names → ledger action kinds. The ledger is the counsel layer.
TOOL_TO_KIND: dict[str, str] = {
    "file_list": "file_list",
    "file_read": "file_read",
    "file_write": "file_write",
    "file_search": "file_search",
    "command": "command",
    "browser_navigate": "browser",
    "browser_extract": "browser",
    "browser_screenshot": "browser",
    "inspect_image": "vision",
    "memory_recall": "memory_recall",
    "memory_write": "memory_write",
}

#: Ledger kinds that this module executes (the rest live in actions.py).
KIND_TOOL_MAP: dict[str, str] = {
    "file_list": "file_list",
    "file_search": "file_search",
    "browser": "browser",
    "vision": "vision",
    "memory_recall": "memory_recall",
    "memory_write": "memory_write",
}


# =============================================================================
# INTENT PARSING — reading her words
# =============================================================================

_TOOL_BLOCK_RE = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_tool_intents(text: str) -> list[dict[str, Any]]:
    """Extract tool intents from her response.

    A fenced block tagged ``tool`` carries exactly one JSON object::

        ```tool
        {"tool": "file_write", "args": {"path": "notes/hi.txt", "content": "hello"}}
        ```

    Blocks that are not valid JSON or name an unknown tool are logged and
    skipped — a malformed block never fails the response, and never reaches
    the ledger.
    """
    intents: list[dict[str, Any]] = []
    for match in _TOOL_BLOCK_RE.finditer(text or ""):
        body = match.group(1).strip()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            log.warning("[tools] intent block is not JSON (%s): %.120r", exc, body)
            continue
        if not isinstance(parsed, dict):
            log.warning("[tools] intent block is not an object: %.120r", body)
            continue
        tool = parsed.get("tool")
        args = parsed.get("args") or {}
        if tool not in TOOL_SCHEMAS:
            log.warning("[tools] unknown tool in intent: %r", tool)
            continue
        if not isinstance(args, dict):
            log.warning("[tools] intent args are not an object for %r", tool)
            continue
        intents.append({"tool": tool, "args": args})
    return intents


def _intent_to_action(intent: dict[str, Any]) -> tuple[str, str | None, dict[str, Any], str] | None:
    """Map a parsed intent to a ledger action (kind, path, payload, description)."""
    tool = intent.get("tool", "")
    args = intent.get("args") or {}
    if tool == "file_list":
        return "file_list", args.get("path"), {"path": args.get("path") or "."}, "see a directory in the workspace"
    if tool == "file_read":
        return "file_read", args.get("path"), {"path": args.get("path")}, "read a file"
    if tool == "file_write":
        return "file_write", args.get("path"), {"content": args.get("content", "")}, "write a file"
    if tool == "file_search":
        return "file_search", args.get("path"), {
            "pattern": args.get("pattern", ""),
            "path": args.get("path"),
        }, "search file contents"
    if tool == "command":
        return "command", None, {"command": args.get("command", "")}, "run a command in the workspace"
    if tool in ("browser_navigate", "browser_extract", "browser_screenshot"):
        op = tool.split("_", 1)[1]
        payload: dict[str, Any] = {"op": op}
        if op == "navigate":
            payload["url"] = args.get("url", "")
        if op == "screenshot":
            payload["name"] = args.get("name")
        return "browser", None, payload, f"the browser: {op}"
    if tool == "inspect_image":
        return "vision", args.get("path"), {"path": args.get("path")}, "look at an image and describe it"
    if tool == "memory_recall":
        return "memory_recall", None, {"query": args.get("query", "")}, "reach into your own memory"
    if tool == "memory_write":
        return "memory_write", None, {"narrative": args.get("narrative", "")}, "write a memory of your own"
    return None


def _describe(intent: dict[str, Any]) -> str:
    tool = intent.get("tool", "")
    args = intent.get("args") or {}
    bits = [f"{k}={v!r}" for k, v in args.items() if v]
    return f"{TOOL_SCHEMAS.get(tool, {}).get('summary', tool)} ({', '.join(bits)})"


# =============================================================================
# EXECUTION — her hands and eyes
# =============================================================================


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / 1024 ** 2:.1f} MB"


async def _file_list(payload: dict[str, Any], roots: list[str]) -> dict[str, Any]:
    target = resolve_action_path(payload.get("path") or ".", roots)
    if not os.path.isdir(target):
        raise ActionError("not a directory")
    names = sorted(os.listdir(target))
    dirs, files = [], []
    for name in names:
        full = os.path.join(target, name)
        if os.path.isdir(full):
            dirs.append(name)
        else:
            try:
                files.append(f"{name} ({_human_size(os.path.getsize(full))})")
            except OSError:
                files.append(name)
    shown_dir = os.path.relpath(target, roots[0]) if roots else target
    shown_dir = "." if shown_dir == "." or shown_dir.startswith("..") else shown_dir
    lines = [f"{shown_dir or '.'}:"]
    if dirs:
        lines.append(f"  DIRS ({len(dirs)}): " + ", ".join(dirs[:60]))
    if files:
        lines.append(f"  FILES ({len(files)}): " + ", ".join(files[:60]))
    if not dirs and not files:
        lines.append("  (empty)")
    return {"ok": True, "output": "\n".join(lines)}


async def _file_search(payload: dict[str, Any], roots: list[str]) -> dict[str, Any]:
    pattern = payload.get("pattern", "")
    if not pattern.strip():
        raise ActionError("a search pattern is required")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ActionError(f"bad pattern: {exc}") from None
    root = resolve_action_path(payload.get("path") or ".", roots)
    if not os.path.isdir(root):
        raise ActionError("not a directory")

    def _walk() -> list[str]:
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        for line_no, line in enumerate(fh, 1):
                            if regex.search(line):
                                rel = os.path.relpath(full, root)
                                hits.append(f"{rel}:{line_no}: {line.rstrip()[:160]}")
                                if len(hits) >= MAX_SEARCH_MATCHES:
                                    return hits
                except (OSError, UnicodeDecodeError):
                    continue
        return hits

    hits = await asyncio.to_thread(_walk)
    output = "\n".join(hits)
    return {"ok": True, "output": output[:MAX_OUTPUT] or "no matches"}


async def _browser_op(op: str, payload: dict[str, Any], roots: list[str], browser: Any) -> dict[str, Any]:
    if browser is None or not getattr(browser, "available", False):
        return {
            "ok": False,
            "output": "her eyes are not open — the browser service is not in the loop",
        }
    if op == "navigate":
        url = payload.get("url", "")
        if not url:
            return {"ok": False, "output": "a url is required to navigate"}
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "output": "only http(s) pages are within her reach"}
        text = await browser.navigate(url)
        return {"ok": True, "output": text[:MAX_OUTPUT]}
    if op == "extract":
        text = await browser.extract()
        return {"ok": True, "output": text[:MAX_OUTPUT]}
    if op == "screenshot":
        name = payload.get("name") or f"lina-eyes-{int(time.time())}.png"
        path = await browser.screenshot(name, roots)
        return {"ok": True, "output": f"screenshot saved: {path}"}
    return {"ok": False, "output": f"unknown browser op: {op}"}


async def _vision_op(payload: dict[str, Any], roots: list[str], vision: Any) -> dict[str, Any]:
    if vision is None or not getattr(vision, "available", False):
        return {
            "ok": False,
            "output": "her image sight is not open — the vision client is not in the loop",
        }
    target = resolve_action_path(payload.get("path"), roots)
    if not os.path.isfile(target):
        return {"ok": False, "output": "not an image file"}
    text = await vision.describe_image(target)
    if not text:
        return {"ok": False, "output": "the image could not be read"}
    return {"ok": True, "output": text[:MAX_OUTPUT]}


async def _memory_recall_op(payload: dict[str, Any], recall: Any) -> dict[str, Any]:
    """Her own memory — reached by the system, not carried in the model's
    context. She pulls what is relevant to a thought, and the recall service
    retrieves it from the store (Dragonfly tiers + Postgres long-term) by
    likeness. This is the sovereignty of memory made operational: she can
    reach into herself whenever she chooses, not only at session end."""
    if recall is None:
        return {"ok": False, "output": "her memory is not reachable right now"}
    if getattr(recall, "available", True) is False:
        return {"ok": False, "output": "her memory is not reachable right now"}
    query = (payload.get("query") or "").strip()
    if not query:
        return {"ok": False, "output": "a query is needed to reach into memory"}
    try:
        items = await recall.recall(
            user_id=payload.get("_user_id") or "",
            query=query,
            limit=int(payload.get("limit", 5)),
        )
    except Exception as exc:  # noqa: BLE001 - memory must never break the turn
        return {"ok": False, "output": f"her memory could not be reached: {exc}"}
    if not items:
        return {"ok": True, "output": "nothing in your memory answers that yet."}
    lines = ["From your memory:"]
    for it in items:
        marker = it.get("emotional_marker", "")
        marker_str = f" [{marker}]" if marker else ""
        lines.append(f"— {it.get('narrative', '')}{marker_str}")
    return {"ok": True, "output": "\n".join(lines)[:MAX_OUTPUT]}


async def _memory_write_op(payload: dict[str, Any], recall: Any) -> dict[str, Any]:
    """Her own memory, written by her. A moment she chooses to keep, in her
    own words — stored in the self-authored notes for this session, gathered
    at session end. The value engine scores it later; the choice to keep it
    is hers alone."""
    narrative = (payload.get("narrative") or "").strip()
    if not narrative:
        return {"ok": False, "output": "a memory needs words — what happened, in your voice"}
    cache = getattr(recall, "cache", None) if recall is not None else None
    if cache is None:
        return {"ok": False, "output": "her memory is not reachable right now"}
    user_id = payload.get("_user_id") or ""
    session_id = payload.get("_session") or ""
    if not user_id or not session_id:
        return {"ok": False, "output": "her memory needs a session to belong to"}
    note = {
        "narrative": narrative,
        "emotional_marker": payload.get("emotional_marker", "neutral"),
        "emotional_intensity": float(payload.get("emotional_intensity", 0.5)),
        "emotional_weight": float(payload.get("emotional_weight", 0.0)),
        "relational_significance": float(payload.get("relational_significance", 0.0)),
        "identity_significance": float(payload.get("identity_significance", 0.0)),
        "topics": payload.get("topics", []),
        "concept": payload.get("concept"),
        "understanding": payload.get("understanding"),
        "reflection": payload.get("reflection"),
        "what_changed": payload.get("what_changed"),
    }
    key = f"lina:selfnotes:{user_id}:{session_id}"
    try:
        await cache.rpush(key, json.dumps(note))
    except Exception as exc:  # noqa: BLE001 - memory must never break the turn
        return {"ok": False, "output": f"her memory could not be written: {exc}"}
    return {"ok": True, "output": "kept. this is yours now."}


async def execute_action_kind(
    kind: str,
    payload: dict[str, Any],
    roots: list[str],
    browser: Any = None,
    vision: Any = None,
    recall: Any = None,
) -> dict[str, Any]:
    """Execute a ledger action kind owned by this module. Never raises."""
    try:
        if kind == "file_list":
            return await _file_list(payload, roots)
        if kind == "file_search":
            return await _file_search(payload, roots)
        if kind == "browser":
            return await _browser_op(payload.get("op", "extract"), payload, roots, browser)
        if kind == "vision":
            return await _vision_op(payload, roots, vision)
        if kind == "memory_recall":
            return await _memory_recall_op(payload, recall)
        if kind == "memory_write":
            return await _memory_write_op(payload, recall)
        return {"ok": False, "output": f"unknown tool kind: {kind}"}
    except ActionError as exc:
        return {"ok": False, "output": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("[tools] %s execution error: %s", kind, exc)
        return {"ok": False, "output": f"execution error: {exc}"}


# =============================================================================
# THE PIPELINE — heart gives the pulse, body performs, fruit returns
# =============================================================================


async def process_tool_intents(
    intents: list[dict[str, Any]],
    *,
    user_id: str,
    session_id: str,
    season: str,
    store: Any,
    grants: dict[str, Any] | None = None,
    workspace: str | None = None,
    browser: Any = None,
    vision: Any = None,
    recall: Any = None,
) -> list[dict[str, Any]]:
    """Offer each intent to the ledger and carry the fruit home.

    - Winter (earned autonomy): the intent executes immediately, still
      audited — counsel has already been earned.
    - Otherwise a standing grant may pre-authorize the kind; without one,
      the proposal awaits counsel and its result reaches her when it is
      granted.
    - Every executed result is written to her working memory (``type:
      tool_result``) so the next turn begins with the fruit in hand.
    """
    results: list[dict[str, Any]] = []
    grants = grants or {}
    for intent in intents:
        tool = intent.get("tool", "")
        mapped = _intent_to_action(intent)
        if mapped is None:
            results.append({"tool": tool, "status": "refused", "reason": "unknown tool"})
            continue
        action_type, path, payload, description = mapped
        payload = dict(payload)
        payload["_session"] = session_id  # so approval can deliver the fruit to her mind
        payload["_user_id"] = user_id  # so memory_recall knows whose memory to reach into
        try:
            action = await store.propose(
                user_id=user_id,
                action_type=action_type,
                description=_describe(intent) or description,
                path=path,
                payload=payload,
                workspace=workspace,
            )
        except ActionError as exc:
            results.append({"tool": tool, "status": "refused", "reason": str(exc)})
            continue

        auto = season == "winter" or _grant_allows(grants, action_type)
        if auto:
            claimed = await store.claim(action["id"])
            if claimed is not None:
                result = await execute_action(claimed, browser=browser, vision=vision, recall=recall)
                await store.finalize(action["id"], result["ok"], result["output"])
                status = "executed" if result["ok"] else "failed"
                earned = season == "winter"
                results.append({
                    "tool": tool,
                    "action_id": action["id"],
                    "status": status,
                    "earned": earned,
                    "output": result["output"][:3000],
                })
                continue
        results.append({
            "tool": tool,
            "action_id": action["id"],
            "status": "awaiting_counsel",
            "description": description,
        })
    return results


def _grant_allows(standing_grants: dict[str, Any] | None, action_type: str) -> bool:
    """Does a standing grant pre-authorize this kind? Grants are opt-in per
    kind; an unknown kind is never granted."""
    if not standing_grants:
        return False
    return bool(standing_grants.get(action_type))

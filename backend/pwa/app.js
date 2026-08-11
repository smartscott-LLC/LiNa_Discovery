/* LINA PWA shell — the interface through which you interact with her.
 * Chat · Actions (human-in-the-loop) · Telemetry (live SSE) · Files (OPFS).
 */
"use strict";

const LinaApp = (() => {
  const $ = (sel) => document.querySelector(sel);
  const state = {
    userId: localStorage.getItem("lina.userId") || "desktop-user",
    sessionId: localStorage.getItem("lina.sessionId") || null,
    pending: [],
  };

  function userId() { return state.userId; }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`${res.status} ${body.slice(0, 160)}`);
    }
    return res.json();
  }

  // ── status chips ──────────────────────────────────────────────────────────
  async function refreshStatus() {
    try {
      const h = await api("/health");
      setChip("chip-bridge", "bridge " + (h.bridge_available ? "up" : "down"),
        h.bridge_available ? "ok" : "warn");
      setChip("chip-voice", "voice " + (h.voice_providers || []).join("/"), h.voice_providers ? "ok" : "warn");
      setChip("chip-db", "db " + (h.database_connected ? "ok" : "down"), h.database_connected ? "ok" : "warn");
      if (h.season) setChip("season-chip", h.season, "ok");
    } catch (e) {
      setChip("chip-db", "offline", "warn");
    }
  }

  function setChip(id, text, cls) {
    const el = $(`#${id}`);
    if (el) { el.textContent = text; el.className = "chip" + (cls ? " " + cls : ""); }
  }

  // ── tabs ──────────────────────────────────────────────────────────────────
  function bindTabs() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        $(`#panel-${tab.dataset.tab}`).classList.add("active");
        if (tab.dataset.tab === "actions") refreshActions();
        if (tab.dataset.tab === "telemetry") refreshTelemetry();
        if (tab.dataset.tab === "files") refreshFiles();
      });
    });
  }

  // ── chat ──────────────────────────────────────────────────────────────────
  async function ensureSession() {
    if (state.sessionId) return state.sessionId;
    const r = await api("/lina/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: state.userId }),
    });
    state.sessionId = r.session_id;
    localStorage.setItem("lina.sessionId", state.sessionId);
    return state.sessionId;
  }

  function appendMessage(who, text, evalInfo) {
    const box = $("#chat-log");
    const div = document.createElement("div");
    div.className = "msg " + who;
    const label = who === "ai" ? "LINA" : "you";
    div.innerHTML =
      `<div class="who">${label}</div><div>${escapeHtml(text)}</div>` +
      (evalInfo ? `<div class="eval">${evalInfo}</div>` : "");
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  async function sendChat(text) {
    appendMessage("user", text);
    await ensureSession();
    try {
      const r = await api("/lina/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: state.userId,
          session_id: state.sessionId,
          message: text,
        }),
      });
      const e = r.evaluation || {};
      const evalInfo = `aligned=${e.is_aligned} score=${e.alignment_score?.toFixed(2)} zone=${e.zone || "?"}`;
      appendMessage("ai", r.response, evalInfo);
    } catch (err) {
      appendMessage("ai", `(I couldn't reach my voice right now: ${err.message})`);
    }
  }

  // ── actions (HITL) ────────────────────────────────────────────────────────
  async function refreshActions() {
    try {
      const data = await api("/lina/actions/pending?user_id=" + encodeURIComponent(state.userId));
      state.pending = data.pending || [];
      $("#pending-count").hidden = state.pending.length === 0;
      $("#pending-count").textContent = state.pending.length;
      $("#pending-count-2").textContent = `(${state.pending.length})`;
      renderPending();
      const audit = await api("/lina/actions?user_id=" + encodeURIComponent(state.userId) + "&limit=20");
      renderAudit(audit.actions || []);
    } catch (e) { /* backend down — offline */ }
  }

  function renderPending() {
    const box = $("#pending-list");
    box.innerHTML = "";
    if (!state.pending.length) {
      box.innerHTML = '<p class="hint">Nothing waiting for your approval.</p>';
      return;
    }
    state.pending.forEach((a) => {
      const div = document.createElement("div");
      div.className = "action";
      const payload = a.payload || {};
      const detail = a.path ? ` · ${a.path}` : (payload.command ? ` · ${payload.command}` : "");
      div.innerHTML = `
        <div class="desc">${escapeHtml(a.description)}</div>
        <div class="meta">${a.action_type}${escapeHtml(detail)} · proposed ${new Date(a.proposed_at).toLocaleTimeString()}</div>
        <div class="buttons">
          <button class="ok-btn" data-act="approve">Approve</button>
          <button class="err-btn" data-act="reject">Reject</button>
          ${a.action_type === "command" ? '<button data-act="modify">Modify &amp; run</button>' : ""}
        </div>`;
      div.querySelector('[data-act="approve"]').onclick = () => resolveAction(a.id, "approve");
      div.querySelector('[data-act="reject"]').onclick = () => resolveAction(a.id, "reject");
      const mod = div.querySelector('[data-act="modify"]');
      if (mod) mod.onclick = () => modifyAction(a);
      box.appendChild(div);
    });
  }

  async function resolveAction(id, act) {
    try {
      const r = await api(`/lina/actions/${id}/${act}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: state.userId }),
      });
      alert(`${act}: ${r.status}${r.output ? "\n\n" + r.output.slice(0, 400) : ""}`);
      refreshActions();
    } catch (e) { alert(e.message); }
  }

  async function modifyAction(a) {
    const current = (a.payload || {}).command || "";
    const next = prompt("Modified command:", current);
    if (next === null) return;
    try {
      const r = await api(`/lina/actions/${a.id}/modify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: { ...(a.payload || {}), command: next } }),
      });
      alert(`modified+executed: ${r.status}\n\n${r.output?.slice(0, 400) || ""}`);
      refreshActions();
    } catch (e) { alert(e.message); }
  }

  function renderAudit(list) {
    const box = $("#audit-list");
    box.innerHTML = "";
    list.forEach((a) => {
      const div = document.createElement("div");
      div.className = "action";
      const out = a.executed_output
        ? `<div class="${a.status === "failed" ? "errout" : "out"}">${escapeHtml(a.executed_output.slice(0, 200))}</div>` : "";
      div.innerHTML = `
        <div class="desc">${escapeHtml(a.description)} <span class="meta">[${a.status}]</span></div>
        <div class="meta">${a.action_type}${a.path ? " · " + escapeHtml(a.path) : ""} · ${new Date(a.proposed_at).toLocaleString()}</div>${out}`;
      box.appendChild(div);
    });
  }

  function bindProposers() {
    $("#propose-command").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        await api("/lina/actions/propose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: state.userId,
            action_type: "command",
            description: f.description.value,
            payload: { command: f.command.value },
          }),
        });
        f.reset();
        refreshActions();
      } catch (err) { alert(err.message); }
    });
    $("#propose-write").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        await api("/lina/actions/propose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: state.userId,
            action_type: "file_write",
            description: f.description.value,
            path: f.path.value,
            payload: { content: f.content.value },
          }),
        });
        f.reset();
        refreshActions();
      } catch (err) { alert(err.message); }
    });
  }

  // ── telemetry ────────────────────────────────────────────────────────────
  async function refreshTelemetry() {
    try {
      const t = await api("/lina/telemetry");
      const cards = $("#metric-cards");
      cards.innerHTML = "";
      Object.entries(t.counters || {}).forEach(([k, v]) => {
        const c = document.createElement("div");
        c.className = "card";
        c.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div>`;
        cards.appendChild(c);
      });
      const up = document.createElement("div");
      up.className = "card";
      up.innerHTML = `<div class="k">uptime</div><div class="v">${Math.round(t.uptime_seconds)}s</div>`;
      cards.appendChild(up);
      if (t.recent_actions && t.recent_actions.length) {
        renderAudit(t.recent_actions);
      }
    } catch (e) { /* offline */ }
  }

  function startTelemetryStream() {
    const feed = $("#telemetry-feed");
    if (window.EventSource) {
      const es = new EventSource("/lina/telemetry/stream");
      es.onmessage = (ev) => {
        try {
          const e = JSON.parse(ev.data);
          const line = e.kind === "action"
            ? `[action] ${e.status} ${e.type} ${e.id?.slice(0, 8)}`
            : `[${e.level}] ${e.message}`;
          feed.textContent = `${new Date(e.ts).toLocaleTimeString()} ${line}\n` + feed.textContent;
          if (feed.textContent.length > 20000) feed.textContent = feed.textContent.slice(0, 20000);
        } catch (_) { /* keep-alive pings */ }
      };
      es.onerror = () => { /* will retry automatically */ };
    }
  }

  // ── files (OPFS) ─────────────────────────────────────────────────────────
  async function refreshFiles() {
    try {
      const entries = await LinaOPFS.list();
      const box = $("#opfs-browser");
      box.innerHTML = entries.length
        ? entries.map((f) => `<div class="file-row" data-name="${escapeHtml(f.name)}">${f.kind === "directory" ? "📁" : "📄"} ${escapeHtml(f.name)}</div>`).join("")
        : '<span class="hint">(empty sandbox)</span>';
      box.querySelectorAll(".file-row").forEach((row) => {
        row.onclick = async () => {
          const name = row.dataset.name;
          const text = await LinaOPFS.readFile(name);
          LinaOPFS.audit("read", name);
          const proposed = confirm(`Read "${name}" (${text.length} chars). Propose writing it to the workspace?`);
          if (proposed) {
            const path = prompt("Workspace path:", name);
            if (path) {
              await api("/lina/actions/propose", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  user_id: state.userId,
                  action_type: "file_write",
                  description: `Copy ${name} from OPFS to workspace`,
                  path,
                  payload: { content: text },
                }),
              });
              alert("Proposed — approve it on the Actions tab.");
              refreshActions();
            }
          }
        };
      });
      const ws = await api("/health");
      const roots = (ws.access_roots || []).join(", ");
      $("#ws-status").textContent =
        `Filesystem service: ${ws.database_connected ? "reachable" : "unreachable"}. ` +
        `Access roots: ${roots || "(none configured)"}. ` +
        `Every read/write goes through the Actions tab for your approval.`;
    } catch (e) {
      $("#opfs-browser").innerHTML = `<span class="errout">${escapeHtml(e.message)}</span>`;
    }
  }

  function bindFiles() {
    $("#opfs-root").onclick = async () => { await LinaOPFS.getRoot(); refreshFiles(); };
    $("#opfs-picker").onclick = async () => {
      try { await LinaOPFS.openPicker(); refreshFiles(); }
      catch (e) { alert(e.message); }
    };
  }

  // ── service worker + offline queue ───────────────────────────────────────
  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/pwa/sw.js").then((reg) => {
      setChip("chip-sw", "offline-ready", "ok");
      reg.addEventListener("updatefound", () => {
        const sw = reg.installing;
        sw && sw.addEventListener("statechange", () => {
          if (sw.state === "installed" && navigator.serviceWorker.controller) {
            sw.postMessage({ type: "SKIP_WAITING" });
          }
        });
      });
    }).catch(() => setChip("chip-sw", "sw unavailable", "warn"));
    navigator.serviceWorker.addEventListener("controllerchange", () => location.reload());
  }

  // ── boot ──────────────────────────────────────────────────────────────────
  function bindChat() {
    $("#chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#chat-input");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendChat(text);
    });
  }

  function boot() {
    bindTabs();
    bindChat();
    bindProposers();
    bindFiles();
    registerServiceWorker();
    refreshStatus();
    refreshActions();
    refreshTelemetry();
    startTelemetryStream();
    setInterval(refreshStatus, 15000);
    setInterval(refreshActions, 5000);
  }

  document.addEventListener("DOMContentLoaded", boot);
  return { userId };
})();

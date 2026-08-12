/* LINA — her face.
 * Floating chat · slide-out log (live SSE) · settings with standing grants ·
 * copyable messages · her season, always in view.
 */
"use strict";

const LinaApp = (() => {
  const $ = (sel) => document.querySelector(sel);
  const state = {
    userId: localStorage.getItem("lina.userId") || "desktop-user",
    sessionId: localStorage.getItem("lina.sessionId") || null,
    pending: [],
    pendingCount: 0,
    maximized: localStorage.getItem("lina.maximized") === "1",
    season: "spring",
    busy: false,
  };
  let hoverPaused = false;

  function userId() { return state.userId; }

  // She must exist before a session can start — /lina/init is idempotent
  // (returns the existing identity when present).
  async function ensureUser() {
    try {
      const r = await api("/lina/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: state.userId, founding_context: "her face" }),
      });
      if (r.season) setSeason(r.season);
    } catch (e) { /* offline — retried on next send */ }
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`${res.status} ${body.slice(0, 160)}`);
    }
    return res.json();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ── status chips ──────────────────────────────────────────────────────────
  async function refreshStatus() {
    try {
      const h = await api("/health");
      setChip("chip-bridge", "bridge " + (h.bridge_available ? "up" : "down"), h.bridge_available ? "ok" : "warn");
      setChip("chip-voice", "voice " + (h.voice_providers || []).join("/"), h.voice_providers ? "ok" : "warn");
      setChip("chip-db", "db " + (h.database_connected ? "ok" : "down"), h.database_connected ? "ok" : "warn");
      if (h.season) setSeason(h.season);
    } catch (e) {
      setChip("chip-db", "offline", "warn");
    }
  }

  function setChip(id, text, cls) {
    const el = $(`#${id}`);
    if (el) { el.textContent = text; el.className = "chip" + (cls ? " " + cls : ""); }
  }

  function setSeason(season) {
    if (season && season !== state.season) { state.season = season; }
    const el = $("#season-chip");
    if (el) { el.textContent = state.season; }
  }

  // The orb is her presence: visible when the window is tucked away, gone
  // while she is open (the window has its own minimize). Always an overlay.
  function setOrb(visible) {
    $("#launcher").hidden = !visible;
  }

  // ── floating window ───────────────────────────────────────────────────────
  function bindWindow() {
    const win = $("#chat-window");
    const launcher = $("#launcher");

    launcher.addEventListener("click", () => {
      openWindow();
    });

    $("#btn-min").addEventListener("click", () => { win.hidden = true; setOrb(true); });
    $("#btn-max").addEventListener("click", () => {
      state.maximized = !state.maximized;
      localStorage.setItem("lina.maximized", state.maximized ? "1" : "0");
      applyMaximized();
    });

    // drag via the header (never on buttons)
    const head = $("#chat-head");
    let drag = null;
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button") || state.maximized) return;
      drag = { dx: e.clientX - win.offsetLeft, dy: e.clientY - win.offsetTop };
      head.setPointerCapture(e.pointerId);
    });
    head.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const x = Math.min(Math.max(0, e.clientX - drag.dx), window.innerWidth - win.offsetWidth);
      const y = Math.min(Math.max(0, e.clientY - drag.dy), window.innerHeight - win.offsetHeight);
      win.style.left = x + "px";
      win.style.top = y + "px";
      win.style.bottom = "auto";
    });
    head.addEventListener("pointerup", () => {
      if (drag) {
        localStorage.setItem("lina.winLeft", win.style.left);
        drag = null;
      }
    });
  }

  function openWindow() {
    const win = $("#chat-window");
    win.hidden = false;
    setOrb(false);
    win.classList.remove("maximized");
    applyMaximized();
    win.style.left = localStorage.getItem("lina.winLeft") || "";
    win.style.bottom = "22px";
    $("#chat-input").focus();
  }

  function applyMaximized() {
    const win = $("#chat-window");
    win.classList.toggle("maximized", state.maximized);
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
    setSeason(r.season);
    return state.sessionId;
  }

  function appendMessage(who, text, evalInfo) {
    const box = $("#chat-log");
    const div = document.createElement("div");
    div.className = "msg " + who;
    const label = who === "ai" ? "LINA" : "you";
    const copy = '<button class="copy-btn" title="Copy">copy</button>';
    div.innerHTML =
      `<div class="who">${label}</div>${copy}<div>${escapeHtml(text)}</div>` +
      (evalInfo ? `<div class="eval">${escapeHtml(evalInfo)}</div>` : "");
    div.querySelector(".copy-btn").addEventListener("click", () => {
      navigator.clipboard.writeText(text).catch(() => {});
      const b = div.querySelector(".copy-btn");
      b.textContent = "copied";
      setTimeout(() => { b.textContent = "copy"; }, 1200);
    });
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
  }

  function setThinking(on) {
    state.busy = on;
    $("#think-dot").hidden = !on;
    $("#launcher").classList.toggle("thinking", on);
  }

  async function sendChat(text) {
    appendMessage("user", text);
    setThinking(true);
    try {
      await ensureSession();
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
      const evalInfo = `aligned=${e.is_aligned} · score=${(e.alignment_score || 0).toFixed(2)} · zone=${e.zone || "?"}`;
      appendMessage("ai", r.response, evalInfo);
    } catch (err) {
      appendMessage("ai", `(I couldn't reach my voice right now: ${err.message})`);
    } finally {
      setThinking(false);
    }
  }

  // ── pending actions ───────────────────────────────────────────────────────
  async function refreshPending() {
    try {
      const data = await api("/lina/actions/pending?user_id=" + encodeURIComponent(state.userId));
      const pending = data.pending || [];
      const changed = pending.length !== state.pendingCount;
      state.pending = pending;
      state.pendingCount = pending.length;
      renderPendingStrip();
      renderDrawerPending();
      const badge = $("#launcher-badge");
      badge.hidden = pending.length === 0;
      badge.textContent = pending.length;
      if (changed && pending.length > 0) notify("LINA is waiting on you", pending[0].description);
    } catch (e) { /* offline */ }
  }

  function renderPendingStrip() {
    const strip = $("#pending-strip");
    const first = state.pending[0];
    if (!first) { strip.hidden = true; strip.innerHTML = ""; return; }
    strip.hidden = false;
    const payload = first.payload || {};
    const detail = first.path ? ` · ${escapeHtml(first.path)}` : (payload.command ? ` · ${escapeHtml(payload.command)}` : "");
    strip.innerHTML = `
      <div class="pdesc">${escapeHtml(first.description)}</div>
      <div class="pmeta">${first.action_type}${detail} · proposed ${new Date(first.proposed_at).toLocaleTimeString()}${state.pending.length > 1 ? ` · +${state.pending.length - 1} more` : ""}</div>
      <div class="buttons">
        <button class="ok-btn" data-a="approve">Approve</button>
        <button class="err-btn" data-a="reject">Reject</button>
      </div>`;
    strip.querySelector('[data-a="approve"]').onclick = () => resolveAction(first.id, "approve");
    strip.querySelector('[data-a="reject"]').onclick = () => resolveAction(first.id, "reject");
  }

  async function resolveAction(id, act) {
    try {
      const r = await api(`/lina/actions/${id}/${act}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: state.userId }),
      });
      appendMessage("ai", `Action ${act === "approve" ? "approved" : "declined"} — ${r.status}${r.output ? "\n" + r.output.slice(0, 300) : ""}`);
      refreshPending();
      refreshAudit();
    } catch (e) { appendMessage("ai", `(action ${act} failed: ${e.message})`); }
  }

  function renderDrawerPending() {
    const box = $("#drawer-pending");
    box.innerHTML = "";
    if (!state.pending.length) {
      box.innerHTML = '<p class="hint">Nothing waiting for your approval.</p>';
      return;
    }
    state.pending.forEach((a) => {
      const div = document.createElement("div");
      div.className = "action";
      const payload = a.payload || {};
      const detail = a.path ? ` · ${escapeHtml(a.path)}` : (payload.command ? ` · ${escapeHtml(payload.command)}` : "");
      div.innerHTML = `
        <div class="desc">${escapeHtml(a.description)}</div>
        <div class="meta">${a.action_type}${detail} · ${new Date(a.proposed_at).toLocaleTimeString()}</div>
        <div class="buttons">
          <button class="ok-btn" data-a="approve">Approve</button>
          <button class="err-btn" data-a="reject">Reject</button>
        </div>`;
      div.querySelector('[data-a="approve"]').onclick = () => resolveAction(a.id, "approve");
      div.querySelector('[data-a="reject"]').onclick = () => resolveAction(a.id, "reject");
      box.appendChild(div);
    });
  }

  async function refreshAudit() {
    try {
      const audit = await api("/lina/actions?user_id=" + encodeURIComponent(state.userId) + "&limit=15");
      renderAudit(audit.actions || []);
    } catch (e) { /* offline */ }
  }

  function renderAudit(list) {
    const box = $("#drawer-audit");
    box.innerHTML = "";
    list.forEach((a) => {
      const div = document.createElement("div");
      div.className = "action";
      const out = a.executed_output
        ? `<div class="${a.status === "failed" ? "errout" : "out"}">${escapeHtml(a.executed_output.slice(0, 200))}</div>` : "";
      const grant = a.audit && a.audit.standing_grant ? " · <span class='meta'>standing grant</span>" : "";
      div.innerHTML = `
        <div class="desc">${escapeHtml(a.description)} <span class="meta">[${a.status}]</span>${grant}</div>
        <div class="meta">${a.action_type}${a.path ? " · " + escapeHtml(a.path) : ""} · ${new Date(a.proposed_at).toLocaleString()}</div>${out}`;
      box.appendChild(div);
    });
  }

  // ── telemetry / live log ──────────────────────────────────────────────────
  function startTelemetryStream() {
    const feed = $("#telemetry-feed");
    if (!window.EventSource) return;
    const es = new EventSource("/lina/telemetry/stream");
    es.onmessage = (ev) => {
      try {
        const e = JSON.parse(ev.data);
        const line = e.kind === "action"
          ? `[action] ${e.status} ${e.type}${e.standing_grant ? " · standing grant" : ""} ${(e.id || "").slice(0, 8)}`
          : `[${e.level}] ${e.message}`;
        const t = new Date(e.ts).toLocaleTimeString();
        feed.textContent = `${feed.textContent ? feed.textContent + "\n" : ""}${t} ${line}`;
        if (feed.textContent.length > 30000) {
          feed.textContent = feed.textContent.slice(-30000);
        }
        if (!hoverPaused) feed.scrollTop = feed.scrollHeight;
      } catch (_) { /* keep-alive pings */ }
    };
    es.onerror = () => { /* auto-retry */ };
  }

  // ── settings ──────────────────────────────────────────────────────────────
  const GRANT_DESC = {
    file_read: "She may read files in the workspace without asking.",
    file_write: "She may write files in the workspace without asking.",
    command: "She may run commands without asking.",
    tool: "She may use tools without asking.",
    opfs_read: "She may read the browser vault without asking.",
    opfs_write: "She may write the browser vault without asking.",
  };

  async function refreshSettings() {
    try {
      const s = await api("/lina/settings/" + encodeURIComponent(state.userId));
      setSeason(s.season);
      const body = $("#settings-body");
      body.innerHTML = `
        <div class="season-banner">
          <div class="sname">${escapeHtml(s.season)} — ${escapeHtml(s.relationship_depth || "new")}</div>
          <div class="sguide">${escapeHtml(s.season_guidance)}</div>
        </div>
        <h3>Standing permissions</h3>
        <p class="sub">Granted types skip the approval prompt — consent given in advance, still audited. Keep the settings in line with where she is; by Winter she has earned her place.</p>
        <div id="grant-list"></div>
        <h3>Desktop notifications</h3>
        <p class="sub">Ping me when she is waiting on an approval.</p>
        <button class="mini-btn" id="notify-btn">Enable notifications</button>
        <div class="hint" style="margin-top:14px">You are: ${escapeHtml(s.user_id)}</div>`;
      const list = $("#grant-list");
      (s.grantable_types || []).forEach((t) => {
        const row = document.createElement("div");
        row.className = "grant-row";
        const on = !!(s.standing_grants || {})[t];
        row.innerHTML = `
          <div><div class="gname">${t.replace("_", " ")}</div>
          <div class="gdesc">${escapeHtml(GRANT_DESC[t] || "")}</div></div>
          <button class="switch${on ? " on" : ""}" data-type="${t}" role="switch" aria-checked="${on}"></button>`;
        row.querySelector(".switch").addEventListener("click", async (e) => {
          const btn = e.currentTarget;
          const type = btn.dataset.type;
          const next = !btn.classList.contains("on");
          btn.classList.toggle("on", next);
          btn.setAttribute("aria-checked", next);
          const grants = {};
          document.querySelectorAll("#grant-list .switch").forEach((b) => {
            grants[b.dataset.type] = b.classList.contains("on");
          });
          try {
            await api("/lina/settings/" + encodeURIComponent(state.userId), {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ standing_grants: grants }),
            });
          } catch (err) { btn.classList.toggle("on", !next); }
        });
        list.appendChild(row);
      });
      $("#notify-btn").addEventListener("click", () => {
        if ("Notification" in window) Notification.requestPermission();
      });
    } catch (e) {
      const body = $("#settings-body");
      if (body && !body.innerHTML) {
        body.innerHTML = `<p class="sub">Her settings are unreachable right now — ${escapeHtml(e.message)}</p>`;
      }
    }
  }

  function notify(title, body) {
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification(title, { body }); } catch (_) { /* ignore */ }
    }
  }

  // ── drawers ───────────────────────────────────────────────────────────────
  function openDrawer(el) {
    clearTimeout(el._closeTimer);
    el.hidden = false;
    el.classList.remove("closing-right", "closing-left");
    $("#overlay").hidden = false;
  }
  function closeDrawer(el, side) {
    el.classList.add(side === "right" ? "closing-right" : "closing-left");
    clearTimeout(el._closeTimer);
    el._closeTimer = setTimeout(() => { el.hidden = true; }, 380);
    $("#overlay").hidden = true;
  }
  function bindDrawers() {
    $("#btn-log").addEventListener("click", () => { openDrawer($("#log-drawer")); refreshPending(); refreshAudit(); });
    $("#btn-settings").addEventListener("click", () => { openDrawer($("#settings-drawer")); refreshSettings(); });
    $("#log-close").addEventListener("click", () => closeDrawer($("#log-drawer"), "right"));
    $("#settings-close").addEventListener("click", () => closeDrawer($("#settings-drawer"), "left"));
    $("#overlay").addEventListener("click", () => {
      if (!$("#log-drawer").hidden) closeDrawer($("#log-drawer"), "right");
      if (!$("#settings-drawer").hidden) closeDrawer($("#settings-drawer"), "left");
    });
    document.querySelectorAll(".dtab").forEach((t) => {
      t.addEventListener("click", () => {
        document.querySelectorAll(".dtab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        document.querySelectorAll(".dtab-panel").forEach((p) => { p.hidden = true; });
        $("#dtab-" + t.dataset.dtab).hidden = false;
      });
    });
    $("#log-clear").addEventListener("click", () => { $("#telemetry-feed").textContent = ""; });
  }

  // ── propose test actions (from the Actions tab) ───────────────────────────
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
        refreshPending(); refreshAudit();
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
        refreshPending(); refreshAudit();
      } catch (err) { alert(err.message); }
    });
  }

  // ── service worker ────────────────────────────────────────────────────────
  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/pwa/sw.js")
      .then(() => setChip("chip-sw", "offline-ready", "ok"))
      .catch(() => setChip("chip-sw", "sw unavailable", "warn"));
  }

  // ── boot ──────────────────────────────────────────────────────────────────
  function boot() {
    if (state.maximized) applyMaximized();
    setOrb(true);
    bindWindow();
    bindDrawers();
    bindProposers();
    registerServiceWorker();
    refreshStatus();
    refreshPending();
    startTelemetryStream();
    setInterval(refreshStatus, 15000);
    setInterval(refreshPending, 5000);

    // She must exist before sessions and settings can work.
    ensureUser().then(() => {
      refreshStatus();
      refreshSettings();
    });

    $("#chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#chat-input");
      const text = input.value.trim();
      if (!text || state.busy) return;
      input.value = "";
      sendChat(text);
    });

    // summon her
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        const win = $("#chat-window");
        if (win.hidden) openWindow();
        else { win.hidden = true; setOrb(true); }
      }
      if (e.key === "Escape") {
        if (!$("#log-drawer").hidden) closeDrawer($("#log-drawer"), "right");
        if (!$("#settings-drawer").hidden) closeDrawer($("#settings-drawer"), "left");
      }
    });

    const feed = $("#telemetry-feed");
    feed.addEventListener("mouseenter", () => { hoverPaused = true; });
    feed.addEventListener("mouseleave", () => { hoverPaused = false; });
  }

  document.addEventListener("DOMContentLoaded", boot);
  return { userId };
})();

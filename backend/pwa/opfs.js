/* LINA OPFS adapter — the browser vault, plus the bridge to your real disk.
 *
 * Two surfaces:
 *   - OPFS root / picked directory: browser-managed storage. Safe (nothing
 *     touches the OS outside the browser), but it is NOT her access to your
 *     filesystem — it is a vault the browser owns.
 *   - Your filesystem (the workspace + LINA_ACCESS_ROOTS): real disk, never
 *     touched directly from here. Operations on it are proposed via
 *     /lina/actions and execute only after human approval (the polytope +
 *     consent boundary).
 */
"use strict";

const LinaOPFS = (() => {
  let rootHandle = null; // FileSystemDirectoryHandle (OPFS root or picked)
  let entries = [];

  async function getRoot() {
    if (rootHandle) return rootHandle;
    rootHandle = await navigator.storage.getDirectory(); // OPFS root
    return rootHandle;
  }

  async function openPicker() {
    if (!window.showDirectoryPicker) {
      throw new Error("File System Access API unavailable in this browser");
    }
    rootHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    return rootHandle;
  }

  async function list() {
    const dir = await getRoot();
    entries = [];
    for await (const [name, handle] of dir.entries()) {
      entries.push({ name, kind: handle.kind });
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    return entries;
  }

  async function readFile(name) {
    const dir = await getRoot();
    const handle = await dir.getFileHandle(name);
    const file = await handle.getFile();
    return await file.text();
  }

  async function writeFile(name, content) {
    const dir = await getRoot();
    const handle = await dir.getFileHandle(name, { create: true });
    const writable = await handle.createWritable();
    await writable.write(content);
    await writable.close();
  }

  async function removeFile(name) {
    const dir = await getRoot();
    await dir.removeEntry(name);
  }

  /** Record an OPFS operation in the backend audit trail (never blocks UI). */
  async function audit(kind, path, note) {
    try {
      await fetch("/lina/actions/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: LinaApp ? LinaApp.userId() : "pwa-user",
          action_type: kind === "read" ? "opfs_read" : "opfs_write",
          description: note || `OPFS ${kind}: ${path}`,
          path,
        }),
      });
    } catch (_) { /* offline — audit will sync later via the queue */ }
  }

  return { getRoot, openPicker, list, readFile, writeFile, removeFile, audit };
})();

window.LinaOPFS = LinaOPFS;

/* LINA PWA — service worker.
 *
 * Strategy:
 *  - GET /pwa/* (the app shell) → network-first, cache fallback. The shell
 *    loads offline from cache when the service is unreachable, so LINA's
 *    interface is never a blank page.
 *  - Everything else — chat, actions, telemetry (SSE), health — passes
 *    straight through to the network and is NEVER cached. POST responses in
 *    particular must be live: caching them would replay stale chat/action
 *    results on reload.
 *
 * Lifecycle:
 *  - install: pre-cache the shell, then skipWaiting so the new worker takes
 *    over immediately (app.js sends SKIP_WAITING on updatefound).
 *  - activate: drop stale caches, claim all clients so the shell is
 *    controlled without a manual reload.
 */

"use strict";

const VERSION = "lina-shell-v5";
const SHELL_CACHE = VERSION;

const SHELL_URLS = [
  "/pwa/",
  "/pwa/index.html",
  "/pwa/styles.css",
  "/pwa/app.js",
  "/pwa/manifest.webmanifest",
  "/pwa/icons/icon.svg",
  "/assets/theme.css",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin requests.
  if (url.origin !== self.location.origin) return;

  // Non-GET (chat, session, actions, feedback…): never cache, always live.
  if (req.method !== "GET") {
    event.respondWith(fetch(req));
    return;
  }

  // App shell assets: network-first with cache fallback. The shell and her
  // theme load offline from cache when the service is unreachable.
  if (url.pathname.startsWith("/pwa/") || url.pathname.startsWith("/assets/")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() =>
          caches.match(req).then((cached) => cached || caches.match("/pwa/"))
        )
    );
    return;
  }

  // Health, telemetry, and everything else: pass through, never cached.
  event.respondWith(fetch(req));
});

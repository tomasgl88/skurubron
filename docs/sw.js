// Skurubron PWA service worker.
// Strategy:
//   - App shell (HTML/CSS/icons/Chart.js): cache-first, so the app opens instantly
//     and works fully offline.
//   - data.json: network-first with cache fallback, so when online we pick up a
//     freshly published month, but offline we still show the last data we had.
const VERSION = "skurubron-v6";
const SHELL = [
  "./index.html",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isData = url.pathname.endsWith("/data.json") || url.pathname.endsWith("data.json");

  // Network-first for the app page itself, so UI/code updates always take effect
  // on the next open (cache is only a fallback when offline).
  const isPage = e.request.mode === "navigate"
    || url.pathname.endsWith("/index.html")
    || url.pathname.endsWith("/") ;
  if (isPage) {
    e.respondWith(
      fetch(e.request)
        .then((resp) => { const c = resp.clone(); caches.open(VERSION).then(k=>k.put(e.request,c)); return resp; })
        .catch(() => caches.match(e.request).then(h => h || caches.match("./index.html")))
    );
    return;
  }

  if (isData) {
    // Network-first for data.
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(VERSION).then((c) => c.put(e.request, copy));
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Cache-first for everything else (app shell).
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});

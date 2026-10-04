/* SIRE Prep offline cache. Change VERSION whenever index.html or sms/ is updated so phones pick up the new copy. */
const VERSION = 'sire-prep-v9';
const PAGES = 'sire-sms-pages-v3'; // SMS manual page images, kept across app updates. Change it when the manuals are re-rendered.
const FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png', './icon-maskable-512.png', './apple-touch-icon.png', './sms/refs.js'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== PAGES).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // Page: try network first (to get updates), fall back to the saved copy when offline.
  // Wait at most 3 s: on a ship LAN the PC server may be switched off and the request would hang.
  if (req.mode === 'navigate') {
    const net = fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        return caches.open(VERSION).then((c) => c.put('./index.html', copy)).then(() => res);
      }
      return res;
    });
    const slow = new Promise((r) => setTimeout(r, 3000)).then(() => caches.match('./index.html')).then((hit) => hit || net);
    e.waitUntil(net.catch(() => {}));
    e.respondWith(Promise.race([net, slow]).catch(() => caches.match('./index.html')));
    return;
  }
  // SMS manual pages: saved copy first; otherwise download once and keep it for offline use.
  if (/\/sms\/[^/]+\/\d+\.webp$/.test(new URL(req.url).pathname)) {
    e.respondWith(
      // cache: 'reload' skips the browser's own HTTP cache, which may still hold older page images.
      caches.open(PAGES).then((c) => c.match(req).then((hit) => hit || fetch(req.url, { cache: 'reload' }).then((res) => {
        if (res.ok) c.put(req, res.clone());
        return res;
      })))
    );
    return;
  }
  // Other files: saved copy first, network if missing.
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});

// 최소 서비스워커 — 쉘만 캐시해 오프라인 아이콘/로딩 유지.
// API 응답은 캐싱하지 않는다 (항상 최신 상태가 필요).
const CACHE = 'mimmy-shell-v1';
const SHELL = [
  '/',
  '/static/app.js',
  '/static/style.css',
  '/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // API / chat / healthz 는 캐시하지 않는다
  if (url.pathname.startsWith('/api/') || url.pathname === '/chat' || url.pathname === '/healthz') {
    return;
  }
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).catch(() => caches.match('/')))
  );
});

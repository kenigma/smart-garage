// Service worker — required for PWA installability.
// Passes all requests through; no caching of API responses.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});

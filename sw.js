// Service Worker fuer das Balkonkraftwerke-Dashboard.
//
// Zweck: (1) die App vom Handy-Homescreen aus wie eine "echte" App oeffnen zu koennen
// (Vollbild, eigenes Icon - das regelt vor allem manifest.json, dieser Service Worker ist
// aber Voraussetzung dafuer, dass Browser die Seite ueberhaupt als "installierbar" ansehen),
// und (2) bei schlechtem/keinem Empfang wenigstens die zuletzt erfolgreich geladenen Werte
// zu zeigen statt einer leeren Fehlerseite.
//
// Strategie fuer ALLE Anfragen (HTML/JS, Bilder, die Google-Tabelle als CSV, die
// historical-solar-*.csv): "Network-first mit Cache-Fallback" - bei Internet wird IMMER die
// aktuelle Version/frische Daten geholt (nichts wird also kuenstlich verzoegert oder veraltet
// angezeigt, solange eine Verbindung besteht); nur wenn die Anfrage fehlschlaegt, wird auf die
// zuletzt erfolgreich gespeicherte Antwort zurueckgegriffen.
//
// Wichtig: die Live-Daten-URLs haben einen Cache-Busting-Parameter ("?cb=<Zeitstempel>"), der
// sich bei jeder Anfrage aendert - ohne Gegenmassnahme wuerde der Cache-Fallback dadurch NIE
// etwas finden (jede Anfrage haette ja eine neue, noch nie gesehene URL). Deshalb wird beim
// Speichern/Nachschlagen im Cache die Query-String immer abgeschnitten, sodass alle Anfragen an
// dieselbe Basis-URL denselben Cache-Eintrag benutzen.

var CACHE_NAME = 'bkw-dashboard-v1';
var APP_SHELL = ['./', './config.js', './haus-solar.jpg', './manifest.json'];

function stripQuery(url) {
  var i = url.indexOf('?');
  return i >= 0 ? url.slice(0, i) : url;
}

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) { return cache.addAll(APP_SHELL); })
      .catch(function () { /* einzelne fehlende Datei soll die Installation nicht verhindern */ })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE_NAME; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;

  var cacheKey = stripQuery(req.url);

  event.respondWith(
    fetch(req).then(function (resp) {
      if (resp && resp.ok) {
        var copy = resp.clone();
        caches.open(CACHE_NAME).then(function (cache) { cache.put(cacheKey, copy); });
      }
      return resp;
    }).catch(function () {
      return caches.match(cacheKey).then(function (cached) {
        return cached || Response.error();
      });
    })
  );
});

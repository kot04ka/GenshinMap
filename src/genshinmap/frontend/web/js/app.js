// API для Python (window.*) и запуск: загрузка данных карты и мост QWebChannel.
window.loadData = loadData;
window.setCollected = setCollected;
window.applyCollected = applyCollected;
window.enableCategory = enableCategory;
window.applyState = applyState;
window.setPlayer = setPlayer;
window.setLostHint = function (on, text) {
  const el = document.getElementById('lost');
  if (text) el.textContent = text;
  el.classList.toggle('on', !!on);
};
// короткая подсказка сверху карты (синяя), сама прячется
window.showMapTip = function (text, ms) {
  const el = document.getElementById('maptip');
  el.textContent = text;
  el.classList.add('on');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('on'), ms || 7000);
};
window.clearPlayer = clearPlayer;
window.highlightPoint = highlightPoint;
window.setMaxMarkers = function (n) { MAX_MARKERS = Math.max(100, n | 0); renderVisible(); };
// мини-режим: свой масштаб (запоминает Python); выход — вернуть вид обычного окна
let normalView = null;
window.setCompact = function (on, zoom) {
  const was = document.body.classList.contains('compact');
  if (on && !was && map) normalView = { c: map.getCenter(), z: map.getZoom() };
  document.body.classList.toggle('compact', !!on);
  if (!on) document.getElementById('sheet').classList.remove('on');
  followWanted = !!on;
  clearTimeout(followTimer); followTimer = null;
  if (map) setTimeout(() => {
    map.invalidateSize();
    if (on && typeof zoom === 'number') map.setZoom(zoom, { animate: false });
    if (on && lastPlayer) setFollow(true);    // мини-режим — сразу за игроком
    if (!on && was && normalView) { map.setView(normalView.c, normalView.z, { animate: false }); normalView = null; }
  }, 50);
};

// Сообщаем Python 'готово' ТОЛЬКО когда И карта построена, И мост подключён —
// иначе applyState/applyCollected прилетят раньше, чем создан map (был баг).
let _built = false, _readySent = false;
function trySignalReady() {
  if (_built && bridge && bridge.on_ready && !_readySent) {
    _readySent = true;
    bridge.on_ready();
  }
}

// Enter / пробел на элементе role="button" (чипы регионов, группы, слои) — как клик
document.addEventListener('keydown', e => {
  const t = e.target;
  if ((e.key === 'Enter' || e.key === ' ') && t.getAttribute && t.getAttribute('role') === 'button'
      && t.tagName !== 'BUTTON' && t.tagName !== 'A') {
    e.preventDefault();
    t.click();
  }
});

// Подгружаем бандл нужной карты по фрагменту #map=<id> и строим карту.
(function loadBundle() {
  const params = new URLSearchParams(location.hash.slice(1));
  const mapId = params.get('map') || '2';
  const s = document.createElement('script');
  s.src = 'mapdata_' + mapId + '.js?v=' + (params.get('v') || '');
  s.onload = () => {
    if (window.__MAPDATA) { loadData(window.__MAPDATA); _built = true; trySignalReady(); }
    else document.getElementById('stat').textContent = 'Пустые данные карты';
  };
  s.onerror = () => {
    document.getElementById('stat').textContent =
      'Нет данных карты. Запусти: python tools/fetch_map_data.py';
    const ln = document.getElementById('loading');
    if (ln) ln.classList.add('hidden');
  };
  document.head.appendChild(s);
})();

// Подключаем мост к Python (для отметок и авто-распознавания).
if (typeof qt !== 'undefined' && qt.webChannelTransport) {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.bridge;
    trySignalReady();
  });
}

// Карта Leaflet: тайлы, кнопки справа, регионы, названия мест, «где остались сундуки».
function initMap() {
  const W = META.total_size[0], H = META.total_size[1];
  const pad = META.padding || [0, 0];
  const cs = META.content_size || META.total_size;
  // Реальная картинка — только часть холста; по ней и центрируем, и ограничиваем.
  CONTENT_BOUNDS = L.latLngBounds([-pad[1], pad[0]], [-(pad[1] + cs[1]), pad[0] + cs[0]]);

  map = L.map('map', { crs: L.CRS.Simple, minZoom: -8, maxZoom: 2,
                       zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,
                       zoomControl: false, attributionControl: false,
                       maxBounds: CONTENT_BOUNDS.pad(0.25), maxBoundsViscosity: 0.85,
                       zoomAnimation: true, markerZoomAnimation: false });
  L.control.zoom({ position: 'topright', zoomInTitle: 'Приблизить', zoomOutTitle: 'Отдалить' }).addTo(map);
  addViewControls();

  // Нативный тайл-слой HoYoLAB v2: Leaflet сам грузит только видимые тайлы
  // по зумам (быстро, все регионы). bounds = контент -> нет 404 за краями.
  const V2Layer = L.TileLayer.extend({
    getTileUrl: function (c) {
      const Z = (c.z < 0 ? 'N' : 'P') + Math.abs(c.z);
      return META.tile_url.replace('{x}', c.x).replace('{y}', c.y).replace('{Z}', Z);
    },
  });
  new V2Layer('', {
    tileSize: META.tile_size || 256, minZoom: -8, maxZoom: 2,
    minNativeZoom: META.min_zoom, maxNativeZoom: META.max_zoom,
    noWrap: true, bounds: CONTENT_BOUNDS, keepBuffer: 3,
  }).addTo(map);

  map.fitBounds(CONTENT_BOUNDS);
  // дальше, чем «вся карта целиком», отдалять смысла нет
  map.setMinZoom(Math.floor(map.getBoundsZoom(CONTENT_BOUNDS) * 4) / 4 - 0.5);

  // подписи регионов — отдельная панель ПОВЕРХ иконок (иначе их не прочесть)
  map.createPane('regionPane').style.zIndex = 650;
  map.createPane('anchorPane').style.zIndex = 450;   // названия мест — под иконками
  map.createPane('pathPane').style.zIndex = 445;     // линии пути — по кнопке «👣»
  map.getPane('pathPane').style.display = 'none';
  markerLayer.addTo(map);
  regionLayer.addTo(map);
  anchorLayer.addTo(map);
  map.on('zoomend', () => { if (heatOn) drawHeat(); });
  buildRegionLabels();
  buildAnchors();
  map.on('zoomend', updateRegionLabels);
  map.on('click', () => document.getElementById('sheet').classList.remove('on'));
  map.on('contextmenu', e => {
    const x = e.latlng.lng - META.origin[0], y = -e.latlng.lat - META.origin[1];
    L.popup({ className: 'gm-card', maxWidth: 240 }).setLatLng(e.latlng)
      .setContent(`<div class="card-btns"><button class="primary" onclick="addCustomHere(${x.toFixed(1)}, ${y.toFixed(1)})">⭐ Своя точка здесь</button></div>` +
                  '<div class="card-muted">Сундук или что-то ещё, чего нет на карте</div>')
      .openOn(map);
  });
  map.on('dragstart', () => {                      // пользователь сам двигает карту
    setFollow(false);
    if (document.body.classList.contains('compact')) scheduleFollowResume();
  });
  map.on('moveend zoomend', debounce(function () { renderVisible(); reportState(); }, 100));
  updateRegionLabels();
}

function addViewControls() {
  const Ctl = L.Control.extend({
    onAdd: function () {
      const box = L.DomUtil.create('div', 'leaflet-bar gm-ctl');
      const home = L.DomUtil.create('a', '', box);
      home.innerHTML = '⌂'; home.title = 'Вся карта';
      home.onclick = () => { selectRegion(null); };
      meBtn = L.DomUtil.create('a', 'off', box);
      meBtn.innerHTML = '⌖'; meBtn.title = 'Показать игрока (нужно отслеживание позиции)';
      meBtn.onclick = () => { if (lastPlayer) map.setView(toLatLng(lastPlayer.x, lastPlayer.y), Math.max(map.getZoom(), 0)); };
      followBtn = L.DomUtil.create('a', 'off', box);
      followBtn.innerHTML = '◎'; followBtn.title = 'Следовать за игроком';
      followBtn.onclick = () => { if (lastPlayer) setFollow(!follow); };
      nearBtn = L.DomUtil.create('a', 'off', box);
      nearBtn.innerHTML = '🧰'; nearBtn.title = 'Вести к ближайшему несобранному сундуку';
      nearBtn.onclick = navNearestChest;
      const routeBtn = L.DomUtil.create('a', '', box);
      routeBtn.innerHTML = '🗺'; routeBtn.title = 'Маршрут по несобранным сундукам региона';
      routeBtn.onclick = () => (route ? clearTarget() : startRoute());
      const clearBtn = L.DomUtil.create('a', '', box);
      clearBtn.innerHTML = '🧹'; clearBtn.title = 'Зачистка региона: что осталось';
      clearBtn.onclick = () => toggleClear();
      L.DomEvent.disableClickPropagation(box);
      return box;
    },
  });
  new Ctl({ position: 'topright' }).addTo(map);
}

// ---------- Регионы ----------
function buildRegions() {
  const box = document.getElementById('regions');
  box.innerHTML = '';
  if (!REGIONS.length) return;
  const all = document.createElement('div');
  all.className = 'rg'; all.dataset.id = ''; all.textContent = 'Весь мир';
  all.onclick = () => selectRegion(null);
  box.appendChild(all);
  REGIONS.forEach(r => {
    const el = document.createElement('div');
    el.className = 'rg'; el.dataset.id = r.id;
    el.innerHTML = `${r.name}<span class="pc"></span>`;
    el.title = 'Показать регион (повторный клик — только перелёт)';
    el.onclick = () => selectRegion(r.id);
    box.appendChild(el);
  });
  highlightRegionChip();
}

function buildAnchors() {
  anchorLayer.clearLayers();
  for (const [name, x, y, lvl] of ANCHORS) {
    L.marker(toLatLng(x, y), { interactive: false, keyboard: false, pane: 'anchorPane',
      icon: L.divIcon({ className: '', iconSize: [0, 0],
        html: `<div class="gm-anchor l${lvl}">${esc(name)}</div>` }) }).addTo(anchorLayer);
  }
  updateRegionLabels();
}

// «где остались сундуки»: несобранные сундуки по клеткам, размер — сколько их
const HEAT_CELL_PX = 90;          // размер ячейки на экране: кружки не налезают
function drawHeat() {
  heatLayer.clearLayers();
  if (!heatOn) return;
  const a = map.latLngToLayerPoint(toLatLng(0, 0)), b = map.latLngToLayerPoint(toLatLng(1000, 0));
  const cell = HEAT_CELL_PX / (Math.abs(b.x - a.x) / 1000 || 1);   // в мировых единицах
  const cells = new Map();
  for (const [pid, [x, y, labelId]] of pointInfo) {
    if (COLLECTED.has(pid) || !isChestLabel(labelId)) continue;
    const k = `${Math.floor(x / cell)},${Math.floor(y / cell)}`;
    const c = cells.get(k) || { n: 0, sx: 0, sy: 0 };
    c.n++; c.sx += x; c.sy += y; cells.set(k, c);
  }
  for (const c of cells.values()) {
    const size = Math.round(Math.min(HEAT_CELL_PX * 0.9, 20 + 6 * Math.sqrt(c.n)));
    const m = L.marker(toLatLng(c.sx / c.n, c.sy / c.n), { keyboard: false,
      icon: L.divIcon({ className: '', iconSize: [0, 0],
        html: `<div class="gm-heat" style="width:${size}px;height:${size}px">${c.n}</div>` }) });
    m.bindTooltip(`Несобранных сундуков: ${c.n}`, { direction: 'top', className: 'gm-tip' });
    m.on('click', () => map.setView(m.getLatLng(), Math.max(map.getZoom() + 1.5, map.getMinZoom() + 2.5)));
    m.addTo(heatLayer);
  }
}
window.toggleHeat = function () {
  heatOn = !heatOn;
  if (heatOn) heatLayer.addTo(map); else map.removeLayer(heatLayer);
  drawHeat();
  alertNav(heatOn ? '🔥 Показано, где остались сундуки (цифра — сколько)' : 'Тепловая карта скрыта');
  if (clearOpen) document.getElementById('sheet-body').innerHTML = clearHtml();
};

function buildRegionLabels() {
  regionLayer.clearLayers();
  REGIONS.forEach(r => {
    const b = r.bbox;
    const c = toLatLng((b[0] + b[2]) / 2, (b[1] + b[3]) / 2);
    const m = L.marker(c, {
      icon: L.divIcon({ className: '', iconSize: [0, 0],
        html: `<div class="gm-region-lbl" data-rid="${r.id}">${r.name}<small></small></div>` }),
      keyboard: false, pane: 'regionPane',
    });
    m.on('click', () => selectRegion(r.id));
    m.addTo(regionLayer);
  });
}

function updateRegionLabels() {
  if (!map) return;
  // подписи нужны только на отдалении, когда виден весь мир
  const z = map.getZoom(), zmin = map.getMinZoom();
  const far = z <= zmin + 1.25;
  const el = document.getElementById('map');
  el.classList.toggle('hide-region-labels', !far);
  el.classList.toggle('show-a1', !far && z < zmin + 3);
  el.classList.toggle('show-a2', z >= zmin + 2.5);
}

function selectRegion(id, opts) {
  id = (id === null || id === undefined || id === '') ? null : Number(id);
  activeRegion = (id !== null && regionById[id]) ? id : null;
  highlightRegionChip();
  if (!(opts && opts.noFly)) {
    const target = activeRegion !== null ? bboxToBounds(regionById[activeRegion].bbox) : CONTENT_BOUNDS;
    setFollow(false);
    map.flyToBounds(target, { padding: activeRegion !== null ? [30, 30] : [0, 0], duration: 0.6 });
  }
  refreshCounts();
  renderVisible();
  reportState();
}

function highlightRegionChip() {
  document.querySelectorAll('#regions .rg').forEach(el => {
    const id = el.dataset.id === '' ? null : Number(el.dataset.id);
    el.classList.toggle('active', id === activeRegion);
  });
}

function inRegion(pt) { return activeRegion === null || pt[3] === activeRegion; }

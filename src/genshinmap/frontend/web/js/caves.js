// Пещеры и многоуровневые места: картинки этажей (appsample), входы, путь внутри.
// Режим «Пещеры»: поверхность затемнена, поверх — нарисованные этажи; точки
// подземелий видны только на выбранном этаже; входы подписаны.
let FLOORS = [];
const floorById = {};
const floorsByGroup = {};
const caveFloor = {};              // group -> выбранный этаж (floor id)
let caveMode = false;
let caveLayer = null, caveRouteLayer = null, cavePick = null;
const caveRoutes = {};             // pid -> 'loading' | {path, entrance, floor, approx} | null

// B1 выше B2; L1 ниже L2 — порядок как в игре: сверху вниз
function floorRank(name) {
  const m = /^([BL])(\d+)$/.exec(name || '');
  if (!m) return 0;
  return m[1] === 'B' ? Number(m[2]) : -Number(m[2]);
}

function initFloors(list) {
  FLOORS = list || [];
  for (const k in floorById) delete floorById[k];
  for (const k in floorsByGroup) delete floorsByGroup[k];
  for (const f of FLOORS) {
    floorById[f.id] = f;
    (floorsByGroup[f.group] = floorsByGroup[f.group] || []).push(f);
  }
  for (const g in floorsByGroup) {
    floorsByGroup[g].sort((a, b) => floorRank(a.name) - floorRank(b.name));
    if (!caveFloor[g]) caveFloor[g] = floorsByGroup[g][0].id;
  }
  caveLayer = caveLayer || L.layerGroup();
  caveRouteLayer = caveRouteLayer || L.layerGroup();
  if (map) { caveLayer.addTo(map); caveRouteLayer.addTo(map); }
  document.body.classList.toggle('has-caves', FLOORS.length > 0);
}

function floorOfPoint(pid) {
  const i = pointInfo.get(String(pid));
  return i && i[5] ? floorById[i[5]] || null : null;
}

// точка видна в текущем режиме? (в режиме пещер — только на выбранном этаже)
function caveVisible(p) {
  if (!caveMode || !p[5]) return true;
  const f = floorById[p[5]];
  return !f || caveFloor[f.group] === p[5];
}

function setCaveMode(on, silent) {
  caveMode = !!on;
  document.body.classList.toggle('cave-mode', caveMode);
  const b = document.getElementById('cave-toggle');
  if (b) { b.classList.toggle('on', caveMode); b.setAttribute('aria-pressed', String(caveMode)); }
  // маркеры пересоздаём: у точек поверхности в режиме пещер другой вид
  if (map) {
    markerLayer.clearLayers();
    for (const k in markerByPoint) delete markerByPoint[k];
  }
  renderCaves();
  if (!silent) renderVisible();
}
window.toggleCaves = () => setCaveMode(!caveMode);

function bboxHits(bb, view) {
  return bboxToBounds(bb).intersects(view);
}

function renderCaves() {
  if (!caveLayer || !map) return;
  caveLayer.clearLayers();
  if (!caveMode) { updateFloorPicker(); return; }
  // затемнение поверхности
  L.rectangle(map.getBounds().pad(4), { pane: 'cavePane', stroke: false, fillColor: '#05080F',
    fillOpacity: 0.62, interactive: false }).addTo(caveLayer);
  const view = map.getBounds().pad(0.3);
  for (const g in floorsByGroup) {
    const f = floorById[caveFloor[g]];
    if (!f || !bboxHits(f.bbox, view)) continue;
    L.imageOverlay(f.img, bboxToBounds(f.bbox), { pane: 'cavePane', opacity: 0.96,
      interactive: false, className: 'gm-floor' }).addTo(caveLayer);
    // входы этой пещеры
    (f.entrances || []).forEach((pid, i) => {
      const e = pointInfo.get(String(pid));
      if (!e) return;
      L.marker(toLatLng(e[0], e[1]), { pane: 'caveLabelPane', keyboard: false,
        icon: L.divIcon({ className: '', iconSize: [0, 0],
          html: `<div class="gm-entry" title="Вход в пещеру">${ICON('cave')}<span>Вход ${i + 1}</span></div>` }) })
        .on('click', () => openCard(String(pid))).addTo(caveLayer);
    });
  }
  updateFloorPicker();
}

// пещера в центре экрана — для переключателя этажей
function caveAtCenter() {
  const c = map.getCenter();
  let best = null, bestA = Infinity;
  for (const g in floorsByGroup) {
    for (const f of floorsByGroup[g]) {
      const b = bboxToBounds(f.bbox);
      if (!b.contains(c)) continue;
      const a = Math.abs((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]));
      if (a < bestA) { bestA = a; best = g; }         // самая «плотная» — вложенные пещеры
    }
  }
  return best;
}

function updateFloorPicker() {
  const box = document.getElementById('floor-pick');
  if (!box) return;
  const g = caveMode ? caveAtCenter() : null;
  const fl = g ? floorsByGroup[g] : null;
  if (!fl) { box.classList.remove('on'); box.innerHTML = ''; cavePick = null; return; }
  if (cavePick === g + ':' + caveFloor[g]) { box.classList.add('on'); return; }
  cavePick = g + ':' + caveFloor[g];
  const n = (fl[0].entrances || []).length;
  let h = `<div class="fp-h">${ICON('cave')}<span>Пещера</span>` +
          `<span class="fp-sub">${n ? 'входов: ' + n : 'вход не найден'}</span></div><div class="fp-row">`;
  for (const f of fl) {
    const on = caveFloor[g] === f.id;
    h += `<button class="${on ? 'on' : ''}" aria-pressed="${on}" onclick="pickFloor(${g}, ${f.id})">${esc(f.name)}</button>`;
  }
  box.innerHTML = h + '</div>';
  box.classList.add('on');
}
window.pickFloor = function (g, fid) {
  caveFloor[g] = fid;
  cavePick = null;
  renderCaves();
  markerLayer.clearLayers();
  for (const k in markerByPoint) delete markerByPoint[k];
  renderVisible();
};

// Показать пещеру точки: режим пещер, её этаж, приблизить к пещере
window.showCave = function (pid) {
  const f = floorOfPoint(pid);
  if (!f) return;
  caveFloor[f.group] = f.id;
  cavePick = null;
  closeCard();
  setCaveMode(true, true);
  const all = floorsByGroup[f.group].map(x => bboxToBounds(x.bbox));
  const b = all.reduce((a, x) => a.extend(x), L.latLngBounds(all[0].getSouthWest(), all[0].getNorthEast()));
  map.fitBounds(b, { padding: [30, 30], maxZoom: 1 });
  setTimeout(() => { renderCaves(); renderVisible(); highlightPoint(String(pid), false); }, 350);
};

// Путь от входа до точки внутри пещеры — считает Python (A* по картинке этажа)
window.loadCaveRoute = function (pid) {
  pid = String(pid);
  caveRoutes[pid] = 'loading';
  refreshCard(pid);
  if (bridge && bridge.request_cave_route) bridge.request_cave_route(pid);
  else { caveRoutes[pid] = null; refreshCard(pid); }
};
window.showCaveRoute = function (pid, data) {
  pid = String(pid);
  caveRoutes[pid] = data && data.path && data.path.length > 1 ? data : null;
  refreshCard(pid);
  drawCaveRoute(pid);
};
function drawCaveRoute(pid) {
  if (!caveRouteLayer) return;
  caveRouteLayer.clearLayers();
  const r = caveRoutes[pid];
  if (!r || r === 'loading') return;
  const f = floorById[r.floor];
  if (f) { caveFloor[f.group] = f.id; cavePick = null; }
  if (!caveMode) setCaveMode(true, true);
  const ll = r.path.map(p => toLatLng(p[0], p[1]));
  L.polyline(ll, { pane: 'caveLabelPane', color: '#05080F', weight: 9, opacity: 0.55,
    interactive: false }).addTo(caveRouteLayer);
  L.polyline(ll, { pane: 'caveLabelPane', color: '#E8B84A', weight: 4, opacity: 0.95,
    dashArray: r.approx ? '2 8' : null, lineCap: 'round', interactive: false,
    className: r.approx ? '' : 'gm-nav-line' }).addTo(caveRouteLayer);
  map.fitBounds(L.latLngBounds(ll), { padding: [60, 60], maxZoom: 1 });
  setTimeout(() => { renderCaves(); renderVisible(); }, 300);
}
window.clearCaveRoute = function () { if (caveRouteLayer) caveRouteLayer.clearLayers(); };

// блок карточки: пещера этой точки, этаж, входы, путь
function caveCardHtml(pid) {
  const f = floorOfPoint(pid);
  if (!f) return '';
  const fl = floorsByGroup[f.group] || [f];
  const n = (f.entrances || []).length;
  const r = caveRoutes[pid];
  let h = `<section class="card-sec cave"><div class="sec-h">${ICON('cave')}Пещера · этаж <b>${esc(f.name)}</b>` +
          (fl.length > 1 ? `<span class="sec-sub">из ${fl.length}: ${fl.map(x => esc(x.name)).join(', ')}</span>` : '') +
          `</div><div class="sec-txt">${n ? `Входов у пещеры: ${n}. Они же — выходы.` : 'Вход в пещеру на карте не найден.'}</div>` +
          `<div class="card-btns"><button onclick="showCave('${pid}')">${ICON('layers')}Карта пещеры</button>`;
  if (n) h += `<button onclick="loadCaveRoute('${pid}')">${ICON('route')}Путь от входа</button>`;
  h += '</div>';
  if (r === 'loading') h += '<div class="card-muted">Ищу путь от входа по карте пещеры…</div>';
  else if (r === null) h += '<div class="card-muted">Путь внутри пещеры построить не удалось</div>';
  else if (r) {
    h += `<div class="sec-txt">${ICON('route', 'inl')}От входа ${r.entrance_no || ''} · ~${Math.round(r.length)} ед.` +
         (r.approx ? ' · <span class="warn">примерно: вход ведёт на другой этаж, лестниц на карте нет</span>' : '') + '</div>';
  }
  return h + '</section>';
}

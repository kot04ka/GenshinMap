// Маркеры точек (только видимая область) и позиция игрока.
// ---------- Маркеры ----------
const LAYER_TEXT = { 1: ICON('cave') + 'В пещере / под землёй — ищи вход',
                     2: ICON('water') + 'Под водой', 3: ICON('down') + 'Нижний уровень' };

// сундуки, связанные с заданием (по тексту описаний) — присылает Python
const QUEST = new Set();
window.setQuestFlags = function (ids, on) {
  for (const pid of ids) {
    const k = String(pid);
    if (on) QUEST.add(k); else QUEST.delete(k);
    const e = markerByPoint[k] && markerByPoint[k].marker.getElement();
    const ico = e && e.querySelector('.gm-ico');
    if (ico) { if (on) ico.dataset.quest = '1'; else delete ico.dataset.quest; }
  }
};
window.questGo = function (pid) { setTarget(String(pid)); };
window.questDone = function (name, done) {
  if (bridge && bridge.on_quest_done) bridge.on_quest_done(name, !!done);
};

function makeIcon(labelId, collected, probable, layer, quest, level) {
  const url = iconUrl(labelId);
  const onerr = "this.style.display='none';this.parentNode.classList.add('gm-fallback')";
  return L.divIcon({
    className: '',
    html: `<div class="gm-ico${collected ? ' collected' : ''}${probable ? ' probable' : ''}"` +
          `${layer ? ` data-layer="${layer}"` : ''}${quest ? ' data-quest="1"' : ''}${level === 'surface' ? ' data-surface="1"' : level ? ' data-other="1"' : ''}>` +
          `<img src="${url}" onerror="${onerr}">` +
          `${level && level !== 'surface' ? `<span class="gm-lvl">${level}</span>` : ''}</div>`,
    iconSize: [30, 30], iconAnchor: [15, 15],
  });
}

// Рендерим ТОЛЬКО иконки видимой области (viewport culling), инкрементально
// добавляя/убирая по краям — DOM-элементов мало, панорама плавная.
let MAX_MARKERS = 1200;   // лимит одновременно показанных иконок (настраивается)
const CELL_PX = 38;       // размер ячейки прореживания (иконка + зазор)

function tipText(labelId, collected, area, probable) {
  const lbl = labelById[labelId];
  const rg = regionById[area];
  const mark = probable ? ' ?' : (collected ? ' ✓' : '');
  const lay = (arguments[4] && LAYER_TEXT[arguments[4]]) ? `<div class="sub">${LAYER_TEXT[arguments[4]]}</div>` : '';
  return `${lbl ? lbl.name : ''}${mark}` +
         (probable ? '<div class="sub">вероятно собрано (не найдено на месте) — клик: подтвердить</div>' : '') +
         lay + (rg ? `<div class="sub">${rg.name}</div>` : '');
}

function addMarker(pid, x, y, labelId, area) {
  const collected = COLLECTED.has(pid), probable = PROBABLE.has(pid);
  const layer = (pointInfo.get(pid) || [])[4] || 0;
  // в режиме пещер точки поверхности и других этажей приглушены (клик — перейти туда)
  const m = L.marker(toLatLng(x, y), { icon: makeIcon(labelId, collected, probable, layer, QUEST.has(pid), levelOf(pid)) });
  m.bindTooltip(tipText(labelId, collected, area, probable, layer),
                { className: 'gm-tip', direction: 'top', offset: [0, -10] });
  m.on('click', () => openCard(pid));
  m.on('contextmenu', () => { if (bridge) bridge.on_marker_clicked(pid); });   // быстрая отметка
  m.addTo(markerLayer);
  markerByPoint[pid] = { marker: m, labelId, x, y, area };
}

function renderVisible() {
  if (!map) return;
  const b = map.getBounds().pad(0.15);
  const N = b.getNorth(), S = b.getSouth(), E = b.getEast(), Wb = b.getWest();
  const ox = META.origin[0], oy = META.origin[1];

  // 1) все точки включённых слоёв в кадре (несобранные — в приоритете)
  const fresh = [], done = [];
  for (const labelId of enabled) {
    const pts = POINTS_BY_LABEL[labelId] || [];
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const lat = -(oy + p[2]), lng = ox + p[1];
      if (lat > N || lat < S || lng < Wb || lng > E || !inRegion(p)) continue;
      const pid = String(p[0]);
      if (COLLECTED.has(pid)) { if (!hideCollected) done.push([pid, p, labelId, lat, lng]); }
      else fresh.push([pid, p, labelId, lat, lng]);
    }
  }
  const all = fresh.concat(done);

  // 2) если точек больше лимита — прореживаем РАВНОМЕРНО по сетке экрана,
  //    а не «первые N по списку» (иначе на отдалении иконки только в одном углу)
  let chosen = all, thinned = false;
  if (all.length > MAX_MARKERS) {
    thinned = true;
    const cell = CELL_PX / Math.pow(2, map.getZoom());   // размер ячейки в пикселях карты
    chosen = thin(all, cell, true);                      // по ячейке + категории
    if (chosen.length > MAX_MARKERS) chosen = thin(all, cell, false);
    if (chosen.length > MAX_MARKERS) chosen = thin(all, cell * 2, false);
    if (chosen.length > MAX_MARKERS) chosen = chosen.slice(0, MAX_MARKERS);
  }

  const need = new Set();
  for (const [pid, p, labelId] of chosen) {
    need.add(pid);
    if (!markerByPoint[pid]) addMarker(pid, p[1], p[2], labelId, p[3]);
  }
  for (const pid in markerByPoint) {
    if (!need.has(pid)) {
      markerLayer.removeLayer(markerByPoint[pid].marker);
      delete markerByPoint[pid];
    }
  }
  lastRenderInfo = { shown: chosen.length, inView: all.length, thinned };
  updateStat();
}

function thin(list, cell, perLabel) {
  const seen = new Set(), out = [];
  for (const it of list) {
    const key = Math.floor(it[4] / cell) + ':' + Math.floor(it[3] / cell) + (perLabel ? ':' + it[2] : '');
    if (seen.has(key)) continue;
    seen.add(key); out.push(it);
  }
  return out;
}

function debounce(fn, ms) {
  let t; return function () { clearTimeout(t); t = setTimeout(fn, ms); };
}

// ---------- Игрок (позиция по мини-карте) ----------
function setPlayer(x, y, score, weak) {
  lastPlayer = { x, y, score };
  const ll = toLatLng(x, y);
  if (!playerMarker) {
    playerMarker = L.marker(ll, {
      icon: L.divIcon({ className: '', iconSize: [22, 22], iconAnchor: [11, 11],
                        html: '<div class="gm-player"><div class="ring"></div><div class="dot"></div></div>' }),
      interactive: false, zIndexOffset: 5000, keyboard: false,
    }).addTo(map);
  } else {
    playerMarker.setLatLng(ll);
  }
  const el = playerMarker.getElement();
  if (el) el.querySelector('.gm-player').classList.toggle('weak', !!weak);
  meBtn.classList.remove('off'); followBtn.classList.remove('off'); nearBtn.classList.remove('off');
  refreshClearSoon();
  document.getElementById('mb-follow').classList.remove('off');
  document.getElementById('mb-chest').classList.remove('off');
  updateNav();
  if (follow) map.panTo(ll, { animate: true, duration: 0.4 });
  else if (followWanted && !followTimer) setFollow(true);   // первая позиция в мини-режиме
}

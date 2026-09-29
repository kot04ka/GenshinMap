// Ведение к цели: путь, телепорты, маршрут по сундукам, мини-панель кнопок.
// ---------- Навигация: линия от игрока до цели ----------
let navPid = null, navLine = null, nearBtn = null;
const ARROWS = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'];

window.setTarget = function (pid, opts) {
  pid = String(pid);
  if (!pointInfo.get(pid)) return;
  if (!(opts && opts.fromRoute)) stopRoute();       // ручная цель — маршрут сбрасываем
  if (navPid !== pid) navPath = null;              // новый путь придёт из Python
  navPid = pid;
  closeCard();
  const [x, y, labelId] = pointInfo.get(pid);
  if (!enabled.has(labelId)) enableCategory(labelId);
  updateNav();
  reportTarget();
  if (opts && opts.noFit) return;
  if (lastPlayer) map.fitBounds(L.latLngBounds([toLatLng(x, y), toLatLng(lastPlayer.x, lastPlayer.y)]).pad(0.3), { maxZoom: 0.5 });
  else map.setView(toLatLng(x, y), Math.max(map.getZoom(), 0));
};

// путь по местности (строит Python, A*)
let navPath = null;
window.setNavPath = function (pts) { navPath = pts && pts.length > 1 ? pts : null; updateNav(); };
function pathNearest(p, x, y) {
  let bi = 0, bd = Infinity;
  for (let i = 0; i < p.length - 1; i++) {
    const [ax, ay] = p[i], [bx, by] = p[i + 1], vx = bx - ax, vy = by - ay;
    const t = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / ((vx * vx + vy * vy) || 1e-9)));
    const d = Math.hypot(x - (ax + t * vx), y - (ay + t * vy));
    if (d < bd) { bd = d; bi = i; }
  }
  return bi;
}
function pathLookahead(p, x, y, ahead) {
  const i0 = pathNearest(p, x, y);
  let cur = [x, y], rest = 0, target = null;
  for (let j = i0 + 1; j < p.length; j++) {
    const seg = Math.hypot(p[j][0] - cur[0], p[j][1] - cur[1]);
    if (!target && rest + seg >= ahead) {
      const k = (ahead - rest) / (seg || 1e-9);
      target = [cur[0] + (p[j][0] - cur[0]) * k, cur[1] + (p[j][1] - cur[1]) * k];
    }
    rest += seg; cur = p[j];
  }
  const t = target || p[p.length - 1];
  return { x: t[0], y: t[1], rest };
}

function clearTarget() {
  navPid = null;
  navPath = null;
  tpHint = null;
  caveVia = caveInside = null;
  if (navLine) { map.removeLayer(navLine); navLine = null; }
  if (tpLine) { map.removeLayer(tpLine); tpLine = null; }
  document.getElementById('nav').classList.remove('on', 'here', 'tp');
  stopRoute();
  reportTarget();
}
window.clearTarget = clearTarget;          // хоткей «перестать вести» из Python

// цель -> Python (HUD поверх игры: стрелка у мини-карты, подсказка, звук)
function reportTarget() {
  if (!bridge || !bridge.on_target_changed) return;
  if (!navPid) { bridge.on_target_changed(''); return; }
  const [x, y, labelId] = pointInfo.get(navPid);
  const st = routeStep();
  bridge.on_target_changed(JSON.stringify({
    pid: navPid, x, y, name: (labelById[labelId] || {}).name || '',
    left: st ? st[1] - st[0] + 1 : 0, step: st,
    layer: pointInfo.get(navPid)[4] || 0,
    tp: tpHint ? { x: tpHint.x, y: tpHint.y, name: tpHint.name } : null,
    via: caveVia ? { x: caveVia.x, y: caveVia.y } : null, show_path: showPath }));
}

// ---------- Телепорты: куда можно прыгнуть ----------
// Открытыми считаем телепорты и статуи, отмеченные как активированные.
const TP_PENALTY = 110;      // «цена» телепорта в единицах пути (загрузка, выход)
const WALK_K = 1.25;         // путь по местности длиннее прямой
let NAV_OPTS = { autoNext: true, useTp: true };
let showPath = false;          // линии пути — только по кнопке «👣» (не навязчиво)
window.togglePath = function (on) {
  showPath = typeof on === 'boolean' ? on : !showPath;
  if (map) map.getPane('pathPane').style.display = showPath ? '' : 'none';
  document.getElementById('nav-path').classList.toggle('on', showPath);
  reportTarget();
};
window.setNavOptions = function (o) { NAV_OPTS = Object.assign(NAV_OPTS, o || {}); tpCache = null; };
let tpCache = null, tpCacheT = 0;
function openTps() {
  const now = Date.now();
  if (NAV_OPTS.useTp === false) return [];
  if (tpCache && now - tpCacheT < 5000) return tpCache;
  const out = [];
  for (const [pid, [x, y, labelId]] of pointInfo) {
    const l = labelById[labelId];
    if (l && (l.kind === 'teleport' || l.kind === 'statue') && COLLECTED.has(pid)) out.push([pid, x, y, l.kind]);
  }
  tpCache = out; tpCacheT = now;
  return out;
}
function nearestTp(x, y, tps) {
  let best = null, bd = Infinity;
  for (const t of tps) {
    const d = Math.hypot(t[1] - x, t[2] - y);
    if (d < bd) { bd = d; best = t; }
  }
  return best ? { pid: best[0], x: best[1], y: best[2], kind: best[3], d: bd } : null;
}
// подпись телепорта — ближайшее название места
function placeName(x, y) {
  let best = '', bd = Infinity;
  for (const [name, ax, ay, lvl] of ANCHORS) {
    const d = Math.hypot(ax - x, ay - y) * (lvl === 2 ? 1 : 1.6);
    if (d < bd) { bd = d; best = name; }
  }
  return bd < 900 ? best : '';
}
// как добраться от (sx, sy) до (x, y): пешком или ТП + пешком — что дешевле
function legPlan(sx, sy, x, y, tps) {
  const walk = WALK_K * Math.hypot(x - sx, y - sy);
  const tp = nearestTp(x, y, tps);
  if (tp && TP_PENALTY + WALK_K * tp.d < walk) return { tp, cost: TP_PENALTY + WALK_K * tp.d };
  return { tp: null, cost: walk };
}

// ---------- Маршрут по несобранным сундукам региона ----------
let route = null, routeSkipped = new Set(), routeLine = null, routeTpLine = null, routeMarks = null;
let tpHint = null, tpLine = null, caveVia = null, caveInside = null;
// вход в пещеру для цели под землёй/под водой: ближайшая метка «Пещера» рядом с целью
const CAVE_MAX = 300;       // дальше — это уже вход в другую пещеру
const CAVE_REACHED = 15;    // дошёл до входа — дальше ведём к самой цели
function caveEntry(x, y) {
  let best = null, bd = CAVE_MAX;
  for (const [pid, [cx, cy, labelId]] of pointInfo) {
    const l = labelById[labelId];
    if (!l || l.kind !== 'cave') continue;
    const d = Math.hypot(cx - x, cy - y);
    if (d < bd) { bd = d; best = { pid, x: cx, y: cy, d }; }
  }
  return best;
}

function isChestLabel(labelId) {
  const l = labelById[labelId];
  return !!l && l.kind === 'chest';
}

// Порядок обхода: ближайший сосед + 2-opt по НАСТОЯЩЕЙ цене участка
// (пешком или телепорт к ближайшему открытому ТП — что выгоднее).
function planRoute(sx, sy, ids, tps) {
  const P = ids.map(pid => pointInfo.get(pid)), n = ids.length;
  const dtp = P.map(p => { const t = nearestTp(p[0], p[1], tps); return t ? t.d : Infinity; });
  const cost = (i, j) => {
    const a = i < 0 ? [sx, sy] : P[i], b = P[j];
    return Math.min(WALK_K * Math.hypot(b[0] - a[0], b[1] - a[1]), TP_PENALTY + WALK_K * dtp[j]);
  };
  const used = new Array(n).fill(false);
  let order = [], cur = -1;
  for (let k = 0; k < n; k++) {
    let bi = -1, bc = Infinity;
    for (let i = 0; i < n; i++) if (!used[i]) { const c = cost(cur, i); if (c < bc) { bc = c; bi = i; } }
    used[bi] = true; order.push(bi); cur = bi;
  }
  // 2-opt: разворот участка i..j. Цена несимметрична (телепорт считается к точке
  // назначения), поэтому внутренние участки тоже пересчитываем — накопительно, O(1) на пару.
  for (let pass = 0, improved = true; improved && pass < 8; pass++) {
    improved = false;
    for (let i = 0; i < n - 1; i++) {
      const prev = i === 0 ? -1 : order[i - 1];
      let inBefore = 0, inAfter = 0;
      for (let j = i + 1; j < n; j++) {
        inBefore += cost(order[j - 1], order[j]);
        inAfter += cost(order[j], order[j - 1]);
        const next = j + 1 < n ? order[j + 1] : null;
        const before = cost(prev, order[i]) + inBefore + (next === null ? 0 : cost(order[j], next));
        const after = cost(prev, order[j]) + inAfter + (next === null ? 0 : cost(order[i], next));
        if (after < before - 1e-6) {
          const seg = order.slice(i, j + 1).reverse();
          order.splice(i, seg.length, ...seg);
          improved = true;
          inBefore = inAfter = 0;
          for (let k = i + 1; k <= j; k++) {           // пересчёт накоплений после разворота
            inBefore += cost(order[k - 1], order[k]);
            inAfter += cost(order[k], order[k - 1]);
          }
        }
      }
    }
  }
  return order.map(i => ids[i]);
}

function routeLeft() { return route ? route.filter(pid => !COLLECTED.has(pid) && !routeSkipped.has(pid)) : []; }
// [номер текущей точки, всего] — для плашки и HUD
function routeStep() {
  if (!route || !navPid) return null;
  const i = route.indexOf(navPid);
  return i < 0 ? null : [i + 1, route.length];
}

window.startRoute = function () {
  if (!lastPlayer) { alertNav('Маршрут: включи отслеживание позиции'); return; }
  // регион — тот, где стоит игрок (по ближайшей точке), а не выбранный фильтр:
  // иначе при выбранном «Ли Юэ» стрелка повела бы из Мондштадта через полмира
  let area = null, bd = Infinity;
  for (const [, [x, y, , a]] of pointInfo) {
    const d = Math.hypot(x - lastPlayer.x, y - lastPlayer.y);
    if (d < bd) { bd = d; area = a; }
  }
  if (activeRegion !== null && activeRegion !== area) selectRegion(area, { noFly: true });
  // только включённые на карте виды сундуков (выключил «Деревянный с морой» — его нет)
  const shown = LABELS.some(l => l.kind === 'chest' && enabled.has(l.id));
  const ids = [];
  let questSkipped = 0;
  for (const [pid, [, , labelId, a]] of pointInfo) {
    if (!(a === area && isChestLabel(labelId) && !COLLECTED.has(pid) && (!shown || enabled.has(labelId)))) continue;
    if (QUEST.has(pid)) { questSkipped++; continue; }     // нужен квест — не бегаем зря
    ids.push(pid);
  }
  if (!ids.length) { alertNav('В этом регионе все сундуки собраны 🎉'); return; }
  tpCache = null;
  const tps = openTps();
  route = planRoute(lastPlayer.x, lastPlayer.y, ids, tps);
  if (questSkipped)
    showMapTip(`🔒 Не в маршруте: ${questSkipped} сундуков, для которых нужно задание (значок 🔒).`, 7000);
  else if (NAV_OPTS.useTp !== false && tps.length < 3)
    showMapTip('🌀 Отметь на карте открытые телепорты (клик по значку → «Собрано») — маршрут начнёт '
               + 'предлагать прыжки и станет короче.', 9000);
  routeSkipped = new Set();
  document.getElementById('mb-route').classList.add('on');
  document.getElementById('nav').classList.add('route');
  setTarget(route[0], { fromRoute: true });
  drawRoute();
};

function stopRoute() {
  if (!route) return;
  route = null;
  routeSkipped = new Set();
  for (const l of [routeLine, routeTpLine, routeMarks]) if (l) map.removeLayer(l);
  routeLine = routeTpLine = routeMarks = null;
  document.getElementById('mb-route').classList.remove('on');
  document.getElementById('nav').classList.remove('route');
}

// Линия маршрута: пешие участки — пунктир, прыжки телепортом — фиолетовым от ТП;
// номера следующих точек (как в списке задач).
const ROUTE_NUMBERS = 40;
const LAYER_ICON = { 1: '🕳', 2: '🌊', 3: '⬇' };
const LAYER_SHORT = { 1: ' · 🕳 в пещере', 2: ' · 🌊 под водой', 3: ' · ⬇ нижний уровень' };
function drawRoute() {
  if (!route) return;
  const tps = openTps();
  const left = routeLeft();
  const walk = [], jumps = [];
  let prev = lastPlayer ? [lastPlayer.x, lastPlayer.y] : null;
  for (const pid of left) {
    const [x, y] = pointInfo.get(pid);
    if (prev) {
      const lp = legPlan(prev[0], prev[1], x, y, tps);
      if (lp.tp) jumps.push([toLatLng(lp.tp.x, lp.tp.y), toLatLng(x, y)]);
      else walk.push([toLatLng(prev[0], prev[1]), toLatLng(x, y)]);
    }
    prev = [x, y];
  }
  if (!routeLine) routeLine = L.polyline(walk, { pane: 'pathPane', color: '#8ea1c2', weight: 2, opacity: .75,
                                                 dashArray: '4 8', interactive: false }).addTo(map);
  else routeLine.setLatLngs(walk);
  if (!routeTpLine) routeTpLine = L.polyline(jumps, { pane: 'pathPane', color: '#b58cff', weight: 2.5, opacity: .9,
                                                     dashArray: '2 6', interactive: false }).addTo(map);
  else routeTpLine.setLatLngs(jumps);
  if (routeMarks) map.removeLayer(routeMarks);
  routeMarks = L.layerGroup();
  left.slice(0, ROUTE_NUMBERS).forEach(pid => {
    const [x, y] = pointInfo.get(pid);
    const k = route.indexOf(pid) + 1;
    const lay = LAYER_ICON[(pointInfo.get(pid) || [])[4] || 0] || '';
    L.marker(toLatLng(x, y), { interactive: false, keyboard: false, pane: 'regionPane',
      icon: L.divIcon({ className: '', iconSize: [0, 0],
        html: `<div class="gm-rnum${pid === navPid ? ' cur' : ''}${lay ? ' under' : ''}">${k}${lay}</div>` }) }).addTo(routeMarks);
  });
  routeMarks.addTo(map);
}

// цель маршрута собрана (или пропущена) — к следующей
function advanceRoute() {
  const next = routeLeft()[0];
  if (next) { setTarget(next, { fromRoute: true, noFit: true }); drawRoute(); }
  else { alertNav('Маршрут пройден: все сундуки региона собраны 🎉'); clearTarget(); }
}
window.skipRoutePoint = function () {
  if (!route || !navPid) return;
  routeSkipped.add(navPid);
  advanceRoute();
};

// цель-сундук собрана без маршрута — сразу ведём к ближайшему следующему
// (выключается в ⚙ Настройках: «Вести к следующему сундуку сам»)
const CHAIN_MAX = 450;
function chainNext() {
  const done = pointInfo.get(navPid);
  if (!NAV_OPTS.autoNext || !lastPlayer || !done || !isChestLabel(done[2])) return false;
  let best = null, bd = CHAIN_MAX;
  for (const [pid, [x, y, labelId]] of pointInfo) {
    if (COLLECTED.has(pid) || !enabled.has(labelId) || !isChestLabel(labelId)) continue;
    const d = Math.hypot(x - lastPlayer.x, y - lastPlayer.y);
    if (d < bd) { bd = d; best = pid; }
  }
  if (!best) return false;
  setTarget(best, { noFit: true });
  return true;
}

function alertNav(text) {
  const nav = document.getElementById('nav');
  nav.classList.add('on');
  document.getElementById('nav-txt').textContent = text;
  setTimeout(() => { if (!navPid) nav.classList.remove('on'); }, 4000);
}
document.getElementById('nav-x').onclick = clearTarget;
document.getElementById('nav-skip').onclick = () => window.skipRoutePoint();
document.getElementById('nav-path').onclick = () => window.togglePath();

function updateNav() {
  if (!navPid) return;
  if (COLLECTED.has(navPid) && !PROBABLE.has(navPid)) {
    if (route) advanceRoute(); else if (!chainNext()) clearTarget();
    return;
  }
  const [x, y, labelId] = pointInfo.get(navPid);
  const nav = document.getElementById('nav');
  const name = (labelById[labelId] || {}).name || '';
  const st = routeStep();
  const prefix = st ? `[${st[0]}/${st[1]}] ` : '';
  const layerTxt = LAYER_SHORT[pointInfo.get(navPid)[4] || 0] || '';
  nav.classList.add('on');
  if (!lastPlayer) {
    document.getElementById('nav-txt').textContent = `${prefix}${name} — включи отслеживание позиции`;
    return;
  }
  // далеко, а открытый телепорт рядом с целью — подсказываем прыжок
  const lp = legPlan(lastPlayer.x, lastPlayer.y, x, y, openTps());
  const hint = lp.tp ? { pid: lp.tp.pid, x: lp.tp.x, y: lp.tp.y, d: lp.tp.d,
                         name: placeName(lp.tp.x, lp.tp.y) } : null;
  if ((hint && hint.pid) !== (tpHint && tpHint.pid)) { tpHint = hint; reportTarget(); }
  tpHint = hint;
  nav.classList.toggle('tp', !!hint);
  if (hint) {
    if (navLine) { map.removeLayer(navLine); navLine = null; }
    const pts = [toLatLng(hint.x, hint.y), toLatLng(x, y)];
    if (!tpLine) tpLine = L.polyline(pts, { pane: 'pathPane', color: '#b58cff', weight: 3, opacity: .95,
                                            className: 'gm-nav-line', interactive: false }).addTo(map);
    else tpLine.setLatLngs(pts);
    nav.querySelector('.arrow').textContent = '🌀';
    nav.classList.remove('here');
    document.getElementById('nav-txt').textContent =
      `${prefix}ТП${hint.name ? ' у «' + hint.name + '»' : ''} → ${name} · ${Math.round(hint.d)} ед. от ТП${layerTxt}`;
    return;
  }
  if (tpLine) { map.removeLayer(tpLine); tpLine = null; }
  // под землёй/под водой: сначала ко входу в пещеру (пока не дошёл до него)
  const lay = pointInfo.get(navPid)[4] || 0;
  let via = null;
  if ((lay === 1 || lay === 2) && caveInside !== navPid) {
    const e = caveEntry(x, y);
    if (e && Math.hypot(e.x - lastPlayer.x, e.y - lastPlayer.y) <= CAVE_REACHED) caveInside = navPid;
    else via = e;
  }
  if ((via && via.pid) !== (caveVia && caveVia.pid)) { caveVia = via; reportTarget(); }
  caveVia = via;
  if (via) {
    const dv = Math.hypot(via.x - lastPlayer.x, via.y - lastPlayer.y);
    const ang = (Math.atan2(via.x - lastPlayer.x, -(via.y - lastPlayer.y)) * 180 / Math.PI + 360) % 360;
    nav.querySelector('.arrow').textContent = ARROWS[Math.round(ang / 45) % 8];
    nav.classList.remove('here');
    document.getElementById('nav-txt').textContent =
      `${prefix}🕳 К входу в пещеру · ${Math.round(dv)} ед. (${name} внутри, ~${Math.round(via.d)} ед. от входа)`;
    const vpts = navPath && navPath.length > 1
      ? [toLatLng(lastPlayer.x, lastPlayer.y)].concat(navPath.slice(pathNearest(navPath, lastPlayer.x, lastPlayer.y) + 1).map(p => toLatLng(p[0], p[1])), [toLatLng(x, y)])
      : [toLatLng(lastPlayer.x, lastPlayer.y), toLatLng(via.x, via.y), toLatLng(x, y)];
    if (!navLine) navLine = L.polyline(vpts, { pane: 'pathPane', color: '#58a6ff', weight: 3, opacity: .9,
                                               className: 'gm-nav-line', interactive: false }).addTo(map);
    else navLine.setLatLngs(vpts);
    return;
  }
  let dx = x - lastPlayer.x, dy = y - lastPlayer.y;
  let d = Math.hypot(dx, dy);
  if (navPath && navPath.length > 1 && d >= 12) {        // по пути: к точке впереди
    const la = pathLookahead(navPath, lastPlayer.x, lastPlayer.y, 35);
    dx = la.x - lastPlayer.x; dy = la.y - lastPlayer.y; d = Math.max(d, la.rest);
  }
  const ang = (Math.atan2(dx, -dy) * 180 / Math.PI + 360) % 360;   // 0 = север (вверх)
  nav.querySelector('.arrow').textContent = d < 12 ? '📍' : ARROWS[Math.round(ang / 45) % 8];
  nav.classList.toggle('here', d < 12);
  document.getElementById('nav-txt').textContent =
    prefix + (d < 12 ? `${name} — ты на месте` : `${name} — ${Math.round(d)} ед.`) + layerTxt;
  const pts = navPath && navPath.length > 1
    ? [toLatLng(lastPlayer.x, lastPlayer.y)].concat(navPath.slice(pathNearest(navPath, lastPlayer.x, lastPlayer.y) + 1).map(p => toLatLng(p[0], p[1])))
    : [toLatLng(lastPlayer.x, lastPlayer.y), toLatLng(x, y)];
  if (!navLine) navLine = L.polyline(pts, { pane: 'pathPane', color: '#58a6ff', weight: 3, opacity: .9,
                                            className: 'gm-nav-line', interactive: false }).addTo(map);
  else navLine.setLatLngs(pts);
}

// нижняя панель мини-режима
document.getElementById('mb-in').onclick = () => map.zoomIn(0.5);
document.getElementById('mb-out').onclick = () => map.zoomOut(0.5);
document.getElementById('mb-home').onclick = () => selectRegion(null);
document.getElementById('mb-chest').onclick = () => navNearestChest();
document.getElementById('mb-route').onclick = () => (route ? clearTarget() : startRoute());
document.getElementById('mb-clear').onclick = () => toggleClear();
document.getElementById('mb-follow').onclick = () => {
  if (!lastPlayer) return;
  setFollow(!follow);
  followWanted = follow;             // выключил вручную — не возвращать само
};

function navNearestChest() {
  if (!lastPlayer) return;
  let best = null, bd = Infinity;
  for (const [pid, [x, y, labelId]] of pointInfo) {
    const lbl = labelById[labelId];
    if (!lbl || lbl.kind !== 'chest' || COLLECTED.has(pid)) continue;
    const d = Math.hypot(x - lastPlayer.x, y - lastPlayer.y);
    if (d < bd) { bd = d; best = pid; }
  }
  if (best) setTarget(best);
}

function clearPlayer() {
  lastPlayer = null;
  if (playerMarker) { map.removeLayer(playerMarker); playerMarker = null; }
  setFollow(false);
  if (meBtn) { meBtn.classList.add('off'); followBtn.classList.add('off'); }
}

// В мини-режиме карта следует за игроком; если сдвинул её рукой — через
// FOLLOW_RESUME_MS без касаний снова возвращается к игроку.
const FOLLOW_RESUME_MS = 6000;
let followWanted = false, followTimer = null;
function scheduleFollowResume() {
  clearTimeout(followTimer);
  followTimer = setTimeout(() => {
    followTimer = null;
    if (followWanted) setFollow(true);
  }, FOLLOW_RESUME_MS);
}

function setFollow(on) {
  follow = !!on && !!lastPlayer;
  if (followBtn) followBtn.classList.toggle('on', follow);
  document.getElementById('mb-follow').classList.toggle('on', follow);
  if (follow) map.setView(toLatLng(lastPlayer.x, lastPlayer.y), Math.max(map.getZoom(), -0.5));
  reportState();
}

// Перелёт к точке + пульсирующее кольцо (авто-отметка, клик по журналу).
// move=false — только кольцо, вид карты не трогаем (авто-отметка не должна
// уводить карту, которую пользователь двигает сам).
function highlightPoint(pid, move) {
  pid = String(pid);
  const info = pointInfo.get(pid);
  if (!info) return;
  const [x, y, labelId] = info;
  const ll = toLatLng(x, y);
  if (move !== false) {
    if (!enabled.has(labelId)) enableCategory(labelId);   // показать слой точки
    setFollow(false);
    map.setView(ll, Math.max(map.getZoom(), 0), { animate: true });
  }
  const ring = L.marker(ll, { icon: L.divIcon({ className: '', iconSize: [44, 44], iconAnchor: [22, 22],
                           html: '<div class="gm-pulse"></div>' }), interactive: false, zIndexOffset: 4000 });
  ring.addTo(map);
  setTimeout(() => map.removeLayer(ring), 3500);
}

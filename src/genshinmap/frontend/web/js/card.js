// Карточка точки, зачистка региона, свои точки, фото и анимация «как пройти».
// ---------- Карточка точки: фото, «как найти», действия ----------
let cardPopup = null, cardPid = null;
const cardInfo = {};          // pid -> данные HoYoLAB (кеш на странице)

function esc(t) { return String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function openCard(pid) {
  pid = String(pid);
  const info = pointInfo.get(pid);
  if (!info) return;
  if (isCustom(pid)) cardInfo[pid] = { custom: true };     // подсказок HoYoLAB у своих нет
  cardPid = pid;
  clearOpen = false;
  if (document.body.classList.contains('compact')) {
    // маленькое окно: всплывашка не влезает — панель снизу на всю ширину
    document.getElementById('sheet-body').innerHTML = cardHtml(pid);
    document.getElementById('sheet').classList.add('on');
  } else {
    if (!cardPopup) cardPopup = L.popup({ className: 'gm-card', maxWidth: 310, autoPanPadding: [40, 40] });
    cardPopup.setLatLng(toLatLng(info[0], info[1])).setContent(cardHtml(pid)).openOn(map);
  }
  if (!cardInfo[pid] && bridge && bridge.request_point_info) bridge.request_point_info(pid);
}

function cardHtml(pid) {
  const [x, y, labelId, area] = pointInfo.get(pid);
  const lbl = labelById[labelId] || {};
  const rg = regionById[area];
  const got = COLLECTED.has(pid), prob = PROBABLE.has(pid);
  const d = cardInfo[pid];
  const gems = lbl.gems ? ` · ${ICON('gem', 'inl')}~${lbl.gems}` : '';
  let dist = '';
  if (lastPlayer) dist = ` · ${Math.round(Math.hypot(x - lastPlayer.x, y - lastPlayer.y))} ед. от тебя`;
  let h = `<div class="card-h"><img src="${iconUrl(labelId)}" alt="" onerror="this.remove()">${esc(lbl.name || '')}</div>` +
          `<div class="card-sub">${rg ? esc(rg.name) : ''}${gems}${dist}</div>`;
  const layer = pointInfo.get(pid)[4] || 0;
  if (LAYER_TEXT[layer]) h += `<div class="card-layer">${LAYER_TEXT[layer]}</div>`;
  h += prob ? `<div class="card-st prob">${ICON('help')}вероятно собрано (не найдено на месте)</div>`
     : got ? `<div class="card-st ok">${ICON('done')}собрано</div>` : '<div class="card-st">не собрано</div>';
  // действия — сразу под статусом, чтобы не листать к ним
  h += '<div class="card-btns">';
  h += got && !prob ? `<button onclick="cardToggle('${pid}')">${ICON('undo')}Снять отметку</button>`
                    : `<button class="primary" onclick="cardToggle('${pid}')">${ICON('check')}${prob ? 'Подтвердить' : 'Собрано'}</button>`;
  h += `<button onclick="setTarget('${pid}')">${ICON('navigate')}Вести сюда</button>`;
  if (!routeClips[pid]) h += `<button onclick="loadRouteClip('${pid}')">${ICON('play')}Как пройти</button>`;
  if (isCustom(pid)) h += `<button class="danger" onclick="deleteCustom('${pid}')">${ICON('trash')}Удалить точку</button>`;
  h += '</div>';
  h += routeClipHtml(pid);
  if (d && d.quest) {
    const q = d.quest;
    h += `<div class="card-quest${q.done ? ' done' : ''}">${ICON('lock')}${q.name ? 'Нужно задание «' + esc(q.name) + '»' : 'Связан с заданием'}` +
         (q.done ? ' · сделано' : '') +
         `<div class="q">${esc(q.quote || '')}</div><div class="card-btns">` +
         (q.start ? `<button onclick="questGo('${q.start.pid}')">${ICON('pin')}Где начать задание</button>` : '') +
         (q.name ? `<button onclick="questDone(${esc(JSON.stringify(q.name))}, ${!q.done})">` +
                   `${q.done ? ICON('undo') + 'Не сделано' : ICON('check') + 'Задание сделал'}</button>` : '') +
         '</div></div>';
  }
  if (d && d.custom) {
    return h + '<div class="card-muted">Своя точка: этого объекта нет на карте HoYoLAB.</div>';
  }
  if (!d) h += '<div class="card-muted">Загружаю подсказки…</div>';
  else if (d.error) h += '<div class="card-muted">Подсказки загрузить не удалось (нет сети?)</div>';
  else {
    if (d.content || d.img) {
      h += '<div class="tip">';
      h += `<div class="card-txt">${d.content ? esc(d.content) : '<span class="card-muted">Фото места</span>'}</div>`;
      if (d.img) h += `<img class="tip-thumb" src="${esc(d.img)}" title="Открыть крупно" onclick="showPhoto('${esc(d.img)}')">`;
      h += '</div>';
    }
    // советы игроков (appsample): как на их сайте — текст, фото, лайки, дата
    if ((d.tips && d.tips.length) || d.summary) {
      h += '<div class="tips-h">Советы игроков <span>appsample</span></div>';
      if (d.summary) h += `<div class="tips-sum">${esc(d.summary)}</div>`;
      for (const t of (d.tips || [])) {
        h += '<div class="tip">';
        h += `<div class="card-txt">${t.text ? esc(t.text) : '<span class="card-muted">Фото</span>'}` +
             `<div class="tip-meta">${ICON('thumb', 'inl')}${t.votes}${t.date ? ' · ' + esc(t.date) : ''}</div></div>`;
        if (t.thumb) h += `<img class="tip-thumb" src="${esc(t.thumb)}" loading="lazy" title="Открыть крупно" onclick="showPhoto('${esc(t.img)}')">`;
        h += '</div>';
      }
    }
    if (!d.content && !d.img && !(d.tips && d.tips.length) && !d.summary)
      h += '<div class="card-muted">У этой точки нет описания и фото</div>';
  }
  return h;
}

function refreshCard(pid) {
  if (cardPid !== String(pid)) return;
  if (cardPopup && map.hasLayer(cardPopup)) cardPopup.setContent(cardHtml(cardPid));
  const sheet = document.getElementById('sheet');
  if (sheet.classList.contains('on')) document.getElementById('sheet-body').innerHTML = cardHtml(cardPid);
}
function closeCard() {
  if (cardPopup) map.closePopup(cardPopup);
  document.getElementById('sheet').classList.remove('on');
  clearOpen = false;
}
document.querySelector('#sheet .sheet-x').innerHTML = ICON('x');
document.querySelector('#sheet .sheet-x').onclick = closeCard;
// ---------- Зачистка региона ----------
const KIND_ROWS = [['chest', 'chest', 'Сундуки'], ['valuable', 'sparkles', 'Окулусы и ценности'],
  ['seelie', 'seelie', 'Феи'], ['challenge', 'timer', 'Испытания'], ['teleport', 'pin', 'Телепорты'],
  ['statue', 'statue', 'Статуи']];
let clearOpen = false, clearTimer = null;

function playerArea() {
  if (!lastPlayer) return activeRegion;
  let area = null, bd = Infinity;
  for (const [, [x, y, , a]] of pointInfo) {
    const d = Math.hypot(x - lastPlayer.x, y - lastPlayer.y);
    if (d < bd) { bd = d; area = a; }
  }
  return area;
}

function clearHtml() {
  const area = playerArea();
  const rg = regionById[area];
  const stat = {}, near = [];
  let gemsGot = 0, gemsAll = 0;
  for (const [pid, [x, y, labelId, a]] of pointInfo) {
    if (a !== area && !(isCustom(pid) && a == null)) continue;   // своя точка без региона — в текущий
    const l = labelById[labelId];
    const kind = Number(labelId) === CUSTOM_LABEL ? 'custom' : (l && l.kind);
    if (!kind) continue;
    const st = stat[kind] = stat[kind] || [0, 0];
    const got = COLLECTED.has(pid);
    st[0]++; if (got) st[1]++;
    if (l && l.gems) { gemsAll += l.gems; if (got) gemsGot += l.gems; }
    if (!got && lastPlayer) near.push([Math.hypot(x - lastPlayer.x, y - lastPlayer.y), pid, labelId]);
  }
  let h = `<div class="clr-h">${ICON('clear')}Зачистка: ${rg ? esc(rg.name) : 'регион не определён'}</div>`;
  const rows = KIND_ROWS.concat([['custom', 'star', 'Свои точки']]);
  for (const [kind, ic, title] of rows) {
    const st = stat[kind];
    if (!st) continue;
    const extra = kind === 'chest' && gemsAll ? ` · ${ICON('gem', 'inl')}~${gemsGot}/${gemsAll}` : '';
    h += `<div class="clr-row"><span class="k">${ICON(ic)}</span><span class="n">${title}</span>` +
         `<span class="v">${st[1]}/${st[0]}${extra}</span></div>` +
         `<div class="clr-bar"><i style="width:${(100 * st[1] / st[0]).toFixed(1)}%"></i></div>`;
  }
  h += '<div class="card-btns"><button class="primary" onclick="startRoute()">' + ICON('route') + 'Маршрут по сундукам</button>' +
       `<button onclick="toggleHeat()">${ICON('flame')}${heatOn ? 'Скрыть «где остались»' : 'Где остались сундуки'}</button></div>`;
  h += '<div class="tips-h">Показать на карте (собранное скрыто)</div><div class="card-btns">' +
       `<button onclick="showKinds(['chest'])">${ICON('chest')}Сундуки</button>` +
       `<button onclick="showKinds(['valuable'])">${ICON('sparkles')}Окулусы</button>` +
       `<button onclick="showKinds(['chest','valuable','seelie','challenge','teleport','statue'])">${ICON('layers')}Всё собираемое</button>` +
       '</div>';
  if (!lastPlayer) return h + '<div class="card-muted">Включи отслеживание позиции — покажу ближайшее.</div>';
  near.sort((a, b) => a[0] - b[0]);
  h += '<div class="tips-h clr-near">Ближайшее несобранное</div>';
  for (const [d, pid, labelId] of near.slice(0, 8)) {
    const l = labelById[labelId] || {};
    h += `<div class="clr-item" role="button" tabindex="0" onclick="setTarget('${pid}')"><img src="${iconUrl(labelId)}" alt="" onerror="this.remove()">` +
         `<span>${esc(l.name || '')}</span><span class="d">${Math.round(d)} ед. ›</span></div>`;
  }
  return h;
}

// быстрые фильтры: включить только слои нужных типов и скрыть собранное
window.showKinds = function (kinds) {
  enabled.clear();
  for (const l of LABELS) if (l.kind && kinds.includes(l.kind)) enabled.add(l.id);
  if (kinds.includes('chest')) enabled.add(CUSTOM_LABEL);
  setHideCollected(true, true);
  refreshPanel(); renderVisible(); reportState();
  alertNav(`Показано: ${enabled.size} слоёв, собранное скрыто`);
};

window.toggleClear = function () {
  const sheet = document.getElementById('sheet');
  if (clearOpen) { closeCard(); return; }
  if (cardPopup) map.closePopup(cardPopup);
  clearOpen = true;
  document.getElementById('sheet-body').innerHTML = clearHtml();
  sheet.classList.add('on');
};

function refreshClearSoon() {
  if (!clearOpen || clearTimer) return;
  clearTimer = setTimeout(() => {
    clearTimer = null;
    if (clearOpen) document.getElementById('sheet-body').innerHTML = clearHtml();
  }, 1500);
}

// ---------- Свои точки ----------
const CUSTOM_LABEL = -1;
function isCustom(pid) { return String(pid).startsWith('u'); }
function iconUrl(labelId) {
  return `${META.icons_base}/${Number(labelId) === CUSTOM_LABEL ? 17 : labelId}.png`;
}
window.addCustomHere = function (x, y) {
  map.closePopup();
  if (bridge && bridge.on_custom_add) bridge.on_custom_add(x, y);
};
window.deleteCustom = function (pid) {
  closeCard();
  if (bridge && bridge.on_custom_delete) bridge.on_custom_delete(String(pid));
};
window.addCustomPoint = function (pid, x, y, area) {
  pid = String(pid);
  const list = POINTS_BY_LABEL[CUSTOM_LABEL] = POINTS_BY_LABEL[CUSTOM_LABEL] || [];
  list.push([pid, x, y, area]);
  pointInfo.set(pid, [x, y, CUSTOM_LABEL, area]);
  if (labelById[CUSTOM_LABEL]) labelById[CUSTOM_LABEL].count = list.length;
  if (!enabled.has(CUSTOM_LABEL)) setLabel(CUSTOM_LABEL, true, true);
  refreshCounts(CUSTOM_LABEL);
  renderVisible();
};
window.removeCustomPoint = function (pid) {
  pid = String(pid);
  const list = POINTS_BY_LABEL[CUSTOM_LABEL] || [];
  POINTS_BY_LABEL[CUSTOM_LABEL] = list.filter(p => String(p[0]) !== pid);
  pointInfo.delete(pid);
  COLLECTED.delete(pid); PROBABLE.delete(pid);
  if (labelById[CUSTOM_LABEL]) labelById[CUSTOM_LABEL].count = POINTS_BY_LABEL[CUSTOM_LABEL].length;
  refreshCounts(CUSTOM_LABEL);
  renderVisible();
};

window.showPointInfo = function (pid, data) { cardInfo[String(pid)] = data || {}; refreshCard(pid); };

// анимация «как пройти»: путь от ближайшего телепорта (или от тебя) — делает Python
const routeClips = {};          // pid -> 'loading' | url | ''
window.loadRouteClip = function (pid) {
  pid = String(pid);
  if (routeClips[pid] && routeClips[pid] !== '') return;
  routeClips[pid] = 'loading';
  refreshCard(pid);
  if (bridge && bridge.request_route_clip) bridge.request_route_clip(pid);
};
window.showRouteClip = function (pid, url) { routeClips[String(pid)] = url; refreshCard(pid); };
function routeClipHtml(pid) {
  const c = routeClips[pid];
  if (c === undefined) return '';
  if (c === 'loading') return '<div class="card-muted">Рисую путь от ближайшего телепорта…</div>';
  if (!c) return '<div class="card-muted">Анимацию пути сделать не удалось (нет сети?)</div>';
  return `<div class="route-clip" title="Открыть крупно" onclick="showPhoto('${esc(c)}')">` +
         `<img src="${esc(c)}" alt=""><span>${ICON('play', 'inl')}Как пройти</span></div>`;
}
window.openExt = function (url) { if (bridge && bridge.open_url) bridge.open_url(url); };
window.cardToggle = function (pid) {
  if (bridge) bridge.on_marker_clicked(String(pid));
  closeCard();
};
// фото — крупно прямо в окне (без внешнего браузера); клик/Esc — закрыть
window.showPhoto = function (url) {
  const lb = document.getElementById('lightbox');
  lb.querySelector('img').src = url;
  lb.classList.add('on');
};
document.getElementById('lightbox').onclick = () => document.getElementById('lightbox').classList.remove('on');
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { document.getElementById('lightbox').classList.remove('on'); closeCard(); }
});

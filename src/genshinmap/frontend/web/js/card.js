// Карточка точки, зачистка региона, свои точки, фото и анимация «как пройти».
// ---------- Карточка точки: фото, «как найти», действия ----------
let cardPopup = null, cardPid = null;
const cardInfo = {};          // pid -> данные HoYoLAB (кеш на странице)

function esc(t) { return String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function openCard(pid) {
  pid = String(pid);
  const info = pointInfo.get(pid);
  if (!info) return;
  syncLevelFor(pid);             // сундук на поверхности — выйти из пещеры, на другом этаже — туда
  if (isCustom(pid)) cardInfo[pid] = { custom: true };     // подсказок HoYoLAB у своих нет
  cardPid = pid;
  clearOpen = false;
  if (document.body.classList.contains('compact')) {
    // маленькое окно: всплывашка не влезает — панель снизу на всю ширину
    document.getElementById('sheet-body').innerHTML = cardHtml(pid);
    document.getElementById('sheet').classList.add('on');
  } else {
    if (!cardPopup) cardPopup = L.popup({ className: 'gm-card', maxWidth: 360, minWidth: 340, autoPanPadding: [40, 40] });
    cardPopup.setLatLng(toLatLng(info[0], info[1])).setContent(cardHtml(pid)).openOn(map);
  }
  if (!cardInfo[pid] && bridge && bridge.request_point_info) bridge.request_point_info(pid);
}

// Всё, что можно показать крупно: фото HoYoLAB, фото из советов, анимация пути
const cardMedia = {};             // pid -> [{src, thumb, caption}]
function mediaOf(pid, d) {
  const out = [];
  if (d && d.img) out.push({ src: d.img, thumb: d.img, caption: d.content || 'Фото места (HoYoLAB)' });
  if (d && d.video) out.push({ src: d.video, thumb: d.img || '', caption: 'Видео', video: true });
  for (const t of (d && d.tips) || []) {
    if (t.img) out.push({ src: t.img, thumb: t.thumb || t.img, caption: t.text || '' });
  }
  const c = routeClips[pid];
  if (c && c !== 'loading') out.unshift({ src: c, thumb: c, caption: 'Как пройти: путь от ближайшего телепорта', clip: true });
  return out;
}

// Доступ: нужно ли задание, чтобы туда попасть (по тексту описания и советов)
function accessHtml(pid, d) {
  if (d && d.quest) {
    const q = d.quest;
    return `<section class="card-sec access quest${q.done ? ' done' : ''}">` +
      `<div class="sec-h">${ICON('lock')}<span>Доступ: ${q.name ? 'нужно задание «' + esc(q.name) + '»' : 'связано с заданием'}</span>` +
      (q.done ? '<span class="sec-sub">сделано</span>' : '') + '</div>' +
      (q.quote ? `<div class="sec-quote">${esc(q.quote)}</div>` : '') +
      '<div class="card-btns">' +
      (q.start ? `<button onclick="questGo('${q.start.pid}')">${ICON('pin')}Где начать задание</button>` : '') +
      (q.name ? `<button onclick="questDone(${esc(JSON.stringify(q.name))}, ${!q.done})">` +
                `${q.done ? ICON('undo') + 'Не сделано' : ICON('check') + 'Задание сделал'}</button>` : '') +
      '</div></section>';
  }
  // в той же пещере есть места «за задание» — возможно, и вход открывается заданием
  const f = floorOfPoint(pid);
  if (f) {
    const other = [...QUEST].find(k => k !== pid && (floorOfPoint(k) || {}).group === f.group);
    if (other) {
      return `<section class="card-sec access maybe"><div class="sec-h">${ICON('help')}<span>Доступ: возможно, по заданию</span></div>` +
        '<div class="sec-txt">В этой пещере есть места, для которых нужно задание — вход может открываться им.</div>' +
        `<div class="card-btns"><button onclick="openCard('${other}')">${ICON('lock')}Показать такое место</button></div></section>`;
    }
  }
  if (d && !d.error && !d.custom) {
    return `<div class="access-ok">${ICON('done', 'inl')}Доступ: задание не упоминается ни в описании, ни в советах</div>`;
  }
  return '';
}

function cardHtml(pid) {
  const [x, y, labelId, area, layer] = pointInfo.get(pid);
  const lbl = labelById[labelId] || {};
  const rg = regionById[area];
  const got = COLLECTED.has(pid), prob = PROBABLE.has(pid);
  const d = cardInfo[pid];
  const sub = [];
  if (rg) sub.push(esc(rg.name));
  if (lbl.gems) sub.push(`${ICON('gem', 'inl')}~${lbl.gems}`);
  if (lastPlayer) sub.push(`${Math.round(Math.hypot(x - lastPlayer.x, y - lastPlayer.y))} ед. от тебя`);
  const pill = prob ? `<span class="pill prob">${ICON('help')}вероятно</span>`
             : got ? `<span class="pill ok">${ICON('check')}собрано</span>` : '<span class="pill">не собрано</span>';
  let h = `<header class="card-top"><img class="card-ico" src="${iconUrl(labelId)}" alt="" onerror="this.remove()">` +
          `<div class="card-title"><div class="card-name">${esc(lbl.name || '')}</div>` +
          `<div class="card-sub">${sub.join(' · ')}</div></div>${pill}</header>`;
  if (LAYER_TEXT[layer] && !floorOfPoint(pid)) h += `<div class="card-layer">${LAYER_TEXT[layer]}</div>`;

  // действия — сразу под шапкой, чтобы не листать к ним
  h += '<div class="card-btns">';
  h += got && !prob ? `<button onclick="cardToggle('${pid}')">${ICON('undo')}Снять отметку</button>`
                    : `<button class="primary" onclick="cardToggle('${pid}')">${ICON('check')}${prob ? 'Подтвердить' : 'Собрано'}</button>`;
  h += `<button onclick="setTarget('${pid}')">${ICON('navigate')}Вести сюда</button>`;
  if (routeClips[pid] === undefined) h += `<button onclick="loadRouteClip('${pid}')">${ICON('play')}Как пройти</button>`;
  if (isCustom(pid)) h += `<button class="danger" onclick="deleteCustom('${pid}')">${ICON('trash')}Удалить точку</button>`;
  h += '</div>';

  h += accessHtml(pid, d);
  h += caveCardHtml(pid);

  if (d && d.custom) return h + '<div class="card-muted">Своя точка: этого объекта нет на карте HoYoLAB.</div>';
  if (routeClips[pid] === 'loading') h += '<div class="card-muted">Рисую путь от ближайшего телепорта…</div>';
  else if (routeClips[pid] === '') h += '<div class="card-muted">Анимацию пути сделать не удалось (нет сети?)</div>';

  // «Как найти»: крупное фото + лента превью (клик — галерея)
  const media = cardMedia[pid] = mediaOf(pid, d);
  if (media.length) {
    const m0 = media[0];
    h += '<section class="card-media">' +
         `<button class="media-main" onclick="openGallery('${pid}', 0)" title="Открыть крупно">` +
         `<img src="${esc(m0.thumb || m0.src)}" alt="" loading="lazy">` +
         (m0.caption ? `<span class="media-cap">${m0.clip ? ICON('play', 'inl') : ''}${esc(m0.caption.slice(0, 80))}</span>` : '') +
         (media.length > 1 ? `<span class="media-count">${ICON('layers', 'inl')}${media.length}</span>` : '') +
         '</button>';
    if (media.length > 1) {
      h += '<div class="media-strip">';
      media.slice(1, 9).forEach((m, i) => {
        h += `<button onclick="openGallery('${pid}', ${i + 1})" title="Открыть крупно" aria-label="Фото ${i + 2}">` +
             `<img src="${esc(m.thumb || m.src)}" alt="" loading="lazy"></button>`;
      });
      h += '</div>';
    }
    h += '</section>';
  }

  if (!d) h += '<div class="card-muted">Загружаю подсказки…</div>';
  else if (d.error) h += '<div class="card-muted">Подсказки загрузить не удалось (нет сети?)</div>';
  else {
    const texts = (d.tips || []).filter(t => t.text);
    if (d.content && !d.img) h += `<div class="card-txt">${esc(d.content)}</div>`;
    if (texts.length || d.summary) {
      h += '<section class="tips"><div class="tips-h">Советы игроков <span>appsample</span></div>';
      if (d.summary) h += `<div class="tips-sum">${esc(d.summary)}</div>`;
      for (const t of texts) {
        const mi = t.img ? media.findIndex(m => m.src === t.img) : -1;
        h += '<div class="tip"><div class="card-txt">' + esc(t.text) +
             `<div class="tip-meta">${ICON('thumb', 'inl')}${t.votes}${t.date ? ' · ' + esc(t.date) : ''}` +
             (mi >= 0 ? ` · <button class="linkbtn" onclick="openGallery('${pid}', ${mi})">фото</button>` : '') +
             '</div></div></div>';
      }
      h += '</section>';
    }
    if (!media.length && !d.content && !texts.length && !d.summary)
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
window.openExt = function (url) { if (bridge && bridge.open_url) bridge.open_url(url); };
window.cardToggle = function (pid) {
  if (bridge) bridge.on_marker_clicked(String(pid));
  closeCard();
};
// Галерея: фото крупно прямо в окне; ← → листать, Esc или клик по фону — закрыть
let gallery = { list: [], i: 0 };
window.openGallery = function (pid, i) {
  gallery = { list: cardMedia[String(pid)] || [], i: i || 0 };
  if (!gallery.list.length) return;
  document.getElementById('lightbox').classList.add('on');
  showGallery();
  document.querySelector('#lightbox .lb-x').focus();
};
window.showPhoto = function (url) {        // одиночное фото
  gallery = { list: [{ src: url, caption: '' }], i: 0 };
  document.getElementById('lightbox').classList.add('on');
  showGallery();
};
function showGallery() {
  const lb = document.getElementById('lightbox');
  const m = gallery.list[gallery.i];
  const img = lb.querySelector('img'), vid = lb.querySelector('video');
  if (m.video) { img.style.display = 'none'; vid.style.display = ''; vid.src = m.src; }
  else { vid.pause(); vid.removeAttribute('src'); vid.style.display = 'none'; img.style.display = ''; img.src = m.src; }
  lb.querySelector('.lb-cap').textContent = m.caption || '';
  lb.querySelector('.lb-n').textContent = gallery.list.length > 1 ? `${gallery.i + 1} / ${gallery.list.length}` : '';
  lb.classList.toggle('multi', gallery.list.length > 1);
  lb.classList.toggle('has-cap', !!(m.caption || gallery.list.length > 1));
}
function galleryStep(d) {
  if (gallery.list.length < 2) return;
  gallery.i = (gallery.i + d + gallery.list.length) % gallery.list.length;
  showGallery();
}
function closeGallery() {
  const lb = document.getElementById('lightbox');
  lb.classList.remove('on');
  lb.querySelector('video').pause();
}
(function initGallery() {
  const lb = document.getElementById('lightbox');
  lb.querySelector('.lb-x').innerHTML = ICON('x');
  lb.querySelector('.lb-prev').innerHTML = ICON('chevron');
  lb.querySelector('.lb-next').innerHTML = ICON('chevron');
  lb.querySelector('.lb-x').onclick = closeGallery;
  lb.querySelector('.lb-prev').onclick = e => { e.stopPropagation(); galleryStep(-1); };
  lb.querySelector('.lb-next').onclick = e => { e.stopPropagation(); galleryStep(1); };
  lb.onclick = e => { if (e.target === lb || e.target.classList.contains('lb-stage')) closeGallery(); };
})();
document.addEventListener('keydown', e => {
  const lbOn = document.getElementById('lightbox').classList.contains('on');
  if (lbOn && e.key === 'ArrowLeft') { galleryStep(-1); e.preventDefault(); }
  else if (lbOn && e.key === 'ArrowRight') { galleryStep(1); e.preventDefault(); }
  else if (e.key === 'Escape') {
    const cardOn = (cardPopup && map.hasLayer(cardPopup)) || document.getElementById('sheet').classList.contains('on');
    if (lbOn) closeGallery(); else if (cardOn) closeCard(); else if (caveMode) setCaveMode(false);
  }
});

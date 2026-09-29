// Сохранение состояния, слои, язык интерфейса, загрузка данных, собранные точки.
// ---------- Сохранение состояния (в Python) ----------
// Стартуем в режиме восстановления, чтобы moveend от начального fitBounds
// не перезаписал сохранённое состояние ДО того, как Python пришлёт applyState.
let _restoring = true;
const reportState = debounce(function () {
  if (_restoring || !bridge || !bridge.on_state_changed || !map) return;
  const c = map.getCenter();
  bridge.on_state_changed(JSON.stringify({
    enabled: Array.from(enabled),
    view: { lat: c.lat, lng: c.lng, zoom: map.getZoom() },
    region: activeRegion,
    hide_collected: hideCollected,
    follow: follow,
    compact: document.body.classList.contains('compact'),
  }));
}, 400);

// --- Python -> JS: восстановить сохранённое состояние ---
function applyState(state) {
  state = state || {};
  if (state.enabled) state.enabled.forEach(id => setLabel(id, true, true));
  setHideCollected(!!state.hide_collected, true);
  if (state.region !== undefined && state.region !== null) selectRegion(state.region, { noFly: true });
  refreshPanel();
  const v = state.view;
  function done() { _restoring = false; renderVisible(); }
  if (v && typeof v.lat === 'number') {
    // повторяем setView, пока не применится (размер контейнера может появиться не сразу)
    let tries = 0;
    (function apply() {
      map.invalidateSize();
      map.setView([v.lat, v.lng], v.zoom, { animate: false });
      tries++;
      const ok = Math.abs(map.getZoom() - v.zoom) < 0.01 &&
                 Math.abs(map.getCenter().lat - v.lat) < 1;
      if (!ok && tries < 20) setTimeout(apply, 200);
      else setTimeout(done, 100);
    })();
  } else {
    setTimeout(done, 200);
  }
}

// ---------- Слои ----------
function setLabel(labelId, on, silent) {
  labelId = Number(labelId);
  if (!labelById[labelId]) return;
  if (on) enabled.add(labelId); else enabled.delete(labelId);
  if (!silent) { refreshPanel(); renderVisible(); reportState(); }
}

function setGroup(gname, on) {
  const g = groupEls[gname];
  g.labels.forEach(id => { if (visibleCount(id) > 0 || !on) setLabel(id, on, true); });
  refreshPanel(); renderVisible(); reportState();
}

function clearLayers() {
  enabled.clear();
  refreshPanel(); renderVisible(); reportState();
}

function setHideCollected(on, silent) {
  hideCollected = !!on;
  document.getElementById('btn-hide').classList.toggle('on', hideCollected);
  if (!silent) { renderVisible(); reportState(); }
}

// --- Язык интерфейса: русский исходный, английский — словарём из Python ---
let UI_LANG = 'ru', I18N = null, I18N_RX = null, i18nObserver = null;
const CYR = /[А-Яа-яЁё]/;
function trText(s) {
  if (!I18N || !s || !CYR.test(s)) return s;
  const core = s.trim();
  if (I18N[core] !== undefined) return s.replace(core, I18N[core]);
  return s.replace(I18N_RX, m => I18N[m]);
}
window.tr = trText;
// пишем только изменившийся текст: запись того же значения снова будит наблюдатель
function setText(n) {
  const v = n.nodeValue;
  if (!v || !CYR.test(v)) return;
  const t = trText(v);
  if (t !== v) n.nodeValue = t;
}
function translateTree(root) {
  if (!I18N || !root) return;
  if (root.nodeType === 3) { setText(root); return; }
  if (root.nodeType !== 1) return;
  for (const a of ['title', 'placeholder', 'alt']) {
    const v = root.getAttribute && root.getAttribute(a);
    if (v && CYR.test(v)) { const t = trText(v); if (t !== v) root.setAttribute(a, t); }
  }
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (n.nodeType === 3) setText(n);
    else for (const a of ['title', 'placeholder', 'alt']) {
      const v = n.getAttribute(a);
      if (v && CYR.test(v)) { const t = trText(v); if (t !== v) n.setAttribute(a, t); }
    }
  }
}
function setLang(lang, table) {
  UI_LANG = lang || 'ru';
  document.documentElement.lang = UI_LANG;
  if (UI_LANG === 'ru' || !table) return;
  I18N = table;
  const keys = Object.keys(table).filter(k => k.length >= 2).sort((a, b) => b.length - a.length);
  const esc_ = k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  I18N_RX = new RegExp('(?<![А-Яа-яЁё])(?:' + keys.map(esc_).join('|') + ')(?![А-Яа-яЁё])', 'g');
  document.title = trText(document.title);
  translateTree(document.body);
  i18nObserver = new MutationObserver(muts => {
    for (const m of muts) {
      if (m.type === 'characterData') translateTree(m.target);
      else if (m.type === 'attributes') translateTree(m.target);
      else m.addedNodes.forEach(translateTree);
    }
  });
  i18nObserver.observe(document.body, { childList: true, subtree: true, characterData: true,
                                       attributes: true, attributeFilter: ['title', 'placeholder'] });
}

// --- Построение карты из бандла mapdata_<id>.js ---
function loadData(payload) {
  const d = (typeof payload === 'string') ? JSON.parse(payload) : payload;
  if (d.ui && d.ui.lang !== UI_LANG) setLang(d.ui.lang, d.ui.table);
  META = d.meta;
  LABELS = d.labels;
  POINTS_BY_LABEL = d.points_by_label;
  REGIONS = d.regions || [];
  ANCHORS = d.anchors || [];
  LABELS.forEach(l => labelById[l.id] = l);
  REGIONS.forEach(r => regionById[r.id] = r);
  for (const lid in POINTS_BY_LABEL) {
    const n = Number(lid);
    for (const p of POINTS_BY_LABEL[lid]) pointInfo.set(String(p[0]), [p[1], p[2], n, p[3], p[4] || 0]);
  }
  document.getElementById('mapname').textContent = META.name || 'Карта';
  document.title = META.name || document.title;
  initMap();
  buildRegions();
  buildPanel();
  refreshCounts();
  const ln = document.getElementById('loading');
  if (ln) ln.classList.add('hidden');
}

// --- Python -> JS: включить категорию (из авто-распознавания) ---
function enableCategory(labelId) {
  labelId = Number(labelId);
  if (!labelById[labelId]) return;
  if (!enabled.has(labelId)) setLabel(labelId, true);
  const r = rowByLabel[labelId];
  if (r) groupEls[r.group].el.classList.add('open');
}

// --- Python -> JS: применить список собранных точек ---
function applyCollected(ids, probable) {
  COLLECTED = new Set((ids || []).map(String));
  PROBABLE = new Set((probable || []).map(String));
  for (const pid of Object.keys(markerByPoint)) paintCollected(pid);
  refreshCounts();
  renderVisible();
}

// --- Python -> JS: отметить/снять отметку конкретной точки ---
// Лёгкий путь: переключаем CSS-класс на существующем элементе, НЕ пересоздаём
// иконку (пересоздание divIcon тормозило при клике).
function setCollected(pointId, collected, probable) {
  pointId = String(pointId);
  if (collected) COLLECTED.add(pointId); else COLLECTED.delete(pointId);
  if (collected && probable) PROBABLE.add(pointId); else PROBABLE.delete(pointId);
  refreshCard(pointId);
  refreshClearSoon();
  if (pointId === navPid) updateNav();
  paintCollected(pointId);
  const info = pointInfo.get(pointId);
  if (info) refreshCounts(info[2]);
  if (hideCollected && collected) renderVisible(); else updateStat();
}

function paintCollected(pid) {
  const entry = markerByPoint[pid];
  if (!entry) return;
  const collected = COLLECTED.has(pid), probable = PROBABLE.has(pid);
  const el = entry.marker.getElement();
  if (el) {
    const ico = el.querySelector('.gm-ico');
    if (ico) {
      ico.classList.toggle('collected', collected);
      ico.classList.toggle('probable', probable);
    }
  }
  if (entry.marker.getTooltip()) entry.marker.setTooltipContent(tipText(entry.labelId, collected, entry.area, probable));
}

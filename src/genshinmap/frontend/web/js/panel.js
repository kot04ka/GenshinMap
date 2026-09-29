// Левая панель: категории, счётчики, прогресс регионов, строка статистики.
// ---------- Панель категорий ----------
const CHEV = '<svg class="chev" viewBox="0 0 24 24"><path d="M8 5l8 7-8 7z"/></svg>';

function buildPanel() {
  const groups = {};
  LABELS.forEach(l => { (groups[l.group] = groups[l.group] || []).push(l); });
  const names = Object.keys(groups).sort((a, b) => {
    const ia = GROUP_ORDER.indexOf(a), ib = GROUP_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b, UI_LANG);
  });
  const box = document.getElementById('cats');
  box.innerHTML = '';
  names.forEach(gname => {
    const items = groups[gname];
    const g = document.createElement('div'); g.className = 'grp';
    const h = document.createElement('div'); h.className = 'grp-h'; kbButton(h);
    const gcb = document.createElement('input'); gcb.type = 'checkbox'; gcb.className = 'cb';
    gcb.title = 'Включить/выключить всю группу';
    gcb.onclick = e => e.stopPropagation();
    gcb.onchange = () => setGroup(gname, gcb.checked);
    const gname_el = document.createElement('span'); gname_el.className = 'g-name';
    gname_el.textContent = items[0].group_label || gname;
    const gcnt = document.createElement('span'); gcnt.className = 'g-cnt';
    h.insertAdjacentHTML('beforeend', CHEV);
    h.append(gname_el, gcnt, gcb);
    const body = document.createElement('div'); body.className = 'grp-body';
    h.onclick = () => g.classList.toggle('open');
    groupEls[gname] = { el: g, cb: gcb, cnt: gcnt, labels: items.map(l => l.id) };
    items.forEach(l => {
      const row = document.createElement('label'); row.className = 'lbl';
      row.dataset.name = l.name.toLowerCase();
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'cb';
      cb.onchange = () => setLabel(l.id, cb.checked);
      const img = document.createElement('img'); img.src = iconUrl(l.id);
      img.onerror = () => { img.classList.add('ico-missing'); img.removeAttribute('src'); };
      const nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = l.name;
      const cnt = document.createElement('span'); cnt.className = 'cnt';
      const bar = document.createElement('div'); bar.className = 'bar';
      bar.innerHTML = '<i></i>';
      row.append(cb, img, nm, cnt, bar);
      body.appendChild(row);
      rowByLabel[l.id] = { row, cb, cnt, bar: bar.firstChild, group: gname };
    });
    g.append(h, body); box.appendChild(g);
  });
  refreshPanel();
}

// сколько точек категории в текущем регионе / сколько из них собрано
const countCache = {};
function computeCounts(labelId) {
  const pts = POINTS_BY_LABEL[labelId] || [];
  let total = 0, got = 0;
  for (const p of pts) {
    if (!inRegion(p)) continue;
    total++;
    if (COLLECTED.has(String(p[0]))) got++;
  }
  countCache[labelId] = [total, got];
}
function visibleCount(labelId) { return (countCache[labelId] || [0])[0]; }

// Пересчёт счётчиков: всех категорий (смена региона/прогресса) или одной.
function refreshCounts(onlyLabel) {
  if (onlyLabel !== undefined) computeCounts(onlyLabel);
  else LABELS.forEach(l => computeCounts(l.id));
  refreshPanel();
  updateRegionProgress();
}

// Отрисовать состояние панели из enabled/countCache (без пересчёта точек).
function refreshPanel() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  for (const gname in groupEls) {
    const g = groupEls[gname];
    let gt = 0, gg = 0, on = 0, shown = 0, avail = 0;
    g.labels.forEach(id => {
      const r = rowByLabel[id];
      const [total, got] = countCache[id] || [0, 0];
      const isOn = enabled.has(id);
      r.cb.checked = isOn;
      r.row.classList.toggle('on', isOn);
      r.cnt.textContent = got ? `${got}/${total}` : String(total);
      r.cnt.classList.toggle('done', total > 0 && got === total);
      r.bar.style.width = total ? (100 * got / total).toFixed(1) + '%' : '0';
      const hit = total > 0 && (!q || r.row.dataset.name.includes(q));
      r.row.style.display = hit ? '' : 'none';
      if (hit) shown++;
      if (total > 0) { avail++; gt += total; gg += got; if (isOn) on++; }
    });
    g.cnt.textContent = gg ? `${gg}/${gt}` : String(gt);
    g.cb.checked = avail > 0 && on === avail;
    g.cb.indeterminate = on > 0 && on < avail;
    g.el.style.display = shown ? '' : 'none';
    if (q) g.el.classList.toggle('open', shown > 0);   // при поиске раскрываем найденное
  }
  renderActive();
}

// Включённые слои: одна строка-сводка «Слоёв на карте: N», чипы — под ней
// (свёрнуты до двух строк, чтобы список категорий не уезжал вниз).
let activeOpen = false;
function renderActive() {
  const box = document.getElementById('active');
  const bar = document.getElementById('active-bar');
  const tog = document.getElementById('active-toggle');
  box.innerHTML = '';
  bar.style.display = enabled.size ? '' : 'none';
  tog.innerHTML = `${ICON('layers')}<span>Слоёв на карте: <b>${enabled.size}</b></span>` +
    (enabled.size > 4 ? ICON('chevron', 'chev' + (activeOpen ? ' up' : '')) : '');
  tog.setAttribute('aria-expanded', String(activeOpen));
  box.classList.toggle('collapsed', !activeOpen && enabled.size > 4);
  for (const id of enabled) {
    const l = labelById[id];
    if (!l) continue;
    const chip = document.createElement('span'); chip.className = 'chip'; kbButton(chip);
    chip.title = 'Выключить слой';
    chip.innerHTML = `<img src="${iconUrl(id)}" alt="" onerror="this.remove()"><span></span>${ICON('x', 'x')}`;
    chip.querySelector('span').textContent = l.name;
    chip.onclick = () => setLabel(id, false);
    box.appendChild(chip);
  }
}

// прогресс «собрано %» на чипах регионов и на подписях карты
function updateRegionProgress() {
  if (heatOn) drawHeat();
  if (!REGIONS.length) return;
  const tot = {}, got = {};
  for (const lid of enabled) {
    for (const p of (POINTS_BY_LABEL[lid] || [])) {
      tot[p[3]] = (tot[p[3]] || 0) + 1;
      if (COLLECTED.has(String(p[0]))) got[p[3]] = (got[p[3]] || 0) + 1;
    }
  }
  REGIONS.forEach(r => {
    const t = tot[r.id] || 0, g = got[r.id] || 0;
    const txt = t ? `${g}/${t}` : '';
    const chip = document.querySelector(`#regions .rg[data-id="${r.id}"] .pc`);
    if (chip) chip.textContent = txt;
    const lbl = document.querySelector(`.gm-region-lbl[data-rid="${r.id}"] small`);
    if (lbl) lbl.textContent = txt ? `собрано ${g} из ${t}` : '';
  });
}

document.getElementById('search').addEventListener('input', refreshPanel);
document.getElementById('btn-hide').innerHTML = `${ICON('eyeoff')}<span>Скрыть собранные</span>`;
document.getElementById('btn-hide').onclick = () => setHideCollected(!hideCollected);
document.getElementById('btn-clear').onclick = clearLayers;
document.getElementById('active-toggle').onclick = () => {
  if (enabled.size <= 4) return;
  activeOpen = !activeOpen;
  renderActive();
};

// Выбор карты (Тейват, Энканомия, …) — Python перезагружает страницу с нужными данными
function fillMapSelect(maps, current) {
  const sel = document.getElementById('mapsel');
  sel.innerHTML = '';
  (maps.length ? maps : [{ id: current, name: META.name || 'Карта' }]).forEach(m => {
    const o = document.createElement('option');
    o.value = m.id; o.textContent = m.name;
    if (String(m.id) === String(current)) o.selected = true;
    sel.appendChild(o);
  });
  sel.disabled = maps.length < 2;
}
document.getElementById('mapsel').onchange = e => {
  const id = Number(e.target.value);
  if (bridge && bridge.switch_map) bridge.switch_map(id);
};

function updateStat() {
  const total = LABELS.reduce((s, l) => s + l.count, 0);
  const ri = lastRenderInfo;
  let view = '';
  if (enabled.size) {
    view = `<br>В кадре: <b>${ri.shown}</b>` +
           (ri.thinned ? ` из ${ri.inView} <span class="warn">· приблизь, чтобы увидеть все</span>` : '');
  }
  const rg = activeRegion !== null ? ` · <b>${regionById[activeRegion].name}</b>` : '';
  document.getElementById('stat').innerHTML =
    `Точек: <b>${total.toLocaleString('ru')}</b> · Собрано: <b>${COLLECTED.size}</b> · ` +
    `Слоёв: <b>${enabled.size}</b>${rg}${view}`;
}

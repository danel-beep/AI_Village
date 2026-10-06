// Object inspector: click a house, plot, lot, landmark (square, market, smithy, mine, forest, river...) or a single
// map object (tree, garden bed, berry bush, fish shoal, rock) to see what it holds now and what happened there.
// Reads the viewer's globals only (header, ticks, i, selected, select, color, tr, esc, lastPanel) and the log's
// `view` (map, plots, chests, orders, projects, market, fire_info; see docs/ARCHITECTURE.md). Hooks in index.html:
// Inspect.click(x, y) when no villager is under the click, Inspect.render() from panel(), Inspect.mark(g) after the map.
const Inspect = (() => {
  const css = document.createElement('style');
  css.textContent = `
    #inspect { position:absolute; top:8px; right:8px; z-index:15; width:330px; max-width:calc(100% - 16px);
      max-height:calc(100% - 70px); overflow:auto; background:rgba(31,38,35,.96); border-radius:10px; padding:10px;
      box-shadow:0 4px 16px rgba(0,0,0,.6); font-size:13px; }
    #inspect[hidden] { display:none; }
    #inspect .top { display:flex; align-items:center; gap:8px; }
    #inspect .top .name { font-size:16px; flex:1; }
    #inspect .x { padding:2px 8px; }
    #inspect h4 { margin:10px 0 4px; font-size:11px; color:var(--muted); text-transform:uppercase; }
    #inspect .bar { height:8px; background:#34403b; border-radius:4px; overflow:hidden; margin:2px 0 4px; }
    #inspect .bar i { display:block; height:100%; }
    #inspect .row { border-bottom:1px solid var(--rule); padding:3px 0; }
    #inspect table { width:100%; border-collapse:collapse; font-size:12px; }
    #inspect td { padding:2px 0; } #inspect td + td { text-align:right; padding-left:8px; }
    #inspect a { color:var(--accent); cursor:pointer; text-decoration:underline; }
  `;
  document.head.appendChild(css);
  const box = Object.assign(document.createElement('div'), { id: 'inspect', hidden: true });
  document.getElementById('map').appendChild(box);
  let open = null, shownAt = -1;   // open = {id} (a place) or {loc, res, slot} (one object); box = its pixels

  const ITEM = { grain: 'зерно', fish: 'рыба', berries: 'ягоды', wood: 'древесина', stone: 'камень', ore: 'руда', water: 'вода',
    bread: 'хлеб', fish_soup: 'уха', tool: 'инструмент', lock: 'замок', egg: 'яйца', milk: 'молоко', honey: 'мёд',
    gold: 'золото', club: 'дубина', spear: 'копьё' };
  const OBJ = { wood: 'Дерево', berries: 'Ягодный куст', fish: 'Косяк рыбы', grain: 'Грядка', stone: 'Камень', ore: 'Рудная жила',
    gold: 'Золотая жила' };
  const PROJECT = { bridge: 'мост через реку' };
  const BUILD = { garden_bed: 'грядка', chicken_coop: 'курятник', cow_pen: 'коровник', beehive: 'улей', fence: 'забор' };
  const PLACE = { square: 'Площадь', market: 'Рынок', smithy: 'Кузница', forest: 'Лес', mine: 'Шахта', river: 'Река',
    field: 'Поле', grove: 'Роща', pond: 'Пруд', quarry: 'Каменоломня', hamlet: 'Хутор', waypoint: 'Развилка' };
  const PROF = { farmer: 'фермер', fisher: 'рыбак', smith: 'кузнец', woodcutter: 'лесоруб', miner: 'шахтёр', baker: 'пекарь',
    trader: 'торговец', builder: 'строитель' };
  const it = k => ITEM[k] || k;
  const goods = o => Object.entries(o || {}).filter(([, q]) => q).map(([k, q]) => `${q} ${it(k)}`).join(', ');
  const who = n => n ? `<a data-who="${esc(n)}" style="color:${color[n] || 'inherit'}">${esc(n)}</a>` : '—';
  const bar = (f, c = '#76b041') => `<div class="bar"><i style="width:${Math.max(0, Math.min(100, f * 100))}%;background:${c}"></i></div>`;
  const when = e => `д${e.day} ${String(e.hour).padStart(2, '0')}:${String(e.minute || 0).padStart(2, '0')}`;
  const table = rows => rows.length ? `<table>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</table>` : '';
  const kindOf = id => {
    const L = PixelMap.layout(), pl = L.gen && L.gen.places && L.gen.places[id];
    if (id.startsWith('home_')) return 'home';
    if (pl) return pl.kind;
    return (id.match(/^[a-z]+/) || [id])[0];
  };
  function title(t, id) {
    const p = (t.view.plots || {})[id];
    if (id.startsWith('home_')) return `Дом ${id.slice(5)}`;
    if (p && p.kind === 'lot') return `Участок «${tr(t.view.locations[id] || id)}»`;
    const k = kindOf(id), name = t.view.locations[id] || id;
    return PLACE[id] || (PLACE[k] && name === id ? PLACE[k] : tr(name));
  }

  // ---------- hit-testing (world pixels) ----------
  function placeAt(wx, wy) {
    const L = PixelMap.layout(), T = PixelMap.T, t = ticks[i];
    let best = null, area = Infinity;
    const take = (id, b) => {
      if (!b || !t.view.locations[id] || wx < b[0] || wx >= b[0] + b[2] || wy < b[1] || wy >= b[1] + b[3] || b[2] * b[3] >= area) return;
      area = b[2] * b[3]; best = { id, box: b };
    };
    for (const [id, b] of Object.entries(L.box || {})) take(id, b);
    for (const [id, b] of Object.entries(L.plots || {})) take(id, b);   // yards and lots of a generated map
    if (!best) {
      const k = L.kind[(wx / T | 0) + ',' + (wy / T | 0)];
      if ((k === 'water' || k === 'dock') && t.view.locations.river) best = { id: 'river', box: null };
    }
    return best;
  }
  function at(x, y) {
    if (!ticks.length) return null;
    const [wx, wy] = Camera.toWorld(x, y);
    const o = window.MapLayer && MapLayer.objectAt && MapLayer.objectAt(wx, wy);
    return o || placeAt(wx, wy);
  }

  // ---------- what happened there (ticks 0..i) ----------
  // Private events the viewer still wants on a place's history (the god's-eye view): thefts from a yard, arson, crops.
  const SECRET = {
    steal: e => e.data.success ? `🕵️ ${who(e.actor)} украл ${e.data.qty} ${it(e.data.item)}` +
      (e.data.witnesses && e.data.witnesses.length ? ` (видели: ${e.data.witnesses.map(who).join(', ')})` : ' (никто не видел)')
      : `${who(e.actor)} пытался украсть, но не вышло`,
    set_fire: e => `🔥 ${who(e.actor)} поджёг дом`,
    crop_ripe: e => esc(tr(e.text)), crop_failed: e => esc(tr(e.text)),
  };
  const QUIET = new Set(['move', 'work', 'slot_empty', 'error', 'eat', 'offer', 'decline', 'witness']);
  function history(id, res, slot) {
    const work = {}, notes = []; let emptied = 0;
    for (let k = 0; k <= i; k++) for (const e of ticks[k].events) {
      const d = e.data || {};
      const here = e.location === id || d.house === id || d.home === id || d.lot === id;
      if (!here) continue;
      if (e.kind === 'work' && e.actor && d.resource && (res === undefined || (d.resource === res && (d.slots || []).includes(slot)))) {
        const w = work[e.actor] = work[e.actor] || {}; w[d.resource] = (w[d.resource] || 0) + (d.amount || 0);
      }
      if (e.kind === 'slot_empty' && (res === undefined || (d.resource === res && d.slot === slot))) emptied++;
      if (res === undefined && (SECRET[e.kind] || (!QUIET.has(e.kind) && e.visibility !== 'private'))) notes.push(e);
    }
    return { work, notes: notes.slice(-12).reverse(), emptied };
  }
  const workTable = (work, verb) => {
    const rows = Object.entries(work).map(([n, r]) => [who(n), goods(r)]);
    return rows.length ? `<h4>${verb}</h4>${table(rows)}` : '';
  };
  const notesHtml = notes => notes.length ? `<h4>История</h4>` +
    notes.map(e => `<div class="row"><span class="muted">${when(e)}</span> ${SECRET[e.kind] && e.visibility === 'private' ? SECRET[e.kind](e) : esc(tr(e.text))}</div>`).join('') : '';
  const people = (t, id) => {
    const here = Object.entries(t.view.agents).filter(([, a]) => a.location === id && a.status === 'active');
    return `<h4>Сейчас здесь</h4>${here.length ? here.map(([n, a]) => who(n) + (a.asleep ? ' 💤' : '')).join(', ') : '<span class="muted">никого</span>'}`;
  };

  // ---------- panels ----------
  const regen = (id, r) => ((((header.config.locations || {})[id] || {}).resources || {})[r] || {}).regen || 0;
  function resources(t, id) {
    const m = (t.view.map || {})[id]; if (!m) return '';
    return `<h4>Ресурсы</h4>` + Object.entries(m.slots).map(([r, arr]) => {
      const cap = (m.cap || {})[r] || 1, left = arr.reduce((s, v) => s + v, 0), full = cap * arr.length, alive = arr.filter(v => v).length;
      const first = ((ticks[0].view.map || {})[id] || { slots: {} }).slots[r], start = first && first.reduce((s, v) => s + v, 0);
      return `<div>${OBJ[r] || r}: ${alive} из ${arr.length} · ${it(r)} ${left} из ${full}${r === 'gold' && start ? ` (в начале было ${start}${regen(id, r) ? `, +${regen(id, r)} за ночь` : ', не восстанавливается'})` : ''}</div>` +
        bar(left / full, r === 'gold' ? '#f2c14e' : r === 'fish' ? '#17bebb' : '#76b041');
    }).join('');
  }

  function plotHtml(t, id) {
    const p = (t.view.plots || {})[id]; if (!p) return '';
    let s = '';
    if (p.kind === 'lot') s += p.owner ? `<div>Владелец: ${who(p.owner)}</div>` : `<div>Продаётся за <b>${p.price}</b> монет</div>`;
    else if (p.house) s += `<div>Дом ${p.house}-го уровня</div>`;
    s += `<div>Земля: ${p.cells} клеток</div>`;
    const b = (p.buildings || []).map(x => {
      const extra = [goods(x.items) && `готово: ${goods(x.items)}`, x.crop && `растёт ${it(x.crop)}, созреет в день ${x.ripe_day}`].filter(Boolean);
      return [BUILD[x.kind] || x.kind, extra.join('; ') || '<span class="muted">пусто</span>'];
    });
    s += `<h4>Хозяйство</h4>${b.length ? table(b) : '<span class="muted">ничего не построено</span>'}`;
    return s;
  }

  function placeHtml(t, id) {
    const v = t.view, k = kindOf(id), h = history(id);
    let s = '';
    if (k === 'home') {
      const owner = id.slice(5), a = v.agents[owner] || {};
      s += `<div>Хозяин: ${who(owner)}${a.profession ? `, ${PROF[a.profession] || a.profession}` : ''}</div>`;
      const f = (v.fire_info || {})[id];
      if (f) s += `<div style="color:#e4572e">🔥 Горит! Нужно ещё ${f.water_needed} вёдер воды, сгорит через ${f.hours_left} ч</div>`;
      s += plotHtml(t, id);
      const ch = (v.chests || []).filter(c => c.location === id);
      if (ch.length) s += `<h4>Сундук</h4>` + ch.map(c => `<div>${c.locked ? '🔒 ' : ''}${goods(c.items) || 'пусто'}${c.coins ? ` · ${c.coins} монет` : ''}</div>`).join('');
    } else if ((v.plots || {})[id]) s += plotHtml(t, id);
    if (id === 'market' && v.market) {
      const rows = Object.entries(v.market).sort((a, b) => a[1][0] - b[1][0]).map(([n, [buy, sell]]) => [it(n), buy, sell]);
      s += `<h4>Цены торговца (монет)</h4><table><tr><td class="muted">товар</td><td class="muted">купить</td><td class="muted">продать</td></tr>` +
        rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('') + '</table>';
      let bought = 0, sold = 0;
      for (let q = 0; q <= i; q++) for (const e of ticks[q].events) if (e.location === 'market') { if (e.kind === 'buy') bought++; if (e.kind === 'sell') sold++; }
      s += `<div class="muted">Сделок за всё время: ${bought} покупок, ${sold} продаж</div>`;
    }
    if (id === 'square') {
      s += `<div>Мэр: ${v.mayor ? who(v.mayor) : '<span class="muted">нет</span>'} · казна ${v.treasury || 0} монет</div>`;
      const ord = v.orders || [];
      s += `<h4>Доска заказов</h4>` + (ord.length ? table(ord.map(o => [goods(o.needs), `${o.reward} монет, до дня ${o.until}`])) : '<span class="muted">заказов нет</span>');
      for (const [id, p] of Object.entries(v.projects || {})) {
        const need = Object.values(p.needs).reduce((a, b) => a + b, 0), got = Object.values(p.contributed || {}).reduce((a, b) => a + b, 0);
        s += `<h4>Стройка: ${PROJECT[id] || esc(tr(p.name))}${p.done ? ' ✅' : ''}</h4>` +
          Object.entries(p.needs).map(([r, q]) => `<div>${it(r)}: ${(p.contributed || {})[r] || 0} из ${q}</div>`).join('') + bar(got / need, '#f2c14e') +
          (Object.keys(p.contributors || {}).length ? `<div class="muted">Вложили: ${Object.entries(p.contributors).map(([n, q]) => `${who(n)} ${q}`).join(', ')}</div>` : '');
      }
    }
    if (id === 'smithy' || k === 'smithy') {
      const rec = Object.entries(header.config.recipes || {}).filter(([, r]) => r.where === 'smithy');
      if (rec.length) s += `<h4>Что здесь куют</h4>` + table(rec.map(([n, r]) => [it(n), goods(r.inputs) + (r.profession ? ` (${PROF[r.profession] || r.profession})` : '')]));
    }
    s += resources(t, id);
    s += people(t, id);
    s += workTable(h.work, k === 'mine' || k === 'quarry' ? 'Кто сколько добыл' : 'Кто сколько собрал');
    s += notesHtml(h.notes);
    return s;
  }

  function objectHtml(t, o) {
    const m = ((t.view.map || {})[o.loc]) || { slots: {}, cap: {}, planted: {} };
    const v = (m.slots[o.res] || [])[o.slot] || 0, cap = (m.cap || {})[o.res] || 1, h = history(o.loc, o.res, o.slot);
    let state = '';
    if (o.res === 'wood') state = v === 0 ? 'пень, отрастёт со временем' : v * 2 < cap ? 'молодое дерево' : 'взрослое дерево';
    else if (o.res === 'grain') { const pl = (m.planted || {})[o.slot];
      state = pl ? `посеял ${who(pl.by)}, созреет в день ${pl.ripe_day}` : v >= cap ? 'созрело' : v ? 'растёт' : 'пустая земля'; }
    else state = v ? '' : 'пусто, восстановится ночью';
    return `<div>${it(o.res)}: ${v} из ${cap}</div>${bar(v / cap, o.res === 'fish' ? '#17bebb' : '#76b041')}` +
      (state ? `<div class="muted">${state}</div>` : '') +
      (h.emptied ? `<div class="muted">Сколько раз опустошали: ${h.emptied}</div>` : '') +
      workTable(h.work, 'Кто здесь работал') +
      `<p><a data-place="${esc(o.loc)}">Всё место: ${esc(title(t, o.loc))} →</a></p>`;
  }

  function render(force) {
    if (!open || !ticks.length) { box.hidden = true; return; }
    if (selected) { close(); return; }   // a villager was picked (map or card): their dossier takes this spot
    if (!force && shownAt === i) return; shownAt = i;
    const t = ticks[Math.min(i, ticks.length - 1)];
    const name = open.res !== undefined ? `${OBJ[open.res] || open.res} · ${esc(title(t, open.loc))}` : esc(title(t, open.id));
    box.innerHTML = `<div class="top"><span class="name">${name}</span><button class="x" title="Закрыть">✕</button></div>` +
      (open.res !== undefined ? objectHtml(t, open) : placeHtml(t, open.id));
    box.hidden = false;
    box.querySelector('.x').onclick = close;
    box.querySelectorAll('[data-who]').forEach(el => el.onclick = () => { close(); select(el.dataset.who); });
    box.querySelectorAll('[data-place]').forEach(el => el.onclick = () => {
      const id = el.dataset.place; open = { id, box: PixelMap.layout().box[id] || null }; render(true); });
  }
  function close() { open = null; shownAt = -1; box.hidden = true; }

  // Canvas pixels (already un-letterboxed by index.html). Returns true if something was opened.
  function click(x, y) {
    const o = at(x, y);
    if (!o) { close(); return false; }
    if (selected) select(selected);   // close the dossier
    open = o; lastPanel = -1; render(true);
    return true;
  }

  // Dashed frame around what is open, drawn on the screen canvas after the map.
  function mark(g) {
    if (!open || !open.box || selected) return;
    const [x, y, w, h] = open.box, [sx, sy] = Camera.toScreen(x, y), [ex, ey] = Camera.toScreen(x + w, y + h);
    g.save(); g.setLineDash([6, 4]); g.lineWidth = 2; g.strokeStyle = '#f7e26b';
    g.strokeRect(sx, sy, ex - sx, ey - sy); g.restore();
  }

  // A hand cursor over anything clickable.
  const cv = document.getElementById('c');
  let hoverAt = 0;
  cv.addEventListener('mousemove', e => {
    const now = performance.now(); if (now - hoverAt < 80 || !ticks.length) return; hoverAt = now;
    const r = cv.getBoundingClientRect(), k = Math.min(r.width / cv.width, r.height / cv.height);
    const x = (e.clientX - r.left - (r.width - cv.width * k) / 2) / k, y = (e.clientY - r.top - (r.height - cv.height * k) / 2) / k;
    cv.style.cursor = PixelMap.pick(x, y) || at(x, y) ? 'pointer' : '';
  });

  return { click, render, mark, close, at };
})();
if (typeof window !== 'undefined') window.Inspect = Inspect;

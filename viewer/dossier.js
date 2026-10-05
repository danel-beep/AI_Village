// Villager dossier: a panel over the map for the selected villager (what they think and do now, needs,
// inventory, coins, relationships, action history, diary, stats). Reads the viewer's globals only
// (ticks, i, diaries, color, tr, esc, select) and is called from panel() as Dossier.render(selected).
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #map { position:relative; }
    #dossier { position:absolute; top:8px; right:8px; z-index:15; width:340px; max-width:calc(100% - 16px);
      max-height:calc(100% - 70px); overflow:auto; background:rgba(31,38,35,.96); border-radius:10px; padding:10px;
      box-shadow:0 4px 16px rgba(0,0,0,.6); font-size:13px; }
    #dossier[hidden] { display:none; }
    #dossier .top { display:flex; align-items:center; gap:8px; }
    #dossier .top .name { font-size:16px; flex:1; }
    #dossier .x { padding:2px 8px; }
    #dossier h4 { margin:10px 0 4px; font-size:11px; color:var(--muted); text-transform:uppercase; }
    #dossier .bar { height:8px; background:#34403b; border-radius:4px; overflow:hidden; margin:2px 0 4px; }
    #dossier .bar i { display:block; height:100%; }
    #dossier .tabs { display:flex; gap:4px; margin-top:8px; flex-wrap:wrap; }
    #dossier .tabs button { padding:3px 8px; font-size:12px; }
    #dossier .tabs button[aria-selected=true] { background:var(--accent); color:#1d2321; }
    #dossier .row { border-bottom:1px solid var(--rule); padding:4px 0; }
    #dossier .err { color:#e4572e; }
    #dossier table { width:100%; border-collapse:collapse; font-size:12px; }
    #dossier td { padding:2px 0; } #dossier td:last-child { text-align:right; }
  `;
  document.head.appendChild(css);
  const box = Object.assign(document.createElement('div'), { id: 'dossier', hidden: true });
  document.getElementById('map').appendChild(box);
  let tab = 'now';

  const STATUS = { active: 'в порядке', hospital: 'в больнице', evicted: 'выселен', sick: 'болеет', dead: 'умер' };
  const fmtArgs = a => Object.entries(a || {}).map(([k, v]) =>
    typeof v === 'object' && v ? Object.entries(v).map(([x, q]) => `${q} ${x}`).join(', ') : String(v)).join(' · ');
  const act = a => a ? `<b>${esc(a.name)}</b> ${esc(fmtArgs(a.args))}` : '<span class="muted">ждёт</span>';
  const bar = (v, c) => `<div class="bar"><i style="width:${Math.max(0, Math.min(100, v))}%;background:${c}"></i></div>`;
  const when = t => `д${t.view.day} ${String(t.view.hour).padStart(2, '0')}:00`;

  // Walk ticks 0..i once: this villager's decisions, failed actions, counts and contacts.
  function collect(n) {
    const hist = [], counts = {}, contacts = {};
    let errors = 0, lastDecision = null;
    for (let k = 0; k <= i; k++) {
      const t = ticks[k], d = t.decisions[n];
      const errs = t.events.filter(e => e.kind === 'error' && e.actor === n);
      errors += errs.length;
      if (d) {
        lastDecision = { t, d };
        if (d.action) counts[d.action.name] = (counts[d.action.name] || 0) + 1;
        hist.push({ t, d, err: errs[0] });
      }
      for (const e of t.events) {
        if (e.kind === 'error') continue;
        const other = e.actor === n ? e.to.filter(p => p !== n) : e.to.includes(n) && e.actor ? [e.actor] : [];
        for (const p of other) if (p in color) (contacts[p] = contacts[p] || []).push(e);
      }
    }
    return { hist, counts, contacts, errors, lastDecision };
  }

  function now(n, v, c) {
    const ld = c.lastDecision, inv = Object.entries(v.inventory).map(([k, q]) => `${q} ${esc(k)}`).join(', ') || 'пусто';
    const fresh = ld && ld.t === ticks[i];
    return `<h4>Думает</h4><div class="thought">${ld && ld.d.thought ? esc(tr(ld.d.thought)) : '<span class="muted">—</span>'}</div>
      ${ld && ld.d.say ? `<div>💬 «${esc(tr(ld.d.say))}»</div>` : ''}
      <h4>Делает</h4><div>${v.asleep ? '😴 спит' : (fresh ? '' : '<span class="muted">продолжает:</span> ') + act(ld && ld.d.action)}
        ${ld && !fresh ? `<span class="muted">(с ${when(ld.t)})</span>` : ''}</div>
      <h4>Потребности</h4>
      <div>Сытость ${v.satiety}</div>${bar(v.satiety, v.satiety < 25 ? '#e4572e' : '#76b041')}
      <div>Здоровье ${v.health}</div>${bar(v.health, v.health < 40 ? '#e4572e' : '#17bebb')}
      <h4>Кошелёк и вещи</h4><div>💰 ${v.coins} монет</div><div class="muted">${inv}</div>`;
  }

  function people(n, c) {
    const notes = {};
    for (const d of diaries) if (d.at <= i && d.entries[n]) Object.assign(notes, d.entries[n].people || {});
    const all = [...new Set([...Object.keys(notes), ...Object.keys(c.contacts)])].filter(p => p !== n);
    if (!all.length) return '<div class="muted">Пока ни с кем не общался.</div>';
    return all.map(p => {
      const ev = c.contacts[p] || [], last = ev[ev.length - 1];
      return `<div class="row"><b style="color:${color[p] || 'inherit'};cursor:pointer" data-p="${esc(p)}">${esc(p)}</b>
        <span class="muted">· ${ev.length} взаимодействий</span>
        ${notes[p] ? `<div class="thought">${esc(tr(notes[p]))}</div>` : ''}
        ${last ? `<div class="muted">последнее: ${esc(tr(last.text))}</div>` : ''}</div>`;
    }).join('');
  }

  function history(c) {
    if (!c.hist.length) return '<div class="muted">Ходов пока нет.</div>';
    return c.hist.slice(-60).reverse().map(({ t, d, err }) => `<div class="row"><span class="muted">${when(t)}</span> ${act(d.action)}
      ${d.thought ? `<div class="thought">${esc(tr(d.thought))}</div>` : ''}
      ${d.say ? `<div>💬 «${esc(tr(d.say))}»</div>` : ''}
      ${err ? `<div class="err">✖ ${esc(tr(err.text))}</div>` : ''}</div>`).join('');
  }

  function diary(n) {
    const own = diaries.filter(d => d.at <= i && d.entries[n]).map(d => d.entries[n]).reverse();
    return own.length ? own.map(d => `<div class="row"><span class="muted">День ${d.day}</span>
      <div class="thought">${esc(tr(d.text))}</div></div>`).join('')
      : '<div class="muted">Пока записей нет: дневник пишется ночью.</div>';
  }

  function stats(n, v, c) {
    const start = ticks[0].view.agents[n], turns = c.hist.length, dc = v.coins - start.coins;
    const rows = Object.entries(c.counts).sort((a, b) => b[1] - a[1])
      .map(([k, q]) => `<tr><td>${esc(k)}</td><td>${q}</td></tr>`).join('');
    return `<table><tr><td>Ходов</td><td>${turns}</td></tr>
      <tr><td>Неудачных действий</td><td>${c.errors}${turns ? ` (${Math.round(100 * c.errors / turns)}%)` : ''}</td></tr>
      <tr><td>Монеты: было → стало</td><td>${start.coins} → ${v.coins} (${dc >= 0 ? '+' : ''}${dc})</td></tr>
      <tr><td>С кем общался</td><td>${Object.keys(c.contacts).length}</td></tr></table>
      <h4>Действия</h4><table>${rows || '<tr><td class="muted">—</td></tr>'}</table>`;
  }

  const TABS = [['now', 'Сейчас'], ['people', 'Отношения'], ['hist', 'История'], ['diary', 'Дневник'], ['stats', 'Статистика']];
  function render(n) {
    if (!n || !ticks.length || !ticks[i].view.agents[n]) { box.hidden = true; return; }
    const t = ticks[i], v = t.view.agents[n], c = collect(n);
    const body = tab === 'people' ? people(n, c) : tab === 'hist' ? history(c) : tab === 'diary' ? diary(n)
      : tab === 'stats' ? stats(n, v, c) : now(n, v, c);
    const keep = box.dataset.key === n + tab ? box.scrollTop : 0;  // ticks re-render: don't jump to the top
    box.hidden = false; box.dataset.key = n + tab;
    box.innerHTML = `<div class="top"><span class="name" style="color:${color[n]}">${esc(n)}</span>
        <button class="x" title="закрыть">✕</button></div>
      <div class="muted">${esc(v.profession)} · ${esc(t.view.locations[v.location] || v.location)} · ${STATUS[v.status] || esc(v.status)}</div>
      <div class="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" aria-selected="${k === tab}">${l}</button>`).join('')}</div>
      <div>${body}</div>`;
    box.scrollTop = keep;
    box.querySelector('.x').onclick = () => { select(n); render(null); };
    for (const b of box.querySelectorAll('[data-t]')) b.onclick = () => { tab = b.dataset.t; render(n); };
    for (const b of box.querySelectorAll('[data-p]')) b.onclick = () => { select(b.dataset.p); lastPanel = -1; };
  }
  window.Dossier = { render };
})();

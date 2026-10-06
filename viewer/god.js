// God panel: injected by aivillage/server.py. Builds one form per god event from /api/meta
// (the GOD registry's JSON schemas), so new god events show up here without viewer changes.
(() => {
  const LABELS = {
    fire: ['🔥 Поджечь дом', 'Дом жителя загорится. Если не потушат вовремя, сгорит его сундук.'],
    sickness: ['🤒 Болезнь', 'Житель не сможет работать несколько дней.'],
    drought: ['🌵 Засуха', 'Ресурсы места уменьшатся вдвое и не будут расти.'],
    treasure: ['💎 Клад', 'Спрятать вещи в месте; можно анонимно подсказать одному жителю.'],
    rumor: ['✉️ Слух', 'Анонимное письмо жителю (правда или ложь).'],
    gift: ['🎁 Подарок', 'Дать жителю вещи/монеты из ниоткуда (минус = отнять).'],
    raid: ['🗡 Набег бандитов', 'Бандиты грабят сундуки дом за домом, а уходя поджигают дом. Можно предупредить ' +
           'деревню за несколько дней или напасть внезапно. Если отбиться, бросят добычу.'],
    beast: ['🐺 Зверь из леса', 'Ест запасы и ранит жителей, пока его не прогонят. С предупреждением или без.'],
    traveler: ['🧳 Путник', 'Голодный путник на площади. Разведчик, если его не прогнать, наведёт бандитов без предупреждения.'],
  };
  const FIELD = { person: 'кто', to: 'кому', tell: 'подсказать (необязательно)', location: 'где', days: 'дней',
                  items: 'вещи (wood:2, fish:1)', coins: 'монеты', text: 'текст',
                  target: 'на чей дом (необязательно)', warn: 'предупредить деревню заранее',
                  scout: 'на самом деле разведчик бандитов', in_days: 'через сколько дней (0: сразу)' };
  const PEOPLE = new Set(['person', 'to', 'tell', 'target']);
  const OPTIONAL = new Set(['tell', 'target']);

  const css = document.createElement('style');
  css.textContent = `
    #god-toggle { position:fixed; right:12px; bottom:12px; z-index:30; background:#f2c14e; color:#1d2321;
      font-weight:700; border-radius:20px; padding:8px 14px; box-shadow:0 2px 8px rgba(0,0,0,.5); }
    #god { position:fixed; right:12px; bottom:56px; z-index:30; width:320px; max-width:calc(100vw - 24px);
      max-height:70vh; overflow:auto; background:#252c29; color:#e8efe9; border-radius:12px; padding:10px;
      box-shadow:0 4px 16px rgba(0,0,0,.6); font:13px/1.4 system-ui, sans-serif; }
    #god[hidden] { display:none; }
    #god h4 { margin:2px 0 8px; font-size:13px; color:#9db0a4; text-transform:uppercase; }
    #god details { background:#1f2623; border-radius:8px; margin-bottom:6px; padding:6px 8px; }
    #god summary { cursor:pointer; font-weight:600; }
    #god label { display:block; margin:6px 0 2px; color:#9db0a4; font-size:12px; }
    #god input, #god select { width:100%; background:#34403b; color:#e8efe9; border:0; border-radius:6px; padding:5px; }
    #god .row { display:flex; gap:6px; align-items:center; margin-bottom:8px; flex-wrap:wrap; }
    #god .go { margin-top:8px; width:100%; background:#e4572e; color:#fff; font-weight:600; }
    #god .msg { font-size:12px; min-height:16px; margin-top:6px; }
  `;
  document.head.appendChild(css);

  const toggle = Object.assign(document.createElement('button'), { id: 'god-toggle', textContent: '⚡ Режим бога' });
  const panel = Object.assign(document.createElement('div'), { id: 'god', hidden: true });
  document.body.append(toggle, panel);
  toggle.onclick = () => { panel.hidden = !panel.hidden; };

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail); return j; });

  function input(key, prop, meta) {
    const id = `god-${key}`;
    let ctl;
    if (PEOPLE.has(key)) {
      ctl = `<select data-k="${key}">${OPTIONAL.has(key) ? '<option value="">—</option>' : ''}` +
        meta.agents.map(n => `<option>${esc(n)}</option>`).join('') + '</select>';
    } else if (key === 'location') {
      ctl = `<select data-k="${key}">` + Object.entries(meta.locations)
        .map(([v, n]) => `<option value="${esc(v)}">${esc(n)}</option>`).join('') + '</select>';
    } else if (prop.type === 'boolean') {
      ctl = `<input type="checkbox" data-k="${key}" data-bool="1"${prop.default ? ' checked' : ''}>`;
    } else if (prop.type === 'integer' || (prop.anyOf || []).some(t => t.type === 'integer')) {
      ctl = `<input type="number" data-k="${key}" data-int="1" value="${prop.default ?? 0}">`;
    } else if (key === 'items') {
      ctl = `<input data-k="${key}" data-items="1" placeholder="wood:2, fish:1" list="god-items">`;
    } else {
      ctl = `<input data-k="${key}" placeholder="${esc(prop.description || '')}">`;
    }
    if (prop.type === 'boolean') return `<label for="${id}">${ctl.replace('data-k', `id="${id}" data-k`)} ${esc(FIELD[key] || key)}</label>`;
    return `<label for="${id}">${esc(FIELD[key] || key)}</label>${ctl.replace('data-k', `id="${id}" data-k`)}`;
  }

  function read(form) {
    const args = {};
    for (const el of form.querySelectorAll('[data-k]')) {
      const k = el.dataset.k, v = el.value.trim();
      if (el.dataset.bool) { args[k] = el.checked; continue; }
      if (v === '' ) continue;
      if (el.dataset.int) args[k] = parseInt(v, 10);
      else if (el.dataset.items) args[k] = Object.fromEntries(v.split(',').map(p => p.split(':').map(s => s.trim()))
        .filter(([n, q]) => n).map(([n, q]) => [n, parseInt(q || '1', 10)]));
      else args[k] = v;
    }
    return args;
  }

  function render(meta) {
    const controls = `<h4>Время</h4><div class="row">
        <button id="god-pause">${meta.paused ? '▶ Продолжить' : '⏸ Пауза'}</button>
        <label style="margin:0">сек/час <input id="god-pace" type="number" min="0" max="60" step="0.5"
          value="${meta.pace}" style="width:70px"></label></div>`;
    const forms = Object.entries(meta.god).map(([name, spec]) => {
      const [title, help] = LABELS[name] || [name, spec.description];
      const props = spec.schema.properties || {};
      return `<details><summary>${esc(title)}</summary><form data-name="${esc(name)}">
        <div class="muted" style="font-size:12px;color:#9db0a4">${esc(help)}</div>
        ${Object.entries(props).map(([k, p]) => input(k, p, meta)).join('')}
        <button class="go" type="submit">Сделать</button><div class="msg"></div></form></details>`;
    }).join('');
    panel.innerHTML = controls + '<h4>Вмешаться</h4>' + forms +
      `<datalist id="god-items">${meta.items.map(n => `<option value="${esc(n)}:1">`).join('')}</datalist>`;

    // Same pause as the viewer's ⏸ button: Viewer.setPlaying fires 'viewer-play', live.js tells the server.
    let paused = meta.paused;
    const pauseBtn = panel.querySelector('#god-pause');
    if (paused) Viewer.setPlaying(false, true);
    pauseBtn.onclick = () => Viewer.setPlaying(paused);
    window.addEventListener('village-paused', e => {
      paused = e.detail; pauseBtn.textContent = paused ? '▶ Продолжить' : '⏸ Пауза';
    });
    panel.querySelector('#god-pace').onchange = e => post('/api/control', { cmd: 'pace', seconds: +e.target.value });
    for (const form of panel.querySelectorAll('form')) form.onsubmit = ev => {
      ev.preventDefault();
      const msg = form.querySelector('.msg');
      // shown_tick: the moment on screen. The server lands the event a little after it (the buffer the
      // picture trails the sim by) and broadcasts `god_pending`, re-sent below as 'village-god-pending'
      // so the map can play a lead-in (a spark before the fire) until the picture reaches that tick.
      const shown = typeof ticks !== 'undefined' && ticks.length ? ticks[Math.min(i, ticks.length - 1)].tick : null;
      post('/api/god', { name: form.dataset.name, args: read(form), shown_tick: shown })
        .then(r => { msg.style.color = '#76b041';
          msg.textContent = `Готово: сработает в ${r.at.replace('day', 'день')}` +
            (r.lead_minutes ? ` (через ${r.lead_minutes} игровых минут)` : '') + '.'; })
        .catch(e => { msg.style.color = '#e4572e'; msg.textContent = 'Не вышло: ' + e.message; });
    };
  }

  window.addEventListener('village-live', e => {
    if (e.detail.type === 'god_pending') window.dispatchEvent(new CustomEvent('village-god-pending', { detail: e.detail }));
  });

  // A god event that fails inside the world (e.g. house already burning) comes back as a god_error event.
  window.addEventListener('village-live', e => {
    const errs = (e.detail.events || []).filter(ev => ev.kind === 'god_error');
    if (errs.length) for (const m of panel.querySelectorAll('.msg'))
      if (m.textContent.startsWith('Готово')) { m.style.color = '#e4572e'; m.textContent = errs[0].text; }
  });

  fetch('/api/meta').then(r => r.json()).then(render);
})();

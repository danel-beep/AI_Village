// Start screen (injected by aivillage/server.py when it runs with --setup, i.e. from the launcher).
// Before a village runs: a full-screen form drawn from GET /api/setup (aivillage/knobs.py), "▶ Играть"
// posts the answers to /api/start and reloads into the live map. While a village runs: a
// "🔄 Новая деревня" button that stops it (POST /api/stop) and comes back here.
// New knobs need no code here: add them to KNOBS in aivillage/knobs.py.
(function () {
  const STORE = 'aivillage-setup';
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || ('ошибка ' + r.status));
      return data;
    });

  fetch('/api/setup').then(r => r.json()).then(info => info.running ? restartButton(info) : screen(info));

  function restartButton(info) {
    if (!info.can_restart) return;
    const b = document.createElement('button');
    b.textContent = '🔄 Новая деревня';
    b.title = 'остановить эту деревню и настроить новую';
    b.style.cssText = 'background:#34403b;color:#e8efe9;border:0;border-radius:20px;padding:7px 12px;' +
      'font:600 13px system-ui,sans-serif;cursor:pointer';
    b.onclick = () => {
      if (!info.finished && !confirm('Остановить эту деревню и настроить новую? Она сохранится (продолжить можно с начального экрана), сводка сессии тоже.')) return;
      post('/api/stop').then(() => location.reload(), e => alert(e.message));
    };
    const bar = document.getElementById('rp-bar');
    if (bar) bar.appendChild(b);
    else { b.style.cssText += ';position:fixed;left:8px;bottom:12px;z-index:30'; document.body.appendChild(b); }
  }

  function screen(info) {
    const css = document.createElement('style');
    css.textContent = `
      #su { position:fixed; inset:0; z-index:31; overflow:auto; background:#1a201e; color:#e8efe9;
        font:14px system-ui, sans-serif; }
      #su .wrap { max-width:760px; margin:0 auto; padding:20px 16px 60px; }
      #su header { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:8px; }
      #su h1 { font-size:24px; margin:0; flex:1; min-width:200px; }
      #su header #st-toggle { position:static; }
      #su .keyline { font-size:13px; color:#9db0a4; margin:0 0 14px; }
      #su .keyline.bad { color:#ffb36b; }
      #su section, #su details { background:#232b28; border-radius:12px; padding:12px 16px; margin-bottom:12px; }
      #su h2, #su summary { font-size:15px; margin:0 0 6px; color:#f2c14e; cursor:default; }
      #su summary { cursor:pointer; margin:0; }
      #su details[open] summary { margin-bottom:6px; }
      #su .k { padding:9px 0; border-top:1px solid #2f3935; }
      #su .k:first-of-type { border-top:0; }
      #su .lab { display:flex; justify-content:space-between; gap:10px; align-items:baseline; }
      #su .lab b { font-weight:600; }
      #su .val { color:#f2c14e; font-weight:700; white-space:nowrap; }
      #su .val.changed::after { content:' ●'; color:#76b041; font-size:10px; }
      #su input[type=range] { width:100%; accent-color:#76b041; margin:6px 0 0; }
      #su input[type=number] { width:160px; background:#1d2321; color:#e8efe9; border:1px solid #4a5650;
        border-radius:6px; padding:6px 8px; font:14px system-ui; margin-top:6px; }
      #su .opts { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
      #su .opts button { background:#2f3935; color:#e8efe9; border:1px solid #3e4a45; border-radius:18px;
        padding:6px 12px; font:13px system-ui; cursor:pointer; }
      #su .opts button.on { background:#76b041; color:#1d2321; border-color:#76b041; font-weight:700; }
      #su .tog { position:relative; width:42px; height:24px; flex:none; }
      #su .tog input { opacity:0; width:0; height:0; }
      #su .tog span { position:absolute; inset:0; background:#3d4a44; border-radius:12px; cursor:pointer; transition:.15s; }
      #su .tog span::before { content:''; position:absolute; width:18px; height:18px; left:3px; top:3px;
        background:#e8efe9; border-radius:50%; transition:.15s; }
      #su .tog input:checked + span { background:#76b041; }
      #su .tog input:checked + span::before { transform:translateX(18px); }
      #su .hint { font-size:12px; color:#9db0a4; margin-top:4px; line-height:1.4; }
      #su .play { position:sticky; bottom:0; background:linear-gradient(transparent, #1a201e 30%);
        padding:16px 0 4px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
      #su .go { background:#76b041; color:#1d2321; border:0; border-radius:12px; padding:14px 28px;
        font:800 18px system-ui; cursor:pointer; }
      #su .go:disabled { opacity:.6; cursor:wait; }
      #su .small { background:#2f3935; color:#e8efe9; border:0; border-radius:8px; padding:8px 12px;
        font:13px system-ui; cursor:pointer; }
      #su .msg { font-size:13px; flex-basis:100%; min-height:18px; }
      #su .bad { color:#ff8a72; }
      #su .runs a { color:#e8efe9; display:inline-block; margin:3px 10px 3px 0; }
      #su .vr { display:grid; grid-template-columns:1fr 1fr 1.3fr; gap:6px; padding:6px 0; border-top:1px solid #2f3935; }
      #su .vr input, #su .vr select { width:100%; box-sizing:border-box; background:#1d2321; color:#e8efe9;
        border:1px solid #4a5650; border-radius:6px; padding:6px 8px; font:13px system-ui; }
      #su .vr .own { grid-column:1 / -1; }
      #su .vr select.look { grid-column:1 / 3; }
      #su .vr .face { width:30px; height:39px; image-rendering:pixelated; align-self:center; }
      #su .vr .hint { grid-column:1 / -1; margin:0; }
      @media (max-width:560px) { #su .vr { grid-template-columns:1fr 1fr; } #su .vr select.ch { grid-column:1 / -1; } }
      #su .vbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:6px 0; }
      #su textarea { width:100%; box-sizing:border-box; background:#1d2321; color:#e8efe9; border:1px solid #4a5650;
        border-radius:6px; padding:6px 8px; font:13px system-ui; min-height:54px; margin-top:6px; }
    `;
    document.head.appendChild(css);
    const drop = document.getElementById('drop');
    if (drop) drop.style.display = 'none';
    const panel = document.getElementById('st');  // the keys panel opens above the start screen
    if (panel) panel.style.zIndex = 40;

    const root = document.createElement('div');
    root.id = 'su';
    root.innerHTML = `<div class="wrap">
      <header><h1>🏡 AI Village: новая деревня</h1></header>
      <p class="keyline" id="su-key"></p>
      <div id="su-groups"></div>
      <details id="su-people"><summary>👥 Жители по одному: имена, профессии, характеры</summary>
        <div class="vbar"><label class="tog"><input type="checkbox" id="su-own"><span></span></label>
          <span>Настроить каждого жителя вручную</span></div>
        <div class="hint">Выключено: имена и профессии подберутся сами, характер по выбору «Характер жителей» выше.
          Характер: мягкий намёк на темперамент в подсказке жителя, а не приказ что-то делать.</div>
        <div id="su-vbox" hidden>
          <div class="vbar"><button class="small" id="su-rand">🎲 Случайные жители</button>
            <button class="small" id="su-neutral">😐 Всем нейтральный</button></div>
          <div id="su-vlist"></div>
        </div>
      </details>
      <div class="play">
        <button class="go" id="su-go">▶ Играть</button>
        <button class="small" id="su-reset">Сбросить к режиму</button>
        <div class="msg" id="su-msg"></div>
      </div>
      <details id="su-past"><summary>📂 Прошлые сессии и отчёт о проблеме</summary>
        <div class="runs" id="su-runs">загружаю…</div>
        <div class="hint" style="margin-top:12px">Что-то пошло не так в последнем прогоне? Опишите, и я соберу файл-отчёт:
          его можно перетащить в чат проекта.</div>
        <textarea id="su-note" placeholder="Например: на второй день все жители стояли на месте"></textarea>
        <button class="small" id="su-report" style="margin-top:6px">🐞 Собрать отчёт</button>
        <div class="msg" id="su-rmsg"></div>
      </details>
    </div>`;
    document.body.appendChild(root);
    const $ = id => document.getElementById(id);
    const st = $('st-toggle');  // settings.js button: keys and model, moved into the header
    if (st) { st.className = ''; st.style.cssText = 'background:#34403b;color:#e8efe9;border:0;border-radius:20px;' +
      'padding:8px 14px;font:600 13px system-ui,sans-serif;cursor:pointer'; root.querySelector('header').appendChild(st); }

    const knobs = info.knobs, byKey = Object.fromEntries(knobs.map(k => [k.key, k]));
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch (e) { /* private window */ }
    const start = Object.assign({}, info.defaults, info.last || {}, saved);
    if (!(start.mode in info.mode_defaults)) start.mode = info.defaults.mode;
    const modeVals = m => info.mode_defaults[m] || {};
    // Config knobs follow the mode until the user moves them; `touched` keeps what they set by hand.
    let touched = new Set(Object.keys(saved.__touched || {}));
    const values = {};
    // A choice with `sets` (random-events preset) moves its sliders like the mode does: mode < preset < hand.
    const presetVals = () => Object.assign({}, ...knobs.filter(k => k.sets).map(k => k.sets[values[k.key]] || {}));
    const base = m => Object.assign({}, modeVals(m), presetVals());
    for (const k of knobs) if (!k.path) values[k.key] = k.key in start ? start[k.key] : k.default;
    for (const k of knobs) if (k.path)
      values[k.key] = touched.has(k.key) && k.key in start ? start[k.key] : base(start.mode)[k.key];

    const fmt = (k, v) => k.type === 'toggle' ? (v ? 'да' : 'нет')
      : k.type === 'choice' ? '' : (v === null || v === undefined || v === '' ? 'случайно' : v + (k.unit || ''));
    const rows = {};

    function row(k) {
      const el = document.createElement('div');
      el.className = 'k';
      const lab = document.createElement('div');
      lab.className = 'lab';
      lab.innerHTML = '<b></b><span class="val"></span>';
      lab.querySelector('b').textContent = k.label;
      el.appendChild(lab);
      const val = lab.querySelector('.val');
      let control;
      if (k.type === 'range') {
        control = document.createElement('input');
        Object.assign(control, { type: 'range', min: k.min, max: k.max, step: k.step || 1 });
        control.oninput = () => set(k, Number(control.value));
        el.appendChild(control);
      } else if (k.type === 'number') {
        control = document.createElement('input');
        Object.assign(control, { type: 'number', min: 1, placeholder: 'случайно' });
        control.oninput = () => set(k, control.value === '' ? null : Number(control.value));
        el.appendChild(control);
      } else if (k.type === 'toggle') {
        const t = document.createElement('label');
        t.className = 'tog';
        t.innerHTML = '<input type="checkbox"><span></span>';
        control = t.querySelector('input');
        control.onchange = () => set(k, control.checked);
        val.replaceWith(t);
      } else {
        control = document.createElement('div');
        control.className = 'opts';
        for (const [v, text] of k.options) {
          const b = document.createElement('button');
          b.textContent = text; b.dataset.v = v;
          b.onclick = () => set(k, v);
          control.appendChild(b);
        }
        el.appendChild(control);
      }
      const about = document.createElement('div');
      about.className = 'hint';
      el.appendChild(about);
      rows[k.key] = { el, control, val, about };
      return el;
    }

    function paint(k) {
      const r = rows[k.key], v = values[k.key];
      if (k.type === 'range') r.control.value = v;
      else if (k.type === 'number') r.control.value = v === null || v === undefined ? '' : v;
      else if (k.type === 'toggle') r.control.checked = !!v;
      else for (const b of r.control.children) b.classList.toggle('on', b.dataset.v === String(v));
      if (r.val.isConnected) {
        r.val.textContent = fmt(k, v);
        r.val.classList.toggle('changed', !!k.path && v !== base(values.mode)[k.key]);
      }
      r.about.textContent = [k.about ? k.about[v] : '', k.hint || ''].filter(Boolean).join(' ');
      r.el.style.display = (k.only && k.only !== values.brains) || (k.mode && k.mode !== values.mode) ? 'none' : '';
    }

    function set(k, v) {
      values[k.key] = v;
      if (k.path) touched.add(k.key);
      if (k.sets) for (const c of Object.keys(k.sets[v] || {})) touched.delete(c);  // the preset takes them back
      if (k.key === 'mode' || k.sets) {  // the mode / preset moves every slider the user has not set by hand
        for (const c of knobs) if (c.path && !touched.has(c.key)) values[c.key] = base(values.mode)[c.key];
      }
      knobs.forEach(paint);
      keyLine();
      if (k.key === 'villagers') syncRoster();
      remember();
    }

    function remember() {
      try {
        localStorage.setItem(STORE, JSON.stringify(Object.assign({}, values,
          { seed: null, roster: roster, __touched: Object.fromEntries([...touched].map(t => [t, 1])) })));
      } catch (e) { /* storage blocked: the form still works */ }
    }

    // Village first, the rest folded away.
    const groups = [];
    for (const k of knobs) if (!groups.includes(k.group)) groups.push(k.group);
    groups.forEach((g, n) => {
      const box = document.createElement(n < 2 ? 'section' : 'details');
      const h = document.createElement(n < 2 ? 'h2' : 'summary');
      h.textContent = g;
      box.appendChild(h);
      for (const k of knobs.filter(k => k.group === g)) box.appendChild(row(k));
      $('su-groups').appendChild(box);
    });
    knobs.forEach(paint);

    let hasKey = info.has_key;
    function keyLine() {
      const el = $('su-key');
      if (values.brains !== 'llm') { el.textContent = 'Боты бесплатные, ключ не нужен.'; el.className = 'keyline'; return; }
      el.className = 'keyline' + (hasKey ? '' : ' bad');
      el.textContent = hasKey ? `Модель жителей: ${info.model}. Поменять модель или ключ: «⚙️ Настройки».`
        : 'Для ИИ-жителей нужен ключ OpenAI или OpenRouter: нажмите «⚙️ Настройки» и вставьте его.';
    }
    keyLine();
    // The settings panel saves keys on its own; notice a new key without a reload.
    setInterval(() => fetch('/api/setup').then(r => r.json()).then(i => {
      if (i.running) return location.reload();  // started from another tab
      if (i.has_key !== hasKey || i.model !== info.model) { hasKey = i.has_key; info.model = i.model; keyLine(); }
    }).catch(() => {}), 3000);

    // --- villagers one by one (knobs.roster / clean_roster on the server) ---
    const PROF = { farmer: 'Фермер', fisher: 'Рыбак', woodcutter: 'Лесоруб', miner: 'Шахтёр', smith: 'Кузнец' };
    let roster = Array.isArray(start.roster) && start.roster.length ? start.roster : null;
    const n = () => values.villagers;
    const fetchRoster = (existing, seed) => post('/api/roster', { n: n(), existing, seed });

    function drawRoster() {
      const list = $('su-vlist');
      list.textContent = '';
      $('su-own').checked = !!roster;
      $('su-vbox').hidden = !roster;
      if (!roster) return;
      roster.slice(0, n()).forEach((v, idx) => {
        const r = document.createElement('div');
        r.className = 'vr';
        const name = document.createElement('input');
        name.value = v.name; name.maxLength = 20; name.placeholder = 'Имя';
        name.oninput = () => { v.name = name.value; remember(); };
        const prof = document.createElement('select');
        for (const p of info.professions) prof.add(new Option(PROF[p] || p, p, false, p === v.profession));
        prof.onchange = () => { v.profession = prof.value; remember(); };
        const ch = document.createElement('select');
        ch.className = 'ch';
        ch.add(new Option('😐 Нейтральный', 'default'));
        for (const [key, c] of Object.entries(info.characters)) ch.add(new Option(c.label, key));
        ch.add(new Option('✍️ Свой текст…', '__own'));
        const custom = !(v.character in info.characters) && v.character !== 'default';
        ch.value = custom ? '__own' : v.character;
        const own = document.createElement('input');
        own.className = 'own'; own.maxLength = 300; own.hidden = !custom;
        own.placeholder = 'Например: You love music and hate being alone.';
        own.value = custom ? v.character : '';
        own.oninput = () => { v.character = own.value.trim() || 'default'; remember(); };
        const about = document.createElement('div');
        about.className = 'hint';
        const showAbout = () => { about.textContent = info.characters[v.character] ? '«' + info.characters[v.character].text + '»' : ''; };
        ch.onchange = () => {
          own.hidden = ch.value !== '__own';
          v.character = ch.value === '__own' ? (own.value.trim() || 'default') : ch.value;
          if (!own.hidden) own.focus();
          showAbout(); remember();
        };
        showAbout();
        // Look (viewer/sprites.js): automatic = by the name's sex and the profession; or any of the drawn villagers.
        const look = document.createElement('select');
        look.className = 'look'; look.title = 'Внешность';
        look.add(new Option('🎲 Внешность: авто', ''));
        const S = window.Sprites, nl = (S && S.LOOKS) || 0;
        for (let k = 0; k < nl; k++) look.add(new Option(`${S.lookIsFemale(k) ? '👩' : '👨'} Внешность ${k + 1}`, String(k)));
        look.value = Number.isInteger(v.look) ? String(v.look) : '';
        const face = document.createElement('canvas');
        face.className = 'face'; face.width = 20; face.height = 26;
        const showFace = () => {
          const g = face.getContext('2d'); g.clearRect(0, 0, face.width, face.height);
          const sheet = Number.isInteger(v.look) && S && S.ok && S.villager(v.look);
          face.hidden = !sheet;
          if (sheet) g.drawImage(sheet, 0, 0, sheet.fw, sheet.fh, (face.width - sheet.fw) / 2, face.height - sheet.fh, sheet.fw, sheet.fh);
        };
        look.onchange = () => { if (look.value === '') delete v.look; else v.look = +look.value; showFace(); remember(); };
        if (S && !S.ok) S.onReady(showFace); else showFace();
        r.append(name, prof, ch, look, face, own, about);
        list.appendChild(r);
      });
    }

    function syncRoster() {
      if (roster && roster.length < n()) fetchRoster(roster).then(d => { roster = d.roster; drawRoster(); remember(); },
        e => { $('su-msg').textContent = e.message; $('su-msg').className = 'msg bad'; });
      else drawRoster();
    }

    $('su-own').onchange = () => {
      if (!$('su-own').checked) { roster = null; drawRoster(); remember(); return; }
      fetchRoster().then(d => { roster = d.roster; drawRoster(); remember(); });
    };
    $('su-rand').onclick = () => fetchRoster([]).then(d => {
      const keys = Object.keys(info.characters);
      roster = d.roster.map(v => Object.assign(v, { character: keys[Math.floor(Math.random() * keys.length)] }));
      drawRoster(); remember();
    });
    $('su-neutral').onclick = () => { roster.forEach(v => { v.character = 'default'; }); drawRoster(); remember(); };
    syncRoster();

    $('su-reset').onclick = () => { touched = new Set(); set(byKey.mode, values.mode); };
    $('su-go').onclick = () => {
      const go = $('su-go');
      go.disabled = true; $('su-msg').textContent = 'Строю деревню…'; $('su-msg').className = 'msg';
      const body = {};
      for (const k of knobs) if (!(k.only && k.only !== values.brains)) body[k.key] = values[k.key];
      if (roster) body.roster = roster.slice(0, n());
      post('/api/start', body).then(() => location.reload(), e => {
        go.disabled = false; $('su-msg').textContent = e.message; $('su-msg').className = 'msg bad';
      });
    };

    // Past sessions (aivillage/session.py): the summary page, plus the replay of the map.
    fetch('/api/sessions').then(r => r.json()).then(d => {
      const box = $('su-runs');
      box.textContent = d.sessions.length ? '' : 'Прошлых сессий пока нет.';
      for (const s of d.sessions.slice(0, 10)) {
        const line = document.createElement('div');
        const a = document.createElement('a');
        a.href = '/session/' + encodeURIComponent(s.name);
        a.textContent = '📋 ' + s.name.replace('_', ' ').replace(/-(\d\d)-(\d\d)$/, ':$1');
        const info = document.createElement('span');
        info.className = 'hint';
        info.textContent = ` ${s.villagers} жит., «${s.mode}»` + (s.summary ? `, ${s.days} дн.` + (s.top ? `: ${s.top}` : '') : '') + (s.note ? ' 💬' : '') + ' ';
        const r = document.createElement('a');
        r.href = '/replay/' + encodeURIComponent(s.name); r.target = '_blank'; r.textContent = '▶ повтор';
        line.append(a, info, r);
        box.appendChild(line);
      }
      if (d.sessions.length) {
        const all = document.createElement('a');
        all.href = '/sessions'; all.textContent = 'Все сессии →';
        box.appendChild(all);
      }
    }).catch(() => { $('su-runs').textContent = ''; });
    $('su-report').onclick = () => post('/api/report-last', { note: $('su-note').value }).then(d => {
      $('su-rmsg').textContent = 'Готово: ' + d.path + '. Перетащите этот файл в чат проекта.'; $('su-rmsg').className = 'msg';
    }, e => { $('su-rmsg').textContent = e.message; $('su-rmsg').className = 'msg bad'; });
  }
})();

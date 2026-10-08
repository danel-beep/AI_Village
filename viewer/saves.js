// Saves (aivillage/saves.py), injected by aivillage/server.py on every page.
// In a village: "💾 Сохранить" in the top-left row (POST /api/save). The village also saves itself every game
// hour, when it is stopped and when it ends. On the start screen's "💾 Продолжить" page (setup.js): the saved villages
// (GET /api/saves) with "▶ Продолжить" (POST /api/load, then the page reloads into the village).
(function () {
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || ('ошибка ' + r.status));
      return data;
    });
  const pad = n => String(n).padStart(2, '0');
  const when = s => `день ${s.day}, ${pad(s.hour)}:${pad(s.minute || 0)}`;
  // run logs are named by their start time: 2026-10-06_03-16-04 -> 06.10 03:16
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const started = name => { const m = /^\d{4}-(\d\d)-(\d\d)_(\d\d)-(\d\d)/.exec(name); return m ? `${m[2]}.${m[1]} ${m[3]}:${m[4]}` : esc(name); };

  fetch('/api/setup').then(r => r.ok ? r.json() : { running: true }).catch(() => ({ running: true }))
    .then(info => info.running ? saveButton() : startScreen());

  function saveButton() {
    const b = document.createElement('button');
    const label = '💾 Сохранить';
    b.textContent = label;
    b.title = 'Сохранить деревню, чтобы потом продолжить с этого места (начальный экран → «Продолжить»). ' +
      'Она и сама сохраняется каждый игровой час и при остановке.';
    const show = (text, ms) => { b.textContent = text; clearTimeout(b._t); if (ms) b._t = setTimeout(() => { b.textContent = label; }, ms); };
    b.onclick = () => {
      b.disabled = true; show('💾 Сохраняю…');
      post('/api/save').then(d => {
        if (d.pending) show('⏳ Сохраню после хода жителей…');
        else show('✓ Сохранено: ' + when(d), 4000);
      }, e => { show('✖ ' + e.message, 6000); }).finally(() => { b.disabled = false; });
    };
    window.addEventListener('village-live', e => {  // a save that waited for the villagers' turn
      if (e.detail && e.detail.type === 'saved' && b.textContent.startsWith('⏳')) show('✓ Сохранено: ' + when(e.detail), 4000);
    });
    const bar = document.getElementById('rp-bar');
    if (bar) { bar.appendChild(b); bar.style.flexWrap = 'wrap'; }
    else {
      b.style.cssText = 'position:fixed;left:8px;top:38px;z-index:30;background:#34403b;color:#e8efe9;border:0;' +
        'border-radius:20px;padding:7px 12px;font:600 13px system-ui,sans-serif;cursor:pointer';
      document.body.appendChild(b);
    }
  }

  function startScreen() {
    fetch('/api/saves').then(r => r.json()).then(d => {
      if (!d.can_load || !d.saves.length) return;
      // setup.js draws the start screen after its own fetch: wait for it
      let tries = 0;
      const t = setInterval(() => {
        const key = document.getElementById('su-saves-slot');
        if (key || ++tries > 100) { clearInterval(t); if (key) draw(key, d.saves); }
      }, 50);
    }).catch(() => {});
  }

  function draw(after, list) {
    const css = document.createElement('style');
    css.textContent = `
      #su-saves .sv { display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:8px 0; border-top:1px solid #2f3935; }
      #su-saves .sv:first-of-type { border-top:0; }
      #su-saves .sv .info { flex:1; min-width:220px; }
      #su-saves .sv .meta { font-size:12px; color:#9db0a4; margin-top:2px; }
      #su-saves .sv button { background:#76b041; color:#1d2321; border:0; border-radius:10px; padding:9px 16px;
        font:700 14px system-ui; cursor:pointer; }
      #su-saves .sv button:disabled { opacity:.6; cursor:wait; }
      #su-saves .sv input { width:56px; background:#1d2321; color:#e8efe9; border:1px solid #4a5650; border-radius:6px;
        padding:6px; font:14px system-ui; }
      #su-saves .more { background:none; border:0; color:#9db0a4; padding:6px 0 0; cursor:pointer; font:13px system-ui; }`;
    document.head.appendChild(css);
    const box = document.createElement('section');
    box.id = 'su-saves';
    box.innerHTML = '<h2>💾 Продолжить деревню</h2><div class="hint" style="margin:0 0 4px">Деревня продолжится ' +
      'с момента сохранения: тот же мир, та же память жителей.</div><div id="su-slist"></div><div class="msg" id="su-smsg"></div>';
    after.insertAdjacentElement('afterend', box);
    const listEl = box.querySelector('#su-slist');
    const msg = box.querySelector('#su-smsg');
    const rows = list.map(s => {
      const row = document.createElement('div');
      row.className = 'sv';
      const who = s.llm ? 'ИИ-жители' : 'боты';
      const alive = s.alive < s.villagers ? ` (живы ${s.alive})` : '';
      row.innerHTML = `<div class="info"><b>Деревня от ${started(s.name)}</b>
        <div class="meta">${s.finished ? 'прогон закончился' : 'остановлена'}: ${when(s)} · ${s.villagers} жителей${alive} · ${who}
        · сохранено ${(s.saved_at || '').slice(5, 16).replace(/^(\d\d)-(\d\d)/, '$2.$1')}</div></div>`;
      const go = document.createElement('button');
      let days = null;
      if (s.finished) {
        days = document.createElement('input');
        days.type = 'number'; days.min = 1; days.max = 365; days.value = s.days || 1; days.title = 'сколько ещё игровых дней';
        const lab = document.createElement('span'); lab.textContent = 'ещё дней:'; lab.style.fontSize = '13px';
        row.append(lab, days);
        go.textContent = '▶ Играть дальше';
      } else go.textContent = '▶ Продолжить';
      go.onclick = () => {
        go.disabled = true; msg.textContent = 'Загружаю деревню…'; msg.className = 'msg';
        const L = window.VillageLoading;  // setup.js: the loading screen until the village is on the map
        if (L) L.start('Загружаю деревню', 'Тот же мир, та же память жителей.');
        post('/api/load', { name: s.name, days: days ? Number(days.value) : null }).then(() => location.reload(), e => {
          if (L) L.fail(e);
          go.disabled = false; msg.textContent = e.message; msg.className = 'msg bad';
        });
      };
      row.appendChild(go);
      return row;
    });
    rows.forEach((r, k) => { if (k >= 3) r.hidden = true; listEl.appendChild(r); });
    if (rows.length > 3) {
      const more = document.createElement('button');
      more.className = 'more'; more.textContent = `показать все (${rows.length})`;
      more.onclick = () => { rows.forEach(r => { r.hidden = false; }); more.remove(); };
      box.insertBefore(more, msg);
    }
  }
})();

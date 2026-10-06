// Scenarios (aivillage/scenario.py, scenarios/*.yaml), injected by aivillage/server.py on every page.
// On the start screen: "🧪 Сценарии", ready-made situations (GET /api/scenarios). "▶ ИИ" plays one with AI
// villagers, "▶ Боты" with bots only (free, to see the setup); POST /api/scenario, then the page reloads into
// the village. What the scenario looked for is written next to the run's log (<log>.scenario.md) at the end.
(function () {
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || ('ошибка ' + r.status));
      return data;
    });

  fetch('/api/setup').then(r => r.ok ? r.json() : { running: true }).catch(() => ({ running: true }))
    .then(info => { if (!info.running) startScreen(); });

  function startScreen() {
    fetch('/api/scenarios').then(r => r.json()).then(d => {
      if (!d.can_start || !d.scenarios.length) return;
      let tries = 0;  // setup.js draws the start screen after its own fetch: wait for it
      const t = setInterval(() => {
        const key = document.getElementById('su-key');
        if (key || ++tries > 100) { clearInterval(t); if (key) draw(key, d.scenarios); }
      }, 50);
    }).catch(() => {});
  }

  function draw(after, list) {
    const css = document.createElement('style');
    css.textContent = `
      #su-scen .sc { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:8px 0; border-top:1px solid #2f3935; }
      #su-scen .sc:first-of-type { border-top:0; }
      #su-scen .sc .info { flex:1; min-width:220px; }
      #su-scen .sc .meta { font-size:12px; color:#9db0a4; margin-top:2px; }
      #su-scen .sc button { background:#76b041; color:#1d2321; border:0; border-radius:10px; padding:9px 14px;
        font:700 14px system-ui; cursor:pointer; }
      #su-scen .sc button.bots { background:#4a5650; color:#e8efe9; }
      #su-scen .sc button:disabled { opacity:.6; cursor:wait; }`;
    document.head.appendChild(css);
    const box = document.createElement('section');
    box.id = 'su-scen';
    box.innerHTML = '<h2>🧪 Сценарии</h2><div class="hint" style="margin:0 0 4px">Деревня начинается не с нуля, ' +
      'а с готовой ситуации: нужный мир и память жителей. Короткий и дешёвый тест одной проблемы.</div>' +
      '<div id="su-sclist"></div><div class="msg" id="su-scmsg"></div>';
    after.insertAdjacentElement('afterend', box);
    const listEl = box.querySelector('#su-sclist');
    const msg = box.querySelector('#su-scmsg');
    const buttons = [];
    list.forEach(s => {
      const row = document.createElement('div');
      row.className = 'sc';
      const ai = s.ai === 'all' ? 'все ИИ' : `ИИ: ${s.ai.length}`;
      row.innerHTML = `<div class="info"><b>${esc(s.title)}</b><div class="meta">${esc(s.about || '')}</div>
        <div class="meta">играть ${s.days} дн. · ${ai}</div></div>`;
      const go = (brains, label, cls) => {
        const b = document.createElement('button');
        b.textContent = label;
        if (cls) b.className = cls;
        b.title = brains === 'llm' ? 'Жители с ИИ (нужен ключ, стоит центы)' : 'Только боты: бесплатно, видно расстановку';
        b.onclick = () => {
          buttons.forEach(x => { x.disabled = true; });
          msg.textContent = 'Готовлю сценарий…'; msg.className = 'msg';
          post('/api/scenario', { name: s.name, brains }).then(() => location.reload(), e => {
            buttons.forEach(x => { x.disabled = false; });
            msg.textContent = e.message; msg.className = 'msg bad';
          });
        };
        buttons.push(b);
        row.appendChild(b);
      };
      go('llm', '▶ ИИ');
      go('bots', '▶ Боты', 'bots');
      listEl.appendChild(row);
    });
  }
})();

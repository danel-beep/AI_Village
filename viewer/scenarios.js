// Scenarios (aivillage/scenario.py, scenarios/*.yaml), injected by aivillage/server.py on every page.
// On the start screen's "🧪 Опыты и сценарии" page (setup.js): ready-made situations (GET /api/scenarios). "▶ ИИ" plays one with AI
// villagers, "▶ Боты" with bots only (free, to see the setup); POST /api/scenario, then the page reloads into
// the village. What the scenario looked for is written next to the run's log (<log>.scenario.md) at the end.
// Experiments (scenarios with arms, replicates or seating, aivillage/lab.py) get «🔬 Опыт» instead: they play in
// the background (POST /api/lab), optionally from a saved village; progress and the comparison show below the list.
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
    Promise.all([fetch('/api/scenarios').then(r => r.json()),
                 fetch('/api/saves').then(r => r.json()).catch(() => ({ saves: [] }))]).then(([d, sv]) => {
      if (!d.can_start || !d.scenarios.length) return;
      let tries = 0;  // setup.js draws the start screen after its own fetch: wait for it
      const t = setInterval(() => {
        const key = document.getElementById('su-scen-slot');
        if (key || ++tries > 100) { clearInterval(t); if (key) draw(key, d.scenarios, sv.saves || []); }
      }, 50);
    }).catch(() => {});
  }

  function labText(j) {
    const where = j.of ? ` · прогон ${j.index} из ${j.of}` + (j.arm ? ` (ветка ${esc(j.arm)}, повтор ${j.replicate})` : '') : '';
    const cost = j.llm ? ` · потрачено $${(j.spent || 0).toFixed(2)}` : '';
    if (j.state === 'running') return `🔬 Опыт «${esc(j.name)}» идёт${where}${cost}`;
    if (j.state === 'error') return `🔬 Опыт «${esc(j.name)}» сломался: ${esc(j.error || '')}`;
    return `🔬 Опыт «${esc(j.name)}» готов${j.stopped ? ' (остановлен: ' + esc(j.stopped) + ')' : ''}${cost}. ` +
      `Файлы: ${esc(j.out)}`;
  }

  function draw(after, list, saved) {
    const css = document.createElement('style');
    css.textContent = `
      #su-scen .sc { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:8px 0; border-top:1px solid #2f3935; }
      #su-scen .sc:first-of-type { border-top:0; }
      #su-scen .sc .info { flex:1; min-width:220px; }
      #su-scen .sc .meta { font-size:12px; color:#9db0a4; margin-top:2px; }
      #su-scen .sc button { background:#76b041; color:#1d2321; border:0; border-radius:10px; padding:9px 14px;
        font:700 14px system-ui; cursor:pointer; }
      #su-scen .sc button.bots { background:#4a5650; color:#e8efe9; }
      #su-scen .sc button:disabled { opacity:.6; cursor:wait; }
      #su-scen .sc select { background:#26302c; color:#e8efe9; border:1px solid #4a5650; border-radius:8px; padding:7px; }
      #su-scen #su-lab { margin-top:8px; }
      #su-scen #su-lab pre { white-space:pre-wrap; background:#1d2321; border:1px solid #2f3935; border-radius:8px;
        padding:10px; max-height:420px; overflow:auto; font:12px/1.45 ui-monospace,monospace; }
      #su-scen #su-lab button { background:#4a5650; color:#e8efe9; border:0; border-radius:8px; padding:6px 10px; cursor:pointer; }`;
    document.head.appendChild(css);
    const box = document.createElement('section');
    box.id = 'su-scen';
    box.innerHTML = '<h2>🧪 Сценарии</h2><div class="hint" style="margin:0 0 4px">Деревня начинается не с нуля, ' +
      'а с готовой ситуации: нужный мир и память жителей. Короткий и дешёвый тест одной проблемы.</div>' +
      '<div id="su-sclist"></div><div class="msg" id="su-scmsg"></div><div id="su-lab"></div>';
    after.insertAdjacentElement('afterend', box);
    const listEl = box.querySelector('#su-sclist');
    const msg = box.querySelector('#su-scmsg');
    const buttons = [];
    const labBox = box.querySelector('#su-lab');
    let polling = null;
    const showLab = () => fetch('/api/lab').then(r => r.json()).then(d => {
      const j = d.job;
      if (!j) { labBox.innerHTML = ''; return; }
      labBox.innerHTML = `<div class="meta">${labText(j)}</div>` +
        (j.state === 'running' ? '<button id="su-labstop">Остановить после этого прогона</button>' : '') +
        (j.report ? `<pre>${esc(j.report)}</pre>` : '');
      const stop = labBox.querySelector('#su-labstop');
      if (stop) stop.onclick = () => post('/api/lab/stop').then(() => { stop.disabled = true; stop.textContent = 'Остановится после этого прогона'; });
      if (j.state === 'running' && !polling) polling = setInterval(showLab, 3000);
      if (j.state !== 'running' && polling) { clearInterval(polling); polling = null; }
    }).catch(() => {});
    showLab();
    list.forEach(s => {
      const row = document.createElement('div');
      row.className = 'sc';
      const ai = s.ai === 'all' ? 'все ИИ' : `ИИ: ${s.ai.length}`;
      const runs = s.lab ? ` · опыт: ветки ${['A'].concat(s.arms.length ? ['AA'] : [], s.arms).join(', ')}, ` +
        `повторов ${s.replicates}` + (s.models.length ? `, модели ${s.models.map(m => m.split('/').pop()).join(' и ')} меняются местами` : '') : '';
      row.innerHTML = `<div class="info"><b>${esc(s.title)}</b><div class="meta">${esc(s.about || '')}</div>
        <div class="meta">играть ${s.days} дн. · ${ai}${esc(runs)}</div></div>`;
      if (s.lab) {
        let from = null;
        if (saved.length) {
          from = document.createElement('select');
          from.title = 'С чего начать каждый прогон';
          from.innerHTML = '<option value="">начать как в сценарии</option>' + saved.map(v =>
            `<option value="${esc(v.name)}">из сохранения: ${esc(v.name)} (день ${v.day})</option>`).join('');
          row.appendChild(from);
        }
        const lab = (brains, label, cls) => {
          const b = document.createElement('button');
          b.textContent = label;
          if (cls) b.className = cls;
          b.title = brains === 'llm' ? 'Все ветки и повторы с ИИ, в фоне (стоит центы за прогон)'
            : 'Все ветки и повторы на ботах: бесплатно, проверить, что опыт собирается';
          b.onclick = () => {
            msg.textContent = ''; msg.className = 'msg';
            post('/api/lab', { name: s.name, brains, save: from ? from.value : '' }).then(showLab, e => {
              msg.textContent = e.message; msg.className = 'msg bad';
            });
          };
          row.appendChild(b);
        };
        lab('llm', '🔬 Опыт');
        lab('bots', '🔬 Боты', 'bots');
        listEl.appendChild(row);
        return;
      }
      const go = (brains, label, cls) => {
        const b = document.createElement('button');
        b.textContent = label;
        if (cls) b.className = cls;
        b.title = brains === 'llm' ? 'Жители с ИИ (нужен ключ, стоит центы)' : 'Только боты: бесплатно, видно расстановку';
        b.onclick = () => {
          buttons.forEach(x => { x.disabled = true; });
          msg.textContent = 'Готовлю сценарий…'; msg.className = 'msg';
          const L = window.VillageLoading;  // setup.js: the loading screen until the village is on the map
          if (L) L.start('Готовлю сценарий', 'Расставляю мир и память жителей.');
          post('/api/scenario', { name: s.name, brains }).then(() => location.reload(), e => {
            if (L) L.fail(e);
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

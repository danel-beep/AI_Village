// Recaps and problem reports: injected by aivillage/server.py. Two buttons at the top left:
// "Что произошло?" (LLM recaps from /api/summary, new ones also arrive over the live feed) and
// "Сообщить о проблеме" (note + the tick being watched -> POST /api/report -> a zip on disk).
// Reads only the viewer globals `ticks` / `i`, so it does not depend on the viewer's layout.
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #rp-bar { position:fixed; left:8px; top:38px; z-index:30; display:flex; gap:6px; }
    #rp-bar button { background:#34403b; color:#e8efe9; border-radius:20px; padding:7px 12px; font-weight:600;
      box-shadow:0 2px 8px rgba(0,0,0,.5); }
    .rp-panel { position:fixed; left:8px; top:78px; z-index:30; width:360px; max-width:calc(100vw - 24px);
      max-height:calc(100vh - 150px); overflow:auto; background:#252c29; color:#e8efe9; border-radius:12px; padding:10px;
      box-shadow:0 4px 16px rgba(0,0,0,.6); font:13px/1.45 system-ui, sans-serif; }
    .rp-panel[hidden] { display:none; }
    .rp-panel h4 { margin:2px 0 8px; font-size:13px; color:#9db0a4; text-transform:uppercase; }
    .rp-panel .when { color:#9db0a4; font-size:12px; margin-top:8px; }
    .rp-panel textarea { width:100%; min-height:90px; background:#34403b; color:#e8efe9; border:0;
      border-radius:6px; padding:6px; box-sizing:border-box; font:13px system-ui; }
    .rp-panel .go { margin-top:8px; width:100%; background:#76b041; color:#1d2321; font-weight:700; }
    .rp-panel .msg { font-size:12px; min-height:16px; margin-top:6px; }
  `;
  document.head.appendChild(css);

  const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const bar = el('div', { id: 'rp-bar' });
  const sumBtn = el('button', { textContent: '📜 Что произошло?' });
  const repBtn = el('button', { textContent: '🐞 Сообщить о проблеме' });
  bar.append(sumBtn, repBtn);
  const sumPanel = el('div', { className: 'rp-panel', hidden: true });
  const repPanel = el('div', { className: 'rp-panel', hidden: true });
  document.body.append(bar, sumPanel, repPanel);

  const watched = () => {
    const t = typeof ticks !== 'undefined' && ticks.length ? ticks[Math.min(i, ticks.length - 1)] : null;
    return t ? { tick: t.tick, day: t.view.day, hour: t.view.hour, minute: t.view.minute || 0 } : null;
  };

  // --- recaps ---
  let summaries = [], enabled = true;
  sumPanel.innerHTML = '<h4>Что произошло</h4><button class="go">Пересказать последние события</button>' +
    '<div class="msg"></div><div class="list"></div>';
  const sumMsg = sumPanel.querySelector('.msg'), list = sumPanel.querySelector('.list');
  function render() {
    list.innerHTML = '';
    if (!enabled) { sumMsg.textContent = 'Сводки работают только с ключом OpenRouter.'; return; }
    if (!summaries.length) list.append(el('div', { className: 'when', textContent: 'Сводка появится в конце каждого игрового дня или по кнопке.' }));
    for (const s of summaries.slice().reverse()) {
      list.append(el('div', { className: 'when', textContent: `${s.from} — ${s.to}` }), el('div', { textContent: s.text }));
    }
  }
  async function loadSummaries() {
    try {
      const r = await (await fetch('/api/summary')).json();
      enabled = r.enabled; summaries = r.summaries || [];
    } catch (e) { /* server is restarting; the live feed will bring new recaps */ }
    render();
  }
  sumBtn.onclick = () => { repPanel.hidden = true; sumPanel.hidden = !sumPanel.hidden; if (!sumPanel.hidden) loadSummaries(); };
  sumPanel.querySelector('.go').onclick = async ev => {
    ev.target.disabled = true; sumMsg.textContent = 'Модель пишет пересказ…';
    try {
      const r = await fetch('/api/summary', { method: 'POST' });
      const body = await r.json();
      sumMsg.textContent = r.ok ? '' : (body.detail || 'Не получилось.');
      if (r.ok && !summaries.some(s => s.from_tick === body.from_tick && s.to_tick === body.to_tick)) summaries.push(body);
    } catch (e) { sumMsg.textContent = 'Нет связи с игрой.'; }
    ev.target.disabled = false; render();
  };
  window.addEventListener('village-live', e => {
    const rec = e.detail;
    if (rec.type !== 'summary') return;
    if (!summaries.some(s => s.from_tick === rec.from_tick && s.to_tick === rec.to_tick)) summaries.push(rec);
    summaries.sort((a, b) => a.from_tick - b.from_tick);
    if (!sumPanel.hidden) render();
  });

  // --- problem reports ---
  repPanel.innerHTML = '<h4>Сообщить о проблеме</h4><div class="when"></div>' +
    '<textarea placeholder="Что не так? Например: Борис застрял у реки, ничего не делает с 10 утра."></textarea>' +
    '<button class="go">Сохранить отчёт</button><div class="msg"></div>';
  const repWhen = repPanel.querySelector('.when'), note = repPanel.querySelector('textarea'),
        repMsg = repPanel.querySelector('.msg');
  let at = null;
  repBtn.onclick = () => {
    sumPanel.hidden = true; repPanel.hidden = !repPanel.hidden;
    if (repPanel.hidden) return;
    at = watched();  // remember the moment the player was looking at when they clicked
    repWhen.textContent = at ? `Момент на экране: день ${at.day}, ${String(at.hour).padStart(2, '0')}:${String(at.minute || 0).padStart(2, '0')} (ход ${at.tick})` : '';
    repMsg.textContent = ''; note.focus();
  };
  repPanel.querySelector('.go').onclick = async ev => {
    if (!note.value.trim()) { repMsg.textContent = 'Напишите пару слов, что не так.'; return; }
    ev.target.disabled = true; repMsg.textContent = 'Сохраняю…';
    try {
      const r = await fetch('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: note.value, tick: at ? at.tick : null }) });
      const body = await r.json();
      if (r.ok) {
        repMsg.textContent = `Готово: файл ${body.name}. Папка с ним открылась сама. Перетащите этот файл в чат проекта с Claude.`;
        note.value = '';
      } else repMsg.textContent = body.detail || 'Не получилось сохранить.';
    } catch (e) { repMsg.textContent = 'Нет связи с игрой.'; }
    ev.target.disabled = false;
  };
})();

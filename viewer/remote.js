// Own AIs over MCP: injected by aivillage/server.py in live mode. Shows nothing unless the village has seats for
// people's own AIs (start screen "Свои ИИ"). A "🔌 Свои ИИ" button opens the links per villager, the internet
// tunnel switch and how to connect; a banner at the top says whom the village is waiting for, so a slow AI never
// looks like a frozen game. Data: GET /api/remote every 1.5 s; POST /api/remote/tunnel, /api/remote/skip.
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #ra-btn { position:fixed; left:8px; top:118px; z-index:30; background:#34403b; color:#e8efe9; border-radius:20px;
      padding:7px 12px; font-weight:600; box-shadow:0 2px 8px rgba(0,0,0,.5); }
    #ra-btn[hidden], #ra-panel[hidden], #ra-wait[hidden] { display:none; }
    #ra-panel { position:fixed; left:8px; top:158px; z-index:31; width:420px; max-width:calc(100vw - 24px);
      max-height:calc(100vh - 180px); overflow:auto; background:#252c29; color:#e8efe9; border-radius:12px;
      padding:10px 12px; box-shadow:0 4px 16px rgba(0,0,0,.6); font:13px/1.45 system-ui, sans-serif; }
    #ra-panel h4 { margin:2px 0 6px; font-size:13px; color:#9db0a4; text-transform:uppercase; }
    #ra-panel .sub { color:#9db0a4; font-size:12px; margin-bottom:8px; }
    #ra-panel button { background:#34403b; color:#e8efe9; border-radius:8px; padding:4px 9px; font-weight:600; }
    #ra-panel .go { background:#76b041; color:#1d2321; }
    #ra-panel .seat { border-top:1px solid #34403b; padding:7px 0; }
    #ra-panel .link { display:flex; gap:6px; margin-top:4px; }
    #ra-panel .link input { flex:1; min-width:0; background:#34403b; color:#e8efe9; border:0; border-radius:6px;
      padding:4px 6px; font:12px ui-monospace, monospace; }
    #ra-panel .note { color:#e3c46b; font-size:12px; margin-top:4px; }
    #ra-panel ol { padding-left:18px; margin:6px 0; } #ra-panel li { margin:4px 0; }
    #ra-panel textarea { width:100%; min-height:86px; background:#34403b; color:#e8efe9; border:0; border-radius:6px;
      padding:6px; box-sizing:border-box; font:12px system-ui; }
    #ra-wait { position:fixed; left:50%; transform:translateX(-50%); top:8px; z-index:32; background:#3b3420;
      color:#f3e3b0; border-radius:20px; padding:6px 14px; font:600 13px system-ui, sans-serif;
      box-shadow:0 2px 10px rgba(0,0,0,.5); display:flex; gap:10px; align-items:center; }
    #ra-wait button { background:#5a4d2a; color:#f3e3b0; border-radius:14px; padding:3px 10px; font-weight:600; }
  `;
  document.head.appendChild(css);

  const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const btn = el('button', { id: 'ra-btn', textContent: '🔌 Свои ИИ', hidden: true });
  const panel = el('div', { id: 'ra-panel', hidden: true });
  const wait = el('div', { id: 'ra-wait', hidden: true });
  document.body.append(btn, panel, wait);
  btn.onclick = () => { panel.hidden = !panel.hidden; if (!panel.hidden) draw(); };

  const PROMPT = 'Сыграй за меня в AI Village через коннектор деревни. Сначала вызови join_village и покажи мне ' +
    'карточку сессии; начинай, только когда я отвечу «да». Потом играй сам до конца игры: next_turn, потом answer, ' +
    'и так по кругу. Не останавливайся и ничего у меня не спрашивай; если ход не твой, снова вызывай next_turn.';
  const STATE = { playing: '🟢 играет', asking: '🟡 ждёт «да» от игрока', offline: '⚪ не подключён' };
  const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) }).then(r => r.json());
  const copy = (text, b) => {
    const done = () => { const t = b.textContent; b.textContent = '✓'; setTimeout(() => { b.textContent = t; }, 1200); };
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(done, () => window.prompt('Скопируйте:', text));
  };

  let st = null;
  const base = () => (st.tunnel.state === 'on' && st.tunnel.url) || st.local;

  function drawWait() {
    if (!st || !st.open) { wait.hidden = true; return; }
    const offline = st.seats.filter(s => s.state !== 'playing' && !s.skipped && s.waiting);
    const thinking = st.seats.filter(s => s.state === 'playing' && s.waiting && s.waiting.seconds >= 3);  // no flicker on quick answers
    wait.innerHTML = '';
    if (offline.length) {
      wait.append(`🔌 Ждём, пока подключатся и скажут «да»: ${offline.map(s => s.name).join(', ')}`);
      const b = el('button', { textContent: 'Играть без них' });
      b.onclick = () => Promise.all(offline.map(s => post('/api/remote/skip', { name: s.name }))).then(poll);
      wait.append(b);
    } else if (thinking.length) {
      const lim = st.wait_minutes * 60;
      wait.append('⏳ Ждём ход своего ИИ: ' + thinking.map(s =>
        `${s.name}${s.client ? ' (' + s.client + ')' : ''} ${mmss(s.waiting.seconds)} из ${mmss(lim)}`).join(', '));
    }
    wait.hidden = !wait.childNodes.length;
  }

  function draw() {
    if (!st || panel.hidden) return;
    const t = st.tunnel;
    const tun = t.state === 'on' ? `🌍 Открыто из интернета: ${t.url}` : t.state === 'starting' ? '🌍 Открываю доступ…'
      : t.state === 'error' ? `⚠️ Не вышло открыть доступ: ${t.error}` : 'Доступ только с этого компьютера.';
    panel.innerHTML = `<h4>Свои ИИ</h4><div class="sub">Сессия ${st.session}${st.finished ? ' (игра окончена)' : ''} · ` +
      `ждать ход ${st.wait_minutes} мин · ${st.style === 'owner' ? 'как владелец' : 'сам за себя'}</div>` +
      `<div>${tun}</div>`;
    const tb = el('button', { className: t.state === 'on' ? '' : 'go',
      textContent: t.state === 'on' || t.state === 'starting' ? 'Закрыть доступ' : '🌍 Открыть доступ из интернета' });
    tb.onclick = () => post('/api/remote/tunnel', { on: !(t.state === 'on' || t.state === 'starting') }).then(poll);
    panel.append(tb);
    if (t.state !== 'on') panel.append(el('div', { className: 'note', textContent:
      'Claude, ChatGPT и Gemini подключаются из своего облака: без доступа из интернета ссылка работает только для ' +
      'Codex или Claude Code на этом компьютере.' }));
    for (const s of st.seats) {
      const row = el('div', { className: 'seat' });
      const status = s.skipped && s.state !== 'playing' ? '⏸ играем без него' : STATE[s.state];
      row.innerHTML = `<b>${s.name}</b> (${s.profession}) · ${status}${s.client ? ' · ' + s.client : ''}` +
        (s.answered ? ` · ходов: ${s.answered}` : '') + (s.misses ? ` · пропустил подряд: ${s.misses}` : '');
      const link = el('div', { className: 'link' });
      const inp = el('input', { value: base() + s.path, readOnly: true });
      const cb = el('button', { textContent: 'Копировать' });
      cb.onclick = () => copy(inp.value, cb);
      link.append(inp, cb);
      row.append(link);
      if (s.state !== 'playing') {
        const sk = el('button', { textContent: s.skipped ? 'Ждать его' : 'Играть без него' });
        sk.style.marginTop = '4px';
        sk.onclick = () => post('/api/remote/skip', { name: s.name, skip: !s.skipped }).then(poll);
        row.append(sk);
      }
      panel.append(row);
    }
    const how = el('div');
    how.innerHTML = '<h4 style="margin-top:10px">Как подключить</h4><ol>' +
      '<li>Откройте доступ из интернета и отправьте другу ссылку его жителя. У каждого жителя своя ссылка; ' +
      'в новой игре ссылки новые.</li>' +
      '<li>Друг добавляет ссылку как коннектор:<br>' +
      '• <b>Claude</b> (claude.ai или приложение): Настройки → Коннекторы → «Добавить свой коннектор».<br>' +
      '• <b>ChatGPT</b>: Настройки → Коннекторы → Дополнительно → Режим разработчика, потом «Создать».<br>' +
      '• <b>Gemini</b>: Настройки → Подключённые приложения → «Добавить своё приложение».<br>' +
      '• <b>Codex</b> на компьютере: <code>codex mcp add village --url ССЫЛКА</code></li>' +
      '<li>Чтобы ИИ играл сам несколько дней без людей, запускайте его в <b>Claude Code</b> (claude.ai/code, ' +
      'новая задача) или в <b>Codex</b>. В обычном чате он иногда остановится и попросит «продолжи».</li>' +
      '<li>Написать своему ИИ (он покажет карточку сессии и спросит «да»):</li></ol>';
    const ta = el('textarea', { value: PROMPT, readOnly: true });
    const pc = el('button', { textContent: 'Копировать текст' });
    pc.onclick = () => copy(PROMPT, pc);
    how.append(ta, pc);
    panel.append(how);
  }

  function poll() {
    return fetch('/api/remote').then(r => r.ok ? r.json() : null).then(d => {
      st = d && d.seats && d.seats.length ? d : null;
      btn.hidden = !st;
      if (!st) { panel.hidden = true; wait.hidden = true; return; }
      const keep = document.activeElement && panel.contains(document.activeElement);
      if (!keep) draw();
      drawWait();
    }).catch(() => {});
  }
  poll();
  setInterval(poll, 1500);
})();

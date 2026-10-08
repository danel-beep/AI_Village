// Live mode: injected by aivillage/server.py after the map viewer (viewer/index.html).
// Contract with the viewer, nothing else: `load(text)` takes a JSONL log, the global `ticks`
// array holds tick records, `i`/`playing` are the cursor. If the viewer exposes
// `window.viewerAppend(rec)`, that is used instead of touching `ticks` directly.
(() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let buffer = [], loaded = false, retry = 1000;
  const badge = document.createElement('div');
  badge.id = 'live-badge';
  badge.style.cssText = 'position:fixed;top:8px;left:8px;z-index:20;padding:3px 8px;border-radius:6px;' +
    'font:600 12px system-ui;background:#252c29;color:#e8efe9;box-shadow:0 1px 4px rgba(0,0,0,.4)';
  document.body.appendChild(badge);
  const setBadge = (text, color) => { badge.textContent = text; badge.style.color = color; };
  // Budget pause (aivillage/budget.py): a large plate over the map, so a stream viewer sees why nothing moves.
  const plate = document.createElement('div');
  plate.id = 'budget-plate';
  plate.style.cssText = 'position:fixed;top:30%;left:50%;transform:translateX(-50%);z-index:30;display:none;' +
    'max-width:min(560px,90vw);padding:18px 26px;border-radius:12px;text-align:center;' +
    'font:600 20px/1.4 system-ui;background:rgba(37,44,41,.94);color:#f2c14e;box-shadow:0 4px 18px rgba(0,0,0,.5)';
  document.body.appendChild(plate);
  const showPlate = text => {
    plate.innerHTML = '';
    const big = document.createElement('div'), small = document.createElement('div');
    big.textContent = '⏸ ' + text;
    small.textContent = 'Деньги на ИИ за сегодня кончились. Деревня продолжит сама, когда начнутся новые сутки.';
    small.style.cssText = 'font:400 14px/1.4 system-ui;color:#e8efe9;margin-top:6px';
    plate.append(big, small);
    plate.style.display = 'block';
  };
  const live = () => setBadge(slowPace ? '● LIVE · 🐢 темп по бюджету' : '● LIVE', '#76b041');
  let slowPace = false;

  function append(rec) {
    if (typeof window.viewerAppend === 'function') return window.viewerAppend(rec);
    if (rec.type !== 'tick') return;
    const follow = i >= ticks.length - 3;  // watching the newest ticks: keep following, never fall behind
    ticks.push(rec);
    document.getElementById('scrub').max = ticks.length - 1;
    if (follow) {
      if (ticks.length - 1 - i > 2) { i = ticks.length - 2; frac = 0; }
      playing = true; document.getElementById('play').textContent = '⏸';
    }
  }

  function connect() {
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onopen = () => {
      retry = 1000; live();
      // joining mid-pause (or a reconnect): the pause event went out before this page listened
      fetch('/api/status').then(r => r.json()).then(s => {
        if (s.budget_paused) { const t = 'Дневной бюджет $' + s.daily_budget + ' потрачен.'; setBadge('⏸ ' + t, '#f2c14e'); showPlate(t); }
      }).catch(() => {});
    };
    ws.onmessage = e => {
      const rec = JSON.parse(e.data);
      if (rec.type === 'header') { buffer = [e.data]; loaded = false; return; }
      if (rec.type === 'tick' || rec.type === 'diary') {  // diaries: the dossier's "Дневник" tab
        if (loaded) append(rec);
        else buffer.push(e.data);
      } else if (rec.type === 'end') setBadge('■ прогон завершён', '#9db0a4');
      else if (rec.type === 'error') setBadge('✖ ошибка: ' + rec.text, '#e4572e');
      else if (rec.type === 'budget_pause') { setBadge('⏸ ' + rec.text, '#f2c14e'); showPlate(rec.text); }
      else if (rec.type === 'budget_resume') { plate.style.display = 'none'; live(); }
      else if (rec.type === 'budget_pace') { slowPace = !!rec.slow; if (badge.textContent.startsWith('● LIVE')) live(); }
      window.dispatchEvent(new CustomEvent('village-live', { detail: rec }));
    };
    ws.onclose = () => {
      setBadge('○ нет связи, переподключаюсь…', '#f2c14e');
      setTimeout(connect, retry); retry = Math.min(retry * 2, 15000);
    };
  }

  // The backlog arrives in one burst; hand it to the viewer as a single log once it settles.
  setInterval(() => {
    if (!loaded && buffer.length > 1) {
      load(buffer.join('\n'));
      loaded = true;
      const drop = document.getElementById('drop');  // the "open a log file" dialog is not needed live
      if (drop) drop.style.display = 'none';
      // Start at the newest ticks: replaying the backlog would make pause look broken (the server stops,
      // the screen keeps playing old hours). The scrubber still reaches the past.
      // (the newest tick by the ticks themselves: night diaries in the backlog are not ticks)
      if (typeof i !== 'undefined') { i = Math.max(0, ticks.length - 1); frac = 1; }
    }
  }, 300);

  // One pause for everything: the viewer's ⏸ (and the god panel's) also stops the simulation on the
  // server, so no ticks (and no model calls) pile up while paused. Status goes out as 'village-paused'.
  window.addEventListener('viewer-play', e => {
    fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd: e.detail ? 'resume' : 'pause' }) }).then(r => r.json()).then(s => {
      if (!s.finished) { if (s.paused) setBadge('⏸ пауза', '#f2c14e'); else live(); }
      window.dispatchEvent(new CustomEvent('village-paused', { detail: s.paused }));
    });
  });

  connect();
})();

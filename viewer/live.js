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
    ws.onopen = () => { retry = 1000; setBadge('● LIVE', '#76b041'); };
    ws.onmessage = e => {
      const rec = JSON.parse(e.data);
      if (rec.type === 'header') { buffer = [e.data]; loaded = false; return; }
      if (rec.type === 'tick' || rec.type === 'diary') {  // diaries: the dossier's "Дневник" tab
        if (loaded) append(rec);
        else buffer.push(e.data);
      } else if (rec.type === 'end') setBadge('■ прогон завершён', '#9db0a4');
      else if (rec.type === 'error') setBadge('✖ ошибка: ' + rec.text, '#e4572e');
      else if (rec.type === 'budget_pause') setBadge('⏸ ' + rec.text, '#f2c14e');
      else if (rec.type === 'budget_resume') setBadge('● LIVE', '#76b041');
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
      const atEnd = buffer.length - 2;
      load(buffer.join('\n'));
      loaded = true;
      const drop = document.getElementById('drop');  // the "open a log file" dialog is not needed live
      if (drop) drop.style.display = 'none';
      // Start at the newest ticks: replaying the backlog would make pause look broken (the server stops,
      // the screen keeps playing old hours). The scrubber still reaches the past.
      if (typeof i !== 'undefined') { i = Math.max(0, atEnd); frac = 1; }
    }
  }, 300);

  // One pause for everything: the viewer's ⏸ (and the god panel's) also stops the simulation on the
  // server, so no ticks (and no model calls) pile up while paused. Status goes out as 'village-paused'.
  window.addEventListener('viewer-play', e => {
    fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd: e.detail ? 'resume' : 'pause' }) }).then(r => r.json()).then(s => {
      if (!s.finished) setBadge(s.paused ? '⏸ пауза' : '● LIVE', s.paused ? '#f2c14e' : '#76b041');
      window.dispatchEvent(new CustomEvent('village-paused', { detail: s.paused }));
    });
  });

  connect();
})();

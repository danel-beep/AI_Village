// Highlights of the day ("⭐ Хайлайты"): 3-5 dramatic moments per game day from aivillage/highlights.py.
// Data: window.EMBEDDED_HIGHLIGHTS (build_demo.py), GET /api/highlights and 'highlights' rows of the live feed.
// Clicking a moment rewinds the viewer to its tick, follows the villager and plays it.
// Uses only the viewer globals ticks / go / selected / setPlaying / tr.
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #hl-btn { background:#34403b; color:#e8efe9; border-radius:20px; padding:7px 12px; font-weight:600;
      box-shadow:0 2px 8px rgba(0,0,0,.5); }
    #hl-btn.own { position:fixed; left:8px; top:38px; z-index:30; }
    #hl-panel { position:fixed; left:8px; top:78px; z-index:31; width:360px; max-width:calc(100vw - 24px);
      max-height:calc(100vh - 150px); overflow:auto; background:#252c29; color:#e8efe9; border-radius:12px; padding:10px;
      box-shadow:0 4px 16px rgba(0,0,0,.6); font:13px/1.45 system-ui, sans-serif; }
    #hl-panel[hidden], #hl-toast[hidden] { display:none; }
    #hl-panel h4 { margin:10px 0 4px; font-size:13px; color:#9db0a4; text-transform:uppercase; }
    #hl-panel .hl { padding:6px 8px; border-radius:8px; cursor:pointer; margin-bottom:4px; background:#2e3733; }
    #hl-panel .hl:hover { background:#3b4842; }
    #hl-panel .hl b { color:#f2c14e; }
    #hl-panel .when, #hl-panel .msg { color:#9db0a4; font-size:12px; }
    #hl-toast { position:fixed; left:50%; bottom:70px; transform:translateX(-50%); z-index:31; max-width:min(560px, calc(100vw - 32px));
      background:rgba(20,26,23,.92); color:#e8efe9; border:1px solid #f2c14e; border-radius:10px; padding:8px 12px;
      font:14px/1.4 system-ui, sans-serif; }
  `;
  document.head.appendChild(css);
  const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const btn = el('button', { id: 'hl-btn', textContent: '⭐ Хайлайты', title: 'самые яркие моменты каждого дня' });
  const panel = el('div', { id: 'hl-panel', hidden: true });
  const toast = el('div', { id: 'hl-toast', hidden: true });
  const msg = el('div', { className: 'msg' }), list = el('div');
  panel.append(msg, list);
  let days = Array.isArray(window.EMBEDDED_HIGHLIGHTS) ? window.EMBEDDED_HIGHLIGHTS : [];
  const live = location.protocol.startsWith('http');

  function mount() {
    const bar = document.getElementById('rp-bar');  // live mode: sit next to the report.js buttons
    if (bar) {
      bar.append(btn);
      bar.addEventListener('click', e => { if (e.target !== btn) panel.hidden = true; });
    } else { btn.className = 'own'; document.body.append(btn); }
    document.body.append(panel, toast);
    btn.hidden = !live && !days.length;
  }
  const say = it => it.source === 'rules' || !it.text
    ? (typeof tr === 'function' ? tr(it.event) : it.event) + (it.times > 1 ? ` (×${it.times} за день)` : '')
    : it.text;

  function render() {
    list.innerHTML = '';
    msg.textContent = days.length ? 'Нажмите на момент, чтобы перемотать к нему.'
      : 'Хайлайты появятся в конце каждого игрового дня.';
    for (const d of days.slice().reverse()) {
      list.append(el('h4', { textContent: `День ${d.day}` }));
      for (const it of d.items) {
        const row = el('div', { className: 'hl' });
        row.append(el('div', { className: 'when', textContent: it.time + (it.who.length ? ' · ' + it.who.join(', ') : '') }),
                   el('b', { textContent: it.title }), el('div', { textContent: say({ ...it, source: d.source }) }));
        row.onclick = () => { panel.hidden = true; show({ ...it, source: d.source }); };
        list.append(row);
      }
    }
  }
  let toastTimer = 0;
  function show(it) {
    const k = ticks.findIndex(t => t.tick === it.tick);
    if (k < 0) { msg.textContent = 'Этот момент ещё не загружен в окно просмотра.'; return; }
    go(Math.max(0, k - 1), true);  // start an hour before, then play the moment itself
    if (it.who.length) { selected = it.who[0]; lastPanel = -1; }
    setPlaying(true);
    toast.textContent = `⭐ ${it.time}. ${it.title}: ${say(it)}`;
    toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.hidden = true, 8000);
  }
  function add(rec) {
    days = days.filter(d => d.day !== rec.day).concat([rec]).sort((a, b) => a.day - b.day);
    btn.hidden = false;
    if (!panel.hidden) render();
  }
  btn.onclick = async () => {
    document.querySelectorAll('.rp-panel').forEach(p => p.hidden = true);
    panel.hidden = !panel.hidden;
    if (panel.hidden) return;
    if (live) try { (await (await fetch('/api/highlights')).json()).highlights.forEach(add); } catch (e) { /* static file */ }
    render();
  };
  window.addEventListener('village-live', e => { if (e.detail.type === 'highlights') add(e.detail); });
  if (document.readyState === 'complete') mount(); else window.addEventListener('load', mount);
})();

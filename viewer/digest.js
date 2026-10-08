// "📰 Главное за день": a small panel over the bottom-right corner of the map with the most dramatic things of the
// day so far (up to the moment on screen), newest first. Scores and labels are the director camera's (camera.js),
// so both agree on what matters. Clicking a line rewinds a little before it and follows the villager.
// Reads the viewer's globals (ticks, i, go, select) at run time; nothing else depends on it.
(() => {
  const MIN = 5, MAX = 5, GROUP = new Set(['starving', 'hospital', 'election_day', 'fire_grows']), THEFT = /^(steal|theft|steal_attempt|robbed|witness)$/;   // one line per kind, names listed
  const box = document.createElement('div');
  box.style.cssText = 'position:absolute;right:8px;z-index:5;width:300px;max-width:45%;font:12px/1.35 system-ui;' +
    'background:rgba(27,27,36,.82);color:#e8efe9;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.4)';
  const head = document.createElement('button');
  head.style.cssText = 'all:unset;display:block;cursor:pointer;padding:5px 9px;font-weight:600;color:#ffe9a8;width:100%;box-sizing:border-box';
  const list = document.createElement('div');
  list.style.cssText = 'padding:0 9px 6px';
  box.append(head, list);
  let open = true, key = null;
  try { open = localStorage.getItem('aiv-digest') !== '0'; } catch (e) {}
  head.onclick = () => { open = !open; key = null; try { localStorage.setItem('aiv-digest', open ? '1' : '0'); } catch (e) {} };

  const pad = n => String(n).padStart(2, '0');
  function collect() {
    // The day a tick's events happened in (its view is the moment after, which may be the next morning).
    const dayOf = k => { const e = (ticks[k].events || []).find(e => e.day != null); return e ? e.day : ticks[Math.max(0, k - 1)].view.day; };
    const now = Math.min(i, ticks.length - 1), day = dayOf(now), seen = new Map();
    for (let k = now; k >= 0 && dayOf(k) >= day; k--) {
      for (const e of ticks[k].events || []) {
        const sc = Camera.score(e.kind, e.data); if (sc < MIN || (e.day != null && e.day !== day)) continue;
        const d = e.data || {}, who = e.actor || d.victim || (e.to || [])[0] || '';
        const group = GROUP.has(e.kind), id = group ? e.kind : (THEFT.test(e.kind) ? 'theft' : e.kind) + '|' + who;
        const it = seen.get(id);
        if (it && !it.target && !group) it.target = (e.to || []).find(n => n !== who);   // one theft, several events
        if (it && THEFT.test(e.kind) && it.k === k) continue;
        if (it) { if (group) { if (who && !it.names.includes(who)) it.names.push(who); } else it.times++; continue; }
        const target = (e.to || []).find(n => n !== who);
        seen.set(id, { k, sc, who, times: 1, names: [who], group, time: `${pad(e.hour)}:${pad(e.minute || 0)}`,
          label: Camera.label(e.kind), target });
      }
    }
    for (const it of seen.values()) it.text = it.label + (it.group ? ': ' + it.names.filter(Boolean).join(', ') :
      (it.who ? ': ' + it.who : '') + (it.target ? ' → ' + it.target : ''));
    return [...seen.values()].sort((a, b) => b.k - a.k || b.sc - a.sc).slice(0, MAX);
  }
  function refresh() {
    const map = document.getElementById('map'), bar = document.getElementById('bar');
    if (!box.parentElement && map) map.appendChild(box);
    if (typeof ticks === 'undefined' || !ticks.length || typeof Camera === 'undefined' || !Camera.score) { box.hidden = true; return; }
    box.hidden = false; box.style.bottom = (bar ? bar.offsetHeight : 40) + 8 + 'px';
    const items = open ? collect() : [], k2 = open + '|' + i + '|' + items.map(x => x.text + x.times).join();
    if (k2 === key) return; key = k2;
    head.textContent = (open ? '▾ ' : '▸ ') + '📰 Главное за день';
    list.hidden = !open;
    list.innerHTML = items.length ? '' : '<div style="color:#9db0a4">Пока тихо.</div>';
    for (const it of items) {
      const row = document.createElement('div');
      row.style.cssText = 'cursor:pointer;padding:2px 0;border-top:1px solid rgba(255,255,255,.08)';
      row.innerHTML = `<span style="color:#9db0a4">${it.time}</span> `;
      row.append(it.text + (it.times > 1 ? ` ×${it.times}` : ''));
      row.title = 'перемотать к этому моменту';
      row.onclick = () => { go(Math.max(0, it.k - 2)); if (it.who && typeof select === 'function' && selected !== it.who) select(it.who);
        if (typeof setPlaying === 'function') setPlaying(true); };
      list.appendChild(row);
    }
  }
  setInterval(refresh, 400);
})();

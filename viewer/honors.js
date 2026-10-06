// "🏅 Доска почёта": the honor board (aivillage/honors.py) at the moment on screen. A chip under the day counter
// (top right of the map) with the number of notes; clicking it opens the board: titles given by law, then the
// latest notes of praise, newest first. Hidden while the board is empty or the mechanic is off.
// Reads the viewer's globals (ticks, i, tr, select) at run time; nothing else depends on it.
(() => {
  const MAX_NOTES = 12;
  const box = document.createElement('div');
  box.style.cssText = 'position:absolute;right:8px;top:40px;z-index:5;width:300px;max-width:45%;font:12px/1.35 system-ui;' +
    'display:flex;flex-direction:column;align-items:flex-end;gap:4px';
  const chip = document.createElement('button');
  chip.style.cssText = 'all:unset;cursor:pointer;padding:3px 8px;border-radius:12px;background:rgba(27,27,36,.82);' +
    'color:#ffe9a8;font-weight:600;box-shadow:0 1px 4px rgba(0,0,0,.35)';
  chip.title = 'доска почёта: похвалы жителей друг другу и звания по закону';
  const panel = document.createElement('div');
  panel.style.cssText = 'width:100%;max-height:50vh;overflow:auto;background:rgba(27,27,36,.88);color:#e8efe9;' +
    'border-radius:8px;padding:6px 9px;box-shadow:0 1px 6px rgba(0,0,0,.4);box-sizing:border-box';
  box.append(chip, panel);
  let open = false, key = null;
  try { open = localStorage.getItem('aiv-honors') === '1'; } catch (e) {}
  chip.onclick = () => { open = !open; key = null; try { localStorage.setItem('aiv-honors', open ? '1' : '0'); } catch (e) {} };

  const t = s => (typeof tr === 'function' ? tr(s) : s);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const who = n => `<a href="#" data-who="${esc(n)}" style="color:#ffe9a8;text-decoration:none">${esc(n)}</a>`;

  function refresh() {
    const map = document.getElementById('map');
    if (!box.parentElement && map) map.appendChild(box);
    const v = typeof ticks !== 'undefined' && ticks.length ? (ticks[Math.min(i, ticks.length - 1)] || {}).view : null;
    const h = v && v.honors;
    if (!h || !((h.notes || []).length || Object.keys(h.titles || {}).length)) { box.hidden = true; key = null; return; }
    box.hidden = false;
    const notes = (h.notes || []).slice(-MAX_NOTES).reverse(), titles = h.titles || {};
    const k2 = open + '|' + JSON.stringify(h) + '|' + (typeof lang !== 'undefined' ? lang : '');
    if (k2 === key) return; key = k2;
    chip.textContent = `${open ? '▾' : '▸'} 🏅 Доска почёта · ${(h.notes || []).length}`;
    panel.hidden = !open;
    if (!open) return;
    const rows = [];
    const names = Object.keys(titles).sort();
    if (names.length) {
      rows.push('<div style="color:#9db0a4;margin:2px 0">Звания</div>');
      for (const n of names) for (const x of titles[n])
        rows.push(`<div style="padding:2px 0">${who(n)}: «${esc(t(x.title))}» <span style="color:#9db0a4">от ${esc(x.by === 'the village' ? 'деревни' : x.by)}, день ${x.day}</span></div>`);
    }
    if (notes.length) {
      rows.push('<div style="color:#9db0a4;margin:6px 0 2px">Похвалы</div>');
      for (const x of notes)
        rows.push(`<div style="padding:3px 0;border-top:1px solid rgba(255,255,255,.08)"><span style="color:#9db0a4">день ${x.day}</span> ` +
          `${who(x.by)} → ${who(x.about)}: «${esc(t(x.text))}»</div>`);
    }
    panel.innerHTML = rows.join('');
    panel.querySelectorAll('a[data-who]').forEach(a => a.onclick = e => {
      e.preventDefault(); if (typeof select === 'function') select(a.dataset.who);
    });
  }
  setInterval(refresh, 500);
})();

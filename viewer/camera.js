// Camera for the pixel map: wheel / +/- buttons / keys zoom, drag pans, a selected villager is followed.
// PixelMap attaches it to its canvas on the first draw; everything here is in map pixels (W x H) or canvas pixels.
const Camera = (() => {
  const MAXZ = 6;
  let cv = null, box = null, W = 1, H = 1, S = 2, z = 1, zt = 1, cx = 0, cy = 0, follow = null, down = null, dragged = false;

  const clampZ = v => Math.max(1, Math.min(MAXZ, v));
  function clampC() {
    const hw = W / (2 * z), hh = H / (2 * z);
    cx = Math.max(hw, Math.min(W - hw, cx)); cy = Math.max(hh, Math.min(H - hh, cy));
  }
  function view() { clampC(); return { x0: cx - W / (2 * z), y0: cy - H / (2 * z), z }; }
  // Client (mouse) coordinates -> canvas pixels; the canvas uses object-fit: contain, so undo the letterboxing.
  function toCanvas(e) {
    const r = cv.getBoundingClientRect(), k = Math.min(r.width / cv.width, r.height / cv.height);
    return [(e.clientX - r.left - (r.width - cv.width * k) / 2) / k, (e.clientY - r.top - (r.height - cv.height * k) / 2) / k];
  }
  function toWorld(px, py) { const v = view(); return [v.x0 + px / (S * z), v.y0 + py / (S * z)]; }
  function toScreen(wx, wy) { const v = view(); return [(wx - v.x0) * S * z, (wy - v.y0) * S * z]; }
  // Zoom keeping the map point under (px, py) canvas pixels in place.
  function zoomAt(f, px = cv.width / 2, py = cv.height / 2) {
    const [wx, wy] = toWorld(px, py);
    z = zt = clampZ(z * f);
    cx = wx - px / (S * z) + W / (2 * z); cy = wy - py / (S * z) + H / (2 * z); clampC();
  }
  function reset() { follow = null; zt = 1; }

  function attach(canvas, w, h, s) {
    W = w; H = h; S = s;
    if (cv === canvas) return;
    cv = canvas; cx = W / 2; cy = H / 2;
    canvas.addEventListener('wheel', e => { e.preventDefault(); zoomAt(Math.exp(-e.deltaY * .0015), ...toCanvas(e)); }, { passive: false });
    canvas.addEventListener('pointerdown', e => { down = { p: toCanvas(e), cx, cy }; dragged = false; });
    window.addEventListener('pointermove', e => {
      if (!down || !(e.buttons & 1)) return;
      const [px, py] = toCanvas(e), dx = px - down.p[0], dy = py - down.p[1];
      if (!dragged && Math.hypot(dx, dy) < 6) return;
      dragged = true; follow = null; canvas.style.cursor = 'grabbing';
      cx = down.cx - dx / (S * z); cy = down.cy - dy / (S * z); clampC();
    });
    window.addEventListener('pointerup', () => { down = null; canvas.style.cursor = ''; });
    // A drag must not count as a click on a villager.
    window.addEventListener('click', e => { if (dragged && e.target === canvas) { e.stopImmediatePropagation(); dragged = false; } }, true);
    window.addEventListener('keydown', e => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName)) return;
      if (e.key === '+' || e.key === '=') zoomAt(1.25); else if (e.key === '-') zoomAt(.8); else if (e.key === '0') reset();
    });
    box = document.createElement('div'); const parent = canvas.parentElement;
    if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
    box.style.cssText = 'position:absolute;left:8px;display:flex;gap:4px;z-index:5';   // bottom-left of the map, kept there in update()
    for (const [t, title, fn] of [['+', 'приблизить (колесо мыши)', () => zoomAt(1.4)], ['−', 'отдалить', () => zoomAt(1 / 1.4)],
                                  ['⤢', 'вся деревня (клавиша 0)', reset]]) {
      const bt = document.createElement('button'); bt.textContent = t; bt.title = title; bt.onclick = fn;
      bt.style.cssText = 'width:30px;height:30px;padding:0;font:600 16px system-ui;opacity:.9';
      box.appendChild(bt);
    }
    parent.appendChild(box);
  }

  // Called every frame. sel: selected villager name; pos(name) -> [x, y] map pixels or undefined.
  let lastSel = null;
  function update(dt, sel, pos) {
    if (sel !== lastSel) { lastSel = sel; follow = sel; if (sel && zt < 2.5) zt = 2.5; }
    if (Math.abs(zt - z) > .001) z += (zt - z) * (1 - Math.exp(-dt * 6)); else z = zt;
    const p = follow && pos(follow);
    if (p) { const f = 1 - Math.exp(-dt * 4); cx += (p[0] - cx) * f; cy += (p[1] - cy) * f; }
    clampC();
    if (box) box.style.top = (cv.offsetTop + cv.offsetHeight - 38) + 'px';
  }

  return { attach, update, view, toWorld, toScreen };
})();

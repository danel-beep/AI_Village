// Things passing between people on the pixel map, and feelings over their heads, played from the tick's events.
// Transfers: a gift, a loan, a repayment, a trade (both ways), nursing, selling to or buying from the trader,
// giving to a building site: the item's icon (viewer/icons.js) or a coin flies in an arc from one to the other,
// again and again for a few seconds. Emotes: a small bubble with a sign pops up over a head (a wedding, a
// proposal, a refusal, a divorce, a gift received, a loss noticed, a theft reported) and floats away.
// Like viewer/combat.js, what a tick shows outlives the tick (replay shows one for a fraction of a second).
// Gestures.plan(t) is pure (tests run it with node); PixelMap calls frame / draw / overlay.
const Gestures = (() => {
  const COIN = 'coins', LINGER = 3.2, CYCLE = 1.4;
  const ITEM_NAMES = () => (typeof window !== 'undefined' && window.ItemIcons ? Object.keys(ItemIcons.MAP) : []);

  // The first item a text names ("gave 3 bread to Anna"), else coins when it names coins, else null.
  function itemOf(text, names = ITEM_NAMES()) {
    const words = String(text || '').toLowerCase().match(/[a-z_]+/g) || [];
    for (const w of words) if (names.includes(w) || names.includes(w.replace(/s$/, ''))) return names.includes(w) ? w : w.replace(/s$/, '');
    return /coin/.test(text || '') ? COIN : null;
  }

  // ---------- what tick t shows (pure) ----------
  function plan(t, names) {
    const moves = [], emotes = [];
    const pass = (from, to, item, place) => from && (to || place) && moves.push({ from, to: to || null, place: place || null, item: item || COIN });
    const feel = (n, sign) => n && !emotes.some(e => e.n === n && e.sign === sign) && emotes.push({ n, sign });
    for (const e of (t && t.events) || []) {
      const d = e.data || {}, to = (e.to || []).find(n => n !== e.actor), item = itemOf(e.text, names);
      switch (e.kind) {
        case 'give': pass(e.actor, to, item); feel(to, '😊'); break;
        case 'care': pass(e.actor, d.person || to, item); feel(d.person || to, '😊'); break;
        case 'lend': pass(e.actor, to, COIN); break;
        case 'repay': if (e.actor && d.lender !== e.actor) pass(e.actor, to || d.lender, item || COIN); break;
        case 'trade': {   // "<partner> and <actor> traded: <what the partner gives> for <what the actor gives>."
          const other = d.partner || to;
          pass(other, e.actor, item); pass(e.actor, other, itemOf(String(e.text).split(/\bfor\b/)[1], names) || COIN); break;
        }
        case 'buy': pass(e.actor, null, COIN, 'market'); moves.push({ from: null, place: 'market', to: e.actor, item: item || COIN }); break;
        case 'sell': pass(e.actor, null, item, 'market'); moves.push({ from: null, place: 'market', to: e.actor, item: COIN }); break;
        case 'contribute': pass(e.actor, null, item || 'wood', e.location); break;
        case 'proposal': feel(e.actor, '💍'); feel(to, '❤️'); break;
        case 'proposal_refused': feel(to, '💔'); break;
        case 'wedding': feel(e.actor, '💞'); feel(to, '💞'); break;
        case 'divorce': feel(e.actor, '💔'); feel(to, '💔'); break;
        case 'robbed': feel(d.victim || to, '😠'); break;
        case 'theft_report': feel(e.actor, '📢'); break;
        case 'help_stranger': feel(e.actor, '🤝'); break;
      }
    }
    return { moves, emotes };
  }

  // ---------- on screen ----------
  let live = [], tickId = null, now = 0;
  function frame(t, sec) {
    now = sec;
    const id = t ? t.tick : null;
    if (id !== tickId) {
      if (id == null || tickId == null || id < tickId || id > tickId + 8) live = [];
      tickId = id;
      if (t) { const p = plan(t);
        p.moves.forEach((m, i) => live.push({ ...m, born: sec + i * .25, until: sec + LINGER + i * .25 }));
        p.emotes.forEach((e, i) => live.push({ ...e, emote: true, born: sec + i * .15, until: sec + 2.6 + i * .15 })); }
    }
    live = live.filter(x => sec < x.until);
  }

  const icons = {};
  const pic = item => item in icons ? icons[item]
    : (icons[item] = (() => { const id = window.ItemIcons && ItemIcons.MAP[item]; return id && window.Icons && Icons.ITEMS[id] ? Icons.canvas(id, 1) : null; })());
  function thing(b, item, x, y) {
    const ic = item !== COIN && pic(item);
    if (ic) { b.drawImage(ic, Math.round(x) - 5, Math.round(y) - 5, 10, 10); return; }
    const cx = Math.round(x), cy = Math.round(y);   // a coin, or a small bundle for an item with no icon
    b.fillStyle = '#1b1b24'; b.fillRect(cx - 2, cy - 3, 5, 7); b.fillRect(cx - 3, cy - 2, 7, 5);
    b.fillStyle = item === COIN ? '#ffd23f' : '#c9a36b'; b.fillRect(cx - 1, cy - 2, 3, 5); b.fillRect(cx - 2, cy - 1, 5, 3);
    b.fillStyle = item === COIN ? '#fff6b0' : '#e8c99a'; b.fillRect(cx - 1, cy - 1, 1, 1);
  }

  // posOf(name) -> [x, mid-body y] or null; anchorOf(place) -> [x, y] or null (map pixels).
  function draw(b, posOf, anchorOf) {
    for (const m of live) {
      if (m.emote || now < m.born) continue;
      const a = m.from ? posOf(m.from) : anchorOf(m.place), z = m.to ? posOf(m.to) : anchorOf(m.place);
      if (!a || !z || (a[0] === z[0] && a[1] === z[1])) continue;
      const u = ((now - m.born) / CYCLE) % 1; if (u > .75) continue;
      const p = u / .75, e = p * p * (3 - 2 * p), h = 10 + Math.min(14, Math.hypot(z[0] - a[0], z[1] - a[1]) * .25);
      thing(b, m.item, a[0] + (z[0] - a[0]) * e, a[1] - 3 + (z[1] - a[1]) * e - Math.sin(e * Math.PI) * h);
    }
  }

  // Full-resolution emote bubbles over heads.
  function overlay(ctx, toScreen, posOf) {
    for (const x of live) {
      if (!x.emote || now < x.born) continue;
      const p = posOf(x.n); if (!p) continue;
      const age = now - x.born, pop = Math.min(1, age / .18), fade = Math.min(1, (x.until - now) / .5);
      const [sx, sy] = toScreen(p[0] + 8, p[1] - 18), y = sy - Math.min(12, age * 8), r = 17 * (.6 + .4 * pop);
      ctx.globalAlpha = fade;
      ctx.fillStyle = 'rgba(255,255,255,.95)'; ctx.strokeStyle = '#1b1b24'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(sx, y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(sx - 5, y + r - 2); ctx.lineTo(sx - 9, y + r + 6); ctx.lineTo(sx + 1, y + r - 1); ctx.fill();
      ctx.font = `${Math.round(20 * (.6 + .4 * pop))}px system-ui, "Apple Color Emoji", "Segoe UI Emoji", sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#000'; ctx.fillText(x.sign, sx, y + 1);
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'; ctx.globalAlpha = 1;
    }
  }

  return { plan, itemOf, frame, draw, overlay };
})();
if (typeof window !== 'undefined') window.Gestures = Gestures;
if (typeof module !== 'undefined') module.exports = Gestures;

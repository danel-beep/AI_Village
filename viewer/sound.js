// Sound: background music and event sounds, all synthesized with WebAudio (no audio files).
// Hooked from index.html's render(): Sound.update(header, ticks, i, playing). It only reads the log rows the viewer
// already shows, so it works the same in replay, the demo page and live mode.
//   - music: a slow generative tune, major by day, minor and quieter at night, in winter, in crises and during fires;
//   - ambience: wind (stronger in autumn/winter), birds by day, crickets on warm nights, market murmur when people
//     are at the market/square, fire roar and crackle while something burns;
//   - cues: one short sound per notable event of a newly shown tick (coins, fight, theft, fire, election...).
// Browsers start audio only after a click or key, so the AudioContext is created on the first gesture.
// Controls (🔊 button, volume, 🎵 music toggle) are added to #bar; the choice is remembered per browser.
(function () {
  // Event kind -> cue name. First match wins; kinds not listed stay silent (moves, work, talk are too frequent).
  const CUES = [
    [/^fire_out$/, 'hiss'],
    [/^(house_burned|burned)$/, 'collapse'],
    [/fire|arson|burning/, 'flare'],
    [/fight|attack|duel|brawl|hit/, 'punch'],
    [/^(steal|theft|robbed|steal_attempt)$/, 'sneak'],
    [/^witness/, 'whistle'],
    [/^(trade|buy|sell|give|share|repay|lend|pay|contribute|order_done|buy_lot)$/, 'coin'],
    [/^(election|election_day|mayor|new_mayor)$/, 'fanfare'],
    [/^(candidate|vote|law|tax)/, 'bell'],
    [/^morning$/, 'rooster'],
    [/^(crisis|threat_warning|threat_arrived)$/, 'omen'],
    [/^(threat_defeated|care)$/, 'relief'],
    [/^(defend|beast_attack|plundered)$/, 'punch'],
    [/^crisis_over$/, 'relief'],
    [/^(craft|build|project_done|upgrade)/, 'hammer'],
    [/^(hospital|evicted|death|died|dead|starving)$/, 'sad'],
    [/^(crop_ripe|harvest|treasure|gift|season|born|birth|wedding|married)/, 'sparkle'],
  ];
  // Cue names for one tick's events: each cue at most once, at most 3, in event order.
  function cues(events) {
    const out = [];
    for (const e of events || []) {
      const c = (CUES.find(([re]) => re.test(e.kind)) || [])[1];
      if (c && !out.includes(c) && out.length < 3) out.push(c);
    }
    return out;
  }
  // Mood of the moment from a view row: what the music and the ambience follow.
  function mood(header, view) {
    const s = header && header.config && header.config.seasons;
    const first = s && s.order ? Math.max(0, s.order.indexOf(s.start || s.order[0])) : 0;   // as aivillage/seasons.py
    const season = s && s.enabled !== false && s.order
      ? s.order[Math.floor((first * s.length_days + (s.offset_days || 0) + view.day - 1) / s.length_days) % s.order.length] : 'summer';
    const h = view.hour + (view.minute || 0) / 60, night = h < 5.5 || h >= 21, dusk = !night && (h < 7 || h >= 19);
    const busy = ['market', 'square'], crowd = Object.values(view.agents || {})
      .filter(a => a.status === 'active' && busy.includes(a.location)).length;
    const fires = (view.fires || []).length, dark = night || season === 'winter' || fires > 0 || (view.crises || []).length > 0;
    return { season, night, dusk, crowd: night ? 0 : crowd, fires, minor: dark };
  }

  let ctx = null, master, comp, bus = {}, beds = {}, noise, timer = 0, lastI = -1, cur = null, nextNote = 0, step = 0, cool = {};
  const prefs = { on: true, vol: 0.6, music: true };
  try { Object.assign(prefs, JSON.parse(localStorage.getItem('aiv-sound') || '{}')); } catch (e) {}
  const save = () => { try { localStorage.setItem('aiv-sound', JSON.stringify(prefs)); } catch (e) {} };

  function init() {
    if (ctx || !(window.AudioContext || window.webkitAudioContext)) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    comp = ctx.createDynamicsCompressor(); comp.connect(ctx.destination);
    master = ctx.createGain(); master.connect(comp);
    for (const [k, v] of Object.entries({ music: .32, amb: .55, sfx: .8 })) { bus[k] = ctx.createGain(); bus[k].gain.value = v; bus[k].connect(master); }
    noise = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const d = noise.getChannelData(0); for (let k = 0; k < d.length; k++) d[k] = Math.random() * 2 - 1;
    beds.wind = bed('bandpass', 500, .6, .07, 250);
    beds.market = bed('bandpass', 380, 1.4, 2.1, 0);
    beds.fire = bed('lowpass', 420, .5, .3, 120);
    applyPrefs();
    timer = setInterval(tickAudio, 100);
    document.addEventListener('visibilitychange', () => document.hidden ? ctx.suspend() : resume());
  }
  function resume() { if (ctx && ctx.state !== 'running' && prefs.on && !document.hidden) ctx.resume(); }
  // A looping filtered-noise layer with a slow wobble on the filter; its gain is the layer's volume.
  function bed(type, freq, q, lfoHz, lfoDepth) {
    const src = ctx.createBufferSource(); src.buffer = noise; src.loop = true;
    const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = ctx.createGain(); g.gain.value = 0;
    src.connect(f); f.connect(g); g.connect(bus.amb); src.start();
    if (lfoDepth) { const o = ctx.createOscillator(), og = ctx.createGain(); o.frequency.value = lfoHz; og.gain.value = lfoDepth; o.connect(og); og.connect(f.frequency); o.start(); }
    return g;
  }
  function applyPrefs() {
    if (!ctx) return;
    master.gain.setTargetAtTime(prefs.on ? prefs.vol : 0, ctx.currentTime, .1);
    bus.music.gain.setTargetAtTime(prefs.music ? .32 : 0, ctx.currentTime, .3);
    if (prefs.on) resume();
  }
  const set = (g, v, tau = 1.5) => g.gain.setTargetAtTime(v, ctx.currentTime, tau);

  // ---- building blocks ----
  function tone(freq, t, dur, { type = 'sine', vol = .3, to, attack = .005, out = bus.sfx, filter } = {}) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(.0001, t + dur);
    let n = o;
    if (filter) { const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = filter; o.connect(f); n = f; }
    n.connect(g); g.connect(out); o.start(t); o.stop(t + dur + .05);
  }
  function burst(t, dur, { type = 'bandpass', freq = 1000, q = 1, vol = .3, to, out = bus.sfx } = {}) {
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noise; f.type = type; f.frequency.setValueAtTime(freq, t); f.Q.value = q;
    if (to) f.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(.0001, t + dur);
    s.connect(f); f.connect(g); g.connect(out); s.start(t, Math.random()); s.stop(t + dur + .05);
  }
  const hz = midi => 440 * Math.pow(2, (midi - 69) / 12);

  // ---- event sounds ----
  const SFX = {
    coin: t => { tone(1900, t, .12, { vol: .18 }); tone(2500, t + .07, .25, { vol: .14 }); },
    punch: t => { for (let k = 0; k < 3; k++) { const s = t + k * .16 + Math.random() * .05;
      tone(140, s, .14, { to: 50, vol: .5 }); burst(s, .08, { type: 'lowpass', freq: 900, vol: .35 }); } },
    sneak: t => [76, 72, 69, 64].forEach((m, k) => tone(hz(m), t + k * .11, .1, { type: 'triangle', vol: .12 })),
    whistle: t => tone(1200, t, .35, { to: 2200, vol: .1, attack: .05 }),
    flare: t => { burst(t, 1.2, { type: 'lowpass', freq: 300, to: 2500, vol: .35 }); burst(t + .2, .9, { freq: 3000, q: .5, vol: .1 }); },
    hiss: t => burst(t, 1.4, { type: 'highpass', freq: 5000, to: 1500, vol: .22 }),
    collapse: t => { burst(t, 1.6, { type: 'lowpass', freq: 400, to: 60, vol: .6 }); tone(60, t, 1.2, { to: 30, vol: .4 }); },
    fanfare: t => [[60, 0], [64, .14], [67, .28], [72, .42], [67, .7], [72, .84]].forEach(([m, d]) =>
      tone(hz(m), t + d, d < .6 ? .2 : .6, { type: 'sawtooth', vol: .09, filter: 2200 })),
    bell: t => { tone(hz(84), t, 1.6, { vol: .12 }); tone(hz(84) * 2.76, t, .8, { vol: .04 }); },
    rooster: t => { tone(700, t, .18, { type: 'sawtooth', to: 900, vol: .05, filter: 1800 });
      tone(900, t + .2, .5, { type: 'sawtooth', to: 600, vol: .06, filter: 1800, attack: .04 }); },
    omen: t => [45, 48, 51].forEach(m => tone(hz(m), t, 2.5, { type: 'sawtooth', vol: .07, filter: 500, attack: .4 })),
    relief: t => [60, 64, 67, 72].forEach((m, k) => tone(hz(m), t + k * .09, 1.4, { type: 'triangle', vol: .07, attack: .05 })),
    hammer: t => [0, .22].forEach(d => { tone(2600, t + d, .15, { type: 'square', vol: .04, filter: 4000 }); tone(180, t + d, .08, { vol: .2 }); }),
    sad: t => [67, 65, 62].forEach((m, k) => tone(hz(m), t + k * .3, .45, { type: 'triangle', vol: .09 })),
    sparkle: t => [84, 88, 91, 96].forEach((m, k) => tone(hz(m), t + k * .06, .3, { vol: .06 })),
  };
  function play(name) {
    if (!ctx || !prefs.on || ctx.state !== 'running') return;
    const now = ctx.currentTime;
    if (cool[name] > now) return;   // the same sound at most every 0.7 s, so a busy tick does not drum
    cool[name] = now + .7; SFX[name](now + .02);
  }

  // ---- ambience + music, every 100 ms while sound runs ----
  function tickAudio() {
    if (!ctx || ctx.state !== 'running' || !cur) return;
    const t = ctx.currentTime, m = cur, cold = m.season === 'winter' || m.season === 'autumn';
    set(beds.wind, m.night ? .12 : cold ? .16 : .06, 3);
    set(beds.market, Math.min(.18, m.crowd * .045), 2);
    set(beds.fire, Math.min(.5, m.fires * .3), 1);
    if (m.fires && Math.random() < .5) burst(t + Math.random() * .1, .03, { type: 'highpass', freq: 2500, vol: .15 + Math.random() * .2, out: bus.amb });
    if (!m.night && m.season !== 'winter' && Math.random() < (m.dusk ? .02 : .04)) {   // a bird: 2-4 quick chirps
      const base = 2400 + Math.random() * 1500, n = 2 + Math.floor(Math.random() * 3);
      for (let k = 0; k < n; k++) tone(base, t + k * .09, .07, { to: base * 1.3, vol: .025, out: bus.amb });
    }
    if (m.night && m.season !== 'winter' && Math.random() < .12)   // crickets
      for (let k = 0; k < 3; k++) tone(4400, t + k * .05, .03, { type: 'square', vol: .006, out: bus.amb, filter: 6000 });
    if (m.crowd > 1 && Math.random() < .01 * m.crowd) play('coin');
    music(t);
  }
  // Generative tune: a pad chord every two bars and a plucked melody on a pentatonic scale, scheduled ~0.4 s ahead.
  const DAY = [[48, 52, 55], [45, 48, 52], [41, 45, 48], [43, 47, 50]], NIGHT = [[45, 48, 52], [41, 45, 48], [48, 52, 55], [40, 43, 47]];
  const MAJ = [0, 2, 4, 7, 9], MIN = [0, 3, 5, 7, 10];
  let note = 0;
  function music(now) {
    if (!prefs.music) { nextNote = now; return; }
    const beat = cur.minor ? .62 : .45;   // eighth notes, slower in the dark
    if (nextNote < now) nextNote = now + .05;
    while (nextNote < now + .4) {
      const t = nextNote, bar = Math.floor(step / 8), chords = cur.minor ? NIGHT : DAY;
      if (step % 16 === 0) chords[(bar / 2) % 4].forEach(mi => {
        tone(hz(mi), t, beat * 16, { type: 'triangle', vol: .05, attack: 1.2, out: bus.music, filter: 900 });
        tone(hz(mi) * 1.004, t, beat * 16, { type: 'sine', vol: .04, attack: 1.4, out: bus.music });
      });
      if (Math.random() < (cur.minor ? .35 : .5)) {
        note = Math.max(0, Math.min(9, note + Math.floor(Math.random() * 5) - 2));
        const sc = cur.minor ? MIN : MAJ, root = cur.minor ? 69 : 72;
        tone(hz(root + sc[note % 5] + 12 * Math.floor(note / 5) - 12), t, beat * 3, { type: 'triangle', vol: .07, out: bus.music, filter: 2500 });
      }
      step = (step + 1) % 128; nextNote += beat;
    }
  }

  // Hook from the viewer: called on every render with the tick being shown.
  function update(header, ticks, i, playing) {
    const t = ticks[i]; if (!t || !t.view) return;
    cur = mood(header, t.view);
    if (i !== lastI) {
      // Only ticks reached by playing forward make sounds; a scrub or jump of several hours stays quiet.
      if (playing && lastI >= 0 && i > lastI && i - lastI <= 4)
        for (let k = lastI + 1; k <= i; k++) cues(ticks[k].events).forEach(play);
      lastI = i;
    }
  }

  // ---- controls in the bottom bar ----
  function controls() {
    const bar = document.getElementById('bar'); if (!bar || document.getElementById('snd')) return;
    const wrap = document.createElement('span'); wrap.id = 'snd';
    wrap.innerHTML = '<button id="sndbtn" title="звук: вкл/выкл"></button>' +
      '<input id="sndvol" type="range" min="0" max="1" step="0.05" title="громкость" style="width:70px">' +
      '<button id="sndmus" title="музыка: вкл/выкл">🎵</button>';
    bar.insertBefore(wrap, document.getElementById('clock'));
    const btn = wrap.querySelector('#sndbtn'), vol = wrap.querySelector('#sndvol'), mus = wrap.querySelector('#sndmus');
    const show = () => { btn.textContent = prefs.on ? '🔊' : '🔇'; vol.value = prefs.vol; mus.style.opacity = prefs.music ? 1 : .4;
      btn.setAttribute('aria-pressed', prefs.on); mus.setAttribute('aria-pressed', prefs.music); };
    btn.onclick = () => { prefs.on = !prefs.on; init(); applyPrefs(); save(); show(); };
    vol.oninput = () => { prefs.vol = +vol.value; prefs.on = prefs.vol > 0; init(); applyPrefs(); save(); show(); };
    mus.onclick = () => { prefs.music = !prefs.music; init(); applyPrefs(); save(); show(); };
    show();
  }
  // The first click or key anywhere unlocks audio (autoplay rules), if sound is on.
  const unlock = () => { if (prefs.on) { init(); resume(); } };
  ['pointerdown', 'keydown'].forEach(ev => window.addEventListener(ev, unlock, { capture: true }));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', controls); else controls();

  // The mixed output as a MediaStream, for recording (viewer/clip.js); follows the sound button and volume.
  let tap = null;
  function captureStream() {
    init(); resume();
    if (!ctx || !ctx.createMediaStreamDestination) return null;
    if (!tap) { tap = ctx.createMediaStreamDestination(); comp.connect(tap); }
    return tap.stream;
  }
  window.Sound = { update, cues, mood, play: n => { init(); resume(); play(n); }, prefs, captureStream };
})();

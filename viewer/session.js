// "🏁 Завершить сессию": injected by aivillage/server.py next to report.js. Stops the village
// (POST /api/end), the server saves the session summary next to the run log (aivillage/session.py),
// and the page opens it (/session/<name>). When all days are played the summary is saved on its own,
// and a banner offers to open it.
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #ss-end { background:#8a3b2e; color:#fff4ec; border-radius:20px; padding:7px 12px; font-weight:600;
      box-shadow:0 2px 8px rgba(0,0,0,.5); }
    #ss-end.solo { position:fixed; left:8px; top:38px; z-index:30; }
    #ss-cover { position:fixed; inset:0; z-index:60; background:rgba(15,19,17,.82); display:flex;
      align-items:center; justify-content:center; }
    #ss-cover[hidden] { display:none; }
    #ss-cover .box { background:#252c29; color:#e8efe9; border-radius:14px; padding:18px; width:380px;
      max-width:calc(100vw - 32px); font:14px/1.5 system-ui, sans-serif; box-shadow:0 6px 24px rgba(0,0,0,.6); }
    #ss-cover h3 { margin:0 0 8px; font-size:17px; }
    #ss-cover .row { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }
    #ss-cover button, #ss-cover a { border-radius:20px; padding:8px 14px; font:600 14px system-ui; border:0;
      background:#34403b; color:#e8efe9; cursor:pointer; text-decoration:none; }
    #ss-cover .go { background:#76b041; color:#1d2321; }
    #ss-cover .msg { color:#9db0a4; font-size:13px; min-height:18px; margin-top:8px; }
  `;
  document.head.appendChild(css);

  const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const btn = el('button', { id: 'ss-end', textContent: '🏁 Завершить сессию',
    title: 'Остановить деревню и посмотреть сводку: что произошло, главные истории, итоги по жителям' });
  const cover = el('div', { id: 'ss-cover', hidden: true });
  cover.innerHTML = '<div class="box"><h3></h3><div class="text"></div><div class="row"></div><div class="msg"></div></div>';
  document.body.appendChild(cover);
  const bar = document.getElementById('rp-bar');  // report.js buttons: sit next to them
  if (bar) bar.append(btn); else { btn.classList.add('solo'); document.body.appendChild(btn); }

  const box = cover.querySelector('.box'), row = box.querySelector('.row'), msg = box.querySelector('.msg');
  function show(title, text, buttons) {
    box.querySelector('h3').textContent = title;
    box.querySelector('.text').textContent = text;
    row.replaceChildren(...buttons); msg.textContent = ''; cover.hidden = false;
  }
  const button = (text, cls, onclick) => el('button', { textContent: text, className: cls || '', onclick });

  let ended = false;
  async function end() {
    row.querySelectorAll('button').forEach(b => { b.disabled = true; });
    msg.textContent = 'Останавливаю деревню и собираю сводку…';
    try {
      const r = await fetch('/api/end', { method: 'POST' });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || 'Не получилось.');
      ended = true;
      if (body.in_flight) {  // already sent: they finish on their own, usually within a minute
        msg.textContent = `Деревня остановлена. Ещё ${body.in_flight} запр. к ИИ в пути, они закончатся сами.`;
        await new Promise(r => setTimeout(r, 2500));
      }
      location.href = body.url;
    } catch (e) {
      msg.textContent = e.message === 'Failed to fetch' ? 'Нет связи с игрой.' : e.message;
      row.querySelectorAll('button').forEach(b => { b.disabled = false; });
    }
  }
  btn.onclick = () => show('Завершить сессию?',
    'Деревня остановится, и откроется сводка: что произошло по дням, главные истории и итоги по жителям. ' +
    'Сводка сохранится, её можно открыть потом в «Прошлых сессиях» и отправить Claude.',
    [button('🏁 Завершить', 'go', end), button('Продолжить игру', '', () => { cover.hidden = true; })]);

  // All days played: the server saves the summary itself and says so over the live feed.
  window.addEventListener('village-live', e => {
    const rec = e.detail;
    if (rec.type !== 'session' || ended || rec.ended_by === 'button') return;
    const open = el('a', { className: 'go', href: '/session/' + encodeURIComponent(rec.name), textContent: '📋 Открыть сводку' });
    show(rec.ended_by === 'error' ? 'Игра остановилась с ошибкой' : 'Все дни сыграны',
      'Сводка сессии сохранена.', [open, button('Остаться на карте', '', () => { cover.hidden = true; })]);
  });
})();

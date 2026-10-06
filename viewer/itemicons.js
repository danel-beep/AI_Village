// Item icons for the villager and building cards (dossier.js, hero.js, inspect.js), from the code-drawn
// 16x16 icons of viewer/icons.js. A game item (config `items`) maps to an icon; items with no icon show text only.
// ItemIcons.img(item) -> '<img ...>' or ''; ItemIcons.list({item: qty}, name) -> '<icon>3 wood, ...' (HTML).
const ItemIcons = (() => {
  const MAP = { wood: 'wood', plank: 'planks', planks: 'planks', stone: 'stone', clay: 'clay', brick: 'brick', ore: 'ore',
    iron: 'iron', gold: 'gold', coal: 'coal', hide: 'hide', leather: 'leather', wool: 'wool', cloth: 'cloth', clothes: 'cloth', rope: 'rope',
    grain: 'grain', hay: 'grain', flour: 'flour', herbs: 'herbs', stone_axe: 'stone_axe', stone_pick: 'stone_pickaxe',
    stone_pickaxe: 'stone_pickaxe', stone_knife: 'stone_knife', stone_hoe: 'stone_hoe', iron_axe: 'iron_axe',
    iron_pick: 'iron_pickaxe', iron_pickaxe: 'iron_pickaxe', hoe: 'iron_hoe', iron_hoe: 'iron_hoe', tool: 'hammer',
    hammer: 'hammer', saw: 'saw', sickle: 'sickle', fishing_rod: 'fishing_rod', club: 'club', spear: 'spear',
    iron_spear: 'iron_spear', bow: 'bow', arrows: 'arrows', sword: 'sword', knife: 'stone_knife',
    leather_armor: 'leather_armor', iron_armor: 'iron_armor', armor: 'leather_armor', leather_cap: 'leather_cap',
    helmet: 'iron_helmet', iron_helmet: 'iron_helmet', shield: 'wooden_shield', wooden_shield: 'wooden_shield',
    iron_shield: 'iron_shield', berries: 'berries', fish: 'fish', meat: 'meat', cooked_meat: 'cooked_meat',
    smoked_meat: 'cooked_meat', smoked_fish: 'smoked_fish', bread: 'bread', fish_soup: 'fish_soup', milk: 'milk',
    egg: 'egg', honey: 'honey', apple: 'apple', stew: 'stew', ring: 'gold' };
  const cache = {};
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function url(item) {
    const id = MAP[item] || item;
    if (id in cache) return cache[id];
    let u = '';
    try { if (window.Icons && Icons.ITEMS[id]) u = Icons.canvas(id, 2).toDataURL(); } catch (e) { u = ''; }
    return cache[id] = u;
  }
  function img(item) {
    const u = url(item);
    return u ? `<img class="itm" src="${u}" alt="" title="${esc(item)}" width="16" height="16" style="image-rendering:pixelated;vertical-align:-3px;margin-right:2px">` : '';
  }
  // {item: qty} -> HTML; name(item) gives the shown name (already safe text or escaped here).
  function list(o, name = k => k) {
    return Object.entries(o || {}).filter(([, q]) => q).map(([k, q]) => `<span style="white-space:nowrap">${img(k)}${q} ${esc(name(k))}</span>`).join(', ');
  }
  return { img, list, MAP };
})();
window.ItemIcons = ItemIcons;

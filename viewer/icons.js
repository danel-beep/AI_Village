// 16x16 item icons for the "from scratch" mode, drawn in code: resources, stone and iron tools, weapons, armour, food.
// Each icon is a pixel template (one letter per pixel, '.' transparent) or a template laid over a wooden handle.
// Stone tools have chipped grey heads lashed with rope; iron ones are smooth steel with a shine.
// API: Icons.draw(g, id, x, y, scale = 1); Icons.canvas(id, scale); Icons.ITEMS[id] = {name, group}.
const Icons = (() => {
  const PAL = {
    k: '#1b1b24', W: '#c08850', w: '#8a5a35', v: '#6b4226', h: '#d9b880', H: '#b48c55',
    S: '#d4d4dc', s: '#9a9aa2', t: '#6f6f78', I: '#f2f6fa', i: '#b8c0cc', j: '#7a8494', J: '#4a525e',
    r: '#d8b878', R: '#a8884a', L: '#d8a070', l: '#a86a3c', n: '#6e4426', e: '#e04a3a', E: '#9a2a22',
    g: '#7ab648', G: '#3d7530', y: '#ffd23f', Y: '#c8961c', o: '#e08a4a', O: '#b8581c', b: '#e8b060',
    B: '#b87a38', N: '#7a4a20', x: '#ffffff', c: '#f2e6c8', C: '#d0c098', u: '#8ac8e8', U: '#3f7fbf',
    V: '#2f5a8f', m: '#f09a8a', M: '#c04a4a', q: '#8a2a2a', a: '#3a3a44', A: '#5a5a66', z: '#d88058',
    p: '#b85a38', P: '#8a3e24', f: '#c8dcea', F: '#8aa8c4', T: '#5a7898', X: '#5a2a7a', Q: '#9a5ac0',
  };

  // [name, group, template rows] or [name, group, rows, {handle: length}] to draw a wooden handle under the template.
  const ITEMS = {
    // ---------- resources ----------
    wood: ['Брёвна', 'res', [
      '................', '................', '................', '...kkkkkkkkkk...',
      '..kWWWWWWWWWkhk.', '..kwwwwwwwwwhHhk', '..kvvvvvvvvvkhk.', '...kkkkkkkkkkk..',
      '.kkkkkkkkkkkk...', 'kWWWWWWWWWWkhk..', 'kwwwwwwwwwwhHhk.', 'kvvvvvvvvvvkhk..',
      '.kkkkkkkkkkkk...', '................', '................', '................']],
    planks: ['Доски', 'res', [
      '................', '................', '................', '.kkkkkkkkkkkkk..',
      '.kWWWWWWWWWWWk..', '.kwwwvwwwwwwwk..', '.kkkkkkkkkkkkkk.', '..kWWWWWWWWWWWk.',
      '..kwwwwwwwvwwwk.', '.kkkkkkkkkkkkkk.', '.kWWWWWWWWWWWk..', '.kwwvwwwwwwwwk..',
      '.kvvvvvvvvvvvk..', '.kkkkkkkkkkkkk..', '................', '................']],
    stone: ['Камень', 'res', [
      '................', '................', '................', '................',
      '.....kkkkk......', '...kkSSSSskk....', '..kSSSsssssskk..', '..kSSssssssstk..',
      '.kSsssssssstttk.', '.ksssssssstttk..', '.kssssstttttttk.', '..kttttttttttk..',
      '...kkkkkkkkkk...', '................', '................', '................']],
    clay: ['Глина', 'res', [
      '................', '................', '................', '................',
      '................', '.....kkkkkk.....', '...kkzzzzppkk...', '..kzzzpppppppk..',
      '..kzppppppppPk..', '.kzpppppppppPPk.', '.kpppppppPPPPPk.', '..kkkkkkkkkkkk..',
      '................', '................', '................', '................']],
    brick: ['Кирпич', 'res', [
      '................', '................', '................', '................',
      '....kkkkkkkk....', '....kzzzzzzk....', '....kppppppk....', '....kPPPPPPk....',
      'kkkkkkkkkkkkkkkk', 'kzzzzzzkkzzzzzzk', 'kppppppkkppppppk', 'kppppppkkppppppk',
      'kPPPPPPkkPPPPPPk', 'kkkkkkkkkkkkkkkk', '................', '................']],
    ore: ['Руда', 'res', [
      '................', '................', '................', '.....kkkkkk.....',
      '...kkSSssssk....', '..kSSoOsssssk...', '..kSsOOssoOstk..', '.kSssssssOOstk..',
      '.kssoOsssssttk..', '.kssOOssoOttttk.', '.ksssssssOOtttk.', '..kttttttttttk..',
      '...kkkkkkkkkk...', '................', '................', '................']],
    iron: ['Железо', 'res', [
      '................', '................', '................', '................',
      '................', '....kkkkkkkk....', '...kIIIIIIIIk...', '..kiIiiiiiiiik..',
      '.kiiiiiiiiiiijk.', '.kjjjjjjjjjjJJk.', '.kJJJJJJJJJJJJk.', '.kkkkkkkkkkkkkk.',
      '................', '................', '................', '................']],
    gold: ['Золото', 'res', [
      '................', '..........x.....', '.........xxx....', '..........x.....',
      '.....kkkk.......', '...kkyyyykk.....', '..kyyxyyyyYk....', '..kyyyyyyYYYkk..',
      '.kyyyyyyYYyyyk..', '.kYyyyyYYyyyYYk.', '.kYYYYYYYYYYYk..', '..kkkkkkkkkkkk..',
      '................', '................', '................', '................']],
    coal: ['Уголь', 'res', [
      '................', '................', '................', '................',
      '......kkkk......', '....kkAAAakk....', '...kAAaaaaak.kk.', '...kAaaaaaakkAk.',
      '.kkkaaaakkkkAak.', 'kAAkkkkkAAakaak.', 'kAaaak.kAaaakkk.', 'kaaaak.kaaaak...',
      '.kkkk...kkkk....', '................', '................', '................']],
    hide: ['Шкура', 'res', [
      '................', '...kk......kk...', '..kLLk....kLLk..', '..kLLLkkkkLLLk..',
      '...kLLLLLLLLk...', '...kLlLLLLlLk...', '..kLLLLLLLLLLk..', '..kLLLlLLlLLLk..',
      '..kLLLLLLLLLLk..', '...kLLLLLLLLk...', '...kLLlLLlLLk...', '..kLLLkkkkLLLk..',
      '..kLLk....kLLk..', '...kk......kk...', '................', '................']],
    leather: ['Кожа', 'res', [
      '................', '................', '................', '..kkkkkkkkkkkk..',
      '..kLLLLLLLLLLk..', '..kLnLnLnLnLLk..', '..klllllllllLk..', '..klllllllllLk..',
      '..kllllllllllk..', '..knlnlnlnlnlk..', '..knnnnnnnnnnk..', '..kkkkkkkkkkkk..',
      '................', '................', '................', '................']],
    wool: ['Шерсть', 'res', [
      '................', '................', '................', '.....kkkkk......',
      '...kkxxxxxkk....', '..kxxxccxxxck...', '.kxxcxxxxcxxck..', '.kxcxxxxxxxcCk..',
      '.kxxxxccxxxxCk..', '.kcxxcxxxxcCCk..', '..kCxxxxxCCCk...', '...kkCCCCCkk....',
      '.....kkkkk......', '................', '................', '................']],
    cloth: ['Ткань', 'res', [
      '................', '................', '................', '..kkkkkkkkkk....',
      '.kUUUUUUUUUUk...', 'kUuUUUUUUUUUUk..', 'kUUUUUUUUUUUVk..', 'kVVVVVVVVVVVVk..',
      'kkkkkkkkkkkkkkk.', '.kUUUUUUUUUUUuUk', '.kVUUUUUUUUUUUVk', '.kVVVVVVVVVVVVVk',
      '..kkkkkkkkkkkkk.', '................', '................', '................']],
    rope: ['Верёвка', 'res', [
      '................', '................', '.....kkkkkk.....', '...kkrrRrrRkk...',
      '..krRkkkkkkrRk..', '.krRk......kRrk.', '.kRk..kkkk..kRk.', '.krk.krRrk..krk.',
      '.kRk.kRkkk..kRk.', '.krRk......kRrk.', '..kRrkkkkkkrRk..', '...kkrRrrRrkkrk.',
      '.....kkkkkk..kRk', '..............kk', '................', '................']],
    grain: ['Зерно', 'res', [
      '................', '...k..k..k......', '..kyk.kyk.kyk...', '..kYk.kyk.kYk...',
      '..kyk.kYk.kyk...', '...kykkykkyk....', '...kYkkYkkYk....', '....kgkgkgk.....',
      '....kRRRRRk.....', '.....kgkgk......', '.....kgkgk......', '....kgk.kgk.....',
      '...kgk...kgk....', '...kk.....kk....', '................', '................']],
    flour: ['Мука', 'res', [
      '................', '................', '.....kk..kk.....', '......kRRk......',
      '.....kkkkkk.....', '....kxxxxxxk....', '...kcxxxxxxck...', '..kcccccccccck..',
      '..kcccxcccccCk..', '..kccxxxccccCk..', '..kcccxcccccCk..', '..kCcccccccCCk..',
      '...kCCCCCCCCk...', '....kkkkkkkk....', '................', '................']],
    herbs: ['Травы', 'res', [
      '................', '................', '......kk........', '.....kgGk..kk...',
      '..kk.kggk.kgGk..', '.kgGkkgGkkggk...', '.kggkkGgkGgk....', '..kGgkkgkGk.....',
      '....kGkgGk......', '.....kkGk.......', '.....krRk.......', '.....kGgk.......',
      '.....kGk........', '......k.........', '................', '................']],
    // ---------- tools: stone ----------
    stone_axe: ['Каменный топор', 'tool', [
      '................', '....kkkkk.......', '...kSSSSskk.....', '..kSSssssssk....',
      '..kSsssssskrRk..', '...kSsssskrRk...', '....ktttkRrk....', '.....kkk........',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 14 }],
    stone_pickaxe: ['Каменная кирка', 'tool', [
      '................', '..kkkk..........', '.kSSsssk........', '..kksssskk......',
      '....kksssskrRk..', '......kkkkrRssk.', '...........kstk.', '............ktk.',
      '.............k..', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 12 }],
    stone_knife: ['Каменный нож', 'tool', [
      '................', '.............kk.', '............kSk.', '...........kSsk.',
      '..........kSstk.', '.........kSstk..', '........kSstk...', '.......kSstk....',
      '......krRtk.....', '.....kRrRk......', '....kwWkk.......', '...kwWk.........',
      '..kwWk..........', '..kkk...........', '................', '................']],
    stone_hoe: ['Каменная мотыга', 'tool', [
      '................', '...kkkkk........', '..kSSSSssk......', '..kSsssssskrRk..',
      '...ktttttk......', '....kkkkk.......', '................', '................',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 14 }],
    // ---------- tools: iron ----------
    iron_axe: ['Железный топор', 'tool', [
      '..kkk...........', '.kIIIkk.........', 'kIIiiiikk.......', 'kIiiiiijkk......',
      'kIiiiiijjjkJJk..', 'kIiiiijjjkJJk...', '.kjjjJJk........', '..kkkk..........',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 12 }],
    iron_pickaxe: ['Железная кирка', 'tool', [
      '................', '.kkkk...........', 'kIIiikkk........', '.kkkiiijkk......',
      '.....kkiijkJJk..', '.........kJJjjk.', '...........kjjk.', '............kjk.',
      '.............k..', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 12 }],
    iron_hoe: ['Железная мотыга', 'tool', [
      '................', '................', '..kkkkkkkkk.....', '..kIIIiiiijkJJk.',
      '..kjjjjjjjJk....', '...kkkkkkkk.....', '................', '................',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 14 }],
    hammer: ['Молот', 'tool', [
      '................', '......kkkkkkkkk.', '......kIIIiiijk.', '......kiiiiijJk.',
      '......kjjjjjJJk.', '......kkkkkkkkk.', '................', '................',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 10 }],
    saw: ['Пила', 'tool', [
      '................', '................', '..kkkkkkkkkk....', '.kIIIIIIIIIIkk..',
      '.kiiiiiiiiiikWWk', '.kjjjjjjjjjjkwWk', '..kjkjkjkjkjkwwk', '...k.k.k.k.k.kkk',
      '................', '................', '................', '................',
      '................', '................', '................', '................']],
    sickle: ['Серп', 'tool', [
      '................', '......kkkk......', '....kkIiiikk....', '...kIikkkkjjk...',
      '..kIk.....kjk...', '..kik......kk...', '..kik...........', '..kjk...........',
      '...kjk..........', '....kjkk........', '.....kkWWk......', '.......kwWk.....',
      '........kwWk....', '.........kwk....', '..........k.....', '................']],
    fishing_rod: ['Удочка', 'tool', [
      '..............kk', '.............kWk', '............kWk.', '...........kWk.r',
      '..........kWk..r', '.........kWk...r', '........kWk....r', '.......kWk.....r',
      '......kWk......r', '.....kwk.....kek', '....kwk......kxk', '...kvvk........k',
      '..kvvk..........', '.kvvk...........', '.kkk............', '................']],
    // ---------- weapons ----------
    club: ['Дубина', 'weapon', [
      '..........kkk...', '.........kWWwk..', '........kWWwwvk.', '.......kWwwkwvk.',
      '......kWwwwwvk..', '.....kWwwkwvk...', '....kWwwwvvk....', '....kWwwvk......',
      '...kWwvk........', '..kWwk..........', '.kWwk...........', 'kWwk............',
      'kvk.............', '.k..............', '................', '................']],
    spear: ['Копьё', 'weapon', [
      '..............kk', '............kkSk', '...........kSSsk', '..........kSsstk',
      '..........krRkk.', '.........krRk...', '................', '................',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 13 }],
    iron_spear: ['Железное копьё', 'weapon', [
      '..............kk', '............kIIk', '...........kIiik', '.........kIiijk.',
      '..........kJJk..', '................', '................', '................',
      '................', '................', '................', '................',
      '................', '................', '................', '................'], { handle: 13 }],
    bow: ['Лук', 'weapon', [
      '....kkkkk.......', '...kWWwwvkk.....', '...kkkkkWwvk....', '...r....kkWvk...',
      '...r......kWvk..', '...r.......kWvk.', '...r.......kWwk.', '...r.......kWwk.',
      '...r.......kWwk.', '...r.......kWvk.', '...r......kWvk..', '...r....kkWvk...',
      '...kkkkkWwvk....', '...kWWwwvkk.....', '....kkkkk.......', '................']],
    arrows: ['Стрелы', 'weapon', [
      '................', '.........k...k..', '........kSk.kSk.', '.......kSsk.kSk.',
      '........kWk..kW.', '.......kWk..kWk.', '......kWk..kWk..', '.....kWk..kWk...',
      '....kWk..kWk....', '...kek..kWk.....', '..kexk.kek......', '..kkk.kexk......',
      '.......kkk......', '................', '................', '................']],
    sword: ['Железный меч', 'weapon', [
      '.............kk.', '............kIk.', '...........kIik.', '..........kIijk.',
      '.........kIijk..', '........kIijk...', '.......kIijk....', '..kk..kIijk.....',
      '..kYkkIijk......', '...kYYijk.......', '....kYYk........', '...kwkYYk.......',
      '..kwvk.kYk......', '.kyvk...kk......', '.kkk............', '................']],
    // ---------- armour ----------
    leather_armor: ['Кожаная броня', 'armor', [
      '................', '...kkk....kkk...', '..kLLLkkkkLLLk..', '.kLLlLLLLLLlLLk.',
      '.kLlLLLLLLLLlLk.', '.kllkLnLLnLklLk.', '..kkkLLLLLLkkk..', '....kLnLLnLk....',
      '....klLLLLlk....', '....kNNyNNNk....', '....klLLLLlk....', '....kllllllk....',
      '....knnnnnnk....', '....kkkkkkkk....', '................', '................']],
    iron_armor: ['Железная броня', 'armor', [
      '................', '...kkk....kkk...', '..kIiikkkkiiIk..', '.kIiiiIIIIiiijk.',
      '.kiijkIiiiIkjjk.', '.kjjkkIiiijkkJk.', '..kkkIiiiijkkk..', '....kIijiiijk...',
      '....kiiijjijk...', '....kJJYJJJk....', '....kIiiiijk....', '....kiiijjjk....',
      '....kjjjJJJk....', '....kkkkkkkk....', '................', '................']],
    leather_cap: ['Кожаный шлем', 'armor', [
      '................', '................', '................', '......kkkk......',
      '....kkLLLLkk....', '...kLLLLLLLlk...', '..kLLLnLLnLLlk..', '..kLLLLLLLLLlk..',
      '..klllllllllnk..', '..knnnnnnnnnnk..', '..kLk......kLk..', '..kkk......kkk..',
      '................', '................', '................', '................']],
    iron_helmet: ['Железный шлем', 'armor', [
      '................', '.......kk.......', '......kEEk......', '.....kkkkkk.....',
      '....kIIIiiik....', '...kIIiiiijjk...', '...kIiiiiijjk...', '..kkkkkkkkkkkk..',
      '..kiikJJJJkijk..', '..kiik....kijk..', '..kiikkJJkkijk..', '..kjjk.kk.kjjk..',
      '...kk......kk...', '................', '................', '................']],
    wooden_shield: ['Деревянный щит', 'armor', [
      '................', '.....kkkkkk.....', '...kkWWwWWwkk...', '..kWWWwWWWwwvk..',
      '.kWWWwWWWWwwwvk.', '.kWWWwkkkkwwwvk.', '.kWWWkjiijkwwvk.', '.kWWWkijjjkwwvk.',
      '.kWWWkjjjJkwwvk.', '.kWWWwkkkkwwwvk.', '.kWWWwWWWWwwwvk.', '..kWWwWWWwwwvk..',
      '...kkvvvvvvkk...', '.....kkkkkk.....', '................', '................']],
    iron_shield: ['Железный щит', 'armor', [
      '................', '..kkkkkkkkkkkk..', '..kIIIIIiiiiik..', '..kIEEEEEEEEjk..',
      '..kIEeeeeeeEjk..', '..kIEeyyyyeEjk..', '..kIEeyeeyeEjk..', '..kiEeeeeeeEjk..',
      '...kiEeeeeEjk...', '...kiEEeeEEjk...', '....kiEEEEjk....', '.....kijjjk.....',
      '......kjjk......', '.......kk.......', '................', '................']],
    // ---------- food ----------
    berries: ['Ягоды', 'food', [
      '................', '.......kk.......', '......kGGk......', '...kk.kGk.kk....',
      '..kGGkkgkkGGk...', '...kkkXkkkk.....', '..kXXkQXkkXXk...', '.kQXXkXXkQXXk...',
      '.kXXXkXXXXXXk...', '..kkkXXQXkkkk...', '....kQXXXXk.....', '....kXXXXXk.....',
      '.....kkkkk......', '................', '................', '................']],
    fish: ['Рыба', 'food', [
      '................', '................', '................', '................',
      '.......kkkkk....', '..kk.kkfffFFkk..', '.kFFkfffffFFFxk.', '.kFFFffffFFFFkk.',
      '.kTTFFFFFFFFFFk.', '.kTTkFTTTTTTFk..', '..kk.kkTTTTkk...', '......kkkkk.....',
      '................', '................', '................', '................']],
    meat: ['Мясо', 'food', [
      '................', '................', '................', '.....kkkkk......',
      '...kkmmmmMkk....', '..kmmmmMMMMMk...', '..kmmxmMMMMMk...', '.kmmMMMMMMMqk.kk',
      '.kmMMMMMMMqqkkxk', '..kMMMMMMqqkcxk.', '..kqqqqqqqkkcxk.', '...kkkkkkk.kxxk.',
      '...........kkk..', '................', '................', '................']],
    cooked_meat: ['Жареное мясо', 'food', [
      '................', '................', '................', '.....kkkkk......',
      '...kkbbbbBkk....', '..kbbbbBBBBBk...', '..kbbxbBBBBBk...', '.kbbBBBBBBBNk.kk',
      '.kbBBBBBBBNNkkxk', '..kBBBBBBNNkcxk.', '..kNNNNNNNkkcxk.', '...kkkkkkk.kxxk.',
      '...........kkk..', '................', '................', '................']],
    smoked_fish: ['Копчёная рыба', 'food', [
      '................', '.......k........', '.......k........', '......kOk.......',
      '......kok.......', '.....kooOk......', '.....kobOk......', '.....kooOk......',
      '.....kboOk......', '.....kooOk......', '......koOk......', '......kOk.......',
      '.....kOkOk......', '.....kk.kk......', '................', '................']],
    bread: ['Хлеб', 'food', [
      '................', '................', '................', '................',
      '.....kkkkkk.....', '...kkbbbbbbkk...', '..kbbcbbcbbcbk..', '.kbbbbbbbbbbBBk.',
      '.kbcbbcbbcbbBBk.', '.kBbbbbbbbbBBNk.', '.kBBBBBBBBBBNNk.', '..kNNNNNNNNNNk..',
      '...kkkkkkkkkk...', '................', '................', '................']],
    fish_soup: ['Уха', 'food', [
      '................', '.....x...x......', '......x...x.....', '.....x...x......',
      '................', '..kkkkkkkkkkkk..', '.kooOoooooOoook.', '.koxoOFFoooxook.',
      '.kkkkkkkkkkkkkk.', '..kWWWWWWWWWWk..', '..kwwwwwwwwwwk..', '...kwwwwwwwwk...',
      '....kvvvvvvk....', '.....kkkkkk.....', '................', '................']],
    milk: ['Молоко', 'food', [
      '................', '.....kkkkkk.....', '.....kWWWwk.....', '......kkkk......',
      '.....kxxxxk.....', '....kxxxxxck....', '...kxxxxxxxck...', '...kxxxxxxxCk...',
      '...kUUUUUUUVk...', '...kxuxxxxxCk...', '...kxxxxxxxCk...', '...kxxxxxxCCk...',
      '....kCCCCCCk....', '.....kkkkkk.....', '................', '................']],
    egg: ['Яйца', 'food', [
      '................', '................', '................', '................',
      '.....kkk........', '....kxxck.......', '...kxxxxck.kkk..', '...kxxxxckkcxck.',
      '...kxxxxCkcxxxck', '....kcCCkkcxxxck', '..kkkkkkkkcCCCk.', '.kRRrRRrRRkkkk..',
      '..kRRRRRRRRRk...', '...kkkkkkkkk....', '................', '................']],
    honey: ['Мёд', 'food', [
      '................', '.....kkkkkk.....', '....kCCCCCCk....', '.....kRrrRk.....',
      '....kkkkkkkk....', '...kyyyyyyyyk...', '..kyyxyyyyyyYk..', '..kyxyyyyyyyYk..',
      '..kyyyYYYYyyYk..', '..kyyYkkkYyyYk..', '..kyyYYYYYyyYk..', '..kYyyyyyyyYYk..',
      '...kYYYYYYYYk...', '....kkkkkkkk....', '................', '................']],
    apple: ['Яблоко', 'food', [
      '................', '........kk......', '.......kvk.kk...', '.......kvkkgGk..',
      '....kkkkvkkkk...', '...keeeeeeeEk...', '..kexxeeeeeeEk..', '..kexeeeeeeeEk..',
      '..keeeeeeeeeEk..', '..keeeeeeeeEEk..', '..kEeeeeeeEEEk..', '...kEEEEEEEEk...',
      '....kkkkkkkk....', '................', '................', '................']],
    stew: ['Похлёбка', 'food', [
      '................', '......x..x......', '.......x..x.....', '................',
      '.kkkkkkkkkkkkkk.', 'kJjjjjjjjjjjjjJk', 'kkMbgBbMgbBbMgkk', '.kBbMbgBbbMbBbk.',
      '.kjjjjjjjjjjjjk.', '.kJjjjjjjjjjjJk.', '..kJJJJJJJJJJk..', '...kkkkkkkkkk...',
      '....kk....kk....', '................', '................', '................']],
  };
  const GROUPS = { res: 'Ресурсы', tool: 'Инструменты', weapon: 'Оружие', armor: 'Броня', food: 'Еда' };

  // A wooden handle from the bottom-left corner going up-right, `len` px long (a 2 px wide stair with an outline).
  function handle(g, len, s) {
    for (let i = 0; i < len; i++) { const y = 15 - i;
      const x0 = Math.max(0, i - 1), x1 = Math.min(16, i + 3);
      g.fillStyle = PAL.k; g.fillRect(x0 * s, y * s, (x1 - x0) * s, s);
      g.fillStyle = PAL.W; g.fillRect(i * s, y * s, s, s); g.fillStyle = PAL.w; g.fillRect((i + 1) * s, y * s, s, s); }
    g.fillStyle = PAL.k; g.fillRect(0, 15 * s, 2 * s, s);
  }
  function draw(g, id, x = 0, y = 0, s = 1) {
    const it = ITEMS[id]; if (!it) return false;
    const [, , rows, opt] = it;
    g.save(); g.translate(x, y);
    if (opt && opt.handle) handle(g, opt.handle, s);
    rows.forEach((row, j) => { for (let i = 0; i < 16; i++) { const c = row[i]; if (!c || c === '.') continue;
      g.fillStyle = PAL[c]; g.fillRect(i * s, j * s, s, s); } });
    g.restore();
    return true;
  }
  function canvas(id, scale = 1, doc = document) {
    const c = doc.createElement('canvas'); c.width = c.height = 16 * scale;
    draw(c.getContext('2d'), id, 0, 0, scale); return c;
  }
  const LIST = Object.keys(ITEMS);
  const META = Object.fromEntries(LIST.map(id => [id, { name: ITEMS[id][0], group: ITEMS[id][1] }]));
  const api = { ITEMS: META, LIST, GROUPS, PAL, draw, canvas, rows: id => ITEMS[id][2] };
  if (typeof window !== 'undefined') window.Icons = api;
  return api;
})();

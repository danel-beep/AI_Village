"""Population: any number of villagers, and a world that grows with them.

`config.population.size = N` gives N villagers: the configured `agents` come first (by default the classic
five), the rest get unique names from `NAMES` (picked by seed, so each seed is a different village) and the
profession that is most under-staffed by `profession_weights`. Resources (start/max/regen of every
location resource except free ones like water), project needs and the number of council orders posted at
once are multiplied by
`resource_scale(cfg)` = max(1, N / base_size), so 20 villagers do not starve on a map tuned for 5.

`resolve(cfg)` runs at the end of `config.make_config`, is pure (seeded by `cfg["seed"]`) and marks the
config `resolved`, so replaying a log header does not grow the village twice.
"""

from __future__ import annotations

import random

# Short, distinct, easy to tell apart in a log or a speech bubble. The five classic names are in DEFAULT_CONFIG.
NAMES = [
    "Aaron", "Agnes", "Albert", "Alice", "Arthur", "Beatrice", "Bruno", "Camille", "Cecil", "Celia",
    "Daisy", "Dora", "Edgar", "Edith", "Emil", "Felix", "Flora", "Frida", "Gideon", "Greta",
    "Hannah", "Harold", "Hugo", "Ida", "Igor", "Irene", "Ivan", "Jasper", "Jonas", "Judith",
    "Karl", "Kira", "Lena", "Leo", "Lidia", "Lucas", "Mabel", "Marta", "Milo", "Nadia",
    "Nina", "Noah", "Olga", "Oscar", "Otto", "Pavel", "Petra", "Quentin", "Rosa", "Rufus",
    "Sofia", "Stefan", "Tamara", "Theo", "Ursula", "Victor", "Vera", "Walter", "Wanda", "Yuri",
    "Zara", "Zoltan",
]

MAX_SIZE = 60  # the name pool is the hard limit; the viewer draws 6 houses per street row


def size(cfg: dict) -> int:
    pop = cfg.get("population") or {}
    return int(pop["size"]) if pop.get("size") else len(cfg["agents"])


def resource_scale(cfg: dict) -> float:
    """How much bigger the world's resources are than the hand-tuned map (1.0 = as written)."""
    pop = cfg.get("population") or {}
    if not pop.get("scale_resources", True):
        return 1.0
    return max(1.0, size(cfg) / float(pop.get("base_size") or 5))


def generate_agents(existing: list[dict], n: int, cfg: dict) -> list[dict]:
    """`existing` (kept as is, first n of them) plus new villagers up to n."""
    agents = [dict(a) for a in existing[:n]]
    taken = {a["name"] for a in agents}
    rng = random.Random(f"{cfg['seed']}:population")
    pool = [x for x in NAMES if x not in taken]
    rng.shuffle(pool)
    weights = (cfg.get("population") or {}).get("profession_weights") or {}
    profs = sorted(cfg["professions"])
    count = {p: sum(a["profession"] == p for a in agents) for p in profs}
    while len(agents) < n:
        # Fill the profession furthest below its share; random tie-break so villages differ.
        load = {p: count[p] / float(weights.get(p, 1)) for p in profs if weights.get(p, 1) > 0}
        low = min(load.values())
        prof = rng.choice([p for p in profs if load.get(p) == low])
        count[prof] += 1
        agents.append({"name": pool.pop(), "profession": prof})
    return agents


def _scale(x: int, k: float) -> int:
    return max(1, round(x * k)) if x > 0 else x


def resolve(cfg: dict) -> dict:
    """Grow `cfg` (in place) to the configured population. Idempotent."""
    pop = cfg.get("population") or {}
    if pop.get("resolved") or not pop.get("size"):
        return cfg
    n = int(pop["size"])
    if not 1 <= n <= MAX_SIZE:
        raise ValueError(f"population.size must be 1..{MAX_SIZE}, got {n}")
    cfg["agents"] = generate_agents(cfg["agents"], n, cfg)
    k = resource_scale(cfg)
    if k != 1.0:
        free = {i for i, spec in cfg["items"].items() if spec.get("value", 1) == 0}  # water: unlimited anyway
        for loc in cfg["locations"].values():
            for item, r in (loc.get("resources") or {}).items():
                if item not in free:
                    for key in ("start", "max", "regen"):
                        if key in r:
                            r[key] = _scale(r[key], k)
        if pop.get("scale_orders", True):
            cfg["orders_per_post"] = max(1, round(cfg.get("orders_per_post", 1) * k))
        if pop.get("scale_projects", True):
            for proj in cfg.get("projects", {}).values():
                proj["needs"] = {i: _scale(q, k) for i, q in proj["needs"].items()}
    pop["resolved"] = True
    cfg["population"] = pop
    return cfg

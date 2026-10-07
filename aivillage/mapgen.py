"""Procedural village map: every seed gives a different village.

`generate(cfg)` places the landmarks (square, market, river, forest, mine, smithy), a few extra
resource patches (grove, pond, quarry), empty lots for sale, one house per villager and the roads between them on a tile grid,
then derives the engine's location graph from it: a road that takes longer than `tiles_per_hour` tiles is
split by waypoints (crossroads, old oak, ...), so far places really take more hours to reach. Each home is
linked to the nearest place on the road network, so some villagers live next to their work and the market
and some live far out: unequal by design.

`map.size` "large" / "huge" keeps that village as it is and adds a wilderness ring with far zones (WILDS:
deep forest, lake, caves with stone and ore, clay hills) two or more hours of walking from the square.

Honest minimum (`check`): the graph is connected, every landmark is at most `max_landmark_hops` from the
square, every home at most `max_home_hops` from the square, and every resource of the base map exists with
at least `min_resource_share` of its base amount. A seed that fails is re-rolled (attempt 1, 2, ...).

Output (all plain JSON, written into the run config and so into the log header):
- `cfg["locations"]`: landmarks + patches + waypoints with generated neighbors and scaled resources;
- `cfg["map"]["homes"]`: {villager: [location ids the house's road leads to]};
- `cfg["map"]["layout"]`: tile geometry for the viewer (see `layout` below);
- `cfg["map"]["fairness"]`: hours from each home to the square, market and the villager's work spot.

Pure and deterministic: depends only on the config (seed, base locations, agents, map params).
`engine.new_world` runs it when `map.procedural` is on and the config has no layout yet, so replaying a
log (whose header already has the layout) never re-generates.
"""

from __future__ import annotations

import copy
import heapq
import math
import random
from collections import deque

from . import settle

# Footprint of each landmark in tiles, matching the viewer art (viewer/pixelmap.js draws the same
# pictures, shifted): box (w, h), the anchor (where villagers stand, relative to the box), tiles that
# block roads, and the reserved area (box plus margins and decor) other things may not overlap.
# Default positions are those of the hand-made map, so the viewer can shift its art by (new - default).
LANDMARKS = {
    "square": {"box": (7, 5), "anchor": (3, 2), "default": (12, 7)},
    "market": {"box": (7, 3), "anchor": (3, 3), "default": (12, 1)},
    "field": {"box": (6, 6), "anchor": (3, 4), "default": (5, 2)},
    "forest": {"box": (9, 8), "anchor": (3, 5), "default": (21, 0)},
    "mine": {"box": (5, 4), "anchor": (2, 4), "default": (25, 8), "extra_rows": 3},
    "smithy": {"box": (4, 4), "anchor": (1, 4), "default": (20, 8)},
}
PATCH = {"box": (4, 3), "anchor": (1, 3)}
HOUSE = {"box": (3, 3), "anchor": (1, 3)}
FAIR_YARD = 5 * 4 - 3 * 3  # yard tiles of the fair plot (one tile left, right and behind the house)
PLOT_CELLS = 6  # plots.py cells of the fair plot (config plots.start_cells)
HAMLET = {"box": (3, 3), "anchor": (1, 1)}  # a small green with a well; houses gather around it
HAMLET_NAMES = ["Mill lane", "Riverside", "Hill end", "Oak row", "Pine corner", "Brook end"]

# Extra resource patches: a smaller copy of a landmark's resources.
PATCHES = {
    "grove": {"name": "Birch grove", "from": "forest", "share": 0.35},
    "pond": {"name": "Pond", "from": "river", "share": 0.4},
    "quarry": {"name": "Old quarry", "from": "mine", "share": 0.4},
}
WAYPOINT_NAMES = ["Crossroads", "Old oak", "Windmill", "Stone cross", "Meadow", "Hill path", "Shrine",
                  "Haystacks", "Signpost", "Fox hollow", "Lone pine", "Old well", "Bee yard", "Mill pond path",
                  "Chapel", "Sheep pen", "Willow bend", "Red barn", "Birch stile", "Watchtower", "Hay cart",
                  "Twin elms", "Boundary stone", "Goat track", "Dry ditch", "Rabbit warren", "Tall cross",
                  "Ash grove path", "Cart ruts", "Owl tree"]
# Empty lots for sale (aivillage/land.py): a fenced patch of bare land, 2 plot cells per tile column.
# No villager names here (population.NAMES): "Daisy lot" read as Daisy's land.
LOT_NAMES = ["Meadow lot", "Hilltop lot", "Brook lot", "Old orchard lot", "Stony lot", "Sunny lot", "Willow lot",
             "Fern lot", "Clover lot", "Heather lot", "Thistle lot", "Barley lot", "Mossy lot", "Windy lot",
             "Pine lot", "Nettle lot", "Rush lot", "Elder lot", "Bramble lot", "Poppy lot"]

# Far wild zones of a large map (`map.size`): the village core stays as compact as on the normal map, and
# the plenty and the rare lie two or more hours of walking away. `from` + `share` copy a share of a base
# location's resources (per resource, like PATCHES); `own` are resources no base location has (clay, scaled
# by the number of villagers). `biome` is written into the location config for other mechanics (animals).
# A `solid` zone is walked around (the cave's rock); the lake is water inside the ellipse of its box.
WILDS = {
    "deepwood": {"name": "Deep forest", "box": (10, 7), "from": "forest", "share": {"wood": 1.5, "berries": 1.5},
                 "biome": "deep_forest"},
    "lake": {"name": "Lake", "box": (9, 6), "from": "river", "share": {"fish": 1.0}, "biome": "lake"},
    "cave": {"name": "Cave", "box": (5, 4), "from": "mine", "share": {"stone": 0.7, "ore": 1.3}, "biome": "cave",
             "solid": True},
    "clayhill": {"name": "Clay hills", "box": (6, 4), "own": {"clay": {"start": 40, "max": 40, "regen": 12, "slots": 6}},
                 "biome": "clay_hills"},
}
WILD_ITEMS = {"clay": {"value": 2}}  # added to config items when a map has them (crafting turns clay into brick)
# `ring`: tiles of wilderness added around the village (all of it away from the river, half above and half
# below); `wilds`: how many zones of each kind. "normal" is the map as it always was.
MAP_SIZES = {
    "normal": {"ring": 0, "wilds": {}},
    "large": {"ring": 20, "wilds": {"deepwood": 1, "lake": 1, "cave": 1, "clayhill": 1}},
    "huge": {"ring": 40, "wilds": {"deepwood": 2, "lake": 1, "cave": 2, "clayhill": 2}},
}
WILD_WAYPOINT_NAMES = ["Deer trail", "Mossy log", "Fallen pine", "Bear rock", "Hunter's hut", "Ford", "Cairn",
                       "Old stump", "Wolf hollow", "Fern gully", "Split boulder", "Hollow oak", "Spring",
                       "Ridge", "Burnt clearing", "Lichen stone", "Elk meadow", "Gorge", "Bramble pass", "Echo cliff"]

MAP_DEFAULTS = {
    "procedural": False,
    "size": "normal",
    "tiles_per_hour": 24,
    "max_home_hops": 2,
    "home_road": 12,
    "max_landmark_hops": 1,
    "max_work_hops": 2,
    "max_market_hops": 3,
    "spread": 17,
    "hub_bias": 1.0,
    "min_resource_share": 0.7,
    # 0 = as equal as the map allows (same plot, money and goods for all, homes as close to work as
    # possible, resources at their base amounts); 1 = random and unfair (plots from none to large,
    # money x0.3..x2.5, some start with a stash, resources x0.6..x1.4, more lonely far-off homes).
    "unfairness": 0.3,
    "patches": [1, 3],
    "attempts": 60,
}

# The main work spot of each profession (patches are a bonus for those who find them). Farmers work their
# own garden beds at home (no common field), so for them the market counts as the place they walk to.
WORK_SPOT = {"farmer": None, "fisher": "river", "woodcutter": "forest", "miner": "mine", "smith": "smithy"}


RELAXABLE = ("max_home_hops", "max_landmark_hops", "max_work_hops", "max_market_hops")


class MapError(ValueError):
    pass


def params(cfg: dict) -> dict:
    """Map settings with the values that follow from `unfairness` filled in (explicit ones win)."""
    p = {**MAP_DEFAULTS, **cfg.get("map", {})}
    if p["size"] not in MAP_SIZES:
        raise ValueError(f"map.size must be one of {sorted(MAP_SIZES)}, got {p['size']!r}")
    u = p["unfairness"] = max(0.0, min(1.0, float(p["unfairness"])))
    derived = {"richness": [1 - 0.4 * u, 1 + 0.4 * u], "lone_share": 0.4 * u,
               "max_work_hops": MAP_DEFAULTS["max_work_hops"] + (1 if u >= 0.7 else 0)}
    return {**p, **{k: v for k, v in derived.items() if k not in cfg.get("map", {})}}


def generate(cfg: dict) -> dict:
    """Return a copy of cfg with a generated map (locations, map.homes, map.layout, map.fairness).

    If no attempt meets the honest minimum (a crowded village), the hour limits are relaxed by one
    and the relaxation is recorded in `map.relaxed`."""
    p = params(cfg)
    seed = p.get("seed", cfg["seed"])
    for relax in range(3):
        q = {**p, **{k: p[k] + relax for k in RELAXABLE}}
        for attempt in range(p["attempts"]):
            rng = random.Random(f"map:{seed}:{relax}:{attempt}")
            try:
                out = _build(cfg, q, rng)
                check(out, cfg["locations"], q)
            except MapError:
                continue
            out["map"].update(attempt=attempt, relaxed=relax)
            return out
    raise MapError(f"no fair map for seed {seed}")


def for_run(override: dict, fixed_map: bool = False, unfairness: float | None = None,
            size: str | None = None) -> dict:
    """World override for a real run (CLI, live server): procedural map on unless the run config already
    says otherwise or --fixed-map; --unfairness and --map-size set those knobs."""
    m = dict(override.get("map") or {})
    if fixed_map:
        m["procedural"] = False
    m.setdefault("procedural", True)
    if unfairness is not None:
        m["unfairness"] = unfairness
    if size is not None:
        m["size"] = size
    return {**override, "map": m}


def add_args(p) -> None:
    """--fixed-map / --unfairness for argparse."""
    p.add_argument("--fixed-map", action="store_true", help="use the hand-made map instead of a generated one")
    p.add_argument("--unfairness", type=float, default=None,
                   help="0 = everyone starts equal ... 1 = random, unfair plots, money and places (default 0.3)")
    p.add_argument("--map-size", choices=list(MAP_SIZES), default=None,
                   help="large / huge: the same compact village with far wild zones around it (default normal)")


# ---------- grid ----------

class Grid:
    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.water: set[tuple[int, int]] = set()
        self.solid: set[tuple[int, int]] = set()
        self.reserved: set[tuple[int, int]] = set()
        self.road: set[tuple[int, int]] = set()

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.cols and 0 <= y < self.rows

    def free(self, tiles) -> bool:
        return all(self.inside(*t) and t not in self.reserved and t not in self.water for t in tiles)

    def walkable(self, t) -> bool:
        return self.inside(*t) and t not in self.water and t not in self.solid

    def path(self, a, b) -> list[tuple[int, int]] | None:
        """A* over walkable tiles, preferring existing roads (they become shared paths)."""
        if not (self.walkable(a) and self.walkable(b)):
            return None
        best, prev, heap = {a: 0.0}, {a: None}, [(0.0, a)]
        while heap:
            _, cur = heapq.heappop(heap)
            if cur == b:
                out = [cur]
                while prev[out[-1]] is not None:
                    out.append(prev[out[-1]])
                return out[::-1]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (cur[0] + dx, cur[1] + dy)
                if not self.walkable(n):
                    continue
                cost = best[cur] + (0.7 if n in self.road else 1.0)
                if cost < best.get(n, math.inf):
                    best[n], prev[n] = cost, cur
                    heapq.heappush(heap, (cost + abs(n[0] - b[0]) + abs(n[1] - b[1]), n))
        return None

    def nearest(self, start, goals: dict[tuple[int, int], str], limit: int):
        """BFS from start to the closest goal tile within `limit` steps: (goal id, path) or None."""
        if not self.walkable(start):
            return None
        prev, q = {start: None}, deque([(start, 0)])
        while q:
            cur, d = q.popleft()
            if cur in goals:
                out = [cur]
                while prev[out[-1]] is not None:
                    out.append(prev[out[-1]])
                return goals[cur], out[::-1]
            if d == limit:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (cur[0] + dx, cur[1] + dy)
                if n not in prev and self.walkable(n):
                    prev[n] = cur
                    q.append((n, d + 1))
        return None


def rect(x, y, w, h):
    return [(i, j) for j in range(y, y + h) for i in range(x, x + w)]


def corners(path: list[tuple[int, int]]) -> list[list[int]]:
    """Compress a tile path to its turning points."""
    out = [list(path[0])]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            out.append(list(b))
    if len(path) > 1:
        out.append(list(path[-1]))
    return out


# ---------- build ----------

def _build(cfg: dict, p: dict, rng: random.Random) -> dict:
    base = cfg["locations"]
    names = [a["name"] for a in cfg["agents"]]
    n = len(names)
    grow = max(0, math.ceil((n - 8) / 4))
    lots = _lots_wanted(cfg, n)
    room = max(grow, math.ceil((n + lots - 5) / 4))  # lots for sale need room at the edges
    size = MAP_SIZES[p["size"]]
    ring, wild = size["ring"], bool(size["wilds"])
    # camp start (settle.py): no houses yet, villagers pick house sites; places further apart, a wider valley
    camp = settle.active(cfg)
    sc = (cfg.get("settle") or {}) if camp else {}
    bonus = int(sc.get("spread_bonus", 0))
    cols, rows = 44 + 4 * room + 2 * ring + 2 * bonus, 32 + 4 * room + 2 * ring + 2 * bonus
    p = {**p, "spread": p["spread"] + grow + bonus}
    gap = int(sc.get("zone_gap", 0))
    zones: list[tuple[int, int]] = []  # anchors of resource places, kept `gap` tiles apart in a camp start
    g = Grid(cols, rows)
    places: dict[str, dict] = {}

    # River: a 3-tile band along the left or right edge that meanders by a tile now and then.
    side = rng.choice(["left", "right"])
    off, span = rng.randint(0, 2), []
    for y in range(rows):
        if y and rng.random() < 0.25:
            off = max(0, min(2, off + rng.choice([-1, 1])))
        x0 = off if side == "left" else cols - 3 - off
        span.append(x0)
        for x in range(x0, x0 + 3):
            g.water.add((x, y))
        # the far bank is too narrow to build on; keep one land tile of margin on the near bank
        g.reserved.update((x, y) for x in (range(0, x0 + 4) if side == "left" else range(x0 - 1, cols)))
    # the village sits where it would on the normal map: next to the river, with the wilderness around it
    bc = cols - 2 * ring
    cx, cy = bc // 2 + (-1 if side == "left" else 1) * (bc // 12) + (2 * ring if side == "right" else 0), rows // 2 - 2
    dock_y = max(5, min(rows - 8, cy + rng.randint(-6, 6)))
    x0 = span[dock_y]
    dock = [x0 + 1, x0 + 2, x0 + 3] if side == "left" else [x0 - 1, x0, x0 + 1]
    river_anchor = (x0 + 4, dock_y) if side == "left" else (x0 - 2, dock_y)
    places["river"] = {"kind": "river", "anchor": list(river_anchor), "box": None}
    for x in dock:
        g.water.discard((x, dock_y))
    g.reserved.update((x + dx, dock_y + dy) for x in dock + [river_anchor[0]] for dx in (-1, 0, 1)
                      for dy in (-1, 0, 1))

    def put(pid: str, kind: str, spec: dict, near: tuple[int, int] | None, dmin: int, dmax: int,
            tries: int = 400, zone: bool = False) -> None:
        w, h = spec["box"]
        ax, ay = spec["anchor"]
        extra = spec.get("extra_rows", 0)
        x0, x1, y0, y1 = 1, cols - w - 1, 1, rows - h - 2 - extra
        if wild and near is not None:  # a big map: look only where the distance can fit
            x0, x1 = max(x0, near[0] - dmax - w), min(x1, near[0] + dmax)
            y0, y1 = max(y0, near[1] - dmax - h), min(y1, near[1] + dmax)
        for _ in range(tries):
            x, y = rng.randint(x0, x1), rng.randint(y0, y1)
            anchor = (x + ax, y + ay)
            if near is not None and not dmin <= abs(anchor[0] - near[0]) + abs(anchor[1] - near[1]) <= dmax:
                continue
            if zone and gap and any(abs(anchor[0] - z[0]) + abs(anchor[1] - z[1]) < gap for z in zones):
                continue
            area = rect(x - 1, y - 1, w + 2, h + 2 + extra)
            if not g.free(rect(x, y, w, h + extra)) or anchor in g.reserved or not g.free([anchor]):
                continue
            # margins may touch the map edge but not other things
            if any(t in g.reserved for t in area if g.inside(*t)) or any(t in g.road for t in rect(x, y, w, h + extra)):
                continue
            g.reserved.update(t for t in area + [anchor] if g.inside(*t))
            g.solid.update(_solid(kind, x, y, w, h))
            if kind == "lake":
                g.water.update(lake_tiles(x, y, w, h))
            places[pid] = {"kind": kind, "box": [x, y, w, h], "anchor": list(anchor)}
            if zone:
                zones.append(anchor)
            return
        raise MapError(f"no room for {pid}")

    put("square", "square", LANDMARKS["square"], (cx, cy), 0, 6)
    sq = tuple(places["square"]["anchor"])
    if camp:
        zones.append(sq)
        zones.append(river_anchor)
    put("market", "market", LANDMARKS["market"], sq, 4, 10)
    put("smithy", "smithy", LANDMARKS["smithy"], sq, 5, 14)
    for lid in ("forest", "field", "mine"):
        if lid in base:  # the field exists only in old configs: farming is private now
            put(lid, lid, LANDMARKS[lid], sq, 7 + bonus // 2, p["spread"], zone=camp)
    lo, hi = sc.get("patches") or p["patches"]
    kinds = list(PATCHES)
    count: dict[str, int] = {}
    if camp:  # every kind of patch before any repeats: groves (game, wood), ponds and quarries in different parts
        rng.shuffle(kinds)
    for i in range(rng.randint(lo, hi) + n // 8):
        kind = kinds[i % len(kinds)] if camp else kinds[rng.randrange(len(kinds))]
        count[kind] = count.get(kind, 0) + 1
        far = int(sc.get("rare_bonus", 0)) if kind == "quarry" else 0  # ore lies a little further out
        put(kind if count[kind] == 1 else f"{kind}{count[kind]}", kind, PATCH, sq, 6 + far, p["spread"] + 6 + far,
            zone=camp)
    pool = rng.sample(HAMLET_NAMES, len(HAMLET_NAMES))
    for _ in range(0 if camp else min(len(pool), n // 4 + rng.randint(0, 1))):
        hname = pool.pop()
        hid = hname.lower().replace(" ", "_")
        put(hid, "hamlet", HAMLET, sq, 9, p["spread"] + 2)
        places[hid]["name"] = hname
    for kind, k in size["wilds"].items():  # far from the square: past the patches, hamlets and lots
        spec = WILDS[kind]
        for i in range(k):
            w, h = spec["box"]
            put(kind if i == 0 else f"{kind}{i + 1}", kind, {"box": (w, h), "anchor": (w // 2, h)}, sq,
                p["spread"] + 12, p["spread"] + 12 + 2 * ring)
    for pl in places.values():
        if pl["kind"] == "pond":
            g.water.update(rect(*pl["box"]))

    # Roads: a tree grown from the square (each place joins the network where the walk to the square
    # stays short, joining the square itself is preferred), plus a few short loops; square-market always.
    ids = list(places)
    anchors = {i: tuple(places[i]["anchor"]) for i in ids}
    dist = lambda a, b: math.dist(anchors[a], anchors[b])
    step = p["tiles_per_hour"]
    depth, edges = {"square": 0.0, "market": dist("square", "market") / step}, [("square", "market")]
    while len(depth) < len(ids):
        cost, a, b = min((depth[a] + dist(a, b) / step + (0 if a == "square" else p["hub_bias"]), a, b)
                         for a in depth for b in ids if b not in depth)
        depth[b] = cost
        edges.append((a, b))
    tree = {frozenset(e) for e in edges}
    spare = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
             if frozenset((a, b)) not in tree and dist(a, b) <= 14]
    rng.shuffle(spare)
    edges += spare[: rng.randint(1, 3)]
    wp_names = WAYPOINT_NAMES[:]
    if wild:  # long trails need more signposts; numbered trail marks if even those run out
        wp_names += WILD_WAYPOINT_NAMES
    rng.shuffle(wp_names)
    if wild:
        wp_names = [f"Trail mark {k}" for k in range(80, 0, -1)] + wp_names

    # A first draft of the roads tells how far each place is from the square.
    draft = _roads(g, anchors, edges, step, wp_names[:])
    hub = distances(draft[0], "square")
    for lid in (LANDMARKS.keys() | {"river"}) & set(base):
        if hub.get(lid, 10 ** 6) > p["max_landmark_hops"] + camp:
            raise MapError(f"{lid} is {hub.get(lid)} hours from the square")
    g.road.clear()

    # Homes: most villagers live around the square or in a hamlet down the road, a few alone next to a
    # field, forest or mine. Houses go up before the real roads, so roads wind between them.
    homes: dict[str, list[str]] = {}
    near = [pid for pid in ids if hub[pid] < p["max_home_hops"]]
    hamlets = [pid for pid in near if places[pid]["kind"] == "hamlet"]
    lone = [pid for pid in near if places[pid]["kind"] not in ("hamlet", "square", "market") + tuple(WILDS)]
    graph0 = {pid: distances(draft[0], pid) for pid in ["square"] + hamlets + lone}
    profession = {a["name"]: a.get("profession") for a in cfg["agents"]}

    def spot(name: str) -> str:
        return WORK_SPOT.get(profession[name], "square") or "market"

    def fits(name: str, c: str) -> bool:  # the honest minimum, judged on the draft roads
        d = graph0[c]
        work = d.get(spot(name), 10 ** 6)
        return 1 + work <= p["max_work_hops"] and 1 + d.get("market", 10 ** 6) <= p["max_market_hops"]

    def walk(name: str, c: str) -> int:
        d = graph0[c]
        return d.get(spot(name), 9) + d.get("market", 9)

    u = p["unfairness"]
    fortune = _fortune(cfg, u, rng)
    taken: dict[str, int] = {}
    if camp:  # nobody has a house yet: everyone sleeps at the camp, house sites wait around the places
        homes = {name: [settle.camp(cfg)] for name in names}
        site_near = _house_sites(g, rng, places, cfg, n, p["home_road"])
    for name in ([] if camp else names):
        options = ["square"] + hamlets
        # fair: the shortest walk to work and market first; unfair: wherever
        options.sort(key=lambda c: (1 - u) * walk(name, c) + 0.5 * taken.get(c, 0) + rng.random() * (0.5 + 2 * u))
        if lone and rng.random() < p["lone_share"]:
            options.insert(0, rng.choice(lone))
        options = [c for c in options + lone if fits(name, c)]
        for around in options:
            if _place_house(g, rng, places, name, around, p["home_road"], fortune[name]["yard"]):
                homes[name] = [around]
                taken[around] = taken.get(around, 0) + 1
                break
        else:
            raise MapError(f"no lot for {name}")

    neighbors, routes, waypoints = _roads(g, anchors, edges, step, wp_names[:])
    for wid, (name, t) in waypoints.items():
        places[wid] = {"kind": "waypoint", "box": None, "anchor": list(t), "name": name}
    for sid, near in (site_near.items() if camp else ()):  # each house site's own short road to its place
        path = g.path(tuple(places[sid]["anchor"]), tuple(places[near]["anchor"]))
        if path is None or len(path) - 1 > 2 * p["home_road"]:
            del places[sid]
            continue
        routes.append({"a": sid, "b": near, "path": corners(path)})
        g.road.update(path)
    if camp and sum(1 for pl in places.values() if pl["kind"] == "homesite") < n:
        raise MapError("too few house sites")
    for name, (around, ) in ([] if camp else homes.items()):
        hid = f"home_{name}"
        path = g.path(tuple(places[hid]["anchor"]), tuple(places[around]["anchor"]))
        if path is None or len(path) - 1 > 2 * p["home_road"]:
            raise MapError(f"no road home for {name}")
        routes.append({"a": hid, "b": around, "path": corners(path)})
        g.road.update(path)

    # Empty lots for sale go wherever there is room left, off the roads, each with its own road to the
    # nearest place (so they never stretch the walks checked above).
    land_cfg = cfg.get("land") or {}
    if lots:
        lot_names = rng.sample(LOT_NAMES, len(LOT_NAMES))
        free_wp = [x for x in wp_names if x not in {nm for nm, _ in waypoints.values()}]
        for i in range(lots):
            cells = rng.choice(land_cfg["cells"])
            w = max(3, cells // 2)
            lid = f"lot_{i + 1}"
            try:
                put(lid, "lot", {"box": (w, 3), "anchor": (w // 2, 3)}, sq, 6, p["spread"] + 10)
            except MapError:
                break  # a crowded village gets fewer lots
            places[lid].update(name=lot_names[i] if i < len(lot_names) else f"Lot {i + 1}", cells=cells,
                               plot=list(places[lid]["box"]))
            anchors[lid] = tuple(places[lid]["anchor"])
            near = min((j for j in anchors if j != lid and not j.startswith("lot_")), key=lambda j: dist(j, lid))
            nb, rt, wp = _roads(g, {near: anchors[near], lid: anchors[lid]}, [(near, lid)], step, free_wp)
            for k, v in nb.items():
                neighbors.setdefault(k, []).extend(v)
            routes += rt
            for wid, (name, t) in wp.items():
                places[wid] = {"kind": "waypoint", "box": None, "anchor": list(t), "name": name}
    hops = distances(neighbors, "square")

    # Locations: landmarks keep their config (scaled resources), patches copy a share of a landmark.
    lo, hi = p["richness"]
    locations: dict[str, dict] = {}
    for pid, pl in places.items():
        if pl["kind"] in ("home", "homesite"):
            continue
        if pl["kind"] == "waypoint":
            locations[pid] = {"name": pl["name"], "neighbors": neighbors[pid]}
        elif pl["kind"] == "hamlet":
            locations[pid] = {"name": pl["name"], "neighbors": neighbors[pid]}
        elif pl["kind"] == "lot":  # dearer next to the square
            ppc = land_cfg["price_per_cell"] * (1.25 if hops.get(pid, 9) <= 1 else 1.0)
            locations[pid] = {"name": pl["name"], "neighbors": neighbors[pid],
                              "lot": {"cells": pl["cells"], "price": round(pl["cells"] * ppc)}}
        elif pl["kind"] in WILDS:
            spec = WILDS[pl["kind"]]
            res = {}
            if "from" in spec:
                src = (base.get(spec["from"]) or _default_locations()[spec["from"]]).get("resources", {})
                f = rng.uniform(lo, hi)
                res = {r: dict(s) if r == "water" else _scale(s, f * spec["share"][r], spec["share"][r])
                       for r, s in src.items() if r == "water" or r in spec["share"]}
            for r, s in spec.get("own", {}).items():
                res[r] = _scale(s, max(1.0, n / 8) * rng.uniform(lo, hi))
            k = pid[len(pl["kind"]):]
            locations[pid] = {"name": spec["name"] + (f" {k}" if k else ""), "neighbors": neighbors[pid],
                              "resources": res, "biome": spec["biome"]}
        elif pl["kind"] in PATCHES:
            spec = PATCHES[pl["kind"]]
            src = base[spec["from"]].get("resources", {})
            f = spec["share"] * rng.uniform(lo, hi)
            res = {r: dict(s) if r == "water" else _scale(s, f, spec["share"]) for r, s in src.items()
                   if s.get("patch", True)}
            nm = spec["name"] if pid == pl["kind"] else f"{spec['name']} {pid[len(pl['kind']):]}"
            locations[pid] = {"name": nm, "neighbors": neighbors[pid], "resources": res}
        else:
            spec = copy.deepcopy(base[pid])
            spec["neighbors"] = neighbors[pid]
            if spec.get("resources"):
                f = rng.uniform(lo, hi)
                spec["resources"] = {r: s if r == "water" else _scale(s, f) for r, s in spec["resources"].items()}
            locations[pid] = spec
    # any other location of the base map (added by a mechanic) hangs off the square
    for lid, spec in base.items():
        if lid not in locations and "lot" not in spec:  # the hand-made map's lots: replaced by generated ones
            spec = copy.deepcopy(spec)
            spec["neighbors"] = ["square"]
            locations[lid] = spec
            locations["square"]["neighbors"].append(lid)

    out = copy.deepcopy(cfg)
    out["locations"] = locations
    for item, spec in WILD_ITEMS.items():
        if any(item in loc.get("resources", {}) for loc in locations.values()):
            out["items"].setdefault(item, dict(spec))
    layout = {
        "cols": cols, "rows": rows,
        "river": {"side": side, "x": span, "dock": {"y": dock_y, "x": dock}},
        "places": {pid: {k: v for k, v in pl.items() if k not in ("name", "cells")} for pid, pl in places.items()},
        "defaults": {k: list(v["default"]) for k, v in LANDMARKS.items()},
        "routes": routes,
    }
    out["map"] = {**cfg.get("map", {}), "procedural": True, "homes": homes, "layout": layout,
                  "start": {n: {"coins": f["coins"], "items": f["items"],
                                **({} if camp else {"plot": places[f"home_{n}"]["plot"]})}
                            for n, f in fortune.items()}}
    if camp:
        out["map"]["camp"] = True
        out["map"]["sites"] = {sid: {"near": pl["near"], "cells": PLOT_CELLS}
                               for sid, pl in places.items() if pl["kind"] == "homesite"}
    # the plots engine (plots.py) reads the start from the agents: yard size in cells and house level
    for a in out["agents"]:
        f = fortune[a["name"]]
        if camp:  # every house site has the fair yard
            a.setdefault("plot_cells", PLOT_CELLS)
        else:
            plot = places[f"home_{a['name']}"]["plot"]
            yard = plot[2] * plot[3] - HOUSE["box"][0] * HOUSE["box"][1]
            a.setdefault("plot_cells", max(1, round(PLOT_CELLS * yard / FAIR_YARD)))
        a.setdefault("house_level", f["house_level"])
    out["map"]["fairness"] = fairness(out)
    return out


def _lots_wanted(cfg: dict, n: int) -> int:
    land_cfg = cfg.get("land") or {}
    if not (land_cfg.get("enabled") and cfg.get("plots", {}).get("enabled")):
        return 0
    from .land import lot_count
    return lot_count(cfg, n)


def _roads(g: Grid, anchors: dict, edges: list, step: int, wp_names: list[str]):
    """Lay a road along each edge; a road longer than `step` tiles is cut by waypoints, one per hour.
    Returns (neighbors, routes, {waypoint id: (name, tile)})."""
    neighbors: dict[str, list[str]] = {i: [] for i in anchors}
    routes: list[dict] = []
    waypoints: dict[str, tuple[str, tuple[int, int]]] = {}
    for a, b in edges:
        path = g.path(anchors[a], anchors[b])
        if path is None:
            raise MapError(f"no road {a}-{b}")
        hops = max(1, math.ceil((len(path) - 1) / step))
        cuts = [round(k * (len(path) - 1) / hops) for k in range(hops + 1)]
        chain = [a]
        for k in range(1, hops):
            if not wp_names:
                raise MapError("out of waypoint names")
            name = wp_names.pop()
            wid = name.lower().replace(" ", "_")
            waypoints[wid] = (name, path[cuts[k]])
            neighbors[wid] = []
            chain.append(wid)
        chain.append(b)
        for k in range(hops):
            x, y = chain[k], chain[k + 1]
            neighbors[x].append(y)
            neighbors[y].append(x)
            seg = path[cuts[k]: cuts[k + 1] + 1]
            routes.append({"a": x, "b": y, "path": corners(seg)})
            g.road.update(seg)
    return neighbors, routes, waypoints


def _fortune(cfg: dict, u: float, rng: random.Random) -> dict:
    """What each villager starts with: yard size around the house (tiles left, right, behind), coins, a stash."""
    goods = [k for k in ("grain", "fish", "wood", "stone", "berries") if k in cfg["items"]]
    out = {}
    for a in cfg["agents"]:
        size = lambda: max(0, min(3, round(1 + u * rng.uniform(-1, 2))))
        coins = max(0, round(cfg["start_coins"] * (1 + u * rng.uniform(-0.7, 1.5))))
        stash = {}
        if goods and rng.random() < u:
            stash[rng.choice(goods)] = rng.randint(1, max(1, round(12 * u)))
        level = 1 + (rng.random() < 0.3 * u) + (rng.random() < 0.1 * u)
        out[a["name"]] = {"yard": (size(), size(), size()), "coins": coins, "items": stash, "house_level": level}
    return out


# Places a villager of a camp start may settle by (house sites around them): not the trader's market, the
# Smithy (only a place name before someone builds a forge), waypoints, lots or hamlets.
SITE_KINDS = ("square", "river", "forest", "field", "mine") + tuple(PATCHES) + tuple(WILDS)


def _house_sites(g: Grid, rng: random.Random, places: dict, cfg: dict, n: int, limit: int) -> dict[str, str]:
    """Free house sites (kind "homesite") around the places of a camp start; {site id: place id}.
    Each gets the fair yard; enough for everyone half again, at least `settle.sites_per_place` per place."""
    near = [pid for pid in places if places[pid]["kind"] in SITE_KINDS]
    k = max(int((cfg.get("settle") or {}).get("sites_per_place", 3)), math.ceil(1.5 * n / max(1, len(near))))
    out: dict[str, str] = {}
    for _ in range(k):  # round by round, so a crowded map still spreads its sites over all places
        for pid in near:
            sid = f"site_{len(out) + 1}"
            if _place_house(g, rng, places, sid, pid, limit):
                pl = places.pop(f"home_{sid}")
                places[sid] = {**pl, "kind": "homesite", "near": pid}
                del places[sid]["owner"]
                out[sid] = pid
    return out


def _place_house(g: Grid, rng: random.Random, places: dict, name: str, around: str, limit: int,
                 yard: tuple[int, int, int] = (1, 1, 1)) -> bool:
    """Put name's house and fenced plot on a free lot whose door is at most `limit` tiles from `around`.
    The plot is the house plus `yard` tiles to the left, right and behind; the door opens on the road."""
    w, h = HOUSE["box"]
    el, er, eu = yard
    ax, ay = places[around]["anchor"]
    lots = []
    for y in range(1, g.rows - h - 1):
        for x in range(1, g.cols - w):
            d = abs(x + 1 - ax) + abs(y + 3 - ay)
            if 2 <= d <= limit:
                lots.append((d + rng.random() * 5, x, y))
    for _, x, y in sorted(lots):
        door = (x + HOUSE["anchor"][0], y + HOUSE["anchor"][1])
        plot = [x - el, y - eu, w + el + er, h + eu]
        tiles = rect(*plot)
        if not g.free(tiles + [door]) or any(t in g.road for t in tiles):
            continue
        # neighbours keep a tile of grass between plots
        if any(t in g.solid or t in g.water for t in rect(plot[0] - 1, plot[1] - 1, plot[2] + 2, plot[3] + 2)
               if g.inside(*t)):
            continue
        g.reserved.update(tiles + [door])
        g.solid.update(tiles)
        places[f"home_{name}"] = {"kind": "home", "box": [x, y, w, h], "anchor": list(door), "owner": name,
                                  "plot": plot}
        return True
    return False


def _solid(kind: str, x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    """Tiles roads must go around. Gates and clearings stay open so the anchor can be reached."""
    if kind in ("square", "grove", "quarry", "hamlet", "deepwood", "clayhill", "lake"):  # lake: its water blocks
        return []
    tiles = rect(x, y, w, h)
    if kind == "field":  # gate in the bottom fence, path up to the anchor
        return [t for t in tiles if not (t[0] == x + 3 and t[1] >= y + 3)]
    if kind == "forest":  # clearing from the anchor down to the forest edge
        return [t for t in tiles if not (abs(t[0] - (x + 3)) <= 1 and t[1] >= y + 4)]
    return tiles


def lake_tiles(x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    """Water tiles of a lake: the ellipse inscribed in its box (viewer/mapgen.js draws the same)."""
    return [(i, j) for i, j in rect(x, y, w, h)
            if ((i + 0.5 - x - w / 2) / (w / 2)) ** 2 + ((j + 0.5 - y - h / 2) / (h / 2)) ** 2 <= 1]


def _default_locations() -> dict:
    from .config import DEFAULT_CONFIG
    return DEFAULT_CONFIG["locations"]


def _scale(spec: dict, f: float, objects: float = 1.0) -> dict:
    """Scale amounts by f and the number of map objects (trees, beds, rocks) by `objects`."""
    out = dict(spec)
    for k in ("start", "max", "regen"):
        if k in out:
            out[k] = max(1, round(out[k] * f))
    if "slots" in out:
        out["slots"] = max(1, min(round(out["slots"] * objects), out["max"]))
    out["start"] = min(out.get("start", 0), out.get("max", out.get("start", 0)))
    return out


# ---------- graph checks ----------

def graph(cfg: dict) -> dict[str, list[str]]:
    """Location graph including homes (as engine.new_world builds it)."""
    adj = {lid: list(s["neighbors"]) for lid, s in cfg["locations"].items()}
    links = cfg.get("map", {}).get("homes", {})
    for a in cfg["agents"]:
        hid = f"home_{a['name']}"
        adj[hid] = list(links.get(a["name"], ["square"]))
        for to in adj[hid]:
            adj[to].append(hid)
    return adj


def distances(adj: dict, src: str) -> dict[str, int]:
    seen, q = {src: 0}, deque([src])
    while q:
        cur = q.popleft()
        for n in adj[cur]:
            if n not in seen:
                seen[n] = seen[cur] + 1
                q.append(n)
    return seen


def fairness(cfg: dict) -> dict:
    """Hours of walking from each home to the square, the market and the villager's main work spot."""
    adj = graph(cfg)
    out = {}
    for a in cfg["agents"]:
        d = distances(adj, f"home_{a['name']}")
        spot = WORK_SPOT.get(a.get("profession"), "square")
        work = d.get(spot) if spot else 0  # a farmer works at home
        start = cfg["map"].get("start", {}).get(a["name"], {})
        out[a["name"]] = {"square": d.get("square"), "market": d.get("market"), "work": work,
                          "work_spot": spot or "home", "coins": start.get("coins", cfg["start_coins"]),
                          "items": start.get("items", {}),
                          "plot_tiles": start["plot"][2] * start["plot"][3] if "plot" in start else None,
                          "plot_cells": a.get("plot_cells"), "house_level": a.get("house_level")}
    return out


def check(cfg: dict, base_locations: dict | None = None, p: dict | None = None) -> None:
    """The honest minimum every generated map must meet. Raises MapError."""
    p = p or params(cfg)
    adj = graph(cfg)
    for lid, ns in adj.items():
        for n in ns:
            if n not in adj or lid not in adj[n]:
                raise MapError(f"road {lid}-{n} is one-way or leads nowhere")
    d = distances(adj, "square")
    if len(d) != len(adj):
        raise MapError(f"unreachable: {sorted(set(adj) - set(d))}")
    if base_locations is None:
        from .config import DEFAULT_CONFIG
        base_locations = DEFAULT_CONFIG["locations"]
    for lid in (LANDMARKS.keys() | {"river"}) & set(base_locations):
        if lid not in d or d[lid] > p["max_landmark_hops"] + bool(cfg["map"].get("camp")):
            raise MapError(f"{lid} is {d.get(lid)} hours from the square")
    landmarks_only = bool(cfg["map"].get("camp"))  # camp start: everyone starts at the camp, homes come later
    for a in ([] if landmarks_only else cfg["agents"]):
        if d[f"home_{a['name']}"] > p["max_home_hops"]:
            raise MapError(f"{a['name']} lives too far")
    for name, f in ({} if landmarks_only else fairness(cfg)).items():
        if f["work"] is None or f["work"] > p["max_work_hops"]:
            raise MapError(f"{name} lives {f['work']} hours from work")
        if f["market"] is None or f["market"] > p["max_market_hops"]:
            raise MapError(f"{name} lives {f['market']} hours from the market")
    base: dict[str, int] = {}
    for spec in base_locations.values():
        for r, s in spec.get("resources", {}).items():
            base[r] = base.get(r, 0) + s["start"]
    have: dict[str, int] = {}
    for spec in cfg["locations"].values():
        for r, s in spec.get("resources", {}).items():
            have[r] = have.get(r, 0) + s["start"]
    for r, n in base.items():
        if have.get(r, 0) < p["min_resource_share"] * n:
            raise MapError(f"too little {r}: {have.get(r, 0)} < {p['min_resource_share']} x {n}")

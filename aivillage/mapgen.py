"""Procedural village map: every seed gives a different village.

`generate(cfg)` places the landmarks (square, market, field, river, forest, mine, smithy), a few extra
resource patches (grove, pond, quarry), one house per villager and the roads between them on a tile grid,
then derives the engine's location graph from it: a road that takes longer than `tiles_per_hour` tiles is
split by waypoints (crossroads, old oak, ...), so far places really take more hours to reach. Each home is
linked to the nearest place on the road network, so some villagers live next to their work and the market
and some live far out: unequal by design.

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
                  "Chapel", "Sheep pen", "Willow bend", "Red barn", "Birch stile", "Watchtower"]

MAP_DEFAULTS = {
    "procedural": False,
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

# The main work spot of each profession (patches are a bonus for those who find them).
WORK_SPOT = {"farmer": "field", "fisher": "river", "woodcutter": "forest", "miner": "mine", "smith": "smithy"}


RELAXABLE = ("max_home_hops", "max_landmark_hops", "max_work_hops", "max_market_hops")


class MapError(ValueError):
    pass


def params(cfg: dict) -> dict:
    """Map settings with the values that follow from `unfairness` filled in (explicit ones win)."""
    p = {**MAP_DEFAULTS, **cfg.get("map", {})}
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


def for_run(override: dict, fixed_map: bool = False, unfairness: float | None = None) -> dict:
    """World override for a real run (CLI, live server): procedural map on unless the run config already
    says otherwise or --fixed-map; --unfairness sets the knob."""
    m = dict(override.get("map") or {})
    if fixed_map:
        m["procedural"] = False
    m.setdefault("procedural", True)
    if unfairness is not None:
        m["unfairness"] = unfairness
    return {**override, "map": m}


def add_args(p) -> None:
    """--fixed-map / --unfairness for argparse."""
    p.add_argument("--fixed-map", action="store_true", help="use the hand-made map instead of a generated one")
    p.add_argument("--unfairness", type=float, default=None,
                   help="0 = everyone starts equal ... 1 = random, unfair plots, money and places (default 0.3)")


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
    cols, rows = 44 + 4 * grow, 32 + 4 * grow
    p = {**p, "spread": p["spread"] + grow}
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
    cx, cy = cols // 2 + (-1 if side == "left" else 1) * (cols // 12), rows // 2 - 2
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
            tries: int = 400) -> None:
        w, h = spec["box"]
        ax, ay = spec["anchor"]
        extra = spec.get("extra_rows", 0)
        for _ in range(tries):
            x, y = rng.randint(1, cols - w - 1), rng.randint(1, rows - h - 2 - extra)
            anchor = (x + ax, y + ay)
            if near is not None and not dmin <= abs(anchor[0] - near[0]) + abs(anchor[1] - near[1]) <= dmax:
                continue
            area = rect(x - 1, y - 1, w + 2, h + 2 + extra)
            if not g.free(rect(x, y, w, h + extra)) or anchor in g.reserved or not g.free([anchor]):
                continue
            # margins may touch the map edge but not other things
            if any(t in g.reserved for t in area if g.inside(*t)):
                continue
            g.reserved.update(t for t in area + [anchor] if g.inside(*t))
            g.solid.update(_solid(kind, x, y, w, h))
            places[pid] = {"kind": kind, "box": [x, y, w, h], "anchor": list(anchor)}
            return
        raise MapError(f"no room for {pid}")

    put("square", "square", LANDMARKS["square"], (cx, cy), 0, 6)
    sq = tuple(places["square"]["anchor"])
    put("market", "market", LANDMARKS["market"], sq, 4, 10)
    put("smithy", "smithy", LANDMARKS["smithy"], sq, 5, 14)
    for lid in ("forest", "field", "mine"):
        put(lid, lid, LANDMARKS[lid], sq, 7, p["spread"])
    lo, hi = p["patches"]
    kinds = list(PATCHES)
    count: dict[str, int] = {}
    for _ in range(rng.randint(lo, hi) + n // 8):
        kind = kinds[rng.randrange(len(kinds))]
        count[kind] = count.get(kind, 0) + 1
        put(kind if count[kind] == 1 else f"{kind}{count[kind]}", kind, PATCH, sq, 6, p["spread"] + 6)
    pool = rng.sample(HAMLET_NAMES, len(HAMLET_NAMES))
    for _ in range(min(len(pool), n // 4 + rng.randint(0, 1))):
        hname = pool.pop()
        hid = hname.lower().replace(" ", "_")
        put(hid, "hamlet", HAMLET, sq, 9, p["spread"] + 2)
        places[hid]["name"] = hname
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
    rng.shuffle(wp_names)

    # A first draft of the roads tells how far each place is from the square.
    draft = _roads(g, anchors, edges, step, wp_names[:])
    hub = distances(draft[0], "square")
    for lid in LANDMARKS.keys() | {"river"}:
        if hub.get(lid, 10 ** 6) > p["max_landmark_hops"]:
            raise MapError(f"{lid} is {hub.get(lid)} hours from the square")
    g.road.clear()

    # Homes: most villagers live around the square or in a hamlet down the road, a few alone next to a
    # field, forest or mine. Houses go up before the real roads, so roads wind between them.
    homes: dict[str, list[str]] = {}
    near = [pid for pid in ids if hub[pid] < p["max_home_hops"]]
    hamlets = [pid for pid in near if places[pid]["kind"] == "hamlet"]
    lone = [pid for pid in near if places[pid]["kind"] not in ("hamlet", "square", "market")]
    graph0 = {pid: distances(draft[0], pid) for pid in ["square"] + hamlets + lone}
    profession = {a["name"]: a.get("profession") for a in cfg["agents"]}

    def fits(name: str, c: str) -> bool:  # the honest minimum, judged on the draft roads
        d = graph0[c]
        work = d.get(WORK_SPOT.get(profession[name], "square"), 10 ** 6)
        return 1 + work <= p["max_work_hops"] and 1 + d.get("market", 10 ** 6) <= p["max_market_hops"]

    def walk(name: str, c: str) -> int:
        d = graph0[c]
        return d.get(WORK_SPOT.get(profession[name], "square"), 9) + d.get("market", 9)

    u = p["unfairness"]
    fortune = _fortune(cfg, u, rng)
    taken: dict[str, int] = {}
    for name in names:
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
    for name, (around, ) in homes.items():
        hid = f"home_{name}"
        path = g.path(tuple(places[hid]["anchor"]), tuple(places[around]["anchor"]))
        if path is None or len(path) - 1 > 2 * p["home_road"]:
            raise MapError(f"no road home for {name}")
        routes.append({"a": hid, "b": around, "path": corners(path)})
        g.road.update(path)

    # Locations: landmarks keep their config (scaled resources), patches copy a share of a landmark.
    lo, hi = p["richness"]
    locations: dict[str, dict] = {}
    for pid, pl in places.items():
        if pl["kind"] == "home":
            continue
        if pl["kind"] == "waypoint":
            locations[pid] = {"name": pl["name"], "neighbors": neighbors[pid]}
        elif pl["kind"] == "hamlet":
            locations[pid] = {"name": pl["name"], "neighbors": neighbors[pid]}
        elif pl["kind"] in PATCHES:
            spec = PATCHES[pl["kind"]]
            src = base[spec["from"]].get("resources", {})
            f = spec["share"] * rng.uniform(lo, hi)
            res = {r: dict(s) if r == "water" else _scale(s, f, spec["share"]) for r, s in src.items()}
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
        if lid not in locations:
            spec = copy.deepcopy(spec)
            spec["neighbors"] = ["square"]
            locations[lid] = spec
            locations["square"]["neighbors"].append(lid)

    out = copy.deepcopy(cfg)
    out["locations"] = locations
    layout = {
        "cols": cols, "rows": rows,
        "river": {"side": side, "x": span, "dock": {"y": dock_y, "x": dock}},
        "places": {pid: {k: v for k, v in pl.items() if k != "name"} for pid, pl in places.items()},
        "defaults": {k: list(v["default"]) for k, v in LANDMARKS.items()},
        "routes": routes,
    }
    out["map"] = {**cfg.get("map", {}), "procedural": True, "homes": homes, "layout": layout,
                  "start": {n: {"coins": f["coins"], "items": f["items"],
                                "plot": places[f"home_{n}"]["plot"]} for n, f in fortune.items()}}
    out["map"]["fairness"] = fairness(out)
    return out


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
        out[a["name"]] = {"yard": (size(), size(), size()), "coins": coins, "items": stash}
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
    if kind in ("square", "grove", "quarry", "hamlet"):
        return []
    tiles = rect(x, y, w, h)
    if kind == "field":  # gate in the bottom fence, path up to the anchor
        return [t for t in tiles if not (t[0] == x + 3 and t[1] >= y + 3)]
    if kind == "forest":  # clearing from the anchor down to the forest edge
        return [t for t in tiles if not (abs(t[0] - (x + 3)) <= 1 and t[1] >= y + 4)]
    return tiles


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
        start = cfg["map"].get("start", {}).get(a["name"], {})
        out[a["name"]] = {"square": d.get("square"), "market": d.get("market"), "work": d.get(spot),
                          "work_spot": spot, "coins": start.get("coins", cfg["start_coins"]),
                          "items": start.get("items", {}),
                          "plot_tiles": start["plot"][2] * start["plot"][3] if "plot" in start else None}
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
    for lid in LANDMARKS.keys() | {"river"}:
        if lid not in d or d[lid] > p["max_landmark_hops"]:
            raise MapError(f"{lid} is {d.get(lid)} hours from the square")
    for a in cfg["agents"]:
        if d[f"home_{a['name']}"] > p["max_home_hops"]:
            raise MapError(f"{a['name']} lives too far")
    for name, f in fairness(cfg).items():
        if f["work"] is None or f["work"] > p["max_work_hops"]:
            raise MapError(f"{name} lives {f['work']} hours from work")
        if f["market"] is None or f["market"] > p["max_market_hops"]:
            raise MapError(f"{name} lives {f['market']} hours from the market")
    if base_locations is None:
        from .config import DEFAULT_CONFIG
        base_locations = DEFAULT_CONFIG["locations"]
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

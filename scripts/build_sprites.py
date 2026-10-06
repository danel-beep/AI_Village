"""Cut the SpriteCook sheets in viewer/art/ into one sprite atlas for the viewer (viewer/sprites_data.js).

    python scripts/build_sprites.py            # needs Pillow (pip install pillow); the viewer itself does not

Each sheet is a grid of objects on a transparent background. Every connected blob is assigned to the grid cell its
centre falls in, so loose bits (bees, sparks) stay with their object. Each object is cropped, scaled to the size it
has on the 16 px tile map, and packed into one PNG that is embedded as a data URL, so the viewer keeps working from
file:// and inside the single-file demo. Houses get one variant per roof colour (the owner's colour on the map).
"""
import base64
import colorsys
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "viewer" / "art"
OUT = ROOT / "viewer" / "sprites_data.js"

# sheet -> (rows, cols, names row by row; None skips a cell)
SHEETS = {
    "buildings": (3, 3, ["house1", "house2", "house3", "market", "smithy", "mine", "coop", "hives", "well"]),
    "nature": (4, 4, ["oak", "pine", "apple_tree", "stump", "sapling", "bush", "berry_bush", "boulder",
                      "copper_rock", "gold_rock", "crystal_rock", "logs", "flowers", "grass", "mushrooms", "pond"]),
    "farm": (4, 4, ["soil", "soil_sprout", "soil_growing", "soil_ripe", "cow", "hen", "hive", "hay",
                    "fence", "fence_post", "scarecrow", "barrel", "crate", "trough", "wheelbarrow", "lamp"]),
    "fx": (4, 4, ["fire0", "fire1", "fire2", "fire3", "smoke", "splash", "bucket", "bucket_full",
                  "axe", "pickaxe", "hoe", "rod", "hammer", "bread", "fish", "coin"]),
    "chars1": (6, 4, [f"v{i}_{p}" for i in range(6) for p in ("down", "step", "up", "side")]),
    "chars2": (6, 4, [f"v{i}_{p}" for i in range(6, 12) for p in ("down", "step", "up", "side")]),
    "chars3": (6, 4, [f"v{i}_{p}" for i in range(12, 18) for p in ("down", "step", "up", "side")]),
    "chars4": (6, 4, [f"v{i}_{p}" for i in range(18, 24) for p in ("down", "step", "up", "side")]),
    # house templates, three per level (procedural variety: each home picks one); all roofs red, recoloured below
    "houses": (3, 3, ["house1a", "house1b", "house1c", "house2a", "house2b", "house2c", "house3a", "house3b", "house3c"]),
    "landscape": (4, 4, ["bridge", "pier", "rowboat", "lilypads", "reeds", "stepping_stones", "pond_small", "quarry_pit",
                         "signpost", "fallen_log", "campfire", "flowerbed", "tall_grass", "mushroom_ring", "woodpile",
                         "notice_board"]),
    "yard": (4, 4, ["fence_h", "fence_v", "fence_corner", "fence_gate", "picket_fence", "stone_wall", "for_sale",
                    "lot_stakes", "bed_empty", "bed_sprouts", "bed_ripe", "mailbox", "pigsty", "small_barn", "doghouse",
                    "path_slab"]),
    "mine": (4, 4, ["mine_big", "mine_cart", "rails", "ore_pile", "amethyst_rock", "emerald_rock", "rubble", "coal_crate",
                    "d20", "d6", "fight_dust", "hit_star", "heart", "heart_broken", "bandage", "dizzy"]),
    "weapons": (4, 4, ["shovel", "pitchfork", "club", "knife", "wood_sword", "sword", "axe2", "sickle", "scythe", "spear",
                       "slingshot", "shield", "bow", "crowbar", "torch", "rolling_pin"]),
    "animals": (4, 4, ["pig", "sheep", "goat", "cow2", "hen2", "rooster", "duck", "chick", "horse", "dog", "cat", "rabbit",
                       "sheep_shorn", "pig_black", "cow_lying", "hen_nest"]),
    "items": (4, 4, ["egg_basket", "milk", "honey", "wool", "cheese", "carrots", "cabbage", "pumpkin", "corn", "grain_sack",
                     "apple", "berries", "iron_ingot", "gold_ingot", "gem", "coin_pouch"]),
    # future businesses (not used by the engine yet)
    "business": (3, 3, ["forge", "store", "bakery", "tavern", "windmill", "barn", "town_hall", "warehouse", "chapel"]),
    "business2": (3, 3, ["smithy2", "butcher", "tailor", "carpenter", "fishmonger", "bank", "stable", "pottery", "herbalist"]),
    # land, building and theft props (for sale / sold, construction stages, chests and locks)
    "property": (4, 4, ["foundation", "house_frame", "scaffold", "planks_stack", "bricks", "stone_blocks", "sawhorse",
                        "ladder", "sold_sign", "deed", "key", "padlock", "treasure_chest", "strongbox", "wanted_poster",
                        "stocks"]),
}
# Ground textures: a 4x4 sheet of square swatches (viewer/art/terrain.png), each made seamless and TEX px square.
TEXTURES = ["grass", "grass2", "flowers", "dirt", "cobble", "soil", "soil_wet", "sand", "water", "deep", "planks", "gravel",
            "wheat", "crops", "moss", "slabs"]
TEX = 48
# Target width (w) or height (h) in map pixels; the viewer map uses 16 px tiles, a house lot is 3x3 tiles.
# Proportions (Stardew-like): a villager is 22 px, a cottage about two villagers tall, a big house three, a tree
# about two and a half.
SIZE = {
    "house1": ("h", 50), "house2": ("w", 52), "house3": ("w", 60), "market": ("w", 34), "smithy": ("w", 72),
    "mine": ("w", 76), "coop": ("w", 20), "hives": ("w", 18), "well": ("w", 30),
    "oak": ("w", 46), "pine": ("w", 36), "apple_tree": ("w", 44), "stump": ("w", 18), "sapling": ("h", 16),
    "bush": ("w", 16), "berry_bush": ("w", 16), "boulder": ("w", 16), "copper_rock": ("w", 16), "gold_rock": ("w", 16),
    "crystal_rock": ("w", 16), "logs": ("w", 16), "flowers": ("w", 12), "grass": ("w", 10), "mushrooms": ("w", 10),
    "pond": ("w", 22), "soil": ("w", 16), "soil_sprout": ("w", 16), "soil_growing": ("w", 16), "soil_ripe": ("w", 16),
    "cow": ("w", 18), "hen": ("w", 7), "hive": ("w", 9), "hay": ("w", 12), "fence": ("w", 16), "fence_post": ("h", 10),
    "scarecrow": ("h", 18), "barrel": ("w", 10), "crate": ("w", 12), "trough": ("w", 14), "wheelbarrow": ("w", 14),
    "lamp": ("h", 20), "fire0": ("h", 14), "fire1": ("h", 14), "fire2": ("h", 14), "fire3": ("h", 14),
    "smoke": ("w", 10), "splash": ("w", 12), "bucket": ("w", 6), "bucket_full": ("w", 6), "axe": ("w", 8),
    "pickaxe": ("w", 8), "hoe": ("w", 8), "rod": ("w", 10), "hammer": ("w", 7), "bread": ("w", 8), "fish": ("w", 8),
    "coin": ("w", 6),
    **{f"house{lv}{v}": ("w", w) for lv, w in ((1, 44), (2, 52), (3, 60)) for v in "abc"},
    "bridge": ("w", 48), "pier": ("w", 30), "rowboat": ("w", 22), "lilypads": ("w", 14), "reeds": ("h", 16),
    "stepping_stones": ("w", 20), "pond_small": ("w", 44), "quarry_pit": ("w", 44), "signpost": ("h", 20),
    "fallen_log": ("w", 26), "campfire": ("w", 16), "flowerbed": ("w", 20), "tall_grass": ("w", 14),
    "mushroom_ring": ("w", 20), "woodpile": ("w", 22), "notice_board": ("w", 20),
    "fence_h": ("w", 16), "fence_v": ("h", 18), "fence_corner": ("h", 14), "fence_gate": ("w", 16), "picket_fence": ("w", 16),
    "stone_wall": ("w", 16), "for_sale": ("h", 20), "lot_stakes": ("w", 26), "bed_empty": ("w", 16), "bed_sprouts": ("w", 16),
    "bed_ripe": ("w", 16), "mailbox": ("h", 16), "pigsty": ("w", 32), "small_barn": ("w", 40), "doghouse": ("w", 18),
    "path_slab": ("w", 14),
    "mine_big": ("w", 80), "mine_cart": ("w", 20), "rails": ("h", 16), "ore_pile": ("w", 16), "amethyst_rock": ("w", 16),
    "emerald_rock": ("w", 16), "rubble": ("w", 16), "coal_crate": ("w", 14), "d20": ("w", 12), "d6": ("w", 10),
    "fight_dust": ("w", 30), "hit_star": ("w", 14), "heart": ("w", 9), "heart_broken": ("w", 9), "bandage": ("w", 10),
    "dizzy": ("w", 14),
    **{n: ("w", 10) for n in ("shovel", "pitchfork", "club", "knife", "wood_sword", "sword", "axe2", "sickle", "slingshot",
                             "shield", "crowbar", "torch", "rolling_pin")},
    "scythe": ("w", 14), "spear": ("w", 14), "bow": ("w", 12),
    "pig": ("w", 16), "sheep": ("w", 16), "goat": ("w", 15), "cow2": ("w", 20), "hen2": ("w", 8), "rooster": ("w", 9),
    "duck": ("w", 9), "chick": ("w", 5), "horse": ("w", 24), "dog": ("w", 13), "cat": ("w", 11), "rabbit": ("w", 9),
    "sheep_shorn": ("w", 15), "pig_black": ("w", 16), "cow_lying": ("w", 20), "hen_nest": ("w", 10),
    **{n: ("w", 10) for n in SHEETS["items"][2]},
    "forge": ("w", 64), "store": ("w", 60), "bakery": ("w", 60), "tavern": ("w", 66), "windmill": ("h", 80), "barn": ("w", 70),
    "town_hall": ("w", 70), "warehouse": ("w", 64), "chapel": ("w", 54),
    "smithy2": ("w", 56), "butcher": ("w", 56), "tailor": ("w", 54), "carpenter": ("w", 58), "fishmonger": ("w", 54),
    "bank": ("w", 60), "stable": ("w", 60), "pottery": ("w", 56), "herbalist": ("w", 54),
    "foundation": ("w", 32), "house_frame": ("w", 36), "scaffold": ("w", 36), "planks_stack": ("w", 18), "bricks": ("w", 16),
    "stone_blocks": ("w", 16), "sawhorse": ("w", 16), "ladder": ("h", 20), "sold_sign": ("h", 20), "deed": ("w", 12),
    "key": ("w", 10), "padlock": ("w", 9), "treasure_chest": ("w", 16), "strongbox": ("w", 14), "wanted_poster": ("w", 16),
    "stocks": ("w", 22),
}
CHAR_H = 22                      # villager height in map pixels (the code-drawn ones are 16)
ROOF_HUE = {"house1": 8, "house2": 222, "house3": 115,   # roof hue of each house as generated
            **{f"house{lv}{v}": 4 for lv in (1, 2, 3) for v in "abc"}}
ROOFS = [5, 215, 100, 280, 30, None]   # hue of the 6 roof colours in viewer/pixelmap.js ROOFS; None = slate grey


def blobs(im):
    """Connected components of opaque pixels: list of pixel lists."""
    w, h = im.size
    a = im.getchannel("A").load()
    seen, out = set(), []
    for y in range(h):
        for x in range(w):
            if a[x, y] < 40 or (x, y) in seen:
                continue
            stack, comp = [(x, y)], []
            seen.add((x, y))
            while stack:
                px, py = stack.pop()
                comp.append((px, py))
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and a[nx, ny] >= 40:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            out.append(comp)
    return out


def cut(sheet, rows, cols):
    """Split a sheet into rows x cols objects (cropped RGBA images), row by row."""
    im = Image.open(ART / f"{sheet}.png").convert("RGBA")
    comps = [c for c in blobs(im) if len(c) >= 4]
    xs = [p[0] for c in comps for p in c]
    ys = [p[1] for c in comps for p in c]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    cells = {}
    for c in comps:
        cx = sum(p[0] for p in c) / len(c)
        cy = sum(p[1] for p in c) / len(c)
        key = (min(rows - 1, int((cy - y0) / (y1 - y0) * rows)), min(cols - 1, int((cx - x0) / (x1 - x0) * cols)))
        cells.setdefault(key, []).extend(c)
    src = im.load()
    out = []
    for r in range(rows):
        for q in range(cols):
            pts = cells.get((r, q), [])
            if not pts:
                out.append(None)
                continue
            bx0, by0 = min(p[0] for p in pts), min(p[1] for p in pts)
            bx1, by1 = max(p[0] for p in pts) + 1, max(p[1] for p in pts) + 1
            spr = Image.new("RGBA", (bx1 - bx0, by1 - by0))
            dst = spr.load()
            for px, py in pts:
                dst[px - bx0, py - by0] = src[px, py]
            out.append(spr)
    return out


def unbleed(spr):
    """Fill transparent pixels with their nearest opaque colour, so box filtering doesn't darken edges."""
    im = spr.copy()
    px = im.load()
    w, h = im.size
    for _ in range(2):
        fill = {}
        for y in range(h):
            for x in range(w):
                if px[x, y][3]:
                    continue
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3]:
                        fill[x, y] = px[nx, ny][:3] + (0,)
                        break
        for k, v in fill.items():
            px[k] = v
    return im


def shrink(spr, f):
    a = spr.getchannel("A").resize((max(1, round(spr.width * f)), max(1, round(spr.height * f))), Image.BOX)
    rgb = unbleed(spr).convert("RGB").resize(a.size, Image.BOX)
    out = rgb.convert("RGBA")
    out.putalpha(a.point(lambda v: 255 if v >= 110 else 0))
    return out


def roof_variants(name, spr):
    """One sprite per roof colour: shift the hue of the roof pixels (the sheet's roof hue, upper part of the house)."""
    px = spr.load()
    w, h = spr.size
    base = ROOF_HUE[name] / 360
    # roof = connected region of pixels near the base hue, grown from the top half
    def near(c):
        hh, ll, ss = colorsys.rgb_to_hls(*(v / 255 for v in c[:3]))
        d = min(abs(hh - base), 1 - abs(hh - base))
        return c[3] and d < .08 and ss > .12
    roof = {(x, y) for y in range(int(h * .62)) for x in range(w) if near(px[x, y])}
    if name[-1] in "abc":   # the templates: grown from the top only, so red brick walls keep their colour
        seeds = [(x, y) for y in range(int(h * .3)) for x in range(w) if (x, y) in roof]
        grown, stack = set(seeds), list(seeds)
        while stack:
            x, y = stack.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in roof and q not in grown:
                    grown.add(q)
                    stack.append(q)
        roof = grown
    out = {}
    for k, hue in enumerate(ROOFS):
        v = spr.copy()
        vp = v.load()
        for x, y in roof:
            r, g, b, a = vp[x, y]
            hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if hue is None:
                nr, ng, nb = colorsys.hls_to_rgb(.62, ll * .95, ss * .15)
            else:
                nr, ng, nb = colorsys.hls_to_rgb(hue / 360, ll, min(1, ss * 1.05))
            vp[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
        out[f"{name}_r{k}"] = v
    return out


def seamless(im):
    """Cross-fade a square texture with itself shifted by half, first across x, then across y: no seams when tiled."""
    n = im.width
    ramp = [min(1, min(i + .5, n - i - .5) / (n * .3)) for i in range(n)]   # 0 at the edges, 1 inside
    for axis in (0, 1):
        shifted = Image.new("RGB", im.size)
        h = n // 2
        if axis == 0:
            shifted.paste(im.crop((h, 0, n, n)), (0, 0)); shifted.paste(im.crop((0, 0, h, n)), (n - h, 0))
        else:
            shifted.paste(im.crop((0, h, n, n)), (0, 0)); shifted.paste(im.crop((0, 0, n, h)), (0, n - h))
        a, b, out = im.load(), shifted.load(), Image.new("RGB", im.size)
        o = out.load()
        for y in range(n):
            for x in range(n):
                t = ramp[x if axis == 0 else y]
                o[x, y] = tuple(round(a[x, y][c] * t + b[x, y][c] * (1 - t)) for c in range(3))
        im = out
    return im


def textures():
    """The 16 swatches of terrain.png (squares on white), each cropped inside its border, TEX px, seamless."""
    im = Image.open(ART / "terrain.png").convert("RGB")
    w, h = im.size
    px = im.load()
    solid = lambda x, y: sum(px[x, y]) < 700
    def runs(prof):
        out, start = [], None
        for i, v in enumerate(prof + [0]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start > 20:
                    out.append((start, i))
                start = None
        return out
    cols = runs([int(sum(solid(x, y) for y in range(h)) > h * .3) for x in range(w)])
    rows = runs([int(sum(solid(x, y) for x in range(w)) > w * .3) for y in range(h)])
    assert len(cols) == 4 and len(rows) == 4, (cols, rows)
    out = {}
    for r, (y0, y1) in enumerate(rows):
        for c, (x0, x1) in enumerate(cols):
            m = round((x1 - x0) * .06)
            sw = im.crop((x0 + m, y0 + m, x1 - m, y1 - m)).resize((TEX, TEX), Image.BOX)
            out["tex_" + TEXTURES[r * 4 + c]] = seamless(sw).convert("RGBA")
    return out


def build():
    sprites = textures()
    for sheet, (rows, cols, names) in SHEETS.items():
        parts = cut(sheet, rows, cols)
        if sheet.startswith("chars"):
            for n, spr in zip(names, parts):
                if spr is not None:
                    sprites[n] = spr
            # one scale per villager (taken from the front view) so all four poses keep the same size
            for i in sorted({n.split("_")[0] for n in names}):
                f = CHAR_H / sprites[f"{i}_down"].height
                for p in ("down", "step", "up", "side"):
                    sprites[f"{i}_{p}"] = shrink(sprites[f"{i}_{p}"], f)
            continue
        for n, spr in zip(names, parts):
            if spr is None or n is None:
                continue
            axis, size = SIZE[n]
            f = size / (spr.width if axis == "w" else spr.height)
            sprites[n] = shrink(spr, f)
    for n in ROOF_HUE:
        sprites.update(roof_variants(n, sprites[n]))
    return sprites


def house_meta(spr):
    """Chimney top and window centres of a house sprite, relative to its bottom-centre (smoke and night lights)."""
    px = spr.load()
    w, h = spr.size
    top = next((x, y) for y in range(h) for x in range(w // 2, w) if px[x, y][3])
    glass = set()
    for y in range(int(h * .4), h):
        for x in range(w):
            r, g, b, a = px[x, y]
            hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if a and .5 < hh < .72 and ss > .18 and ll > .3:
                glass.add((x, y))
    wins = []
    while glass:
        stack, comp = [glass.pop()], []
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in glass:
                    glass.remove(q)
                    stack.append(q)
        if len(comp) >= 2:
            wins.append([round(sum(p[0] for p in comp) / len(comp) - w / 2), round(sum(p[1] for p in comp) / len(comp) - h)])
    merged = []   # panes of one window -> one light
    for x, y in sorted(wins):
        near = next((m for m in merged if abs(m[0] - x) <= 5 and abs(m[1] - y) <= 5), None)
        if near:
            near[0], near[1] = round((near[0] + x) / 2), round((near[1] + y) / 2)
        else:
            merged.append([x, y])
    return {"chimney": [top[0] - w // 2, top[1] - h], "windows": merged}


def pack(sprites, width=512):
    """Shelf-pack sprites into one atlas; returns (image, {name: [x, y, w, h]})."""
    order = sorted(sprites, key=lambda n: (-sprites[n].height, n))
    x = y = shelf = 0
    frames = {}
    for n in order:
        s = sprites[n]
        if x + s.width > width:
            x, y, shelf = 0, y + shelf + 1, 0
        frames[n] = [x, y, s.width, s.height]
        x += s.width + 1
        shelf = max(shelf, s.height)
    atlas = Image.new("RGBA", (width, y + shelf))
    for n, (fx, fy, _, _) in frames.items():
        atlas.paste(sprites[n], (fx, fy))
    return atlas, dict(sorted(frames.items()))


def main():
    sprites = build()
    meta = {n: house_meta(sprites[n]) for n in ROOF_HUE}
    atlas, frames = pack(sprites)
    buf = io.BytesIO()
    # 256 colours keep the pixel art intact and cut the embedded atlas about 4x (it rides in every page and the demo)
    atlas.quantize(256, method=Image.Quantize.FASTOCTREE).save(buf, "PNG", optimize=True)
    (ART / "atlas_preview.png").write_bytes(buf.getvalue())
    data = {"src": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "frames": frames, "meta": meta}
    OUT.write_text("// Generated by scripts/build_sprites.py from the SpriteCook sheets in viewer/art/. Do not edit.\n"
                   "window.SPRITE_ATLAS = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"{len(frames)} sprites, atlas {atlas.width}x{atlas.height}, {len(buf.getvalue()) // 1024} KB -> {OUT}")


if __name__ == "__main__":
    main()

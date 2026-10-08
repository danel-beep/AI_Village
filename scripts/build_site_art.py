"""Cuts the game's own sprites out of viewer/sprites_data.js for the download site (site/art/).

python scripts/build_site_art.py  -> site/art/<name>.png at the atlas' pixel size (the page scales them up
with image-rendering: pixelated) plus site/art/walkers.png, a strip of villager walk frames for CSS animation.
"""
import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "art"
NAMES = ["tex_grass", "tex_planks", "tex_dirt", "tex_water", "oak", "pine", "bush", "flowers", "house1a_r1",
         "house2a_r2", "house2b_r4", "house3a_r0", "market", "well", "town_hall", "windmill", "tavern",
         "coin_pouch", "em_heart", "em_handshake", "em_angry", "fire2", "notice_board", "ballot_box",
         "treasure_chest", "signpost", "beast_roar", "fence_h", "campfire", "bread", "sword", "key",
         "lanterns", "bunting", "scarecrow", "hen2", "cow2", "berry_bush", "gift_box", "deed"]
WALKERS = ["v0", "v3", "v7", "v11", "v15", "v20"]


def atlas():
    s = (ROOT / "viewer" / "sprites_data.js").read_text()
    i = s.index("{")
    d = json.loads(s[i:s.index("\n", i)].rstrip(";"))
    img = Image.open(io.BytesIO(base64.b64decode(d["src"].split(",", 1)[1]))).convert("RGBA")
    return img, d["frames"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    img, fr = atlas()
    crop = lambda n: img.crop((fr[n][0], fr[n][1], fr[n][0] + fr[n][2], fr[n][1] + fr[n][3]))
    for n in NAMES:
        crop(n).save(OUT / f"{n}.png", optimize=True)
    # walkers.png: one row per villager, frames down, step (16x24 cells, bottom-centred)
    w, h = 16, 24
    strip = Image.new("RGBA", (w * 2, h * len(WALKERS)))
    for r, v in enumerate(WALKERS):
        for c, f in enumerate(("down", "step")):
            s = crop(f"{v}_{f}")
            strip.paste(s, (c * w + (w - s.width) // 2, r * h + h - s.height))
    strip.save(OUT / "walkers.png", optimize=True)


if __name__ == "__main__":
    main()

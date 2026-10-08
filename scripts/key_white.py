"""Make the white background of a generated sprite sheet transparent, in place.

    python scripts/key_white.py viewer/art/bandits.png [more.png ...]

GPT Image and similar tools give sheets on plain white. Only white connected to the border is removed (flood fill),
so white inside a sprite (eyes, stars, bandages) stays. Near-white pixels next to removed ones go too (soft edges).
"""
import sys
from collections import deque

from PIL import Image


def key(path, near=232, edge=200):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    white = lambda c, t: min(c[:3]) >= t and max(c[:3]) - min(c[:3]) <= 18
    seen = bytearray(w * h)
    q = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i] or not white(px[x, y], near):
            continue
        seen[i] = 1
        px[x, y] = (255, 255, 255, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                q.append((nx, ny))
    for y in range(h):   # one pass of soft edge: light pixels touching the cleared background
        for x in range(w):
            c = px[x, y]
            if c[3] and white(c, edge) and any(0 <= nx < w and 0 <= ny < h and px[nx, ny][3] == 0
                                               for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
                px[x, y] = (255, 255, 255, 0)
    im.save(path)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        key(p)
        print("keyed", p)

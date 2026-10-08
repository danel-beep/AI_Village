"""The public site (site/) ships no keys and links to the game and its own images."""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
KEY = re.compile(rb"sk-(?:or-v1|proj|ant)-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}")


def test_site_has_no_keys():
    for f in SITE.rglob("*"):
        if f.is_file():
            assert not KEY.search(f.read_bytes()), f


def test_site_links_exist():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'href="https://ai-village.up.railway.app"' in html  # the «Играть» button (docs/site.md)
    for src in re.findall(r'(?:src|poster|href)="(img/[^"]+)"', html):
        assert (SITE / src).exists(), src

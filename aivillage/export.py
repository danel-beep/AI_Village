"""Sealed export of a finished run from the public website, for writing reports in the cloud.

The website's volume can't be reached from where reports are made, so the site serves its newest run at
GET /export (aivillage/web.py) as a sealed box: a tar.gz of the run's files (runs/<stem>.* and the clips made
since it began) encrypted to the public key in configs/export_key.json. Only the holder of the private key can
open it, so the endpoint needs no password and the box may pass through public places (a GitHub Actions job
fetches it, .github/workflows/run-export.yml). Model keys never touch the disk (aivillage/keys.py), so a box
never holds one.

Sealing (stdlib only, the hosting image has no crypto library): RSA-KEM, a random r < n sent as r^e mod n,
key = sha256(r); the tar.gz XOR shake_256(key) keystream; an HMAC-SHA256 tag over the ciphertext.

    python -m aivillage.export open BOX PRIVATE.json OUT.tar.gz
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import sys
import tarfile
from pathlib import Path

MAGIC = b"AIVX1"
KEY_FILE = Path(__file__).resolve().parent.parent / "configs" / "export_key.json"
MAX_RUN_BYTES = 400 * 1024 * 1024


def public_key(path: Path = KEY_FILE) -> tuple[int, int]:
    k = json.loads(Path(path).read_text())
    return int(k["n"], 16), int(k["e"])


def _stream(key: bytes, n: int) -> bytes:
    return hashlib.shake_256(b"aiv-export:" + key).digest(n) if n else b""


def _xor(a: bytes, b: bytes) -> bytes:
    if not a:
        return b""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def seal(data: bytes, n: int, e: int) -> bytes:
    size = (n.bit_length() + 7) // 8
    r = secrets.randbelow(n - 2) + 2
    c = pow(r, e, n).to_bytes(size, "big")
    key = hashlib.sha256(r.to_bytes(size, "big")).digest()
    body = _xor(data, _stream(key, len(data)))
    tag = hmac.new(key, body, hashlib.sha256).digest()
    return MAGIC + len(c).to_bytes(2, "big") + c + tag + body


def unseal(box: bytes, n: int, d: int) -> bytes:
    if not box.startswith(MAGIC):
        raise ValueError("not a sealed export")
    p = len(MAGIC)
    clen = int.from_bytes(box[p:p + 2], "big")
    c, tag, body = box[p + 2:p + 2 + clen], box[p + 2 + clen:p + 34 + clen], box[p + 34 + clen:]
    size = (n.bit_length() + 7) // 8
    key = hashlib.sha256(pow(int.from_bytes(c, "big"), d, n).to_bytes(size, "big")).digest()
    if not hmac.compare_digest(tag, hmac.new(key, body, hashlib.sha256).digest()):
        raise ValueError("wrong key or damaged box")
    return _xor(body, _stream(key, len(body)))


def runs(data: Path) -> list[Path]:
    """Every run log on the site, newest first."""
    found = [p for p in Path(data).glob("ws/*/runs/*.jsonl") if p.is_file()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def pack(data: Path, nth: int = 0) -> bytes:
    """tar.gz of the nth newest run: its runs/<stem>.* files, the workspace's clips made since it began, and
    index.json listing every run on the site (so another one can be asked for with ?n=)."""
    all_runs = runs(data)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        index = [{"n": k, "workspace": p.parent.parent.name, "run": p.stem, "bytes": p.stat().st_size,
                  "mtime": int(p.stat().st_mtime)} for k, p in enumerate(all_runs[:50])]
        raw = json.dumps(index, indent=1).encode()
        info = tarfile.TarInfo("index.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
        if 0 <= nth < len(all_runs):
            log = all_runs[nth]
            home, total = log.parent.parent, 0
            begun = _started(log)
            files = sorted(log.parent.glob(log.stem + ".*"))
            files += [p for p in home.rglob("*.mp4") if p.stat().st_mtime >= begun]
            for p in files:
                total += p.stat().st_size
                if total > MAX_RUN_BYTES:
                    break
                tar.add(p, arcname=str(p.relative_to(home)))
    return buf.getvalue()


def _started(log: Path) -> float:
    """When a run began, from its file name (YYYY-MM-DD_HH-MM-SS); its mtime if the name is something else."""
    import datetime
    try:
        return datetime.datetime.strptime(log.stem[:19], "%Y-%m-%d_%H-%M-%S").timestamp() - 60
    except ValueError:
        return log.stat().st_mtime - 86400


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 4 or a[0] != "open":
        print(__doc__)
        return 2
    k = json.loads(Path(a[2]).read_text())
    Path(a[3]).write_bytes(unseal(Path(a[1]).read_bytes(), int(k["n"], 16), int(k["d"], 16)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

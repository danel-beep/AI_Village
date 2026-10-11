"""Sealed run export (aivillage/export.py, GET /export in aivillage/web.py)."""
import io
import json
import os
import tarfile
import time

import pytest

from aivillage import export

# a tiny RSA key from two Mersenne primes: enough to test the sealing, nothing else
P, Q, E = 2 ** 127 - 1, 2 ** 89 - 1, 65537
N, D = P * Q, pow(E, -1, (P - 1) * (Q - 1))


def test_seal_roundtrip_and_tamper():
    data = os.urandom(5000) + b"village"
    box = export.seal(data, N, E)
    assert box.startswith(export.MAGIC) and data not in box
    assert export.unseal(box, N, D) == data
    assert export.unseal(export.seal(b"", N, E), N, D) == b""
    bad = box[:-1] + bytes([box[-1] ^ 1])
    with pytest.raises(ValueError):
        export.unseal(bad, N, D)


def test_repo_key_is_a_public_key_only():
    k = json.loads(export.KEY_FILE.read_text())
    assert set(k) == {"n", "e"} and int(k["n"], 16).bit_length() >= 3072


def make_run(data, ws, name, mtime):
    runs = data / "ws" / ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for ext in (".jsonl", ".summary.json"):
        f = runs / (name + ext)
        f.write_text(f"{name}{ext}")
        os.utime(f, (mtime, mtime))
    return runs


def test_pack_newest_run_with_its_files_and_clips(tmp_path):
    now = time.time()
    make_run(tmp_path, "a", "2026-10-09_10-00-00", now - 3000)
    make_run(tmp_path, "b", "2026-10-10_21-27-26", now)
    (tmp_path / "ws" / "b" / "videos").mkdir()
    (tmp_path / "ws" / "b" / "videos" / "nedelya-1.mp4").write_bytes(b"mp4")
    (tmp_path / "ws" / "b" / "secret").write_text("never")
    tar = tarfile.open(fileobj=io.BytesIO(export.pack(tmp_path)), mode="r:gz")
    names = set(tar.getnames())
    assert names == {"index.json", "runs/2026-10-10_21-27-26.jsonl", "runs/2026-10-10_21-27-26.summary.json",
                     "videos/nedelya-1.mp4"}
    index = json.loads(tar.extractfile("index.json").read())
    assert [r["run"] for r in index] == ["2026-10-10_21-27-26", "2026-10-09_10-00-00"]
    older = tarfile.open(fileobj=io.BytesIO(export.pack(tmp_path, 1)), mode="r:gz")
    assert "runs/2026-10-09_10-00-00.jsonl" in older.getnames()


def test_export_endpoint_is_sealed_and_rate_limited(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from aivillage import web
    make_run(tmp_path, "b", "2026-10-10_21-27-26", time.time())
    monkeypatch.setattr(export, "public_key", lambda path=None: (N, E))
    with TestClient(web.create_app(web.Site(tmp_path, "pw"))) as c:
        r = c.get("/export")
        assert r.status_code == 200 and r.content.startswith(export.MAGIC)
        tar = tarfile.open(fileobj=io.BytesIO(export.unseal(r.content, N, D)), mode="r:gz")
        assert "runs/2026-10-10_21-27-26.jsonl" in tar.getnames()
        assert c.get("/export").status_code == 429

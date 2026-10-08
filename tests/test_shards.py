"""CI splits the suite by file (AIV_SHARD=k/n): every test file must land in exactly one shard."""
from pathlib import Path

from conftest import _shard_files


def test_every_test_file_runs_in_exactly_one_shard():
    files = sorted(p.name for p in Path(__file__).parent.glob("test_*.py"))
    for n in (1, 2, 3):
        shards = _shard_files(files, n)
        assert sorted(f for s in shards for f in s) == files
        assert all(shards), "an empty shard means a CI job that checks nothing"

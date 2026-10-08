"""With AIV_NO_SKIPS=1 (set in CI) any skipped test fails the run: server and viewer tests skip
when fastapi/httpx/node are missing, and a CI that silently skips them is not checking the app.

With AIV_SHARD=k/n (CI) only shard k of n runs: whole test files are spread over the shards by
their rough cost in tests/durations.json (files not listed count as 2 s), so shards finish together."""
import json
import os
from pathlib import Path

_skipped: list[str] = []


def pytest_runtest_logreport(report):
    if report.skipped and not hasattr(report, "wasxfail"):
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("AIV_NO_SKIPS") == "1" and _skipped and exitstatus == 0:
        print(f"\nAIV_NO_SKIPS: {len(_skipped)} test(s) skipped, install all deps (pip install -e .[live,dev]):")
        for nodeid in _skipped[:20]:
            print("  " + nodeid)
        session.exitstatus = 1


def _shard_files(files: list[str], n: int) -> list[set[str]]:
    cost = json.loads((Path(__file__).parent / "durations.json").read_text())
    shards: list[tuple[float, set[str]]] = [(0.0, set()) for _ in range(n)]
    for f in sorted(files, key=lambda f: (-cost.get(f, 2.0), f)):
        i = min(range(n), key=lambda i: (shards[i][0], i))
        shards[i] = (shards[i][0] + cost.get(f, 2.0), shards[i][1] | {f})
    return [files for _, files in shards]


def pytest_collection_modifyitems(config, items):
    spec = os.environ.get("AIV_SHARD")
    if not spec:
        return
    k, n = (int(x) for x in spec.split("/"))
    files = sorted({Path(item.fspath).name for item in items})
    mine = _shard_files(files, n)[k - 1]
    keep = [item for item in items if Path(item.fspath).name in mine]
    config.hook.pytest_deselected(items=[item for item in items if Path(item.fspath).name not in mine])
    items[:] = keep

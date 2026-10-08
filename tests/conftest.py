"""With AIV_NO_SKIPS=1 (set in CI) any skipped test fails the run: server and viewer tests skip
when fastapi/httpx/node are missing, and a CI that silently skips them is not checking the app."""
import os

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

"""The installed start scripts follow the code: old desktop icons switch to the stable tag."""

from pathlib import Path

from aivillage.launcher import refresh_start_scripts

ROOT = Path(__file__).resolve().parents[1]


def _app(home: Path) -> Path:
    app = home / "app" / "scripts"
    app.mkdir(parents=True)
    (app / "start.sh").write_text("new sh\n")
    (app / "start.ps1").write_text("new ps1\n")
    return home / "app"


def test_old_scripts_are_replaced(tmp_path):
    home, desk = tmp_path / "AIVillage", tmp_path / "Desktop"
    app = _app(home)
    desk.mkdir()
    (home / "start.sh").write_text("old main\n")
    (home / "start.sh").chmod(0o755)
    (desk / "AI Village.command").write_text("old main\n")
    updated = refresh_start_scripts(home, app, desk)
    assert set(updated) == {home / "start.sh", desk / "AI Village.command"}
    assert (home / "start.sh").read_text() == "new sh\n"
    assert (home / "start.sh").stat().st_mode & 0o111
    assert not (home / "start.ps1").exists()  # nothing installed there, nothing created
    assert refresh_start_scripts(home, app, desk) == []  # already fresh


def test_dev_checkout_is_left_alone(tmp_path):
    home = tmp_path / "AIVillage"
    _app(home)
    home.joinpath("start.sh").write_text("old\n")
    assert refresh_start_scripts(home, ROOT, tmp_path) == []
    assert home.joinpath("start.sh").read_text() == "old\n"


def test_shipped_scripts_use_stable_tag_and_lock():
    for name in ("start.sh", "start.ps1"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
        assert "refs/tags/stable" in text and "refs/heads/main" not in text
        assert "--frozen" in text
    assert (ROOT / "uv.lock").is_file()

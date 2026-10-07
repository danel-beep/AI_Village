"""Open the village to the internet for own AIs: a Cloudflare quick tunnel (free, no account).

Claude, ChatGPT and Gemini connect to MCP servers from their own clouds, so `http://localhost` is not enough.
`cloudflared tunnel --url http://127.0.0.1:<port>` gives a temporary `https://<words>.trycloudflare.com` address
that forwards to this computer while the app runs. The binary comes from PATH or is downloaded once into
`<home>/bin` from Cloudflare's GitHub releases. Through the tunnel only `/mcp/...` is reachable
(`mcpserver.OutsideOnlyMcp`)."""

from __future__ import annotations

import atexit
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import urllib.request
from pathlib import Path

from . import keys

RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


def asset(system: str | None = None, machine: str | None = None) -> str:
    """Release file name for this computer."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arm = machine in ("arm64", "aarch64")
    if system == "windows":
        return "cloudflared-windows-amd64.exe"
    if system == "darwin":
        return f"cloudflared-darwin-{'arm64' if arm else 'amd64'}.tgz"
    return f"cloudflared-linux-{'arm64' if arm else 'amd64'}"


def binary(download: bool = True) -> Path | None:
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    name = "cloudflared.exe" if platform.system() == "Windows" else "cloudflared"
    path = keys.home() / "bin" / name
    if path.is_file() or not download:
        return path if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    file = asset()
    tmp = path.parent / (file + ".part")
    urllib.request.urlretrieve(RELEASES + file, tmp)
    if file.endswith(".tgz"):
        with tarfile.open(tmp) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("cloudflared"))
            with tar.extractfile(member) as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp.unlink()
    else:
        tmp.replace(path)
    path.chmod(0o755)
    return path


def find_url(line: str) -> str | None:
    m = URL_RE.search(line)
    return m.group(0) if m else None


class Tunnel:
    """One quick tunnel for the app's lifetime. `state`: off / starting / on / error."""

    def __init__(self):
        self.state, self.url, self.error = "off", "", ""
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def start(self, port: int) -> None:
        with self.lock:
            if self.state in ("starting", "on"):
                return
            self.state, self.url, self.error = "starting", "", ""
        threading.Thread(target=self._run, args=(port,), name="tunnel", daemon=True).start()

    def _run(self, port: int) -> None:
        try:
            exe = binary()
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.proc = subprocess.Popen([str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                         creationflags=flags)
            atexit.register(self.stop)
            for line in self.proc.stderr:
                url = find_url(line)
                if url and not self.url:
                    self.url, self.state = url, "on"
            if self.state != "off":
                self.state, self.error = "error", f"cloudflared stopped (code {self.proc.wait()})"
        except Exception as e:
            self.state, self.error = "error", f"{type(e).__name__}: {e}"

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        self.state, self.url = "off", ""
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def status(self) -> dict:
        return {"state": self.state, "url": self.url, "error": self.error}


TUNNEL = Tunnel()

"""API keys and provider choice, kept on the player's computer (never in the repo or in run logs).

One JSON file, `<home>/settings.json` (home: env AIVILLAGE_HOME, else ~/AIVillage):

    {"provider": "auto|openai|openrouter", "model": "openai/gpt-6-luna",
     "openai_key": "sk-...", "openrouter_key": "sk-or-...", "parallel": 16, "openai_tier": "flex|default"}

Values in the file win over environment variables (OPENAI_API_KEY, OPENROUTER_API_KEY,
AIVILLAGE_PROVIDER, AIVILLAGE_MODEL), so a key changed in the viewer's settings panel takes
effect on the next model call. The file is re-read only when it changes.
The old launcher file `<home>/openrouter_key` is still read as the OpenRouter key.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

PROVIDERS = ("auto", "openai", "openrouter")
FIELDS = ("provider", "model", "openai_key", "openrouter_key", "parallel", "openai_tier")
ENV = {"openai_key": "OPENAI_API_KEY", "openrouter_key": "OPENROUTER_API_KEY",
       "provider": "AIVILLAGE_PROVIDER", "model": "AIVILLAGE_MODEL", "parallel": "AIVILLAGE_MAX_PARALLEL",
       "openai_tier": "AIVILLAGE_OPENAI_TIER"}

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def home() -> Path:
    return Path(os.environ.get("AIVILLAGE_HOME") or Path.home() / "AIVillage")


def path(h: Path | None = None) -> Path:
    return (h or home()) / "settings.json"


def load(h: Path | None = None) -> dict:
    """Saved settings only (no environment). Missing or broken file -> {}."""
    h = h or home()
    f = path(h)
    try:
        mtime = f.stat().st_mtime
    except OSError:
        mtime = -1.0
    with _lock:
        hit = _cache.get(str(f))
        if hit and hit[0] == mtime:
            return dict(hit[1])
    data: dict = {}
    if mtime >= 0:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            data = {k: raw[k] for k in FIELDS if raw.get(k) not in (None, "")}
        except (OSError, ValueError):
            data = {}
    legacy = h / "openrouter_key"
    if "openrouter_key" not in data and legacy.exists():
        key = legacy.read_text(encoding="utf-8").strip()
        if key:
            data["openrouter_key"] = key
    with _lock:
        _cache[str(f)] = (mtime, data)
    return dict(data)


def save(changes: dict, h: Path | None = None) -> dict:
    """Merge `changes` into the file. An empty string removes a field. Returns the saved settings."""
    h = h or home()
    data = load(h)
    for k, v in changes.items():
        if k not in FIELDS:
            continue
        v = v.strip() if isinstance(v, str) else v
        if v in (None, ""):
            data.pop(k, None)
        else:
            data[k] = v
    if data.get("provider") not in (None, *PROVIDERS):
        raise ValueError(f"provider must be one of {PROVIDERS}")
    if data.get("openai_tier") not in (None, "flex", "default"):
        raise ValueError("openai_tier must be flex or default")
    if "parallel" in data:
        data["parallel"] = max(1, min(64, int(data["parallel"])))
    h.mkdir(parents=True, exist_ok=True)
    f = path(h)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(f)
    with _lock:
        _cache.pop(str(f), None)
    return load(h)


def get(name: str, h: Path | None = None):
    """Saved value, else environment variable, else None."""
    v = load(h).get(name)
    if v in (None, ""):
        v = os.environ.get(ENV[name]) or None
    return v


def provider(h: Path | None = None) -> str:
    p = (get("provider", h) or "auto").lower()
    return p if p in PROVIDERS else "auto"


def has_any_key(h: Path | None = None) -> bool:
    return bool(get("openai_key", h) or get("openrouter_key", h))


def mask(key: str | None) -> str:
    """What the settings panel may show: never the key itself."""
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "…"


def public(h: Path | None = None) -> dict:
    """Settings for the viewer: keys masked, plus where each value came from."""
    saved = load(h)
    out: dict = {"provider": provider(h), "model": get("model", h) or "", "parallel": get("parallel", h) or "",
                 "openai_tier": get("openai_tier", h) or "default"}
    for k in ("openai_key", "openrouter_key"):
        v = get(k, h)
        out[k] = {"set": bool(v), "masked": mask(v), "from": "file" if saved.get(k) else ("env" if v else "")}
    return out

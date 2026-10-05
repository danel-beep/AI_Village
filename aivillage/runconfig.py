"""Run config: one YAML file describes a whole run (agents, models, mechanics, world settings, god script).

    python -m aivillage.run --config configs/example.yaml

Everything is validated up front, so a typo fails before any model is called.
The resolved world settings end up in the log header, so replay never needs the YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .bots import BOT_TYPES
from . import modes
from .config import DEFAULT_CONFIG
from .registry import ACTIONS, GOD

UNDISABLEABLE = {"wait"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSpec(Strict):
    name: str
    profession: str
    model: str | None = None  # OpenRouter model id, or "stub"
    bot: str | None = None  # scripted bot kind
    # Private plot at start (aivillage/plots.py); None = config "plots" defaults
    plot_cells: int | None = Field(default=None, ge=0)
    house_level: int | None = Field(default=None, ge=1)
    buildings: list[str] | None = None  # built for free at the start

    @model_validator(mode="after")
    def one_brain(self):
        if self.model and self.bot:
            raise ValueError(f"agent {self.name}: give either 'model' or 'bot', not both")
        return self


class Mechanics(Strict):
    disabled: list[str] = Field(default_factory=list)


class GodEvent(Strict):
    day: int = Field(ge=1)
    hour: int
    name: str
    args: dict = Field(default_factory=dict)


class RunConfig(Strict):
    days: int = Field(default=3, ge=1)
    seed: int = 1
    log: str | None = None
    # Default brain for agents that name none: a model id ("stub" works offline) or a bot kind.
    model: str | None = None
    bot: str = "worker"
    # Backup OpenRouter models for when the main one is rate-limited or down (empty = env AIVILLAGE_FALLBACK_MODELS).
    fallback_models: list[str] = Field(default_factory=list)
    mode: str = modes.DEFAULT_MODE  # economy mode, see aivillage/modes.py
    agents: list[AgentSpec] | None = None  # None = the default villagers
    # How many villagers: `agents` (or the default five) first, the rest generated (aivillage/population.py).
    villagers: int | None = Field(default=None, ge=1, le=60)
    mechanics: Mechanics = Field(default_factory=Mechanics)
    world: dict = Field(default_factory=dict)  # overrides of config.DEFAULT_CONFIG
    god: list[GodEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_names(self):
        errs = []
        if self.mode not in modes.MODES:
            errs.append(f"mode: unknown economy mode '{self.mode}' (have: {', '.join(modes.MODES)})")
        unknown = set(self.world) - set(DEFAULT_CONFIG)
        if unknown:
            errs.append(f"world: unknown settings {sorted(unknown)}")
        for key in ("agents", "seed", "disabled_actions"):
            if key in self.world:
                errs.append(f"world.{key}: set it at the top level of the run config instead")
        bad = set(self.mechanics.disabled) - set(ACTIONS.specs)
        if bad:
            errs.append(f"mechanics.disabled: unknown actions {sorted(bad)}")
        if UNDISABLEABLE & set(self.mechanics.disabled):
            errs.append("mechanics.disabled: 'wait' cannot be switched off")
        professions = {**DEFAULT_CONFIG["professions"], **(self.world.get("professions") or {})}
        names = [a.name for a in self.agents or []]
        if len(names) != len(set(names)):
            errs.append("agents: names must be unique")
        for a in self.agents or []:
            if a.profession not in professions:
                errs.append(f"agent {a.name}: unknown profession '{a.profession}'")
        for kind in {self.bot} | {a.bot for a in self.agents or [] if a.bot}:
            if kind not in BOT_TYPES:
                errs.append(f"unknown bot '{kind}' (have: {', '.join(BOT_TYPES)})")
        start = self.world.get("day_start_hour", DEFAULT_CONFIG["day_start_hour"])
        end = self.world.get("day_end_hour", DEFAULT_CONFIG["day_end_hour"])
        for g in self.god:
            if g.name not in GOD.specs:
                errs.append(f"god: unknown event '{g.name}' (have: {', '.join(GOD.specs)})")
            else:
                try:
                    GOD.specs[g.name].args.model_validate(g.args)
                except ValidationError as e:
                    errs.append(f"god {g.name} day {g.day}: bad args ({e.error_count()} errors: "
                                + ", ".join(".".join(map(str, x["loc"])) for x in e.errors()) + ")")
            if not start <= g.hour < end:
                errs.append(f"god {g.name}: hour must be in [{start}, {end})")
            if g.day > self.days:
                errs.append(f"god {g.name}: day {g.day} is after the last day ({self.days})")
        if errs:
            raise ValueError("; ".join(errs))
        return self

    def world_override(self) -> dict:
        """Partial world config for `engine.new_world` (brains stripped from agents)."""
        out = modes.world_override(self.mode, self.world)
        out["seed"] = self.seed
        if self.agents is not None:
            out["agents"] = [{"name": a.name, "profession": a.profession,
                              **a.model_dump(include={"plot_cells", "house_level", "buildings"}, exclude_none=True)}
                             for a in self.agents]
        if self.villagers:
            out["population"] = {**(out.get("population") or {}), "size": self.villagers}
        off = set(self.mechanics.disabled) | set(modes.disabled(self.mode))
        if off:
            out["disabled_actions"] = sorted(off)
        return out

    def brains(self, names: list[str]) -> dict[str, tuple[Literal["model", "bot"], str]]:
        """name -> ("model", id) or ("bot", kind)."""
        per = {a.name: a for a in self.agents or []}
        out = {}
        for n in names:
            a = per.get(n)
            if a and a.model:
                out[n] = ("model", a.model)
            elif a and a.bot:
                out[n] = ("bot", a.bot)
            elif self.model:
                out[n] = ("model", self.model)
            else:
                out[n] = ("bot", self.bot)
        return out

    def god_script(self, world_config: dict) -> dict[int, list]:
        """{tick: [event, ...]}; tick 0 is day 1 at day_start_hour."""
        from .clock import tick_of
        script: dict[int, list] = {}
        for g in self.god:
            tick = tick_of(world_config, g.day, g.hour)
            script.setdefault(tick, []).append({"name": g.name, "args": g.args})
        return script


class ConfigError(Exception):
    pass


def load(path: str | Path) -> RunConfig:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"{path}: {e}") from None
    return parse(data, str(path))


def parse(data: dict, source: str = "config") -> RunConfig:
    try:
        return RunConfig.model_validate(data)
    except ValidationError as e:
        msgs = "\n".join(f"  {'.'.join(map(str, x['loc'])) or '(top)'}: {x['msg']}" for x in e.errors())
        raise ConfigError(f"{source} is invalid:\n{msgs}") from None

"""Action registry: one declaration per action produces its prompt description,
its JSON schema, its validation and its effect.

Adding a mechanic = adding one `@registry.action(...)` function. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from .ops import Ctx
from .state import Agent


class NoArgs(BaseModel):
    pass


class ActionError(Exception):
    """Raised by an action when it cannot be done; the message is shown to the agent."""


# apply(ctx, actor, args) -> None; raises ActionError if the action is impossible.
ApplyFn = Callable[[Ctx, Agent, BaseModel], None]
# available(ctx, actor) -> bool: cheap check used to list actions in the observation.
AvailFn = Callable[[Ctx, Agent], bool]


@dataclass
class ActionSpec:
    name: str
    description: str
    args: type[BaseModel]
    apply: ApplyFn
    available: AvailFn

    def schema(self) -> dict:
        return self.args.model_json_schema()

    def prompt_line(self) -> str:
        props = self.schema().get("properties", {})
        sig = ", ".join(props.keys())
        return f"{self.name}({sig}): {self.description}"


class Registry:
    def __init__(self) -> None:
        self.specs: dict[str, ActionSpec] = {}

    def action(self, name: str, description: str, args: type[BaseModel] = NoArgs,
               available: AvailFn | None = None):
        def deco(fn: ApplyFn) -> ApplyFn:
            assert name not in self.specs, f"duplicate action {name}"
            self.specs[name] = ActionSpec(name, description, args, fn, available or (lambda c, a: True))
            return fn
        return deco

    def parse(self, name: str, raw_args: dict | None) -> tuple[ActionSpec, BaseModel]:
        spec = self.specs.get(name)
        if spec is None:
            raise ActionError(f"unknown action '{name}'")
        try:
            args = spec.args.model_validate(raw_args or {})
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'args'}: {x['msg']}" for x in e.errors())
            raise ActionError(f"bad arguments for {name}: {msgs}") from None
        return spec, args

    def run(self, ctx: Ctx, actor: Agent, name: str, raw_args: dict | None) -> None:
        spec, args = self.parse(name, raw_args)
        spec.apply(ctx, actor, args)

    def available(self, ctx: Ctx, actor: Agent) -> list[str]:
        return [n for n, s in self.specs.items() if s.available(ctx, actor)]

    def describe(self) -> str:
        return "\n".join(s.prompt_line() for s in self.specs.values())

    def schemas(self) -> dict[str, dict]:
        return {n: s.schema() for n, s in self.specs.items()}


ACTIONS = Registry()
GOD = Registry()

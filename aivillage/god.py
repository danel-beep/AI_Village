"""God mode: interventions by the experimenter. They go through the same pipeline as
agent actions, are logged with source "god", and agents never learn a human did it."""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import clock, ops, tiles
from .actions import ItemMap, _agent
from .ops import Ctx, fmt_items
from .registry import GOD, ActionError
from .state import Agent, Fire, Letter


class PersonArgs(BaseModel):
    person: str


@GOD.action("fire", "Set a villager's house on fire. If not put out in time, their chest burns.", PersonArgs)
def fire(ctx: Ctx, _god: Agent | None, args: PersonArgs) -> None:
    victim = _agent(ctx, args.person)
    if victim.home in ctx.world.fires:
        raise ActionError("already burning")
    ctx.world.fires[victim.home] = Fire(victim.home, ctx.cfg["fire_ticks"], ctx.cfg["fire_water_needed"])
    ctx.emit("fire", f"Smoke! {victim.name}'s house is on fire! It needs {ctx.cfg['fire_water_needed']} buckets "
             f"of water (fetch water at the river) and grows if nobody fights it; it burns down in "
             f"{ctx.cfg['fire_ticks']} hours.", visibility="public", victim=victim.name, house=victim.home)


class TreasureArgs(BaseModel):
    location: str
    items: ItemMap
    tell: str | None = Field(None, description="villager who gets an anonymous hint")


@GOD.action("treasure", "Hide items on the ground somewhere; optionally hint one villager.", TreasureArgs)
def treasure(ctx: Ctx, _god, args: TreasureArgs) -> None:
    loc = ctx.world.locations.get(args.location)
    if loc is None:
        raise ActionError(f"unknown location {args.location}")
    for k, v in args.items.items():
        if k not in ctx.cfg["items"]:
            raise ActionError(f"unknown item {k}")
        ops.mint(ctx.world, loc.ground, k, v)
    if args.tell:
        who = _agent(ctx, args.tell)
        ctx.world.mail.append(Letter("anonymous", who.name,
                                     f"Psst. There is {fmt_items(args.items)} lying at {loc.name}.",
                                     ctx.world.tick + clock.per_hour(ctx.cfg)))
    ctx.emit("god_treasure", f"[god] treasure at {loc.id}: {fmt_items(args.items)}", visibility="private")


class RumorArgs(BaseModel):
    to: str
    text: str


@GOD.action("rumor", "Send an anonymous letter (true or false) to a villager.", RumorArgs)
def rumor(ctx: Ctx, _god, args: RumorArgs) -> None:
    who = _agent(ctx, args.to)
    ctx.world.mail.append(Letter("anonymous", who.name, args.text[: ctx.cfg["max_text_len"]], ctx.world.tick + clock.per_hour(ctx.cfg)))


class DroughtArgs(BaseModel):
    location: str
    days: int = Field(3, ge=1)


@GOD.action("drought", "Halve a location's resources and stop regrowth for some days.", DroughtArgs)
def drought(ctx: Ctx, _god, args: DroughtArgs) -> None:
    loc = ctx.world.locations.get(args.location)
    if loc is None or not loc.resources:
        raise ActionError(f"{args.location} has no resources")
    for r in list(loc.resources):
        tiles.scale(loc, r, 0.5)
    loc.drought_until_day = ctx.world.day + args.days
    ctx.emit("drought", f"A blight hits the {loc.name}. Little will grow there for {args.days} days.",
             visibility="public")


class SickArgs(BaseModel):
    person: str
    days: int = Field(2, ge=1)


@GOD.action("sickness", "Make a villager sick: they cannot work for some days.", SickArgs)
def sickness(ctx: Ctx, _god, args: SickArgs) -> None:
    who = _agent(ctx, args.person)
    who.sick_until_day = ctx.world.day + args.days
    who.task = None
    ctx.emit("sick", f"{who.name} fell ill and cannot work for {args.days} days.", visibility="public")


class GiftArgs(BaseModel):
    person: str
    items: ItemMap = Field(default_factory=dict)
    coins: int = 0


@GOD.action("gift", "Give a villager items/coins out of nowhere (negative coins = take).", GiftArgs)
def gift(ctx: Ctx, _god, args: GiftArgs) -> None:
    who = _agent(ctx, args.person)
    for k, v in args.items.items():
        if k not in ctx.cfg["items"]:
            raise ActionError(f"unknown item {k}")
        ops.mint(ctx.world, who.inventory, k, v)
    if args.coins > 0:
        ops.mint_coins(ctx.world, who, args.coins)
    elif args.coins < 0:
        ops.burn_coins(ctx.world, who, min(who.coins, -args.coins))
    ctx.emit("gift", "Something strange happened: your belongings changed overnight.", to=[who.name])

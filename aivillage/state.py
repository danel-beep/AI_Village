"""World state. Plain dataclasses that serialize to JSON and back losslessly.

The state is the single source of truth: everything an agent can see and everything
replay must reproduce lives here. No RNG state is stored: randomness is derived from
(seed, tick), so a state plus a list of decisions always yields the same future.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Agent:
    name: str
    profession: str
    home: str
    location: str
    inventory: dict[str, int] = field(default_factory=dict)
    coins: int = 0
    satiety: int = 80
    health: int = 100
    asleep: bool = False
    # Multi-tick task the engine continues without asking the agent:
    # {"kind": "move", "path": [...]} or {"kind": "work", "hours_left": n, "resource": r}
    task: dict | None = None
    busy_until: int = 0  # tick at which the current action (or task step) is over; not asked before it
    tool_wear: int = 0
    status: str = "active"  # active | hospital | dead
    status_until_day: int = 0
    sick_until_day: int = 0
    evicted_until_day: int = 0
    last_error: str | None = None
    inbox: list[str] = field(default_factory=list)
    # reputation.py: own tally of what this agent saw others do, and rumors it heard
    reputation: dict[str, dict] = field(default_factory=dict)
    rumors: list[dict] = field(default_factory=list)


@dataclass
class Chest:
    id: str
    owner: str
    location: str
    items: dict[str, int] = field(default_factory=dict)
    coins: int = 0
    locked: bool = False
    shared_with: list[str] = field(default_factory=list)


@dataclass
class Location:
    id: str
    name: str
    neighbors: list[str]
    resources: dict[str, int] = field(default_factory=dict)
    ground: dict[str, int] = field(default_factory=dict)
    drought_until_day: int = 0
    # Finite map objects (see tiles.py): resource -> units left in each tree / bed / bush / rock.
    slots: dict[str, list[int]] = field(default_factory=dict)
    # Sown beds: slot index (str) -> {"resource", "by", "ripe_day"}.
    planted: dict[str, dict] = field(default_factory=dict)


@dataclass
class Offer:
    id: str
    sender: str
    to: str
    give: dict[str, int]
    want: dict[str, int]
    expires_tick: int


@dataclass
class Debt:
    id: str
    lender: str
    borrower: str
    coins_owed: int
    due_day: int
    status: str = "open"  # open | repaid | defaulted


@dataclass
class Order:
    id: str
    needs: dict[str, int]
    reward: int
    expires_day: int
    status: str = "open"  # open | fulfilled | expired
    fulfilled_by: str | None = None


@dataclass
class Project:
    id: str
    name: str
    needs: dict[str, int]
    contributed: dict[str, int] = field(default_factory=dict)
    contributors: dict[str, int] = field(default_factory=dict)  # agent -> units given
    done: bool = False


@dataclass
class Fire:
    location: str
    ticks_left: int  # hours until the house burns down
    water_needed: int  # buckets still needed; grows while nobody fights the fire
    hours: int = 0  # how long it has been burning


@dataclass
class Letter:
    sender: str
    to: str
    text: str
    deliver_tick: int


@dataclass
class LawProposal:
    id: str
    law: str  # tax | theft_fine | mayor_salary | exile | payout | grant
    proposer: str
    closes_tick: int
    value: int | None = None
    person: str | None = None
    yes: list[str] = field(default_factory=list)
    no: list[str] = field(default_factory=list)


@dataclass
class Governance:
    """Mayor, treasury and laws (aivillage/governance.py). `coins` is the treasury."""
    mayor: str | None = None
    coins: int = 0
    laws: dict[str, int] = field(default_factory=dict)  # law -> value in force (overrides config)
    candidates: dict[str, str] = field(default_factory=dict)  # name -> campaign pitch
    votes: dict[str, str] = field(default_factory=dict)  # voter -> candidate (secret ballot)
    proposals: dict[str, LawProposal] = field(default_factory=dict)  # open law proposals
    # Witnessed thefts that can still be reported: {"thief", "victim", "day", "known_by": [...]}
    crimes: list[dict] = field(default_factory=list)
    exiled: dict[str, int] = field(default_factory=dict)  # name -> exiled until this day

    @classmethod
    def from_dict(cls, d: dict) -> "Governance":
        d = dict(d)
        d["proposals"] = {k: LawProposal(**v) for k, v in d.get("proposals", {}).items()}
        return cls(**d)


@dataclass
class Marriage:
    id: str
    spouses: list[str]
    home: str  # the shared house (the proposer's)
    since_day: int


@dataclass
class Proposal:
    id: str
    sender: str
    to: str
    expires_day: int


@dataclass
class Kin:
    """Relationships (aivillage/family.py): feelings, marriages, proposals."""
    # feelings[a][b]: what a feels about b, in [-feeling_max, feeling_max]; zeros are dropped
    feelings: dict[str, dict[str, int]] = field(default_factory=dict)
    marriages: dict[str, Marriage] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    hung_out: dict[str, int] = field(default_factory=dict)  # "A|B" (sorted) -> last day
    settled: list[str] = field(default_factory=list)  # agents whose estate was passed on

    @classmethod
    def from_dict(cls, d: dict) -> "Kin":
        return cls(feelings=d.get("feelings", {}),
                   marriages={k: Marriage(**v) for k, v in d.get("marriages", {}).items()},
                   proposals={k: Proposal(**v) for k, v in d.get("proposals", {}).items()},
                   hung_out=d.get("hung_out", {}), settled=d.get("settled", []))


@dataclass
class Plot:
    """A house's private yard (aivillage/plots.py). Buildings: {"id", "kind", "built_day", "items",
    and for garden beds "crop" / "ripe_day"}; `items` is what lies ready to collect (or steal)."""
    owner: str  # "" = land for sale (a lot nobody owns yet)
    home: str  # location id: home_<Name> or a lot (aivillage/land.py)
    cells: int
    house: int = 1  # 0 on a lot: bare land, no house
    expansions: int = 0
    buildings: list[dict] = field(default_factory=list)
    kind: str = "home"  # home | lot
    price: int = 0  # lot: what the village asks for it while unowned
    sale: dict | None = None  # lot: {"to", "price", "expires_tick"} offered by its owner


@dataclass
class World:
    config: dict[str, Any]
    tick: int = 0
    day: int = 1
    hour: int = 6
    minute: int = 0
    agents: dict[str, Agent] = field(default_factory=dict)
    chests: dict[str, Chest] = field(default_factory=dict)
    locations: dict[str, Location] = field(default_factory=dict)
    offers: dict[str, Offer] = field(default_factory=dict)
    debts: dict[str, Debt] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    fires: dict[str, Fire] = field(default_factory=dict)
    mail: list[Letter] = field(default_factory=list)
    kin: Kin = field(default_factory=Kin)
    governance: Governance = field(default_factory=Governance)
    plots: dict[str, Plot] = field(default_factory=dict)  # home or lot location id -> plot
    crises: list[dict] = field(default_factory=list)  # active and finished world crises (crises.py)
    next_id: int = 1
    # Net amount of each item (and "coins") ever created minus destroyed.
    # Invariant: everything held in the world sums exactly to this.
    ledger: dict[str, int] = field(default_factory=dict)

    def new_id(self, prefix: str) -> str:
        i = self.next_id
        self.next_id += 1
        return f"{prefix}{i}"

    # ---- serialization ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        return cls(
            config=d["config"],
            tick=d["tick"],
            day=d["day"],
            hour=d["hour"],
            minute=d.get("minute", 0),
            agents={k: Agent(**v) for k, v in d["agents"].items()},
            chests={k: Chest(**v) for k, v in d["chests"].items()},
            locations={k: Location(**v) for k, v in d["locations"].items()},
            offers={k: Offer(**v) for k, v in d["offers"].items()},
            debts={k: Debt(**v) for k, v in d["debts"].items()},
            orders={k: Order(**v) for k, v in d["orders"].items()},
            projects={k: Project(**v) for k, v in d["projects"].items()},
            fires={k: Fire(**v) for k, v in d["fires"].items()},
            mail=[Letter(**v) for v in d["mail"]],
            kin=Kin.from_dict(d.get("kin", {})),
            governance=Governance.from_dict(d.get("governance", {})),
            plots={k: Plot(**v) for k, v in d.get("plots", {}).items()},
            crises=d.get("crises", []),
            next_id=d["next_id"],
            ledger=d["ledger"],
        )

    def hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

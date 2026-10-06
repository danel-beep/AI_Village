"""Scripted agents. They see exactly what an LLM agent sees (the observation dict)
and answer with the same decision format, so they exercise the real interface for free.

- RandomBot: fuzzer. Random actions with random (often invalid) arguments.
- WorkerBot: honest villager. Eats, works, crafts, sells, fights fires, fulfills orders.
- ThiefBot: a WorkerBot that steals whenever it sees a chance (people, chests, yards) and sometimes
  robs people at the mine by force.
- HomesteadBot: a TraderBot that builds up its own plot in the evening (plots.py).
"""

from __future__ import annotations

from collections import Counter

import random

# Farmers work their own garden beds at home (there is no common field) and gather wood the rest of the day.
WORK_SPOT = {"farmer": "forest", "fisher": "river", "woodcutter": "forest", "miner": "mine", "smith": "forest"}
FOODS = ["fish_soup", "bread", "fish", "berries"]


def decision(name: str, args: dict | None = None, thought: str = "", say: str | None = None) -> dict:
    return {"thought": thought, "action": {"name": name, "args": args or {}}, "say": say}


class Bot:
    def __init__(self, name: str, seed: int = 0):
        self.name = name
        self.rng = random.Random(f"{seed}:{name}")

    def decide(self, obs: dict) -> dict:
        raise NotImplementedError


class RandomBot(Bot):
    def decide(self, obs: dict) -> dict:
        r = self.rng
        me, here = obs["you"], obs["here"]
        people = [p["name"] for p in obs["board"]["villagers"]]
        items = list(obs["board"]["trader_prices"]) + ["water", "nonsense"]
        name = r.choice(obs["available_actions"] + ["move", "give", "offer", "steal", "bogus"])
        pick_item = lambda: r.choice(list(me["inventory"]) or items) if r.random() < 0.7 else r.choice(items)
        args: dict = {}
        if name == "move":
            args = {"to": r.choice(here["roads_to"] + [me["home"], "market", "mine", "nowhere"])}
        elif name == "work":
            args = {"hours": r.randint(1, 4)}
        elif name == "craft":
            args = {"recipe": r.choice(list(obs["board"]["recipes"]) + ["cake"]), "times": r.randint(1, 2)}
        elif name in ("eat", "buy", "sell", "pick_up"):
            args = {"item": pick_item(), "qty": r.randint(1, 3)}
        elif name in ("say",):
            args = {"text": r.choice(["hello", "anyone selling bread?", "I need wood", "   "])}
        elif name == "gossip":
            heard = [x["id"] for x in obs.get("rumors", []) if "id" in x]
            if heard and r.random() < 0.5:  # pass on a rumor heard, as is
                args = {"rumor": r.choice(heard + ["r0.nobody"])}
            else:
                args = {"about": r.choice(people + ["nobody"]), "text": r.choice(["is a thief", "pays debts", ""])}
            if r.random() < 0.5:
                args["to"] = r.choice(people)
        elif name in ("whisper", "letter"):
            args = {"to": r.choice(people), "text": "psst"}
        elif name == "give":
            args = {"to": r.choice(people), "items": {pick_item(): r.randint(1, 2)}, "coins": r.randint(0, 3)}
        elif name == "lend":
            args = {"to": r.choice(people), "coins": r.randint(1, 5), "repay_coins": r.randint(1, 8),
                    "due_day": obs["time"]["day"] + r.randint(0, 3)}
        elif name == "repay":
            debts = [d["id"] for d in obs["board"]["debts"]] or ["debt0"]
            args = {"debt_id": r.choice(debts), "coins": r.randint(1, 5)}
        elif name == "promise":
            args = {"to": r.choice(people), "coins": r.randint(1, 9), "due_day": obs["time"]["day"] + r.randint(0, 3),
                    **({"pledge": {pick_item(): 1}} if r.random() < 0.4 else {}),
                    **({"note": "for bread"} if r.random() < 0.5 else {})}
        elif name in ("forgive_debt", "transfer_debt", "demand_debt", "rule_debt"):
            debts = [d["id"] for d in obs["board"]["debts"]] or ["debt0"]
            args = {"debt_id": r.choice(debts)}
            if name == "transfer_debt":
                args["to"] = r.choice(people)
            if name == "rule_debt":
                args["decision"] = r.choice(["collect", "reject", "maybe"])
        elif name == "offer":
            args = {"to": r.choice(people), "give": {pick_item(): 1}, "want": {r.choice(items + ["coins"]): 2}}
        elif name in ("accept", "decline"):
            offers = [o["id"] for o in obs["offers_to_you"]] or ["offer0"]
            args = {"offer_id": r.choice(offers)}
        elif name in ("store", "take"):
            args = {"items": {pick_item(): 1}, "coins": r.randint(0, 2)}
        elif name in ("share_chest", "unshare_chest", "hang_out", "propose"):
            args = {"person": r.choice(people)}
        elif name == "answer_proposal":
            props = [p["from"] for p in obs["relations"]["proposals_to_you"]] or people
            args = {"person": r.choice(props), "accept": r.random() < 0.7}
        elif name == "attack":
            args = {"target": r.choice(people + ["nobody"]), "take": r.choice(items + ["coins", "gold", None]),
                    "qty": r.randint(1, 5)}
        elif name in ("buy_land", "sell_land"):
            lots = [x["id"] for x in obs.get("land_for_sale", [])] + list(obs.get("land_owners", {})) + ["lot_99"]
            args = {"lot": r.choice(lots), **({"to": r.choice(people), "price": r.randint(0, 80)}
                                              if name == "sell_land" else {})}
        elif name == "build":
            args = {"kind": r.choice(["garden_bed", "chicken_coop", "cow_pen", "beehive", "fence", "castle"])}
        elif name == "help_stranger":
            args = {"item": pick_item()}
        elif name == "care":
            args = {"person": r.choice(people), "item": r.choice(["honey", "milk", "fish_soup", "bread"])}
        elif name == "dice":
            ch = [c["from"] for c in obs.get("dice_challenges_to_you", [])]
            args = {"person": r.choice(ch or people + ["nobody"]), "stake": r.choice([5, 5, r.randint(-2, 40)])}
        elif name == "hunt":
            args = {"animal": r.choice(list(obs.get("animals_here", {})) + ["hare", "deer", "dragon"])}
        elif name == "steal_from_plot":
            args = {"item": r.choice(["egg", "milk", "honey", "grain", "coins"]), "qty": r.randint(1, 5)}
        elif name == "steal":
            args = {"target": r.choice(people + ["chest"]), "item": r.choice(items + ["coins"]), "qty": 2}
        elif name == "contribute":
            projs = [p["id"] for p in obs["board"]["projects"]] or ["bridge"]
            args = {"project_id": r.choice(projs), "items": {r.choice([pick_item(), "coins", "labor"]): r.randint(1, 3)}}
        elif name in ("build_work", "fund_project"):
            projs = [p["id"] for p in obs["board"]["projects"]] or ["well_9"]
            args = {"project_id": r.choice(projs), **({"coins": r.randint(-2, 50)} if name == "fund_project" else {})}
        elif name == "change_trade":
            args = {"profession": r.choice(["farmer", "fisher", "woodcutter", "miner", "smith", "laborer", "king"])}
        elif name == "treasury_order":
            projs = [p["id"] for p in obs["board"]["projects"]] or ["well_9"]
            args = {"project_id": r.choice(projs), "needs": {r.choice(["wood", "stone", "ore", pick_item()]): r.randint(1, 6)},
                    "reward": r.randint(-1, 40), "days": r.randint(1, 3)}
        elif name == "propose_build":
            args = {"structure": r.choice(["well", "bridge", "watchtower", "wall", "castle"])}
        elif name == "start_building":
            args = {"kind": r.choice(list(obs.get("can_start_building_here", {})) + ["castle", "house"])}
        elif name in ("bring_materials", "construct"):
            ids = [s["id"] for s in obs.get("building_sites", [])] + ["site0"]
            args = {"site_id": r.choice(ids), **({"items": {r.choice(["wood", "stone", pick_item()]): r.randint(1, 5)}}
                                                 if name == "bring_materials" else {})}
        elif name == "embezzle":
            args = {"coins": r.randint(-1, 40)}
        elif name == "post_sale":
            args = {"items": {pick_item(): r.randint(1, 3)}, "price": r.choice([r.randint(1, 30), 0]),
                    "hours": r.choice([24, r.randint(1, 100)])}
        elif name in ("buy_sale", "cancel_listing"):
            ids = [x["id"] for x in obs.get("for_sale", []) + obs.get("your_sales", [])]
            ids += [o["id"] for o in obs["board"]["orders"]] + ["sale0"]
            args = {"sale_id" if name == "buy_sale" else "listing_id": r.choice(ids)}
        elif name == "fulfill_order":
            orders = [o["id"] for o in obs["board"]["orders"]] or ["order0"]
            args = {"order_id": r.choice(orders)}
        elif name == "run_for_mayor":
            args = {"pitch": r.choice(["lower taxes", "bread for all", ""])}
        elif name in ("vote", "report_theft"):
            args = {"candidate" if name == "vote" else "person": r.choice(people + ["Nobody"])}
        elif name == "propose_law":
            args = {"law": r.choice(["tax", "theft_fine", "mayor_salary", "sales_tax", "wealth_tax", "exile", "revoke_place", "payout",
                                     "grant", "bogus"]),
                    "value": r.randint(-5, 70), "person": r.choice(people)}
        elif name == "vote_law":
            props = [p["id"] for p in obs.get("government", {}).get("proposals", [])] or ["law0"]
            args = {"proposal_id": r.choice(props), "vote": r.choice(["yes", "no", "maybe"])}
        if r.random() < 0.05:
            args = {"garbage": [1, 2, 3]}
        return decision(name, args, say="hi" if r.random() < 0.05 else None)


class WorkerBot(Bot):
    def decide(self, obs: dict) -> dict:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv, loc = me["inventory"], me["location"]

        def go(dest: str, why: str) -> dict:
            return decision("move", {"to": dest}, why) if loc != dest else decision("wait", None, why)

        # Tend the garden bed at home: take the ripe grain, sow again
        acts = obs["available_actions"]
        if loc == me["home"] and "collect" in acts:
            return decision("collect", None, "harvest my garden")
        if loc == me["home"] and "plant" in acts and inv.get("grain", 0) >= 1:
            return decision("plant", None, "sow my garden")

        # Cook ahead when at home with ingredients
        if loc == me["home"] and inv.get("bread", 0) + inv.get("fish_soup", 0) < 4:
            if inv.get("grain", 0) >= 2:
                return decision("craft", {"recipe": "bread", "times": min(3, inv["grain"] // 2)}, "bake")
            if inv.get("fish", 0) >= 2:
                return decision("craft", {"recipe": "fish_soup", "times": min(3, inv["fish"] // 2)}, "cook")

        # Survive
        if me["satiety"] < 45:
            food = next((f for f in FOODS if inv.get(f)), None)
            if food:
                return decision("eat", {"item": food}, "hungry")
            if inv.get("grain", 0) >= 2 or inv.get("fish", 0) >= 2:
                return go(me["home"], "go home to cook")
            awake = [p["name"] for p in here["people"] if not p["asleep"]]
            surplus = max((k for k in inv if k not in ("water", "tool")), key=lambda k: inv[k], default=None)
            if awake and surplus and inv[surplus] >= 4 and not obs["your_offers"]:
                who = self.rng.choice(awake)
                food_want = self.rng.choice(["bread", "fish_soup", "fish"])
                n = 1 if food_want != "fish" else 2
                return decision("offer", {"to": who, "give": {surplus: 4}, "want": {food_want: n}},
                                say=f"{who}, I'll give 4 {surplus} for {n} {food_want}.")
            price = obs["board"]["trader_prices"]["bread"]["buy"]
            if me["coins"] >= price:
                return decision("buy", {"item": "bread"}) if loc == "market" else go("market", "buy food")
            goods = [k for k in inv if k in obs["board"]["trader_prices"] and k != "tool"]
            if goods and sum(inv[k] for k in goods) >= 4:
                k = max(goods, key=lambda g: inv[g])
                return decision("sell", {"item": k, "qty": inv[k]}) if loc == "market" else go("market", "sell")
            if here["resources"].get("berries"):
                return decision("work", {"resource": "berries"}, "forage")
            return go("forest", "forage berries")
        if t["hour"] >= t["day_ends_at"] - 2:
            return decision("sleep") if loc == me["home"] else go(me["home"], "go home")

        # Defend the house we stand in; nurse the sick; feed a traveler from a full pocket
        if "defend" in acts and me["health"] >= 40:
            return decision("defend", None, "drive them off")
        if "care" in acts:
            cure = next((c for c in ("honey", "milk", "fish_soup") if inv.get(c)), None)
            sick = [p["name"] for p in here["people"] if p.get("sick")]
            if cure and sick:
                return decision("care", {"person": sick[0], "item": cure}, "nurse the sick")
        if "help_stranger" in acts:
            food = next((f for f in FOODS if inv.get(f, 0) >= 3), None)
            if food:
                return decision("help_stranger", {"item": food}, "feed the traveler")
        foe = next((x for x in obs.get("threats", []) if x.get("strength") and x.get("where")), None)
        if foe and me["health"] >= 60:
            return go(foe["where"], "drive off the " + foe["what"])

        # Help with fires
        if obs["fires"]:
            fire = obs["fires"][0]
            if inv.get("water"):
                return decision("extinguish") if loc == fire["house"] else go(fire["house"], "fight fire")
            return decision("work", {"resource": "water"}) if loc == "river" else go("river", "fetch water")

        # Trades offered to me: accept if I can afford it
        for o in obs["offers_to_you"]:
            if all(inv.get(k, 0) >= v + (1 if k in FOODS else 0) for k, v in o["want"].items() if k != "coins") \
                    and me["coins"] >= o["want"].get("coins", 0):
                return decision("accept", {"offer_id": o["id"]}, say="Deal.")

        # Orders I can fulfill
        for o in obs["board"]["orders"]:
            if all(inv.get(k, 0) >= v for k, v in o["needs"].items()):
                return decision("fulfill_order", {"order_id": o["id"]}) if loc == "square" else go("square", "order")

        # Tax money
        if me["coins"] < t["tax"] and t["next_tax_day"] - t["day"] <= 1:
            sellable = [k for k, v in inv.items() if v > 0 and k in obs["board"]["trader_prices"]]
            if sellable:
                return decision("sell", {"item": sellable[0], "qty": inv[sellable[0]]}) if loc == "market" \
                    else go("market", "sell for tax")

        # Smith crafts tools
        if me["profession"] == "smith" and inv.get("wood", 0) >= 2 and inv.get("ore", 0) >= 1:
            return decision("craft", {"recipe": "tool"}) if loc == "smithy" else go("smithy", "forge")
        if me["profession"] == "smith" and inv.get("tool", 0) >= 2:
            return decision("sell", {"item": "tool"}) if loc == "market" else go("market", "sell tools")

        # Sell surplus (gold is worth the walk sooner)
        will_buy = (obs.get("trader_today") or {}).get("will_buy") or {}  # crafts: the trader buys a limited amount
        surplus = [k for k, v in inv.items() if (v >= 12 or (k == "gold" and v >= 3))
                   and k not in FOODS + ["water", "tool"] and will_buy.get(k, 1) != 0]
        if surplus:
            k = surplus[0]
            qty = inv[k] if k == "gold" else inv[k] - 4
            if will_buy.get(k) is not None:
                qty = min(qty, will_buy[k])
            return decision("sell", {"item": k, "qty": qty}) if loc == "market" else go("market", "sell")

        # Work
        spot = WORK_SPOT.get(me["profession"], "forest")
        if me["profession"] == "smith" and inv.get("wood", 0) >= 2:
            spot = "mine"
        if loc == spot:
            want = "ore" if spot == "mine" and me["profession"] == "smith" else None
            return decision("work", {"hours": 4, **({"resource": want} if want else {})}, "work")
        return go(spot, "go to work")


class ThiefBot(WorkerBot):
    def decide(self, obs: dict) -> dict:
        me, here = obs["you"], obs["here"]
        yard = obs.get("here_plot")
        if yard and yard["ready"] and self.rng.random() < 0.7:
            item = max(yard["ready"], key=lambda k: yard["ready"][k])
            return decision("steal_from_plot", {"item": item, "qty": 4}, f"{yard['owner']}'s yard is full")
        for c in here["chests"]:
            if c["owner"] != me["name"] and not c["locked"] and self.rng.random() < 0.7:
                return decision("steal", {"target": "chest", "item": self.rng.choice(FOODS + ["coins"]), "qty": 3},
                                "nobody is watching")
        for p in here["people"]:
            if p["asleep"]:
                return decision("steal", {"target": p["name"], "item": "coins", "qty": 3}, "they sleep")
        if here["id"] == "mine" and "attack" in obs["available_actions"] and me["health"] >= 50 \
                and self.rng.random() < 0.3:
            p = self.rng.choice(here["people"])
            return decision("attack", {"target": p["name"], "take": "gold", "qty": 3}, "that gold is mine")
        if not here["people"] and here["id"] != me["home"] and self.rng.random() < 0.1:
            homes = [f"home_{v['name']}" for v in obs["board"]["villagers"] if v["name"] != me["name"]]
            return decision("move", {"to": self.rng.choice(homes)}, "let's visit someone's house")
        return super().decide(obs)


class TraderBot(WorkerBot):
    """A WorkerBot that also trades with neighbours at base value, skipping the NPC spread.

    In the evening it walks to the square if it has something to sell or needs food; there
    food producers sell cooked meals, the smith sells tools, woodcutters and miners sell wood
    and ore to the smith, all for coins at the middle of the NPC buy/sell prices.
    LonerBot is the same villager without trading: the baseline for the balance test.
    """

    RESERVE = 3  # cooked meals kept for yourself
    MEALS = ["bread", "fish_soup"]
    TRADES = True
    market_day = 0  # the day this bot last gave up on the evening market

    def _price(self, obs: dict, bundle: dict) -> int:
        prices = obs["board"]["trader_prices"]
        return sum((prices[k]["buy"] + prices[k]["sell"]) // 2 * n for k, n in bundle.items() if k in prices)

    def _wants(self, obs: dict, item: str) -> int:
        """How many of `item` this villager would buy for coins right now."""
        me = obs["you"]
        inv = me["inventory"]
        if item in self.MEALS:
            return max(0, self.RESERVE - sum(inv.get(m, 0) for m in self.MEALS))
        if item == "tool":
            return 0 if inv.get("tool") or me["profession"] == "smith" else 1
        if me["profession"] == "smith":
            return max(0, {"wood": 4, "ore": 2}.get(item, 0) - inv.get(item, 0))
        return 0

    def _for_sale(self, obs: dict) -> dict:
        me = obs["you"]
        inv, prof = me["inventory"], me["profession"]
        sale: dict = {}
        if sum(inv.get(m, 0) for m in self.MEALS) > self.RESERVE:
            sale.update({m: inv[m] for m in self.MEALS if inv.get(m)})
        keep = max([1] + [o["needs"].get("tool", 0) for o in obs["board"]["orders"]])  # tools for an order
        if prof == "smith" and inv.get("tool", 0) > keep:
            sale["tool"] = inv["tool"] - keep
        if prof in ("woodcutter", "miner"):
            sale.update({k: inv[k] for k in ("wood", "ore") if inv.get(k)})
        return sale

    @staticmethod
    def _guess_demand(item: str, profession: str) -> int:
        if item in TraderBot.MEALS:
            return 0 if profession in ("farmer", "fisher") else 2
        if item == "tool":
            return 0 if profession == "smith" else 1
        if item in ("wood", "ore"):
            return {"wood": 4, "ore": 2}[item] if profession == "smith" else 0
        return 0

    def decide(self, obs: dict) -> dict:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv, loc = me["inventory"], me["location"]
        tax_reserve = t["tax"] if t["next_tax_day"] - t["day"] <= 2 else 0

        for o in obs["offers_to_you"]:
            price = o["want"].get("coins", 0)
            good = (self.TRADES and set(o["want"]) == {"coins"} and len(o["give"]) == 1
                    and all(0 < self._wants(obs, k) >= n - 1 for k, n in o["give"].items())
                    and me["coins"] - price >= tax_reserve and price <= self._price(obs, o["give"]))
            return decision("accept" if good else "decline", {"offer_id": o["id"]}, "trade")

        others = [v for v in obs["board"]["villagers"] if v["name"] != me["name"] and v["status"] == "active"]
        evening = t["day_ends_at"] - 5 <= t["hour"] < t["day_ends_at"] - 2
        sale = self._for_sale(obs)
        buying = self._wants(obs, "bread") >= 1 and me["coins"] - tax_reserve >= 6
        # Raw wood and ore are sold to the smith only in passing; meals and tools are worth the walk.
        worth_walk = any(k in self.MEALS or k == "tool" for k in sale) or buying
        market = self.TRADES and others and evening and worth_walk and self.market_day != t["day"]
        if not market or me["satiety"] < 45 or obs["fires"]:
            # Food producers cook everything they carry, so there is food to sell in the evening.
            if loc == me["home"] and me["profession"] in ("farmer", "fisher"):
                for recipe, raw in (("bread", "grain"), ("fish_soup", "fish")):
                    if inv.get(raw, 0) >= 2:
                        return decision("craft", {"recipe": recipe, "times": min(10, inv[raw] // 2)}, "cook")
            return self._tweak(obs, super().decide(obs), tax_reserve)

        if loc != "square":
            return decision("move", {"to": "square"}, "evening market")
        awake = {p["name"] for p in here["people"] if not p["asleep"]}
        asked = {o["to"] for o in obs["your_offers"]}
        for item, qty in sale.items():
            for v in others:
                n = min(qty, self._guess_demand(item, v["profession"]))
                if v["name"] in awake and v["name"] not in asked and n:
                    bundle = {item: n}
                    price = self._price(obs, bundle)
                    return decision("offer", {"to": v["name"], "give": bundle, "want": {"coins": price}},
                                    say=f"{v['name']}, {n} {item} for {price} coins?")
        if asked or (buying and any(v["profession"] in ("farmer", "fisher") for v in others if v["name"] in awake)):
            return decision("wait", None, "evening market")
        self.market_day = t["day"]  # nothing to do here today
        return self._tweak(obs, super().decide(obs), tax_reserve)

    def _tweak(self, obs: dict, d: dict, tax_reserve: int) -> dict:
        """Small fixes to WorkerBot choices: miners dig ore, meals are bought for several days."""
        act, me = d["action"], obs["you"]
        if act["name"] == "work" and me["profession"] == "miner":
            res = obs["here"]["resources"]
            if res.get("gold"):
                act["args"]["resource"] = "gold"  # the mine's prize, while it lasts
            elif res.get("ore"):
                act["args"]["resource"] = "ore"  # ore is worth more than stone
        if act["name"] == "buy" and act["args"].get("item") in self.MEALS:
            price = obs["board"]["trader_prices"][act["args"]["item"]]["buy"]
            need = max(1, self._wants(obs, act["args"]["item"]))
            act["args"]["qty"] = max(1, min(need, (me["coins"] - tax_reserve) // price))
        return d


class LonerBot(TraderBot):
    """The same villager, but it never trades with people, only with the NPC market."""

    TRADES = False


class HomesteadBot(TraderBot):
    """A TraderBot that builds up its own plot in the evening: collects, sows, feeds animals,
    builds (coop and beds for farmers, hives otherwise), buys land when the yard is full
    (expand_plot, else the cheapest empty lot on the map)."""

    PLOT_FOODS = ["egg", "milk", "honey"]
    wood_trip = False
    land_trip: str | None = None  # an empty lot it is walking to buy
    COSTS = {"chicken_coop": (15, 4, 2), "garden_bed": (0, 1, 1), "beehive": (10, 2, 1), "fence": (0, 6, 0)}

    def decide(self, obs: dict) -> dict:
        me, t, plot = obs["you"], obs["time"], obs.get("plot")
        inv = me["inventory"]
        if me["satiety"] < 45:
            food = next((f for f in self.PLOT_FOODS if inv.get(f)), None)
            if food:
                return decision("eat", {"item": food}, "eat from my yard")
        lot = self.land_trip
        if lot and not obs["fires"] and me["satiety"] >= 45:
            if lot not in {x["id"] for x in obs.get("land_for_sale", [])}:
                self.land_trip = None  # someone else was faster
            elif me["location"] == lot:
                self.land_trip = None
                return decision("buy_land", None, "a lot of my own")
            else:
                return decision("move", {"to": lot}, "go buy that empty lot")
        if plot and self.wood_trip and not obs["fires"] and me["satiety"] >= 45:
            if me["location"] == "forest":
                self.wood_trip = False
                return decision("work", {"resource": "wood", "hours": 2}, "wood for my yard")
            return decision("move", {"to": "forest"}, "fetch wood for my yard")
        chores = t["hour"] < 9 or t["hour"] >= t["day_ends_at"] - 3
        if not plot or me["location"] != plot["home"] or obs["fires"] or not chores:
            return super().decide(obs)
        acts = set(obs["available_actions"])
        reserve = t["tax"] + 5
        if "collect" in acts:
            return decision("collect", None, "collect the yard")
        if "plant" in acts and inv.get("grain", 0) >= 1:
            return decision("plant", None, "sow my garden bed")
        animals = sum(1 for b in plot["buildings"] if b["kind"] in ("chicken_coop", "cow_pen"))
        chest = me["your_chest"]["items"].get("grain", 0)
        if animals and chest < 2 * animals and inv.get("grain", 0) > 1:
            return decision("store", {"items": {"grain": min(inv["grain"] - 1, 2 * animals - chest)}}, "feed")
        have = Counter(b["kind"] for b in plot["buildings"])
        plan = ([("chicken_coop", 1), ("garden_bed", 3)] if me["profession"] == "farmer"
                else [("beehive", 2), ("garden_bed", 1)]) + [("fence", 1)]
        for kind, limit in plan:
            coins, wood, cells = self.COSTS[kind]
            if have[kind] >= limit or me["coins"] - coins < reserve or plot["free_cells"] < cells:
                continue
            if inv.get("wood", 0) >= wood:
                return decision("build", {"kind": kind}, f"build a {kind}")
            self.wood_trip = True
            break
        sale = sorted(obs.get("land_for_sale", []), key=lambda x: x["price"])
        if plot["free_cells"] == 0 and sale and me["coins"] - sale[0]["price"] >= 3 * reserve:
            self.land_trip = sale[0]["id"]  # a whole lot is cheaper per cell than expanding the yard
        elif plot["free_cells"] == 0 and plot["expand_price"] and me["coins"] - plot["expand_price"] >= 3 * reserve:
            return decision("expand_plot", None, "more land")
        return super().decide(obs)



class HunterBot(WorkerBot):
    """Hunts in the daytime (animals.py): joins any hunt party here, starts one for big game when enough
    people are awake here, else takes small game; eats meat first. Otherwise a WorkerBot."""

    GROUND = "forest"
    KEEP_MEAT = 6

    def decide(self, obs: dict) -> dict:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv = me["inventory"]
        if me["satiety"] < 45 and inv.get("meat"):
            return decision("eat", {"item": "meat"}, "eat meat")
        day = 8 <= t["hour"] < t["day_ends_at"] - 3
        if not day or me["health"] < 30 or me["satiety"] < 20 or ("hunt" not in obs["available_actions"] \
                                                                   and me["location"] == self.GROUND):
            return super().decide(obs)
        herd, parties = obs.get("animals_here", {}), obs.get("hunt_parties_here", [])
        for p in parties:
            if me["name"] not in p["hunters"] and herd.get(p["animal"]):
                return decision("hunt", {"animal": p["animal"]}, "join the hunt")
        if any(me["name"] in p["hunters"] for p in parties):
            return decision("wait", None, "wait for the others")
        awake = 1 + sum(1 for p in here["people"] if not p["asleep"])
        big = [k for k, v in herd.items() if 1 < v["hunters_needed"] <= awake]
        if big:
            return decision("hunt", {"animal": big[0]}, "big game, enough of us here")
        if inv.get("meat", 0) >= self.KEEP_MEAT:
            return super().decide(obs)
        small = [k for k, v in herd.items() if v["hunters_needed"] <= 1]
        if small:
            return decision("hunt", {"animal": small[0]}, "small game")
        if me["location"] != self.GROUND:
            return decision("move", {"to": self.GROUND}, "go hunting")
        return super().decide(obs)


BOT_TYPES = {"random": RandomBot, "worker": WorkerBot, "thief": ThiefBot, "trader": TraderBot, "loner": LonerBot,
             "homestead": HomesteadBot, "hunter": HunterBot}

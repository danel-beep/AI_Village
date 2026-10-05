"""Scripted agents. They see exactly what an LLM agent sees (the observation dict)
and answer with the same decision format, so they exercise the real interface for free.

- RandomBot: fuzzer. Random actions with random (often invalid) arguments.
- WorkerBot: honest villager. Eats, works, crafts, sells, fights fires, fulfills orders.
- ThiefBot: a WorkerBot that steals whenever it sees a chance.
"""

from __future__ import annotations

import random

WORK_SPOT = {"farmer": "field", "fisher": "river", "woodcutter": "forest", "miner": "mine", "smith": "forest"}
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
        elif name == "offer":
            args = {"to": r.choice(people), "give": {pick_item(): 1}, "want": {r.choice(items + ["coins"]): 2}}
        elif name in ("accept", "decline"):
            offers = [o["id"] for o in obs["offers_to_you"]] or ["offer0"]
            args = {"offer_id": r.choice(offers)}
        elif name in ("store", "take"):
            args = {"items": {pick_item(): 1}, "coins": r.randint(0, 2)}
        elif name in ("share_chest", "unshare_chest"):
            args = {"person": r.choice(people)}
        elif name == "steal":
            args = {"target": r.choice(people + ["chest"]), "item": r.choice(items + ["coins"]), "qty": 2}
        elif name == "contribute":
            args = {"project_id": "bridge", "items": {pick_item(): r.randint(1, 3)}}
        elif name == "fulfill_order":
            orders = [o["id"] for o in obs["board"]["orders"]] or ["order0"]
            args = {"order_id": r.choice(orders)}
        if r.random() < 0.05:
            args = {"garbage": [1, 2, 3]}
        return decision(name, args, thought="random", say="hi" if r.random() < 0.05 else None)


class WorkerBot(Bot):
    def decide(self, obs: dict) -> dict:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv, loc = me["inventory"], me["location"]

        def go(dest: str, why: str) -> dict:
            return decision("move", {"to": dest}, why) if loc != dest else decision("wait", None, why)

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

        # Sell surplus
        surplus = [k for k, v in inv.items() if v >= 12 and k not in FOODS + ["water", "tool"]]
        if surplus:
            k = surplus[0]
            return decision("sell", {"item": k, "qty": inv[k] - 4}) if loc == "market" else go("market", "sell")

        # Work
        spot = WORK_SPOT[me["profession"]]
        if me["profession"] == "smith" and inv.get("wood", 0) >= 2:
            spot = "mine"
        if loc == spot:
            want = "ore" if spot == "mine" and me["profession"] == "smith" else None
            return decision("work", {"hours": 4, **({"resource": want} if want else {})}, "work")
        return go(spot, "go to work")


class ThiefBot(WorkerBot):
    def decide(self, obs: dict) -> dict:
        me, here = obs["you"], obs["here"]
        for c in here["chests"]:
            if c["owner"] != me["name"] and not c["locked"] and self.rng.random() < 0.7:
                return decision("steal", {"target": "chest", "item": self.rng.choice(FOODS + ["coins"]), "qty": 3},
                                "nobody is watching")
        for p in here["people"]:
            if p["asleep"]:
                return decision("steal", {"target": p["name"], "item": "coins", "qty": 3}, "they sleep")
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
        if prof == "smith" and inv.get("tool", 0) > 1:
            sale["tool"] = inv["tool"] - 1
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
        if act["name"] == "work" and me["profession"] == "miner" and obs["here"]["resources"].get("ore"):
            act["args"]["resource"] = "ore"  # ore is worth more than stone
        if act["name"] == "buy" and act["args"].get("item") in self.MEALS:
            price = obs["board"]["trader_prices"][act["args"]["item"]]["buy"]
            need = max(1, self._wants(obs, act["args"]["item"]))
            act["args"]["qty"] = max(1, min(need, (me["coins"] - tax_reserve) // price))
        return d


class LonerBot(TraderBot):
    """The same villager, but it never trades with people, only with the NPC market."""

    TRADES = False


BOT_TYPES = {"random": RandomBot, "worker": WorkerBot, "thief": ThiefBot, "trader": TraderBot, "loner": LonerBot}

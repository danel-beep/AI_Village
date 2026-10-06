"""Scripted agents. They see exactly what an LLM agent sees (the observation dict)
and answer with the same decision format, so they exercise the real interface for free.

- RandomBot: fuzzer. Random actions with random (often invalid) arguments.
- WorkerBot: honest villager. Eats, works, crafts, sells, fights fires, fulfills orders.
- ThiefBot: a WorkerBot that steals whenever it sees a chance (people, chests, yards) and sometimes
  robs people at the mine by force.
- HomesteadBot: a TraderBot that builds up its own plot in the evening (plots.py).
- BuilderBot: a villager of the «С нуля» mode: feeds itself, hunts, builds what the next village stage needs.
"""

from __future__ import annotations

from collections import Counter

import random

# Farmers work their own garden beds at home (there is no common field) and gather wood the rest of the day.
WORK_SPOT = {"farmer": "forest", "fisher": "river", "woodcutter": "forest", "miner": "mine", "smith": "forest"}
FOODS = ["fish_soup", "bread", "fish", "berries"]


def batches(obs: dict, recipe: str, default: dict) -> int:
    """How many times the villager can make `recipe` from what it carries (inputs from the recipe table
    when the observation has it, else `default`), e.g. bread needs wood too in the crafts mode."""
    inv = obs["you"]["inventory"]
    need = ((obs["board"].get("recipes") or {}).get(recipe) or {}).get("inputs") or default
    return min(inv.get(k, 0) // n for k, n in need.items())


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
        elif name == "host_feast":
            args = {"items": {pick_item(): r.randint(1, 4)}}
        elif name == "teach":
            args = {"person": r.choice(people), "recipe": r.choice((obs.get("recipes_you_know")
                                                                    or ["iron"]) + ["cake"]),
                    **({"price": {r.choice(items[:3] + ["coins"]): r.randint(1, 3)}} if r.random() < 0.5 else {})}
        elif name == "learn":
            lessons = obs.get("lessons_offered") or [{"teacher": "nobody", "recipe": "cake"}]
            les = r.choice(lessons)
            args = {"teacher": les["teacher"], "recipe": les["recipe"]}
        elif name in ("catch_animal", "buy_animal"):  # transport.py
            args = {"animal": r.choice(["horse", "donkey", "unicorn"])}
        elif name in ("take_animal", "feed_animal"):
            t = obs.get("transport") or {}
            ids = [x["id"] for x in t.get("animals_here", []) + t.get("your_animals", [])] + ["horse0"]
            args = {"animal": r.choice(ids)}
            if name == "feed_animal":
                args.update(item=r.choice(["hay", "grain", "stone"]), qty=r.randint(1, 3))
        elif name in ("lend_animal", "give_animal"):
            args = {"to": r.choice(people + ["nobody"])}
            if name == "lend_animal":
                args["days"] = r.randint(1, 3)
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
        elif name == "praise":
            args = {"person": r.choice(people + ["nobody"]), "text": r.choice(["helped with the roof", "fair trade", ""])}
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
        elif name in ("buy_land", "sell_land", "give_land"):
            lots = [x["id"] for x in obs.get("land_for_sale", []) + obs.get("land_free", [])] \
                + list(obs.get("land_owners", {})) + ["lot_99"]
            args = {"lot": r.choice(lots), **({"to": r.choice(people), "price": r.randint(0, 80)}
                                              if name == "sell_land" else {}),
                    **({"to": r.choice(people)} if name == "give_land" else {})}
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
        elif name == "offer_job":
            args = {"to": r.choice(people + ["nobody"]), "task": r.choice(["wood", "stone", "build", "guard", "dance"]),
                    "hours": r.randint(1, 4), "wage": {r.choice(["coins", pick_item()]): r.randint(1, 4)},
                    "pay": r.choice(["before", "after"])}
        elif name in ("accept_job", "decline_job", "end_job", "pay_job"):
            ids = [j["id"] for j in obs.get("jobs_offered_to_you", []) + obs.get("job_board", [])] or ["job0"]
            args = {"job_id": r.choice(ids)}
        elif name == "hire_npc":
            args = {"kind": r.choice(["worker", "guard"]), "resource": r.choice(["wood", "fish", "air"]),
                    "hours": r.randint(1, 3), "days": r.randint(1, 2)}
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
        elif name in ("join_polity", "give_to_polity"):
            ids = [x["id"] for x in obs.get("polities", [])] + ["polity0"]
            args = {"polity": r.choice(ids)} | ({"coins": r.randint(1, 10)} if name == "give_to_polity" else {})
        elif name == "polity_vote":
            args = {"topic": r.choice(["name", "coin", "form", "leader", "bogus"]),
                    "choice": r.choice(people + ["assembly", "council", "ruler", "Dale", ""])}
        elif name == "polity_propose":
            args = {"law": r.choice(["tax", "fine", "grant", "payout", "expel", "bogus"]),
                    "value": r.randint(-5, 60), "person": r.choice(people)}
        elif name == "polity_vote_law":
            props = [pr["id"] for x in obs.get("polities", []) for pr in x.get("proposals", [])] or ["plaw0"]
            args = {"proposal_id": r.choice(props), "vote": r.choice(["yes", "no", "maybe"])}
        elif name == "polity_embezzle":
            args = {"coins": r.randint(-2, 20)}
        elif name == "sign_petition":
            args = {"form": r.choice(["assembly", "council", "ruler", "anarchy"])}
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

        # Crafting chains on (crafting.py): grind flour for bread, bake it at home, make a stone tool for the trade
        recipes = obs["board"].get("recipes") or {}  # the LLM stub sees no recipe table
        if "stone_pick" in recipes:
            if "flour" in recipes["bread"]["inputs"] and inv.get("grain", 0) >= 3 and inv.get("flour", 0) < 2:
                return decision("craft", {"recipe": "flour", "times": min(3, (inv["grain"] - 1) // 2)}, "grind")
            if loc == me["home"] and inv.get("flour", 0) and inv.get("wood", 0) and inv.get("bread", 0) < 4:
                return decision("craft", {"recipe": "bread", "times": min(inv["flour"], inv["wood"], 3)}, "bake")
            kit = {"miner": "stone_pick", "woodcutter": "stone_axe"}.get(me["profession"])
            if kit and not inv.get(kit) and not inv.get("tool") \
                    and all(inv.get(k, 0) >= n for k, n in recipes[kit]["inputs"].items()):
                return decision("craft", {"recipe": kit}, "make a tool")

        # Cook ahead when at home with ingredients
        if loc == me["home"] and inv.get("bread", 0) + inv.get("fish_soup", 0) < 4:
            if (n := batches(obs, "bread", {"grain": 2})) and "flour" not in recipes.get("bread", {}).get("inputs", {}):
                return decision("craft", {"recipe": "bread", "times": min(3, n)}, "bake")
            if n := batches(obs, "fish_soup", {"fish": 2}):
                return decision("craft", {"recipe": "fish_soup", "times": min(3, n)}, "cook")

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
            price = obs["board"]["trader_prices"].get("bread", {}).get("buy")  # no trader yet: {} (progress.py)
            if price is not None and me["coins"] >= price:
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
        if me["coins"] < t.get("tax", 0) and t.get("next_tax_day", 0) - t["day"] <= 1:
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

        # Work (the crafts mode allows only so many hours of gathering a day)
        if (obs.get("work_today") or {}).get("hours_left") == 0:
            return decision("wait", None, "done working today") if loc == me["home"] else go(me["home"], "home")
        if me["profession"] == "smith" and "work_today" in obs:  # crafts: a smith gathers nothing, buys ore and wood
            return decision("wait", None, "wait for ore and wood") if loc == "smithy" else go("smithy", "to the forge")
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
        acts = obs["available_actions"]
        if "claim_land" in acts:  # theft.py / land.py «first come»: an empty or unbuilt lot, nobody to stop me
            return decision("claim_land", None, "nobody is using this land")
        halls = {p["town_hall_at"] for p in obs.get("polities", []) if p.get("treasury")}
        gov = obs.get("government") or {}
        if here["id"] in halls or (here["id"] == "square" and not halls and gov.get("treasury")):
            if self.rng.random() < 0.3:
                return decision("steal", {"target": "treasury", "item": "coins", "qty": 3}, "the treasury is right here")
        if obs["time"].get("dark") is False and self.rng.random() < 0.4:
            return super().decide(obs)  # too light to steal now
        yard = obs.get("here_plot")
        if yard and yard["ready"] and self.rng.random() < 0.7:
            item = max(yard["ready"], key=lambda k: yard["ready"][k])
            return decision("steal_from_plot", {"item": item, "qty": 4}, f"{yard['owner']}'s yard is full")
        for c in here["chests"]:
            if c["owner"] != me["name"] and not c["locked"] and self.rng.random() < 0.7:
                seen = dict(c.get("food") or {}, **({"coins": c["coins"]} if c.get("coins") else {}))
                item = max(seen, key=seen.get) if seen else self.rng.choice(FOODS + ["coins"])
                return decision("steal", {"target": "chest", "item": item, "qty": 3}, "nobody is watching")
        for p in here["people"]:
            if p["asleep"]:
                return decision("steal", {"target": p["name"], "item": "coins", "qty": 3}, "they sleep")
        if here["id"] == "mine" and "attack" in obs["available_actions"] and me["health"] >= 50 \
                and self.rng.random() < 0.3:
            p = self.rng.choice(here["people"])
            return decision("attack", {"target": p["name"], "take": "gold", "qty": 3}, "that gold is mine")
        if not here["people"] and here["id"] != me["home"] and self.rng.random() < 0.1:
            homes = [f"home_{v['name']}" for v in obs["board"]["villagers"] if v["name"] != me["name"]]
            homes += [x["id"] for x in obs.get("land_free", [])]
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
        tax_reserve = t.get("tax", 0) if t.get("next_tax_day", 0) - t["day"] <= 2 else 0

        for o in obs["offers_to_you"]:
            price = o["want"].get("coins", 0)
            good = (self.TRADES and set(o["want"]) == {"coins"} and len(o["give"]) == 1
                    and all(0 < self._wants(obs, k) >= n - 1 for k, n in o["give"].items())
                    and me["coins"] - price >= tax_reserve and price <= self._price(obs, o["give"]))
            return decision("accept" if good else "decline", {"offer_id": o["id"]}, "trade")

        if self.TRADES and "work_today" in obs and (d := self._board(obs, tax_reserve)):
            return d
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
                    if n := batches(obs, recipe, {raw: 2}):
                        return decision("craft", {"recipe": recipe, "times": min(10, n)}, "cook")
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

    # Food points of what the board may offer, and what each trade lists there in the crafts mode.
    BOARD_FOOD = {"berries": 10, "fish": 15, "bread": 40, "fish_soup": 45, "stew": 75, "meat": 25}
    BOARD_GOODS = {"farmer": ["bread", "berries", "grain"], "fisher": ["fish_soup", "fish"], "woodcutter": ["wood"],
                   "miner": ["ore", "stone"], "smith": ["tool"]}
    BOARD_KEEP = 6  # units of a good the seller keeps for itself

    def _board(self, obs: dict, tax_reserve: int) -> dict | None:
        """The crafts mode (labor on): only the trade gathers its goods, so food and materials change hands on
        the market board, from anywhere. Sellers list their surplus at the middle of the trader's prices; a
        hungry villager with nothing to eat buys the cheapest food, the smith buys ore and wood for tools."""
        me, acts = obs["you"], obs["available_actions"]
        inv, budget = me["inventory"], me["coins"] - tax_reserve
        listings = obs.get("for_sale") or []
        if "buy_sale" in acts and me["satiety"] < 60 and not any(inv.get(f) for f in FOODS):
            food = [(s["price"] / pts, s["id"]) for s in listings
                    if (pts := sum(self.BOARD_FOOD.get(k, 0) * n for k, n in s["items"].items()))
                    and s["price"] <= budget]
            if food:
                return decision("buy_sale", {"sale_id": min(food)[1]}, "food from the board")
        if "buy_sale" in acts and self._wants(obs, "tool"):
            tools = [(s["price"], s["id"]) for s in listings if s["items"] == {"tool": 1} and s["price"] <= budget]
            if tools:
                return decision("buy_sale", {"sale_id": min(tools)[1]}, "a new tool")
        cook = {"farmer": ("grain", "bread"), "fisher": ("fish", "fish_soup")}.get(me["profession"])
        if "buy_sale" in acts and cook and inv.get(cook[0], 0) >= 4 and not inv.get("wood"):
            wood = [(s["price"], s["id"]) for s in listings if set(s["items"]) == {"wood"}
                    and s["price"] <= min(budget, self._price(obs, s["items"]))]
            if wood:  # bread and soup are cooked on firewood (crafts mode)
                return decision("buy_sale", {"sale_id": min(wood)[1]}, f"firewood for {cook[1]}")
        if "buy_sale" in acts and me["profession"] == "smith":
            for s in listings:
                if set(s["items"]) <= {"wood", "ore"} and all(self._wants(obs, k) for k in s["items"]) \
                        and s["price"] <= min(budget, self._price(obs, s["items"])):
                    return decision("buy_sale", {"sale_id": s["id"]}, "materials for tools")
        if "post_sale" in acts:
            listed = {k for s in obs.get("your_sales") or [] for k in s["items"]}
            for k in self.BOARD_GOODS.get(me["profession"], []):
                extra = inv.get(k, 0) - {"tool": 1, "ore": 0}.get(k, self.BOARD_KEEP)  # ore is the smith's
                if (extra >= 3 or (k == "tool" and extra >= 1)) and k not in listed and len(listed) < 3:
                    lot = {k: 1 if k == "tool" else min(extra, 6)}
                    return decision("post_sale", {"items": lot, "price": max(1, self._price(obs, lot))},
                                    "sell my surplus on the board")
        return None

    def _tweak(self, obs: dict, d: dict, tax_reserve: int) -> dict:
        """Small fixes to WorkerBot choices: miners dig ore, meals are bought for several days."""
        act, me = d["action"], obs["you"]
        if act["name"] == "work" and me["profession"] == "miner":
            res = obs["here"]["resources"]
            will_buy = ((obs.get("trader_today") or {}).get("will_buy") or {}).get("gold")
            if res.get("gold") and (will_buy is None or me["inventory"].get("gold", 0) < max(2, will_buy)):
                act["args"]["resource"] = "gold"  # the mine's prize, while it lasts (no more than the trader takes)
            elif res.get("ore"):
                act["args"]["resource"] = "ore"  # ore is worth more than stone
        if act["name"] == "buy" and act["args"].get("item") in self.MEALS \
                and act["args"]["item"] in obs["board"]["trader_prices"]:
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
            free = {x["id"] for x in obs.get("land_free", [])}
            if lot not in {x["id"] for x in obs.get("land_for_sale", [])} | free:
                self.land_trip = None  # someone else was faster
            elif me["location"] == lot:
                self.land_trip = None
                return decision("claim_land" if lot in free else "buy_land", None, "a lot of my own")
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
        reserve = t.get("tax", 0) + 5
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
        sale = sorted(obs.get("land_for_sale", []) + [dict(x, price=0) for x in obs.get("land_free", [])],
                      key=lambda x: x["price"])
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
        crafts = obs.get("crafts_here", {})
        if "bow" in crafts and inv.get("plank") and inv.get("hide") and not inv.get("bow"):
            return decision("craft", {"recipe": "bow"}, "make a bow")
        if "bow" in obs["board"]["recipes"] and not obs.get("your_gear", {}).get("weapon") \
                and inv.get("wood", 0) >= 3 and me["location"] == me["home"]:
            return decision("craft", {"recipe": "club"}, "make a club")
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


class BuilderBot(WorkerBot):
    """A villager of the «С нуля» mode (construction on), who starts with nothing: feeds itself (small game,
    any hunt party here, fish cooked into soup at home, berries), makes stone tools, raises its own house
    and helps with what the village's next stage needs. Big builds are worked together from TEAM_HOUR, so
    the people they need meet on the site. Keeps wood for its hearth (warmth.py, when that is on) and sells
    hides for the tax. Without construction it is a WorkerBot."""

    FOOD = {"fish_soup": 45, "bread": 40, "smoked_meat": 35, "meat": 40, "honey": 25, "milk": 20, "fish": 15,
            "berries": 10, "egg": 10}
    TEAM_HOUR = 13             # from this hour the village's team site is worked together
    SPOT = {"wood": "forest", "stone": "mine", "ore": "mine", "fish": "river", "berries": "forest"}
    TOOL = {"wood": "stone_axe", "stone": "stone_pick", "ore": "stone_pick", "clay": "stone_pick"}
    YARD_RANK = {"workbench": 0, "smithy": 1, "kiln": 2}  # which villager (by name) raises a yard workshop
    VILLAGE_AT = {"market_square": "square", "town_hall": "square", "tavern": "square", "palisade": "square"}
    STOCK = {"wood": 6, "stone": 4}  # carried ahead when no site needs anything

    def __init__(self, name: str, seed: int = 0):
        super().__init__(name, seed)
        self.seen: dict[str, dict] = {}   # place -> resources last seen there
        self.game: dict[str, dict] = {}   # place -> small game last seen there
        self.big: dict[str, dict] = {}    # place -> big game last seen there
        self.places: set[str] = {"forest", "river", "mine", "square"}  # every place a road was seen to
        self.shared: set[str] = set()     # who got meat from my last big catch
        self.failed: set[tuple] = set()   # (day, action) that failed today
        self.seen_day: dict[str, int] = {}
        self.game_ever: set[str] = set()
        self.res_ever: dict[str, set] = {}
        self.foraging = False             # on a food trip until the stock is well above the need
        self.home_fire = 0                # wood in my hearth when I last saw it (warmth.py)
        self.clay_given: tuple = ((), 0)  # (brick sites, clay handed to the kiln's owner for them)
        self.last: dict | None = None

    # ---------- helpers ----------

    def _food_left(self, inv: dict) -> int:
        return sum(self.FOOD.get(k, 0) * n for k, n in inv.items())

    def _best_food(self, inv: dict, satiety: int) -> str | None:
        have = [k for k in self.FOOD if inv.get(k)]
        fits = [k for k in have if self.FOOD[k] <= 100 - satiety]
        return max(fits, key=self.FOOD.get) if fits else min(have, key=self.FOOD.get, default=None)

    def _place_of(self, res: str) -> str:
        known = [p for p, r in self.seen.items() if r.get(res)]
        default = self.SPOT.get(res, "forest")
        if default in known or not known:
            return default
        return max(known, key=lambda p: self.seen[p][res])

    def _firewood(self, obs: dict) -> int:
        """Wood kept back for my hearth tonight (warmth.py): two nights' worth, less what it holds."""
        burn = (obs.get("warmth") or {}).get("wood_a_fire_burns_tonight", 0)
        has_house = (obs.get("plot") or {}).get("house_level", 0) >= 1
        return max(0, 2 * burn - self.home_fire) if has_house else 0

    def decide(self, obs: dict) -> dict:
        if "building_sites" not in obs:
            return super().decide(obs)
        if obs.get("last_error") and self.last:  # what just failed is not tried again today
            self.failed.add((obs["time"]["day"], repr(self.last)))
        d = self._decide(obs)
        if (obs["time"]["day"], repr(d["action"])) in self.failed:
            d = decision("wait", None, "that did not work")
        self.last = d["action"]
        return d

    def _decide(self, obs: dict) -> dict:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv, loc, acts = me["inventory"], me["location"], set(obs["available_actions"])
        hour, end = t["hour"], t["day_ends_at"]
        self.seen[loc] = dict(here["resources"])
        herd = obs.get("animals_here") or {}
        self.game[loc] = {k: v["count"] for k, v in herd.items() if v["hunters_needed"] <= 1}
        self.big[loc] = {k: v["count"] for k, v in herd.items() if v["hunters_needed"] > 1 and v["count"]}
        self.places.update(p for p in here["roads_to"] if not p.startswith(("home_", "lot_")))
        self.seen_day[loc] = t["day"]
        if self.game[loc]:
            self.game_ever.add(loc)
        self.res_ever.setdefault(loc, set()).update(k for k, v in here["resources"].items() if v)

        def go(dest: str, why: str) -> dict:
            return decision("move", {"to": dest}, why) if loc != dest else decision("wait", None, why)

        if obs["fires"] or "defend" in acts:
            return super().decide(obs)
        for o in obs["offers_to_you"]:
            return decision("decline", {"offer_id": o["id"]}, "no thanks")
        if me["satiety"] < 55 and (food := self._best_food(inv, me["satiety"])):
            return decision("eat", {"item": food}, "hungry")
        if loc == me["home"] and inv.get("fish", 0) >= 2 and inv.get("wood", 0) >= 1:
            return decision("craft", {"recipe": "fish_soup", "times": min(5, inv["fish"] // 2, inv["wood"])}, "cook")
        warm = obs.get("warmth") or {}
        burn = warm.get("wood_a_fire_burns_tonight", 0)
        if warm and loc == me["home"]:
            self.home_fire = warm["here"].get("fire_wood", 0)
            if hour >= end - 4 and burn and warm["here"].get("fireplace") and self.home_fire < 2 * burn \
                    and inv.get("wood"):
                return decision("stoke", {"wood": min(inv["wood"], 2 * burn - self.home_fire)}, "wood for tonight")
        if hour >= end - 2 and loc == me["home"]:
            return decision("sleep", None, "night")
        if hour >= end - 3:
            return go(me["home"], "home for the night")
        # Camp start (settle.py): take a house site at the first place I work at (the camp itself from day 2).
        sites = obs.get("house_sites")
        if sites and sites["yours"] is None and sites["free_here"] and "settle" in acts \
                and (loc != "square" or t["day"] >= 2):
            return decision("settle", None, "I will live here")
        # Tax day: sell hides and other spare goods to the trader for the coins.
        if t.get("tax", 0) > me["coins"] and t.get("next_tax_day", 0) - t["day"] <= 1 \
                and "sell" not in (obs.get("locked_actions") or []):
            spare = [k for k in ("hide", "meat", "stone", "wood", "ore") if inv.get(k, 0) > (4 if k != "hide" else 0)]
            if spare:
                k = spare[0]
                return decision("sell", {"item": k, "qty": inv[k] - (4 if k != "hide" else 0)}, "coins for the tax") \
                    if loc == "market" else go("market", "sell for the tax")

        # Materials I carry for a site where I stand go in first (a quarter hour).
        firewood = self._firewood(obs)
        for s in obs["building_sites"]:
            give = {k: min(n, inv.get(k, 0) - (firewood if k == "wood" else 0)) for k, n in s["still_needs"].items()}
            give = {k: n for k, n in give.items() if n > 0}
            if s["at"] == loc and give and (s["for"] in (me["name"], "the village") or s["people_needed_on_the_same_day"] > 1):
                return decision("bring_materials", {"site_id": s["id"], "items": give}, "materials for the site")

        # A big catch is shared with the people here (the hunters), two portions each.
        awake_here = [p["name"] for p in here["people"] if not p["asleep"] and p["name"] not in self.shared]
        if inv.get("meat", 0) >= 6 and awake_here:
            self.shared.add(awake_here[0])
            return decision("give", {"to": awake_here[0], "items": {"meat": 2}}, "share the catch")
        if inv.get("meat", 0) < 4:
            self.shared.clear()

        # A hunt for big game here: join it (the killing blow takes the meat), or wait for it to run.
        parties = obs.get("hunt_parties_here") or []
        if any(me["name"] in p["hunters"] for p in parties):
            return decision("wait", None, "wait for the hunt")
        for p in parties:
            if herd.get(p["animal"]) and me["health"] >= 40:
                return decision("hunt", {"animal": p["animal"]}, "join the hunt")

        # Food for today and tomorrow morning comes first.
        left = (obs.get("work_today") or {}).get("hours_left")
        stock, reserve = me["satiety"] + self._food_left(inv), 2 * (end - hour) + 70
        if stock < reserve:
            self.foraging = True
        elif stock >= reserve + 25:
            self.foraging = False
        if self.foraging and (d := self._get_food(obs, go, left)):
            return d
        self.foraging = False
        return self._build(obs, go, left) or (stock < reserve + 100 and self._get_food(obs, go, left)) \
            or (decision("wait", None, "rest") if loc == me["home"] else go(me["home"], "nothing to do: home"))

    def _food_score(self, place: str, day: int, left: int | None) -> int:
        """How good a place looks for food: small game (no work hours needed), fish, berries. What was seen
        on an earlier day may have grown back."""
        fresh = self.seen_day.get(place) == day
        game = sum((self.game.get(place) or {}).values())
        res = self.seen.get(place, {})
        est = lambda n, ever: n if fresh else (max(n, 2) if ever else 0)
        score = 12 * min(est(game, place in self.game_ever), 3)
        if left != 0:
            score += 15 * min(est(res.get("fish", 0), "fish" in self.res_ever.get(place, ())), 2)
            score += 10 * min(est(res.get("berries", 0), "berries" in self.res_ever.get(place, ())), 2)
        return score

    def _get_food(self, obs: dict, go, left: int | None) -> dict | None:
        """Hunt or gather food here, else walk to the best place known for it; None if there is none."""
        me, here, day = obs["you"], obs["here"], obs["time"]["day"]
        loc, herd = me["location"], obs.get("animals_here") or {}
        if "hunt" in obs["available_actions"] and me["health"] >= 30:
            awake = 1 + sum(1 for p in here["people"] if not p["asleep"])
            big = [k for k, v in herd.items() if 1 < v["hunters_needed"] <= awake and v["count"]]
            if big and me["health"] >= 60:
                return decision("hunt", {"animal": max(big, key=lambda k: herd[k]["hunters_needed"])},
                                "big game, enough of us here")
            small = [k for k, v in herd.items() if v["hunters_needed"] <= 1 and v["count"]]
            if small:
                return decision("hunt", {"animal": small[0]}, "small game")
        if left != 0:
            for r in ("fish", "berries"):
                if here["resources"].get(r):
                    return decision("work", {"resource": r, "hours": 2}, "food")
        big = sorted(p for p, g in self.big.items() if g and p != loc)
        if big and obs["time"]["hour"] < 10 and me["health"] >= 60:
            return go(big[0], "a hunt for big game: more of us will come")
        unseen = sorted(p for p in self.places if p not in self.seen and p not in ("market", "smithy"))
        if unseen and len(self.seen) < 5 and obs["time"]["hour"] < 12:  # look around once: game, fish, wood
            return go(unseen[sum(map(ord, me["name"])) % len(unseen)], "look around")
        scores = {p: self._food_score(p, day, left) for p in self.seen if p != loc}
        best = max(scores, key=lambda p: (scores[p], p), default=None)
        if best and scores[best] > 0:
            return go(best, "go where there is food")
        if unseen and obs["time"]["hour"] < obs["time"]["day_ends_at"] - 6:
            return go(unseen[0], "look for food elsewhere")
        stale = [p for p in self.seen if p != loc and (p in self.game_ever or self.res_ever.get(p, set()) & {"fish", "berries"})]
        if stale:  # what was empty may have grown back
            return go(min(stale, key=lambda p: (self.seen_day.get(p, 0), p)), "look for food again")
        return None

    def _build(self, obs: dict, go, left: int | None) -> dict | None:
        me, here, t = obs["you"], obs["here"], obs["time"]
        inv, loc, name = me["inventory"], me["location"], me["name"]
        sites = obs["building_sites"]
        plot = obs.get("plot") or {}
        startable = obs.get("can_start_building_here") or {}
        living = sorted(v["name"] for v in obs["board"]["villagers"] if v["status"] != "dead")
        rank = living.index(name) if name in living else 0
        stage = obs.get("village_stage") or {}
        missing = {}
        for k, v in (stage.get("next_stage_needs_standing") or {}).items():
            have, need = (int(x) for x in v.split("/"))
            if have < need:
                missing[k] = need - have

        def site_of(kind: str, level: int = 0, at: str | None = None) -> dict | None:
            return next((s for s in sites if s["building"] == kind and (not level or s["level"] == level)
                         and (at is None or s["at"] == at)), None)

        # What I would start, and where.
        wants: list[tuple[str, str]] = []
        house = plot.get("house_level", 0)
        if house == 0 and not site_of("house", at=me["home"]):
            wants.append(("house", me["home"]))
        team_open = [s for s in sites if s["people_needed_on_the_same_day"] > 1 and s["work_left_hours"] > 0]
        for key, n in missing.items():
            kind, _, lvl = key.partition("@")
            if kind == "house" and lvl == "2":
                if house == 1 and not site_of("house", 2, me["home"]) \
                        and sum(1 for s in sites if s["building"] == "house" and s["level"] == 2) < n:
                    wants.append(("house", me["home"]))
            elif kind in self.YARD_RANK:
                mine_to_raise = rank == self.YARD_RANK[kind] % len(living) or t["day"] >= 3 + self.YARD_RANK[kind]
                if not site_of(kind) and mine_to_raise and house >= 1:
                    wants.append((kind, me["home"]))
            elif kind in self.VILLAGE_AT and not site_of(kind) and not team_open:
                wants.append((kind, self.VILLAGE_AT[kind]))
        kiln = any(b.get("kind") == "kiln" for b in plot.get("buildings", []))
        bricks = any(s["still_needs"].get("brick") for s in sites) or "town_hall" in missing
        if bricks and not kiln and not site_of("kiln", at=me["home"]) and house >= 1 \
                and rank == self.YARD_RANK["kiln"] % len(living):
            wants.append(("kiln", me["home"]))
        for kind, place in wants:
            if loc == place and kind in startable:
                return decision("start_building", {"kind": kind}, f"start a {kind}")
        start_trip = next((place for kind, place in wants), None)

        # Sites I work on: my own, the team sites; materials still needed there.
        mine = [s for s in sites if s["for"] == name]
        team = sorted(team_open, key=lambda s: (len(s["id"]), s["id"]))  # oldest first: everyone picks the same
        focus = mine + [s for s in sites if s not in mine and (s["people_needed_on_the_same_day"] > 1
                                                             or bricks and s["building"] == "kiln")]
        if house == 0 and any(s["building"] == "house" for s in mine):  # a roof of my own comes first
            focus, team = [s for s in mine if s["building"] == "house"], []
        firewood = self._firewood(obs)
        spare = {k: n - (firewood if k == "wood" else 0) for k, n in inv.items()}
        for s in focus:  # deliver what I carry to a site where I stand
            give = {k: min(n, spare.get(k, 0)) for k, n in s["still_needs"].items() if spare.get(k, 0) > 0}
            if s["at"] == loc and give:
                return decision("bring_materials", {"site_id": s["id"], "items": give}, "materials for the site")
        # A yard kiln serves only its owner's household, so the others hand their clay to the owner.
        kiln_owner = living[self.YARD_RANK["kiln"] % len(living)] if living else name
        key = tuple(sorted(s["id"] for s in sites if s["still_needs"].get("brick")))
        if self.clay_given[0] != key:
            self.clay_given = (key, 0)
        clay = inv.get("clay", 0)
        if key and not kiln and name != kiln_owner and clay >= 2 \
                and any(p["name"] == kiln_owner and not p["asleep"] for p in here["people"]):
            self.clay_given = (key, self.clay_given[1] + clay)
            give = {"clay": clay}
            if (wood := min(spare.get("wood", 0), -(-clay // 2))) > 0:
                give["wood"] = wood
            return decision("give", {"to": kiln_owner, "items": give}, "clay for the kiln")
        if team and t["hour"] >= self.TEAM_HOUR:
            s = team[0]
            if loc != s["at"]:
                return go(s["at"], f"build the {s['building']} together")
            return decision("construct", {"site_id": s["id"]}, f"build the {s['building']} together")
        if start_trip and t["hour"] < t["day_ends_at"] - 5:
            return go(start_trip, "start building")

        need: Counter = Counter()
        for s in [s for s in mine if s["still_needs"]] or focus:  # my own sites' materials first
            need.update(s["still_needs"])
        if not focus:
            need.update(self.STOCK)
        need["wood"] += firewood
        # Crafted materials: planks from wood by hand; bricks at my own kiln from clay and wood, else my share
        # of the clay for the kiln's owner.
        if (short := need.pop("plank", 0) - inv.get("plank", 0)) > 0:
            if spare.get("wood", 0) >= 2:
                return decision("craft", {"recipe": "plank", "times": min(short, spare["wood"] // 2, 10)}, "planks")
            need["wood"] += 2 * short
        if (short := need.pop("brick", 0) - inv.get("brick", 0)) > 0 and kiln:
            batches = -(-short // 2)
            if inv.get("clay", 0) >= 2 and spare.get("wood", 0) >= 1:
                if loc == me["home"]:
                    return decision("craft", {"recipe": "brick",
                                              "times": min(batches, inv["clay"] // 2, spare["wood"])},
                                    "bricks at my kiln")
                if t["hour"] < t["day_ends_at"] - 4 and inv["clay"] >= min(2 * batches, 8):
                    return go(me["home"], "make bricks at my kiln")
            need["clay"] += 2 * batches
            need["wood"] += batches
        elif short > 0 and name != kiln_owner:
            share = 2 * -(-short // len(living)) - self.clay_given[1]  # twice my clay share: some fall short
            if share > 0:
                need["clay"] += share
                need["wood"] += -(-share // 2)
        need.pop("iron", None)
        deficit = {k: n - inv.get(k, 0) for k, n in need.items() if n > inv.get(k, 0)}
        carrying = any(spare.get(k, 0) > 0 for s in focus for k in s["still_needs"])

        # Stone tools first: they make every hour of gathering count more.
        for res in ("wood", "stone", "clay"):
            kit = self.TOOL[res]
            if res in deficit and not inv.get(kit):
                if inv.get("wood", 0) >= 1 and inv.get("stone", 0) >= 2:
                    return decision("craft", {"recipe": kit}, "make a tool")
                if res != "wood" and not inv.get("wood"):
                    deficit["wood"] = max(deficit.get("wood", 0), 1)
        if "ore" in deficit and not inv.get("stone_pick") and not inv.get("iron_pick"):
            if inv.get("wood", 0) >= 1 and inv.get("stone", 0) >= 2:
                return decision("craft", {"recipe": "stone_pick"}, "a pick for ore")
            deficit["stone"] = max(deficit.get("stone", 0), 2 - inv.get("stone", 0))
            deficit["wood"] = max(deficit.get("wood", 0), 1 - inv.get("wood", 0))
            deficit.pop("ore")
            deficit = {k: n for k, n in deficit.items() if n > 0}
        if left != 0 and deficit:
            res = max(deficit, key=lambda k: (deficit[k], k))
            if here["resources"].get(res):
                return decision("work", {"resource": res, "hours": 4}, f"{res} for building")
            if res not in self.SPOT and not any(r.get(res) for r in self.seen.values()):
                unseen = sorted(p for p in self.places if p not in self.seen and p not in ("market", "smithy"))
                if unseen:
                    return go(unseen[0], f"look for {res}")
            return go(self._place_of(res), f"fetch {res}")
        if carrying:
            s = next(s for s in focus if any(spare.get(k, 0) > 0 for k in s["still_needs"]))
            return go(s["at"], "bring materials")
        # Solo hours on my own site (they never get lost), else help any site with work left.
        late = t["hour"] >= t["day_ends_at"] - 5
        for s in mine + team + [s for s in sites if s["work_left_hours"] > 0]:
            if late and s["at"] != loc and s not in mine:
                continue
            if s["work_left_hours"] > 0 and (s["people_needed_on_the_same_day"] <= 1 or s is (team or [None])[0]
                                             and t["hour"] >= self.TEAM_HOUR):
                if loc != s["at"]:
                    return go(s["at"], f"work on the {s['building']}")
                return decision("construct", {"site_id": s["id"]}, f"work on the {s['building']}")
        return None


BOT_TYPES = {"random": RandomBot, "worker": WorkerBot, "thief": ThiefBot, "trader": TraderBot, "loner": LonerBot,
             "homestead": HomesteadBot, "hunter": HunterBot,
             "builder": BuilderBot}

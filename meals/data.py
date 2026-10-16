"""Loading the kitchen's data. It has its own cache, separate from the money data,
so money pages never load recipes and kitchen pages never load your transactions.
Saving something in the kitchen only refreshes this cache (a shopping trip refreshes both)."""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import cached_property

import pandas as pd
import streamlit as st

from core.db import transact
from meals.logic import OPEN, ROLE_ORDER, SLOTS, allocate, eaters, pot_waste, reminders, suggested_pot
from meals.units import base_of, fmt, fmt_stock, make_pack, plural

TTL = int(os.environ.get("CASHEW_CACHE_SECONDS", "60"))  # tests shorten this
HOUSEHOLD_KEY = "meals_household"


def slot_key(slot):
    """Where the usual number of people for a breakfast, lunch or supper is kept (app_meta)."""
    return f"meals_people_{slot.lower()}"


def fmt_portions(n):
    from meals.units import frac, plural
    return f"{frac(n)} {plural('portion', n)}"

# Every table the kitchen screens need, as (columns, query). They all come back in ONE round trip (as JSON),
# instead of one trip per table: on a distant database each trip costs ~0.1-0.2 s.
QUERIES = {
    "ingredients": (["id", "name", "unit", "category", "low_level", "pack_name", "pack_size", "kind", "loose",
                     "alt_units", "section"],
                    "SELECT id, name, unit, category, low_level, pack_name, pack_size, kind, loose, alt_units, section "
                    "FROM meals.ingredients ORDER BY lower(name)"),
    "recipes": (["id", "name", "portions", "keeps_days", "prep_note", "prep_hours", "method", "bought", "price",
                 "count_unit", "shop", "category", "role"],
                "SELECT id, name, portions, keeps_days, prep_note, prep_hours, method, bought, price, count_unit, shop, "
                "category, role FROM meals.recipes ORDER BY lower(name)"),
    "items": (["id", "recipe_id", "ingredient_id", "qty", "unit"],
              "SELECT id, recipe_id, ingredient_id, qty, unit FROM meals.recipe_items ORDER BY id"),
    "pairings": (["id", "name"], "SELECT id, name FROM meals.pairings ORDER BY lower(name)"),
    "pairing_items": (["id", "pairing_id", "recipe_id", "ingredient_id", "qty", "unit"],
                      "SELECT id, pairing_id, recipe_id, ingredient_id, qty, unit FROM meals.pairing_items ORDER BY id"),
    # a window around this week is all the screens need
    "plan": (["id", "day", "slot", "recipe_id", "ingredient_id", "qty", "unit", "status", "done_at", "done_by", "label",
              "price", "short", "people"],
             "SELECT id, day, slot, recipe_id, ingredient_id, qty, unit, status, done_at, done_by, label, price, "
             "undo->'short' AS short, people "  # short: what the pantry didn't have when it was ticked
             "FROM meals.plan WHERE day BETWEEN CURRENT_DATE - 40 AND CURRENT_DATE + 63 ORDER BY day, id"),
    "fridge": (["id", "recipe_id", "label", "portions", "cooked_on", "eat_by", "plan_id", "unit"],
               "SELECT id, recipe_id, label, portions, cooked_on, eat_by, plan_id, unit FROM meals.fridge "
               "WHERE portions > 0 ORDER BY eat_by, id"),
    "pantry": (["ingredient_id", "unit", "qty", "updated_at"],
               "SELECT ingredient_id, unit, qty, updated_at FROM meals.pantry"),
    "prices": (["ingredient_id", "unit", "per_unit"], "SELECT ingredient_id, unit, per_unit FROM meals.prices"),
    "trips": (["id", "date", "account", "total", "created_by", "shop", "items"],
              "SELECT t.id, t.date, t.account, t.total, t.created_by, t.shop, count(i.id) AS items "
              "FROM meals.trips t LEFT JOIN meals.trip_items i ON i.trip_id = t.id "
              "GROUP BY t.id ORDER BY t.date DESC, t.id DESC LIMIT 20"),
    "settings": (["key", "value"], "SELECT key, value FROM app_meta WHERE key LIKE 'meals_%' OR key = 'feature_fun'"),
    # what each item cost per base unit on every trip in the last year, and where (for price trends)
    "history": (["ingredient_id", "unit", "qty", "price", "date", "shop", "trip_id"],
                "SELECT i.ingredient_id, i.unit, i.qty, i.price, t.date, t.shop, t.id AS trip_id FROM meals.trip_items i "
                "JOIN meals.trips t ON t.id = i.trip_id WHERE t.date >= CURRENT_DATE - 400 AND i.qty > 0 "
                "AND i.ingredient_id IS NOT NULL ORDER BY t.date, t.id, i.id"),
    # what was paid for bought food (kenkey, waakye…) on each day, for price trends
    "bought": (["date", "recipe_id", "label", "qty", "unit", "paid", "shop"],
               "SELECT date, recipe_id, label, qty, unit, paid, shop FROM meals.bought "
               "WHERE date >= CURRENT_DATE - 400 AND qty > 0 ORDER BY date, id"),
    "waste": (["id", "date", "label", "amount", "unit", "value", "recipe_id"],
              "SELECT id, date, label, amount, unit, value, recipe_id FROM meals.waste "
              "WHERE date >= CURRENT_DATE - 400 ORDER BY date DESC, id DESC"),
}
# Postgres doesn't promise to keep a subquery's ORDER BY inside json_agg, so the order that matters is set
# again after loading: (columns, ascending)
ORDER = {"trips": (["date", "id"], False), "history": (["date", "trip_id"], True), "bought": (["date"], True),
         "waste": (["date", "id"], False)}
SQL = "SELECT " + ", ".join(
    f"(SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t) AS {name}" for name, (_, sql) in QUERIES.items())
DATES = {"plan": ["day"], "fridge": ["cooked_on", "eat_by"], "trips": ["date"], "history": ["date"],
         "bought": ["date"], "waste": ["date"]}


def _load(conn):
    with conn.cursor() as cur:
        cur.execute(SQL)
        row = cur.fetchone()
    out = {}
    for (name, (cols, _)), records in zip(QUERIES.items(), row):
        df = pd.DataFrame(records or [], columns=cols)
        for c in DATES.get(name, []):
            df[c] = [date.fromisoformat(str(x)[:10]) if x else None for x in df[c]]
        if ORDER.get(name) and len(df):
            by, asc = ORDER[name]
            df = df.sort_values(by, ascending=asc, kind="stable").reset_index(drop=True)
        out[name] = df
    return out


@st.cache_resource(ttl=TTL, show_spinner=False)
def load_kitchen():
    return Kitchen(transact(_load, read_only=True))


def kitchen():
    return load_kitchen()


def invalidate_kitchen():
    load_kitchen.clear()


def _f(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else float(x)


class Kitchen:
    """Everything the meal screens need. Shared between sessions, so treat it as read-only."""

    def __init__(self, f):
        self.f = f
        ing = f["ingredients"]
        self.ingredients = ing
        self.names = dict(zip(ing["id"], ing["name"]))
        self.unit_of = dict(zip(ing["id"], ing["unit"]))
        self.category_of = {i: c for i, c in zip(ing["id"], ing["category"]) if c}
        # household supplies (cleaning things, toilet roll…) share the pantry and shopping list with food,
        # but never appear in recipes or meal ideas, and have their own budget
        self.supplies = {int(i) for i, kd in zip(ing["id"], ing["kind"]) if kd == "household"}
        self.food_names = {i: n for i, n in self.names.items() if int(i) not in self.supplies}
        self.food_categories = {c for i, c in self.category_of.items() if int(i) not in self.supplies}
        self.supply_categories = {c for i, c in self.category_of.items() if int(i) in self.supplies}
        # containers: {ingredient_id: (name, size in base unit, base unit, sold loose, {other unit: base units})}
        self.packs = {}
        for i, u, pn, ps, lo, au in zip(ing["id"], ing["unit"], ing["pack_name"], ing["pack_size"], ing["loose"],
                                        ing["alt_units"]):
            pack = make_pack(u, pn, ps, lo, au)
            if pack:
                self.packs[int(i)] = pack
        self.recipes = {int(r["id"]): {"name": r["name"], "portions": float(r["portions"]), "keeps_days": int(r["keeps_days"]),
                                       "prep_note": r["prep_note"], "prep_hours": None if pd.isna(r["prep_hours"])
                                       else int(r["prep_hours"]), "method": r["method"],
                                       # bought ready-made: no ingredients, a usual price per unit instead
                                       "bought": bool(r["bought"]), "price": _f(r["price"]),
                                       "count_unit": r["count_unit"] or "portion", "shop": r["shop"] or "",
                                       "category": r["category"] or "",
                                       # starch, soup, stew, sauce, side or main: orders a meal's name
                                       "role": r["role"] or "main"}
                        for r in f["recipes"].to_dict("records")}
        # what bought food is paid under counts as food too (e.g. Dining Out)
        self.food_categories |= {r["category"] for r in self.recipes.values() if r["bought"] and r["category"]}
        items = defaultdict(list)
        for rid, iid, qty, unit in zip(f["items"]["recipe_id"], f["items"]["ingredient_id"], f["items"]["qty"],
                                       f["items"]["unit"]):
            items[int(rid)].append((int(iid), float(qty), unit))
        self.items = dict(items)
        # ready-made pairings: {id: {"name", "parts": [{"recipe_id"} or {"ingredient_id", "qty" per person, "unit"}]}}
        self.pairings = {int(i): {"name": n, "parts": []} for i, n in zip(f["pairings"]["id"], f["pairings"]["name"])}
        for r in f["pairing_items"].to_dict("records"):
            p = self.pairings.get(int(r["pairing_id"]))
            if p is None:
                continue
            if r["recipe_id"] is not None and not pd.isna(r["recipe_id"]) and int(r["recipe_id"]) in self.recipes:
                p["parts"].append({"recipe_id": int(r["recipe_id"])})
            elif r["ingredient_id"] is not None and not pd.isna(r["ingredient_id"]) and int(r["ingredient_id"]) in self.names:
                p["parts"].append({"ingredient_id": int(r["ingredient_id"]), "qty": _f(r["qty"]) or 1.0,
                                   "unit": r["unit"] or self.unit_of.get(int(r["ingredient_id"]), "pcs")})
        self.pairings = {i: p for i, p in self.pairings.items() if len(p["parts"]) >= 2}  # a pairing pairs things
        self.plan = [
            {"id": int(r["id"]), "day": r["day"], "slot": r["slot"],
             "recipe_id": None if pd.isna(r["recipe_id"]) else int(r["recipe_id"]),
             "ingredient_id": None if pd.isna(r["ingredient_id"]) else int(r["ingredient_id"]),
             "qty": float(r["qty"]), "unit": r["unit"], "status": r["status"], "done_by": r["done_by"],
             "label": r["label"], "price": _f(r["price"]),
             "short": r["short"] if isinstance(r.get("short"), list) else [],
             "people": _f(r.get("people"))}  # None: the usual number for that meal
            for r in f["plan"].to_dict("records")]
        self.plan.sort(key=lambda e: (e["day"], e["id"]))
        self._by_day = defaultdict(list)  # day -> its entries, so each day card doesn't scan the whole plan
        for e in self.plan:
            self._by_day[e["day"]].append(e)
        self.fridge = [
            {"id": int(r["id"]), "recipe_id": None if pd.isna(r["recipe_id"]) else int(r["recipe_id"]),
             "label": r["label"], "portions": float(r["portions"]), "cooked_on": r["cooked_on"], "eat_by": r["eat_by"],
             "unit": r["unit"] or "portion"}
            for r in f["fridge"].to_dict("records")]
        self.fridge.sort(key=lambda b: (b["eat_by"], b["id"]))
        pan, pri = f["pantry"], f["prices"]
        self.pantry = {(int(i), u): float(q) for i, u, q in zip(pan["ingredient_id"], pan["unit"], pan["qty"])}
        self.prices = {(int(i), u): float(p) for i, u, p in zip(pri["ingredient_id"], pri["unit"], pri["per_unit"])}
        self.low_levels = {(int(i), base_of(u)): _f(lv) for i, u, lv in zip(ing["id"], ing["unit"], ing["low_level"])
                           if _f(lv) is not None}
        self.trips = f["trips"]
        h = f["history"]
        if len(h):
            h = h.assign(per_unit=h["price"].astype(float) / h["qty"].astype(float))
        self.history = h
        self.waste = f["waste"]
        self.bought_history = f["bought"]
        settings = dict(zip(f["settings"]["key"], f["settings"]["value"]))
        try:
            self.household = max(int(settings.get(HOUSEHOLD_KEY, 4)), 1)
        except ValueError:
            self.household = 4
        # the usual number eating each meal (lunch is often eaten at work or school); the household size otherwise
        self.slot_people = {}
        for slot in SLOTS:
            try:
                self.slot_people[slot] = max(int(settings.get(slot_key(slot), self.household)), 0)
            except ValueError:
                self.slot_people[slot] = self.household
        self.fun = settings.get("feature_fun", "on") != "off"  # jokes in the reminders
        self._alloc = {}

    # ---- the next two weeks, worked out once per data change -----------------------------
    HORIZON = 14

    def window(self, today=None):
        today = today or date.today()
        return today, today + timedelta(days=self.HORIZON - 1)

    def allocation(self, today=None):
        """Stock shared out across every open meal in the next 14 days (see logic.allocate). Worked out once
        for each day and each data change, and shared by every screen and everyone using the app."""
        today = today or date.today()
        if today not in self._alloc:
            start, end = self.window(today)
            self._alloc[today] = allocate(self.open_entries(start, end), self.recipes, self.items, self.pantry,
                                          self.fridge, self.slot_people, today, self.packs)
        return self._alloc[today]

    def meal_status(self, entry_id, today=None):
        return self.allocation(today)["meals"].get(entry_id)

    # ---- people per meal --------------------------------------------------------------------------
    def people(self, e):
        """How many eat this planned dish: the number set on the meal, or the usual for its slot."""
        return eaters(e, self.slot_people)

    def meal_people(self, day, slot):
        """How many eat this day's breakfast, lunch or supper (the number set on it, or the usual)."""
        parts = [x for x in self._by_day.get(day, []) if x["slot"] == slot and x.get("people")]
        return float(parts[0]["people"]) if parts else float(self.slot_people.get(slot, self.household))

    # ---- pots that will partly go off ------------------------------------------------------------
    def pot_warnings(self, today=None):
        """Planned pots that make more than the plan eats before they go off:
        [{"entry_id", "recipe_id", "name", "day", "slot", "cooked", "eaten", "left", "eat_by", "suggest", "text"}]."""
        today = today or date.today()
        _, end = self.window(today)
        out = []
        for p in pot_waste(self.allocation(today), end):
            name = self.recipes.get(p["recipe_id"], {}).get("name", "?")
            n = suggested_pot(p)
            p.update(name=name, suggest=n, text=(
                f"{name} on {p['day']:%a %d}: {fmt_portions(p['cooked'])} cooked, but only "
                f"{fmt_portions(p['eaten'])} eaten before it goes off on {p['eat_by']:%a %d}, so "
                f"{fmt_portions(p['left'])} would be thrown away. Cook {fmt_portions(n)}, or plan it for more meals "
                "that week."))
            out.append(p)
        return out

    # ---- ingredients that ran out while cooking ------------------------------------------------
    RAN_SHORT_DAYS = 7

    def ran_short(self, today=None):
        """Ingredients a meal needed but the pantry didn't have when it was ticked as cooked or eaten, in the
        last week, and still not restocked: {(ingredient_id, base): {"qty", "short", "for": [meals],
        "mismatch": the unit the pantry counts it in, when that's why it couldn't be taken off}}.

        Stock never goes below zero, so this is how a shortfall stays visible: it's a reminder in the morning
        message and on the plan, and a line on the shopping list, until enough is bought or the pantry is
        corrected."""
        today = today or date.today()
        out = {}
        for e in self.entries(today - timedelta(days=self.RAN_SHORT_DAYS), today):
            if e["status"] == OPEN:
                continue
            for ing, base, q in e.get("short") or []:
                ing, q = int(ing), float(q)
                if ing in self.supplies or ing not in self.names:
                    continue
                if float(self.pantry.get((ing, base), 0.0)) >= q - 1e-9:
                    continue  # bought since, or the pantry was corrected
                t = out.setdefault((ing, base), {"qty": 0.0, "short": 0.0, "for": [], "mismatch": None})
                t["qty"] += q
                t["short"] += q
                meal = self.meal_name_of(e)
                if meal not in t["for"]:
                    t["for"].append(meal)
                # stock kept in another unit (cups) than the recipe asks for (grams) can't be taken off
                other = [b for (i, b), v in self.pantry.items() if i == ing and b != base and v > 0]
                if other:
                    t["mismatch"] = other[0]
        return out

    def _ran_short_notes(self, today):
        """The reminders for ingredients that ran out while cooking: [(tone, text, kind)]."""
        short = self.ran_short(today)
        notes = []
        plain = [(ing, base, t) for (ing, base), t in short.items() if not t["mismatch"]]
        if plain:
            items = ", ".join(f"{fmt(t['short'], base, self.unit_of.get(ing))} {self.names[ing]}".replace(" pcs", "")
                              for ing, base, t in plain)
            meals = ", ".join(dict.fromkeys(m for _, _, t in plain for m in t["for"]))
            notes.append(("warn", f"Ran out while cooking ({meals}): {items} short. Buy more, or correct the "
                                  "pantry if you still have some.", "ran_short"))
        for (ing, base), t in short.items():
            if t["mismatch"]:
                usual = self.unit_of.get(ing)
                kept = usual if base_of(usual) == t["mismatch"] else t["mismatch"]
                notes.append(("warn", f"{self.names[ing]} couldn't be taken off the pantry: the recipe measures it "
                                      f"in {base}, but the pantry counts it in {plural(kept)}. Change the unit in "
                                      "the recipe.", "ran_short"))
        return notes

    def _extra_notes(self, today):
        """Reminders worked out here rather than in logic.reminders(): what ran out while cooking, and pots
        cooked today or tomorrow that are bigger than the plan eats (still time to cook less)."""
        soon = [("warn", p["text"], "pot_waste") for p in self.pot_warnings(today)
                if p["day"] <= today + timedelta(days=1)]
        return self._ran_short_notes(today) + soon

    def notes(self, now=None):
        """Today's and tomorrow's reminders, with jokes if they're switched on."""
        now = now or datetime.now()
        today = now.date()
        food_low = {key: v for key, v in self.low_levels.items() if key[0] not in self.supplies}
        out = reminders(now, self.entries(today, today + timedelta(days=1)), self.recipes, self.items, self.pantry,
                        self.fridge, self.names, self.slot_people, packs=self.packs, alloc=self.allocation(today),
                        fun=self.fun, low_levels=food_low, usual=self.unit_of)
        return [(tone, text) for tone, text, _ in self._extra_notes(today)] + out

    def urgent(self, now=None):
        """The reminders worth a line in the morning message: prep to start (soak the beans), and fridge food
        past its date or to eat by today or tomorrow. Plain text, no jokes: [text]."""
        now = now or datetime.now()
        today = now.date()
        food_low = {key: v for key, v in self.low_levels.items() if key[0] not in self.supplies}
        notes = reminders(now, self.entries(today, today + timedelta(days=1)), self.recipes, self.items, self.pantry,
                          self.fridge, self.names, self.slot_people, packs=self.packs, alloc=self.allocation(today),
                          fun=False, low_levels=food_low, usual=self.unit_of, with_kind=True)
        return ([text for _, text, _ in self._extra_notes(today)]
                + [text for _, text, kind in notes if kind in ("prep", "past", "eat_soon")])

    def stocktake(self, today=None, days=7, most=10):
        """The pantry items used most in the last week, to count by hand: [(name, what the pantry says)].
        Stock drifts (gifts, borrowing, cooking that was never ticked), and every missing / running-low
        line is only as right as these numbers."""
        today = today or date.today()
        used = defaultdict(int)
        for e in self.entries(today - timedelta(days=days), today):
            if e["status"] != "cooked":
                continue
            if e.get("recipe_id"):
                for ing, _, _ in self.items.get(e["recipe_id"], []):
                    used[ing] += 1
            elif e.get("ingredient_id"):
                used[int(e["ingredient_id"])] += 1
        picked = sorted((i for i in used if i not in self.supplies and i in self.names),
                        key=lambda i: (-used[i], self.names[i].lower()))[:most]
        out = []
        for i in picked:
            usual = self.unit_of.get(i, "pcs")
            base = base_of(usual)
            have = float(self.pantry.get((i, base), 0.0))
            out.append((self.names[i], fmt_stock(have, base, self.pack(i), usual) if have > 0 else "none"))
        return out

    def food_low(self):
        """Food staples at or below their warning level, by name (household supplies have supplies_low)."""
        return sorted(self.names.get(ing, "?") for (ing, base), level in self.low_levels.items()
                      if ing not in self.supplies and level is not None
                      and float(self.pantry.get((ing, base), 0.0)) <= float(level))

    def supplies_low(self):
        """Household supplies at or below their warning level (or out), by name."""
        out = []
        for i in sorted(self.supplies, key=lambda x: self.names.get(x, "").lower()):
            base = base_of(self.unit_of.get(i, "pcs"))
            have = float(self.pantry.get((i, base), 0.0))
            level = self.low_levels.get((i, base))
            if have <= 0 or (level is not None and have <= level):
                out.append(self.names.get(i, "?"))
        return out

    # ---- names ----------------------------------------------------------------
    def entry_name(self, e):
        if e.get("label") and not e.get("recipe_id") and not e.get("ingredient_id"):
            return e["label"]
        if e.get("recipe_id"):
            return self.recipes.get(e["recipe_id"], {}).get("name", "Deleted recipe")
        return self.names.get(e.get("ingredient_id"), "Deleted item")

    # ---- the plan --------------------------------------------------------------
    def entries(self, start, end=None):
        end = end or start
        if (end - start).days > 120:
            return [e for e in self.plan if start <= e["day"] <= end]
        out = []
        d = start
        while d <= end:
            out += self._by_day.get(d, [])
            d += timedelta(days=1)
        return out

    # ---- meals: everything planned for one day's breakfast, lunch or supper is ONE meal ---------------
    # "Kokonte + Palm nut soup" is one lunch, not two dishes: it's ticked off, counted, named and paid for
    # as one meal, while the stock and fridge still work dish by dish (the soup can come from the fridge
    # while the kokonte is cooked fresh).
    def meal_parts(self, e):
        """Every entry sharing this entry's day and meal."""
        return [x for x in self._by_day.get(e["day"], []) if x["slot"] == e["slot"]]

    def meal_count(self, entries):
        return len({(e["day"], e["slot"]) for e in entries})

    def _part_order(self, e):
        if e.get("recipe_id"):
            role = self.recipes.get(e["recipe_id"], {}).get("role", "main")
            return ROLE_ORDER.get(role, 2), e.get("id") or 0
        return (2 if e.get("label") else 4), e.get("id") or 0

    def meal_name(self, parts):
        """"Kokonte + Palm nut soup": the starch first, then the soup or stew, then sides."""
        names = []
        for e in sorted(parts, key=self._part_order):
            n = self.entry_name(e)
            if n not in names:
                names.append(n)
        return " + ".join(names)

    def meal_name_of(self, e):
        return self.meal_name(self.meal_parts(e)) if e.get("id") is not None else self.entry_name(e)

    def open_entries(self, start, end):
        return [e for e in self.entries(start, end) if e["status"] == OPEN]

    def is_bought(self, e):
        """Food bought ready-made: a bought dish from the recipe book, or a one-off typed into the plan."""
        if e.get("recipe_id"):
            return bool(self.recipes.get(e["recipe_id"], {}).get("bought"))
        return not e.get("ingredient_id") and bool(e.get("label"))

    def bought_price(self, e):
        """(price for one unit, unit name) for a bought entry; price may be None if never set."""
        if e.get("recipe_id"):
            r = self.recipes.get(e["recipe_id"], {})
            return (e.get("price") or r.get("price")), r.get("count_unit") or "portion"
        return e.get("price"), e.get("unit") or "portion"

    # ---- fridge ------------------------------------------------------------------
    def fridge_portions(self, recipe_id, today=None):
        today = today or date.today()
        return sum(b["portions"] for b in self.fridge if b["recipe_id"] == recipe_id and b["eat_by"] >= today)

    @cached_property
    def used_ingredients(self):
        used = {i for lines in self.items.values() for i, _, _ in lines}
        used |= {e["ingredient_id"] for e in self.plan if e["ingredient_id"]}
        return used

    # ---- money ------------------------------------------------------------------
    def pack(self, ing):
        return self.packs.get(ing)

    def shops(self):
        return sorted({x for x in self.trips["shop"] if isinstance(x, str) and x}) if len(self.trips) else []

    def waste_this_month(self, today=None):
        today = today or date.today()
        w = self.waste
        if not len(w):
            return 0.0, 0.0, 0
        w = w[pd.to_datetime(w["date"]).dt.to_period("M") == pd.Period(today, "M")]
        return float(w["amount"].astype(float).sum()), float(w["value"].fillna(0).astype(float).sum()), len(w)

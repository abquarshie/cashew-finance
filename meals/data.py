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
from meals.logic import OPEN, allocate, reminders
from meals.units import base_of

TTL = int(os.environ.get("CASHEW_CACHE_SECONDS", "60"))  # tests shorten this
HOUSEHOLD_KEY = "meals_household"

QUERIES = {
    "ingredients": "SELECT id, name, unit, category, low_level, pack_name, pack_size FROM meals.ingredients "
                   "ORDER BY lower(name)",
    "recipes": "SELECT id, name, portions, keeps_days, prep_note, prep_hours, method FROM meals.recipes ORDER BY lower(name)",
    "items": "SELECT id, recipe_id, ingredient_id, qty, unit FROM meals.recipe_items ORDER BY id",
    # a window around this week is all the screens need
    "plan": "SELECT id, day, slot, recipe_id, ingredient_id, qty, unit, status, done_at, done_by FROM meals.plan "
            "WHERE day BETWEEN CURRENT_DATE - 28 AND CURRENT_DATE + 63 ORDER BY day, id",
    "fridge": "SELECT id, recipe_id, label, portions, cooked_on, eat_by, plan_id, unit FROM meals.fridge "
              "WHERE portions > 0 ORDER BY eat_by, id",
    "pantry": "SELECT ingredient_id, unit, qty, updated_at FROM meals.pantry",
    "prices": "SELECT ingredient_id, unit, per_unit FROM meals.prices",
    "trips": "SELECT t.id, t.date, t.account, t.total, t.created_by, t.shop, count(i.id) AS items "
             "FROM meals.trips t LEFT JOIN meals.trip_items i ON i.trip_id = t.id "
             "GROUP BY t.id ORDER BY t.date DESC, t.id DESC LIMIT 20",
    "settings": "SELECT key, value FROM app_meta WHERE key LIKE 'meals_%' OR key = 'feature_fun'",
    # what each item cost per base unit on every trip in the last six months, and where
    "history": "SELECT i.ingredient_id, i.unit, i.qty, i.price, t.date, t.shop FROM meals.trip_items i "
               "JOIN meals.trips t ON t.id = i.trip_id WHERE t.date >= CURRENT_DATE - 183 AND i.qty > 0 "
               "AND i.ingredient_id IS NOT NULL ORDER BY t.date",
    "waste": "SELECT id, date, label, amount, unit, value, recipe_id FROM meals.waste "
             "WHERE date >= CURRENT_DATE - 400 ORDER BY date DESC, id DESC",
}


def _load(conn):
    out = {}
    with conn.cursor() as cur:
        for name, sql in QUERIES.items():
            cur.execute(sql)
            out[name] = pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
    return out


@st.cache_resource(ttl=TTL, show_spinner=False)
def load_kitchen():
    return Kitchen(transact(_load))


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
        # containers: {ingredient_id: (name, size in base unit, base unit)}
        self.packs = {int(i): (pn, float(ps), base_of(u)) for i, u, pn, ps in
                      zip(ing["id"], ing["unit"], ing["pack_name"], ing["pack_size"])
                      if pn and ps is not None and not pd.isna(ps) and float(ps) > 0}
        self.recipes = {int(r["id"]): {"name": r["name"], "portions": float(r["portions"]), "keeps_days": int(r["keeps_days"]),
                                       "prep_note": r["prep_note"], "prep_hours": None if pd.isna(r["prep_hours"])
                                       else int(r["prep_hours"]), "method": r["method"]}
                        for _, r in f["recipes"].iterrows()}
        items = defaultdict(list)
        for _, r in f["items"].iterrows():
            items[int(r["recipe_id"])].append((int(r["ingredient_id"]), float(r["qty"]), r["unit"]))
        self.items = dict(items)
        self.plan = [
            {"id": int(r["id"]), "day": r["day"], "slot": r["slot"],
             "recipe_id": None if pd.isna(r["recipe_id"]) else int(r["recipe_id"]),
             "ingredient_id": None if pd.isna(r["ingredient_id"]) else int(r["ingredient_id"]),
             "qty": float(r["qty"]), "unit": r["unit"], "status": r["status"], "done_by": r["done_by"]}
            for _, r in f["plan"].iterrows()]
        self.fridge = [
            {"id": int(r["id"]), "recipe_id": None if pd.isna(r["recipe_id"]) else int(r["recipe_id"]),
             "label": r["label"], "portions": float(r["portions"]), "cooked_on": r["cooked_on"], "eat_by": r["eat_by"],
             "unit": r["unit"] or "portion"}
            for _, r in f["fridge"].iterrows()]
        self.pantry = {(int(r["ingredient_id"]), r["unit"]): float(r["qty"]) for _, r in f["pantry"].iterrows()}
        self.prices = {(int(r["ingredient_id"]), r["unit"]): float(r["per_unit"]) for _, r in f["prices"].iterrows()}
        self.low_levels = {(int(r["id"]), base_of(r["unit"])): _f(r["low_level"])
                           for _, r in ing.iterrows() if _f(r["low_level"]) is not None}
        self.trips = f["trips"]
        h = f["history"]
        if len(h):
            h = h.assign(per_unit=h["price"].astype(float) / h["qty"].astype(float))
        self.history = h
        self.waste = f["waste"]
        settings = dict(zip(f["settings"]["key"], f["settings"]["value"]))
        try:
            self.household = max(int(settings.get(HOUSEHOLD_KEY, 4)), 1)
        except ValueError:
            self.household = 4
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
                                          self.fridge, self.household, today, self.packs)
        return self._alloc[today]

    def meal_status(self, entry_id, today=None):
        return self.allocation(today)["meals"].get(entry_id)

    def notes(self, now=None):
        """Today's and tomorrow's reminders, with jokes if they're switched on."""
        now = now or datetime.now()
        today = now.date()
        return reminders(now, self.entries(today, today + timedelta(days=1)), self.recipes, self.items, self.pantry,
                         self.fridge, self.names, self.household, packs=self.packs, alloc=self.allocation(today),
                         fun=self.fun, low_levels=self.low_levels)

    # ---- names ----------------------------------------------------------------
    def entry_name(self, e):
        if e.get("recipe_id"):
            return self.recipes.get(e["recipe_id"], {}).get("name", "Deleted recipe")
        return self.names.get(e.get("ingredient_id"), "Deleted item")

    # ---- the plan --------------------------------------------------------------
    def entries(self, start, end=None):
        end = end or start
        return [e for e in self.plan if start <= e["day"] <= end]

    def open_entries(self, start, end):
        return [e for e in self.entries(start, end) if e["status"] == OPEN]

    @staticmethod
    def week_of(day):
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)

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

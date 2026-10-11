"""Loading the kitchen's data. It has its own cache, separate from the money data,
so money pages never load recipes and kitchen pages never load your transactions.
Saving something in the kitchen only refreshes this cache (a shopping trip refreshes both)."""
import os
from collections import defaultdict
from datetime import date, timedelta
from functools import cached_property

import pandas as pd
import streamlit as st

from core.db import transact
from meals.logic import OPEN
from meals.units import base_of

TTL = int(os.environ.get("CASHEW_CACHE_SECONDS", "60"))  # tests shorten this
HOUSEHOLD_KEY = "meals_household"

QUERIES = {
    "ingredients": "SELECT id, name, unit, category, low_level FROM meals.ingredients ORDER BY lower(name)",
    "recipes": "SELECT id, name, portions, keeps_days, prep_note, prep_hours, method FROM meals.recipes ORDER BY lower(name)",
    "items": "SELECT id, recipe_id, ingredient_id, qty, unit FROM meals.recipe_items ORDER BY id",
    # a window around this week is all the screens need
    "plan": "SELECT id, day, slot, recipe_id, ingredient_id, qty, unit, status, done_at, done_by FROM meals.plan "
            "WHERE day BETWEEN CURRENT_DATE - 28 AND CURRENT_DATE + 63 ORDER BY day, id",
    "fridge": "SELECT id, recipe_id, label, portions, cooked_on, eat_by, plan_id FROM meals.fridge "
              "WHERE portions > 0 ORDER BY eat_by, id",
    "pantry": "SELECT ingredient_id, unit, qty, updated_at FROM meals.pantry",
    "prices": "SELECT ingredient_id, unit, per_unit FROM meals.prices",
    "trips": "SELECT t.id, t.date, t.account, t.total, t.created_by, count(i.id) AS items "
             "FROM meals.trips t LEFT JOIN meals.trip_items i ON i.trip_id = t.id "
             "GROUP BY t.id ORDER BY t.date DESC, t.id DESC LIMIT 20",
    "settings": "SELECT key, value FROM app_meta WHERE key LIKE 'meals_%'",
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
        self.recipes = {int(r["id"]): {"name": r["name"], "portions": int(r["portions"]), "keeps_days": int(r["keeps_days"]),
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
             "label": r["label"], "portions": float(r["portions"]), "cooked_on": r["cooked_on"], "eat_by": r["eat_by"]}
            for _, r in f["fridge"].iterrows()]
        self.pantry = {(int(r["ingredient_id"]), r["unit"]): float(r["qty"]) for _, r in f["pantry"].iterrows()}
        self.prices = {(int(r["ingredient_id"]), r["unit"]): float(r["per_unit"]) for _, r in f["prices"].iterrows()}
        self.low_levels = {(int(r["id"]), base_of(r["unit"])): _f(r["low_level"])
                           for _, r in ing.iterrows() if _f(r["low_level"]) is not None}
        self.trips = f["trips"]
        settings = dict(zip(f["settings"]["key"], f["settings"]["value"]))
        try:
            self.household = max(int(settings.get(HOUSEHOLD_KEY, 4)), 1)
        except ValueError:
            self.household = 4

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

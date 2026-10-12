"""Everything that changes kitchen data. Each action is one database transaction: it all
happens, or none of it does. Ticking a meal records exactly what it changed in the pantry
and fridge, so unticking puts things back as they were."""
import json
from collections import defaultdict
from datetime import date, timedelta

import streamlit as st

from core.db import invalidate, transact
from meals.data import HOUSEHOLD_KEY, invalidate_kitchen
from meals.logic import OPEN, entry_needs, price_changes
from meals.units import base_of, fmt, to_base


def _me():
    return (st.session_state.get("user") or {}).get("username")


def _run(fn):
    result = transact(fn)
    invalidate_kitchen()
    return result


# ---- pantry helpers (inside a transaction) -----------------------------------------------
def _add_stock(cur, ing, base, qty):
    cur.execute(
        "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, %s, GREATEST(%s, 0)) "
        "ON CONFLICT (ingredient_id, unit) DO UPDATE SET qty = GREATEST(meals.pantry.qty + %s, 0), updated_at = now()",
        (ing, base, qty, qty))


def _take_stock(cur, ing, base, qty):
    """Take up to qty from the pantry; returns how much was actually there to take."""
    cur.execute("SELECT qty FROM meals.pantry WHERE ingredient_id = %s AND unit = %s FOR UPDATE", (ing, base))
    row = cur.fetchone()
    have = float(row[0]) if row else 0.0
    took = min(have, qty)
    if row:
        cur.execute("UPDATE meals.pantry SET qty = %s, updated_at = now() WHERE ingredient_id = %s AND unit = %s",
                    (have - took, ing, base))
    return took


def _packs(cur):
    """{ingredient_id: (container, size in base unit, base unit)} for converting '1 crate' and similar."""
    cur.execute("SELECT id, unit, pack_name, pack_size FROM meals.ingredients WHERE pack_name IS NOT NULL "
                "AND pack_size > 0")
    return {i: (pn, float(ps), base_of(u)) for i, u, pn, ps in cur.fetchall()}


def _recipe(cur, recipe_id):
    cur.execute("SELECT name, portions, keeps_days FROM meals.recipes WHERE id = %s", (recipe_id,))
    name, portions, keeps = cur.fetchone()
    cur.execute("SELECT ingredient_id, qty, unit FROM meals.recipe_items WHERE recipe_id = %s", (recipe_id,))
    items = [(i, float(q), u) for i, q, u in cur.fetchall()]
    return {"name": name, "portions": int(portions), "keeps_days": int(keeps)}, items


def _entry(cur, entry_id):
    cur.execute("SELECT id, day, slot, recipe_id, ingredient_id, qty, unit, status, undo FROM meals.plan "
                "WHERE id = %s FOR UPDATE", (entry_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ["id", "day", "slot", "recipe_id", "ingredient_id", "qty", "unit", "status", "undo"]
    e = dict(zip(keys, row))
    e["qty"] = float(e["qty"])
    return e


# ---- ticking meals ----------------------------------------------------------------------------
def mark_cooked(entry_id, household):
    """Cooked: the recipe's ingredients come out of the pantry, and portions not eaten at
    this meal go into the fridge. Returns ingredients that weren't in the pantry."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["recipe_id"]:
                return []
            r, items = _recipe(cur, e["recipe_id"])
            uses = entry_needs(e, {e["recipe_id"]: r}, {e["recipe_id"]: items}, _packs(cur))
            removed, short = [], []
            for ing, base, q in uses:
                took = _take_stock(cur, ing, base, q)
                removed.append([ing, base, took])
                if q - took > 1e-6:
                    short.append((ing, base, q - took))
            left = max(e["qty"] - min(float(household), e["qty"]), 0.0)
            made = None
            if left > 0:
                cooked = date.today()
                cur.execute("INSERT INTO meals.fridge (recipe_id, label, portions, cooked_on, eat_by, plan_id, created_by) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (e["recipe_id"], r["name"], left, cooked, cooked + timedelta(days=r["keeps_days"]),
                             e["id"], _me()))
                made = [cur.fetchone()[0], left]
            cur.execute("UPDATE meals.plan SET status = 'cooked', done_at = now(), done_by = %s, undo = %s WHERE id = %s",
                        (_me(), json.dumps({"pantry": removed, "fridge_made": made}), e["id"]))
            return short
    return _run(work)


def mark_from_fridge(entry_id, household):
    """Eaten from the fridge: portions come off the oldest leftovers first. Returns portions that weren't there."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["recipe_id"]:
                return 0
            wanted = min(float(household), e["qty"])
            cur.execute("SELECT id, portions FROM meals.fridge WHERE recipe_id = %s AND portions > 0 "
                        "ORDER BY eat_by, id FOR UPDATE", (e["recipe_id"],))
            taken, left = [], wanted
            for bid, portions in cur.fetchall():
                if left <= 0:
                    break
                t = min(float(portions), left)
                cur.execute("UPDATE meals.fridge SET portions = portions - %s WHERE id = %s", (t, bid))
                taken.append([bid, t])
                left -= t
            cur.execute("UPDATE meals.plan SET status = 'from_fridge', done_at = now(), done_by = %s, undo = %s "
                        "WHERE id = %s", (_me(), json.dumps({"fridge_taken": taken}), e["id"]))
            return max(left, 0.0)
    return _run(work)


def mark_done(entry_id):
    """A plain item (fruit, bread, a snack) was eaten: it comes out of the pantry."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["ingredient_id"]:
                return
            q, base = to_base(e["qty"], e["unit"] or "pcs", _packs(cur).get(e["ingredient_id"]))
            took = _take_stock(cur, e["ingredient_id"], base, q)
            cur.execute("UPDATE meals.plan SET status = 'done', done_at = now(), done_by = %s, undo = %s WHERE id = %s",
                        (_me(), json.dumps({"pantry": [[e["ingredient_id"], base, took]]}), e["id"]))
    _run(work)


def _reverse(cur, e):
    """Undo what ticking this entry did to the pantry and fridge."""
    undo = e["undo"] or {}
    for ing, base, q in undo.get("pantry") or []:
        _add_stock(cur, ing, base, float(q))
    made = undo.get("fridge_made")
    if made:  # leftovers this cooking made; whatever hasn't been eaten yet goes away again
        cur.execute("UPDATE meals.fridge SET portions = GREATEST(portions - %s, 0) WHERE id = %s", (float(made[1]), made[0]))
    for bid, t in undo.get("fridge_taken") or []:
        cur.execute("UPDATE meals.fridge SET portions = portions + %s WHERE id = %s", (float(t), bid))


def untick(entry_id):
    """Put the pantry and fridge back the way they were before the entry was ticked."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] == OPEN:
                return
            _reverse(cur, e)
            cur.execute("UPDATE meals.plan SET status = 'planned', done_at = NULL, done_by = NULL, undo = NULL "
                        "WHERE id = %s", (e["id"],))
    _run(work)


# ---- the plan ---------------------------------------------------------------------------------
def add_to_plan(day, slot, recipe_id=None, ingredient_id=None, qty=1, unit=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO meals.plan (day, slot, recipe_id, ingredient_id, qty, unit) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (day, slot, recipe_id, ingredient_id, qty, unit))
    _run(work)


def remove_from_plan(entry_id):
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if e and e["status"] != OPEN:
                _reverse(cur, e)  # removing a ticked meal puts its ingredients and portions back
            cur.execute("DELETE FROM meals.plan WHERE id = %s", (entry_id,))
    _run(work)


def copy_week(from_start, to_start):
    """Copy one week's plan onto another week (as not-yet-cooked entries). Returns how many were copied."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meals.plan (day, slot, recipe_id, ingredient_id, qty, unit) "
                "SELECT day + %s, slot, recipe_id, ingredient_id, qty, unit FROM meals.plan "
                "WHERE day BETWEEN %s AND %s ORDER BY day, id",
                ((to_start - from_start).days, from_start, from_start + timedelta(days=6)))
            return cur.rowcount
    return _run(work)


def set_household(n):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = "
                        "EXCLUDED.value", (HOUSEHOLD_KEY, str(int(n))))
    _run(work)


# ---- ingredients and recipes -------------------------------------------------------------------
def add_ingredient(name, unit, category, low_level=None, pack_name=None, pack_size=None):
    """pack_size is in the base unit (e.g. 30 for a crate of eggs, 5000 for a 5 kg bag of rice)."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level, pack_name, pack_size) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (name.strip(), unit, category, low_level, pack_name or None, pack_size or None))
            return cur.fetchone()[0]
    return _run(work)


def update_ingredient(ing_id, name, unit, category, low_level, pack_name=None, pack_size=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE meals.ingredients SET name = %s, unit = %s, category = %s, low_level = %s, "
                        "pack_name = %s, pack_size = %s WHERE id = %s",
                        (name.strip(), unit, category, low_level, pack_name or None, pack_size or None, ing_id))
    _run(work)


def delete_ingredient(ing_id):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meals.ingredients WHERE id = %s", (ing_id,))
    _run(work)


def save_recipe(recipe_id, name, portions, keeps_days, prep_note, prep_hours, method, lines):
    """Create or update a recipe and replace its ingredient lines [(ingredient_id, qty, unit)]. Returns its id."""
    def work(conn):
        with conn.cursor() as cur:
            fields = (name.strip(), int(portions), int(keeps_days), prep_note or None, prep_hours or None, method or None)
            if recipe_id:
                cur.execute("UPDATE meals.recipes SET name=%s, portions=%s, keeps_days=%s, prep_note=%s, prep_hours=%s, "
                            "method=%s WHERE id=%s", fields + (recipe_id,))
                rid = recipe_id
                cur.execute("DELETE FROM meals.recipe_items WHERE recipe_id = %s", (rid,))
            else:
                cur.execute("INSERT INTO meals.recipes (name, portions, keeps_days, prep_note, prep_hours, method) "
                            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", fields)
                rid = cur.fetchone()[0]
            for ing, qty, unit in lines:
                cur.execute("INSERT INTO meals.recipe_items (recipe_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (rid, ing, qty, unit))
            return rid
    return _run(work)


def delete_recipe(recipe_id):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meals.plan WHERE recipe_id = %s AND status = 'planned'", (recipe_id,))
            cur.execute("UPDATE meals.plan SET recipe_id = NULL WHERE recipe_id = %s AND ingredient_id IS NOT NULL",
                        (recipe_id,))
            cur.execute("DELETE FROM meals.recipes WHERE id = %s", (recipe_id,))
    _run(work)


# ---- fridge and pantry -------------------------------------------------------------------------
def set_portions(batch_id, portions):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE meals.fridge SET portions = GREATEST(%s, 0) WHERE id = %s", (portions, batch_id))
    _run(work)


def add_to_fridge(label, portions, eat_by, recipe_id=None, unit="portion"):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO meals.fridge (recipe_id, label, portions, cooked_on, eat_by, created_by, unit) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (recipe_id, label, portions, date.today(), eat_by, _me(), unit or "portion"))
    _run(work)


def throw_away(batch_id, value_each=None, amount=None):
    """Thrown away: logged as food waste (with its estimated cost) and taken out of the fridge.
    amount defaults to everything that's left."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT label, portions, unit, recipe_id FROM meals.fridge WHERE id = %s FOR UPDATE", (batch_id,))
            row = cur.fetchone()
            if not row:
                return 0.0
            label, portions, unit, rid = row
            gone = min(float(amount if amount is not None else portions), float(portions))
            if gone <= 0:
                return 0.0
            cur.execute("INSERT INTO meals.waste (date, label, amount, unit, value, recipe_id, created_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (date.today(), label, gone, unit, round(value_each * gone, 2) if value_each else None, rid, _me()))
            cur.execute("UPDATE meals.fridge SET portions = portions - %s WHERE id = %s", (gone, batch_id))
            return gone
    return _run(work)


def set_stock(changes):
    """Stocktake: [(ingredient_id, base_unit, new_qty)]."""
    def work(conn):
        with conn.cursor() as cur:
            for ing, base, qty in changes:
                cur.execute("INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, %s, %s) "
                            "ON CONFLICT (ingredient_id, unit) DO UPDATE SET qty = EXCLUDED.qty, updated_at = now()",
                            (ing, base, max(float(qty), 0)))
    _run(work)


# ---- shopping ---------------------------------------------------------------------------------
def save_trip(day, account, lines, shop=None):
    """Record a shopping trip in one step: what was bought goes into the pantry, prices are remembered,
    and the cost is logged in the money tracker as one expense per category.

    lines: [{"ingredient_id", "name", "qty" (base unit), "base", "price", "category"}]
    Returns (trip id, {category: amount}, big price changes since last time).
    """
    lines = [ln for ln in lines if ln["price"] and ln["price"] > 0]
    by_cat = defaultdict(list)
    for ln in lines:
        by_cat[ln["category"]].append(ln)

    def work(conn):
        with conn.cursor() as cur:
            total = round(sum(ln["price"] for ln in lines), 2)
            cur.execute("SELECT ingredient_id, unit, per_unit FROM meals.prices")
            old = {(i, u): float(p) for i, u, p in cur.fetchall()}
            cur.execute("INSERT INTO meals.trips (date, account, total, created_by, shop) VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING id", (day, account, total, _me(), (shop or "").strip() or None))
            trip = cur.fetchone()[0]
            for ln in lines:
                cur.execute("INSERT INTO meals.trip_items (trip_id, ingredient_id, name, qty, unit, price, category) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (trip, ln["ingredient_id"], ln["name"], ln["qty"], ln["base"], ln["price"], ln["category"]))
                if ln["ingredient_id"] and ln["qty"] > 0:
                    _add_stock(cur, ln["ingredient_id"], ln["base"], ln["qty"])
                    cur.execute(
                        "INSERT INTO meals.prices (ingredient_id, unit, per_unit) VALUES (%s, %s, %s) "
                        "ON CONFLICT (ingredient_id, unit) DO UPDATE SET per_unit = EXCLUDED.per_unit, updated_at = now()",
                        (ln["ingredient_id"], ln["base"], ln["price"] / ln["qty"]))
            for cat, items in by_cat.items():
                names = ", ".join(i["name"] for i in items[:4]) + (f" and {len(items) - 4} more" if len(items) > 4 else "")
                where = f" at {shop.strip()}" if shop and shop.strip() else ""
                cur.execute(
                    "INSERT INTO transactions (date, type, category, amount, note, member, account, created_by) "
                    "VALUES (%s, 'Expense', %s, %s, %s, 'Household', %s, %s)",
                    (day, cat, round(sum(i["price"] for i in items), 2), f"Groceries{where} (trip {trip}): {names}",
                     account, _me()))
            return trip, price_changes(lines, old)
    trip, changes = transact(work)
    invalidate()          # the money side changed too
    invalidate_kitchen()
    return trip, {c: round(sum(i["price"] for i in items), 2) for c, items in by_cat.items()}, changes


def describe_short(short, names):
    return ", ".join(f"{fmt(q, base)} {names.get(ing, '?')}".replace(" pcs", "") for ing, base, q in short)


def default_low(unit):
    """A sensible 'running low' level for a new ingredient, in its base unit."""
    return {"g": 500.0, "ml": 250.0}.get(base_of(unit), 1.0)

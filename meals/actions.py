"""Everything that changes kitchen data. Each action is one database transaction: it all
happens, or none of it does. Ticking a meal records exactly what it changed in the pantry
and fridge, so unticking puts things back as they were."""
import json
from collections import defaultdict
from datetime import date, timedelta

import streamlit as st

from core.db import invalidate, transact
from meals.data import HOUSEHOLD_KEY, invalidate_kitchen
from meals.logic import OPEN, entry_needs, price_changes, take_portions
from meals.units import fmt, make_pack, to_base


def _me():
    return (st.session_state.get("user") or {}).get("username")


def _run(fn, money=False):
    """Run one transaction, then refresh the kitchen data (and the money data too when money changed)."""
    result = transact(fn)
    invalidate() if money else invalidate_kitchen()
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
    """{ingredient_id: pack} for converting '1 crate', '2 tbsp' of margarine and similar (see units.make_pack)."""
    cur.execute("SELECT id, unit, pack_name, pack_size, loose, alt_units FROM meals.ingredients "
                "WHERE pack_name IS NOT NULL AND pack_size > 0")
    return {i: make_pack(u, pn, ps, lo, au) for i, u, pn, ps, lo, au in cur.fetchall()}


def _recipe(cur, recipe_id):
    cur.execute("SELECT name, portions, keeps_days FROM meals.recipes WHERE id = %s", (recipe_id,))
    name, portions, keeps = cur.fetchone()
    cur.execute("SELECT ingredient_id, qty, unit FROM meals.recipe_items WHERE recipe_id = %s", (recipe_id,))
    items = [(i, float(q), u) for i, q, u in cur.fetchall()]
    return {"name": name, "portions": float(portions), "keeps_days": int(keeps)}, items


def _entry(cur, entry_id):
    cur.execute("SELECT id, day, slot, recipe_id, ingredient_id, qty, unit, status, undo, label, price FROM meals.plan "
                "WHERE id = %s FOR UPDATE", (entry_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ["id", "day", "slot", "recipe_id", "ingredient_id", "qty", "unit", "status", "undo", "label", "price"]
    e = dict(zip(keys, row))
    e["qty"] = float(e["qty"])
    return e


# ---- ticking meals ----------------------------------------------------------------------------
def _is_bought(cur, e):
    if e["recipe_id"]:
        cur.execute("SELECT bought FROM meals.recipes WHERE id = %s", (e["recipe_id"],))
        row = cur.fetchone()
        return bool(row and row[0])
    return not e["ingredient_id"] and bool(e["label"])


def _cook(cur, e, household, packs):
    """The recipe's ingredients come out of the pantry; portions not eaten now go into the fridge.
    Returns ingredients that weren't in the pantry."""
    r, items = _recipe(cur, e["recipe_id"])
    uses = entry_needs(e, {e["recipe_id"]: r}, {e["recipe_id"]: items}, packs)
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
                    (e["recipe_id"], r["name"], left, cooked, cooked + timedelta(days=r["keeps_days"]), e["id"], _me()))
        made = [cur.fetchone()[0], left]
    cur.execute("UPDATE meals.plan SET status = 'cooked', done_at = now(), done_by = %s, undo = %s WHERE id = %s",
                (_me(), json.dumps({"pantry": removed, "fridge_made": made}), e["id"]))
    return short


def _eat_leftovers(cur, e, household):
    """Portions come off the leftovers that go off soonest. Food past its eat-by date is never eaten from
    here: it's for the bin (and the waste log), not the plate. Returns portions that weren't there."""
    wanted = min(float(household), e["qty"])
    cur.execute("SELECT id, portions, eat_by FROM meals.fridge WHERE recipe_id = %s AND portions > 0 "
                "AND eat_by >= CURRENT_DATE FOR UPDATE", (e["recipe_id"],))
    batches = [{"id": i, "portions": float(p), "eat_by": by} for i, p, by in cur.fetchall()]
    taken, missing = take_portions(batches, wanted)
    for bid, t in taken:
        cur.execute("UPDATE meals.fridge SET portions = GREATEST(portions - %s, 0) WHERE id = %s", (t, bid))
    cur.execute("UPDATE meals.plan SET status = 'from_fridge', done_at = now(), done_by = %s, undo = %s "
                "WHERE id = %s", (_me(), json.dumps({"fridge_taken": [list(x) for x in taken]}), e["id"]))
    return missing


def _eaten(cur, e, packs):
    """A plain item (fruit, bread, gari) comes out of the pantry."""
    q, base = to_base(e["qty"], e["unit"] or "pcs", packs.get(e["ingredient_id"]))
    took = _take_stock(cur, e["ingredient_id"], base, q)
    cur.execute("UPDATE meals.plan SET status = 'done', done_at = now(), done_by = %s, undo = %s WHERE id = %s",
                (_me(), json.dumps({"pantry": [[e["ingredient_id"], base, took]]}), e["id"]))


def mark_cooked(entry_id, household):
    """Cooked: the recipe's ingredients come out of the pantry, and portions not eaten at
    this meal go into the fridge. Returns ingredients that weren't in the pantry."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["recipe_id"]:
                return []
            return _cook(cur, e, household, _packs(cur))
    return _run(work)


def mark_from_fridge(entry_id, household):
    """Eaten from the fridge: portions come off the oldest leftovers first. Returns portions that weren't there."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["recipe_id"]:
                return 0
            return _eat_leftovers(cur, e, household)
    return _run(work)


def mark_done(entry_id):
    """A plain item (fruit, bread, a snack) was eaten: it comes out of the pantry."""
    def work(conn):
        with conn.cursor() as cur:
            e = _entry(cur, entry_id)
            if not e or e["status"] != OPEN or not e["ingredient_id"]:
                return
            _eaten(cur, e, _packs(cur))
    _run(work)


def mark_meal(entry_ids, household):
    """A meal of several dishes was eaten (Kokonte + Palm nut soup), all in one go:
    - a dish with enough fresh leftovers in the fridge is eaten from there (the week's soup),
    - any other dish is cooked: its ingredients come out of the pantry, extra portions go into the fridge,
    - plain items (gari, bread) come out of the pantry.
    Bought food isn't touched: it's ticked off when it's paid for.
    Returns {"cooked": [names], "fridge": [names], "short": [(ing, base, qty)], "fridge_short": portions}."""
    def work(conn):
        out = {"cooked": [], "fridge": [], "eaten": [], "short": [], "fridge_short": 0.0}
        with conn.cursor() as cur:
            packs = _packs(cur)
            for entry_id in entry_ids:
                e = _entry(cur, entry_id)
                if not e or e["status"] != OPEN or _is_bought(cur, e):
                    continue
                if e["recipe_id"]:
                    name = _recipe(cur, e["recipe_id"])[0]["name"]
                    want = min(float(household), e["qty"])
                    cur.execute("SELECT COALESCE(SUM(portions), 0) FROM meals.fridge WHERE recipe_id = %s "
                                "AND portions > 0 AND eat_by >= CURRENT_DATE", (e["recipe_id"],))
                    if float(cur.fetchone()[0]) >= want - 1e-9:
                        out["fridge_short"] += _eat_leftovers(cur, e, household)
                        out["fridge"].append(name)
                    else:
                        out["short"] += _cook(cur, e, household, packs)
                        out["cooked"].append(name)
                elif e["ingredient_id"]:
                    _eaten(cur, e, packs)
                    out["eaten"].append(e["ingredient_id"])
        return out
    return _run(work)


def untick_meal(entry_ids):
    """Put the pantry, fridge and any payment back for every ticked dish of a meal."""
    def work(conn):
        with conn.cursor() as cur:
            for entry_id in entry_ids:
                e = _entry(cur, entry_id)
                if not e or e["status"] == OPEN:
                    continue
                _reverse(cur, e)
                cur.execute("UPDATE meals.plan SET status = 'planned', done_at = NULL, done_by = NULL, undo = NULL "
                            "WHERE id = %s", (e["id"],))
    _run(work, money=True)


def _buy(cur, entries, paid, account, category):
    """One payment for the bought food in a meal (kenkey and fried fish together are one expense).
    The amount is shared between the dishes by their usual prices, to keep each dish's price up to date."""
    from core.data import SHARED
    from meals.units import frac, plural

    rows = []
    for e in entries:
        if e["recipe_id"]:
            cur.execute("SELECT name, count_unit, shop, price FROM meals.recipes WHERE id = %s", (e["recipe_id"],))
            name, unit, shop, before = cur.fetchone()
        else:
            name, unit, shop, before = e["label"], e["unit"], None, None
        expected = float(e["price"] or before or 0) * float(e["qty"])
        rows.append((e, name, unit or "portion", shop, before, expected))
    when = min(min(e["day"] for e in entries), date.today())
    shops = list(dict.fromkeys(r[3] for r in rows if r[3]))
    note = "Bought: " + " + ".join(f"{name} ({frac(e['qty'])} {plural(unit, e['qty'])})" for e, name, unit, *_ in rows) \
        + (f" at {', '.join(shops)}" if shops else "")
    cur.execute("INSERT INTO transactions (date, type, category, amount, note, member, account, created_by) "
                "VALUES (%s, 'Expense', %s, %s, %s, %s, %s, %s) RETURNING id",
                (when, category, round(float(paid), 2), note, SHARED, account, _me()))
    tx = cur.fetchone()[0]
    total_expected = sum(r[5] for r in rows)
    for e, name, unit, shop, before, expected in rows:
        share = float(paid) * (expected / total_expected if total_expected else 1 / len(rows))
        cur.execute("INSERT INTO meals.bought (date, plan_id, recipe_id, label, qty, unit, paid, shop) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (when, e["id"], e["recipe_id"], name, e["qty"], unit, round(share, 2), shop))
        bought_id = cur.fetchone()[0]
        if e["recipe_id"] and e["qty"]:
            cur.execute("UPDATE meals.recipes SET price = %s WHERE id = %s",
                        (round(share / float(e["qty"]), 2), e["recipe_id"]))
        undo = {"tx": tx, "bought": bought_id, "price_before": float(before) if before is not None else None}
        cur.execute("UPDATE meals.plan SET status = 'bought', done_at = now(), done_by = %s, undo = %s WHERE id = %s",
                    (_me(), json.dumps(undo), e["id"]))
    return tx


def mark_bought(entry_id, paid, account, category):
    """Bought food was bought: the payment goes into the money records as an expense, the price is remembered
    for next time (and for price trends), and unticking takes it all back out.
    entry_id can be a list: the bought dishes of one meal are paid for together, as one expense."""
    ids = entry_id if isinstance(entry_id, (list, tuple)) else [entry_id]

    def work(conn):
        with conn.cursor() as cur:
            entries = [e for e in (_entry(cur, i) for i in ids) if e and e["status"] == OPEN]
            if not entries:
                return None
            return _buy(cur, entries, paid, account, category)
    return _run(work, money=True)


def _reverse(cur, e):
    """Undo what ticking this entry did to the pantry and fridge (or, for bought food, the payment)."""
    undo = e["undo"] or {}
    if undo.get("tx"):  # a shared payment (several bought dishes in one meal) is deleted by the first one
        cur.execute("DELETE FROM transactions WHERE id = %s", (undo["tx"],))
        cur.execute("DELETE FROM meals.bought WHERE id = %s", (undo.get("bought"),))
        if e.get("recipe_id") and "price_before" in undo:
            cur.execute("UPDATE meals.recipes SET price = %s WHERE id = %s", (undo["price_before"], e["recipe_id"]))
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
    _run(work, money=True)


# ---- the plan ---------------------------------------------------------------------------------
def add_to_plan(day, slot, recipe_id=None, ingredient_id=None, qty=1, unit=None, label=None, price=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO meals.plan (day, slot, recipe_id, ingredient_id, qty, unit, label, price) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (day, slot, recipe_id, ingredient_id, qty, unit, label, price))
    _run(work)


def add_many(entries):
    """Add several plan entries at once (dicts with day, slot, recipe_id, ingredient_id, qty, unit)."""
    def work(conn):
        with conn.cursor() as cur:
            for e in entries:
                cur.execute("INSERT INTO meals.plan (day, slot, recipe_id, ingredient_id, qty, unit, label, price) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                            (e["day"], e["slot"], e.get("recipe_id"), e.get("ingredient_id"), e["qty"], e.get("unit"),
                             e.get("label"), e.get("price")))
        return len(entries)
    return _run(work)


def remove_from_plan(entry_id):
    """Remove a dish (or, given a list, every dish of a meal) from the plan."""
    ids = entry_id if isinstance(entry_id, (list, tuple)) else [entry_id]

    def work(conn):
        with conn.cursor() as cur:
            for i in ids:
                e = _entry(cur, i)
                if e and e["status"] != OPEN:
                    _reverse(cur, e)  # removing a ticked meal puts its ingredients and portions back
                cur.execute("DELETE FROM meals.plan WHERE id = %s", (i,))
    _run(work, money=True)


def set_household(n):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = "
                        "EXCLUDED.value", (HOUSEHOLD_KEY, str(int(n))))
    _run(work)


# ---- ingredients and recipes -------------------------------------------------------------------
def add_ingredient(name, unit, category, low_level=None, pack_name=None, pack_size=None, kind="food", loose=False,
                   section=None):
    """pack_size is in the base unit (e.g. 30 for a crate of eggs, 5000 for a 5 kg bag of rice).
    kind: 'food', or 'household' for cleaning things, toilet roll and other supplies."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level, pack_name, pack_size, kind, "
                        "loose, section) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (name.strip(), unit, category, low_level, pack_name or None, pack_size or None, kind,
                         bool(loose), section or None))
            return cur.fetchone()[0]
    return _run(work)


SUPPLIES_CATEGORY, SUPPLIES_GROUP = "Cleaning supplies", "Household"


def ensure_supplies_category(cur):
    """The money category household supplies are logged under, created the first time it's needed."""
    cur.execute("INSERT INTO categories (name, group_name, kind) VALUES (%s, %s, 'Expense') ON CONFLICT (name) DO NOTHING",
                (SUPPLIES_CATEGORY, SUPPLIES_GROUP))


def add_supply(name, unit, category, low_level=None, pack_name=None, pack_size=None):
    def work(conn):
        with conn.cursor() as cur:
            ensure_supplies_category(cur)
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level, pack_name, pack_size, kind) "
                        "VALUES (%s, %s, %s, %s, %s, %s, 'household') RETURNING id",
                        (name.strip(), unit, category or SUPPLIES_CATEGORY, low_level, pack_name or None,
                         pack_size or None))
            return cur.fetchone()[0]
    return _run(work, money=True)


def load_supplies_starter():
    """The everyday cleaning things most homes keep, ready to count. Skips names already there."""
    from meals.starter import SUPPLIES
    from meals.units import to_base

    def work(conn):
        added = 0
        with conn.cursor() as cur:
            ensure_supplies_category(cur)
            for name, unit, low, pack, size in SUPPLIES:
                cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level, pack_name, pack_size, kind) "
                            "VALUES (%s, %s, %s, %s, %s, %s, 'household') ON CONFLICT (name) DO NOTHING",
                            (name, unit, SUPPLIES_CATEGORY, to_base(low, unit)[0] if low is not None else None,
                             pack, to_base(size, unit)[0] if size else None))
                added += cur.rowcount
        return added
    return _run(work, money=True)


def set_budget(category, limit):
    from core.db import execute
    execute("INSERT INTO budgets (category, monthly_limit) VALUES (%s, %s) "
            "ON CONFLICT (category) DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit", (category, float(limit)))


def update_ingredient(ing_id, name, unit, category, low_level, pack_name=None, pack_size=None, loose=None,
                      section=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE meals.ingredients SET name = %s, unit = %s, category = %s, low_level = %s, "
                        "pack_name = %s, pack_size = %s, loose = COALESCE(%s, loose), section = COALESCE(%s, section) "
                        "WHERE id = %s",
                        (name.strip(), unit, category, low_level, pack_name or None, pack_size or None, loose,
                         section or None, ing_id))
    _run(work)


def save_recipe(recipe_id, name, portions, keeps_days, prep_note, prep_hours, method, lines, role="main"):
    """Create or update a recipe and replace its ingredient lines [(ingredient_id, qty, unit)]. Returns its id.
    role: starch, soup, stew, sauce, side or main (see logic.ROLES)."""
    def work(conn):
        with conn.cursor() as cur:
            fields = (name.strip(), round(float(portions), 2), int(keeps_days), prep_note or None, prep_hours or None,
                      method or None, role or "main")
            if recipe_id:
                cur.execute("UPDATE meals.recipes SET name=%s, portions=%s, keeps_days=%s, prep_note=%s, prep_hours=%s, "
                            "method=%s, role=%s, bought=FALSE WHERE id=%s", fields + (recipe_id,))
                rid = recipe_id
                cur.execute("DELETE FROM meals.recipe_items WHERE recipe_id = %s", (rid,))
            else:
                cur.execute("INSERT INTO meals.recipes (name, portions, keeps_days, prep_note, prep_hours, method, role) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", fields)
                rid = cur.fetchone()[0]
            for ing, qty, unit in lines:
                cur.execute("INSERT INTO meals.recipe_items (recipe_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (rid, ing, qty, unit))
            return rid
    return _run(work)


def save_bought_dish(recipe_id, name, count_unit, price, shop, category):
    """A dish bought ready-made (kenkey, waakye…): no ingredients, a usual price per unit. Returns its id."""
    def work(conn):
        with conn.cursor() as cur:
            fields = (name.strip(), count_unit or "portion", round(float(price), 2) if price else None, shop or None,
                      category or None)
            if recipe_id:
                cur.execute("UPDATE meals.recipes SET name=%s, count_unit=%s, price=%s, shop=%s, category=%s, bought=TRUE "
                            "WHERE id=%s", fields + (recipe_id,))
                cur.execute("DELETE FROM meals.recipe_items WHERE recipe_id = %s", (recipe_id,))
                return recipe_id
            cur.execute("INSERT INTO meals.recipes (name, count_unit, price, shop, category, bought, portions, keeps_days) "
                        "VALUES (%s, %s, %s, %s, %s, TRUE, 1, 1) RETURNING id", fields)
            return cur.fetchone()[0]
    return _run(work)


def recipe_delete_statements(recipe_id, name):
    """Deleting a recipe: meals not yet cooked come off the plan; meals already cooked or bought stay in the
    history under the dish's name (the database would otherwise delete them with it), and pairings that
    would be left with a single dish go too."""
    return [
        ("DELETE FROM meals.plan WHERE recipe_id = %s AND status = 'planned'", (recipe_id,)),
        ("UPDATE meals.plan SET label = %s, recipe_id = NULL WHERE recipe_id = %s", (name[:80], recipe_id)),
        ("DELETE FROM meals.recipes WHERE id = %s", (recipe_id,)),
        ("DELETE FROM meals.pairings p WHERE (SELECT count(*) FROM meals.pairing_items i WHERE i.pairing_id = p.id) < 2",
         None),
    ]


def ingredient_delete_statements(ingredient_id, name):
    """Deleting an item: like a recipe, it comes off the plan where it hasn't been had yet, and stays in the
    history (by name) where it has, however old. Its stock and prices go with it; a pairing that used it as a
    side is removed if that leaves fewer than two parts."""
    return [
        ("DELETE FROM meals.plan WHERE ingredient_id = %s AND status = 'planned'", (ingredient_id,)),
        ("UPDATE meals.plan SET label = COALESCE(label, %s), ingredient_id = NULL WHERE ingredient_id = %s",
         (name[:80], ingredient_id)),
        ("DELETE FROM meals.ingredients WHERE id = %s", (ingredient_id,)),
        ("DELETE FROM meals.pairings p WHERE (SELECT count(*) FROM meals.pairing_items i WHERE i.pairing_id = p.id) < 2",
         None),
    ]


# ---- pairings ---------------------------------------------------------------------------------------
def save_pairing(pairing_id, name, recipe_ids, side=None):
    """Create or replace a pairing for the planner: its dishes, and optionally a side item eaten with it
    as (ingredient_id, amount per person, unit). Returns its id."""
    def work(conn):
        with conn.cursor() as cur:
            if pairing_id:
                cur.execute("UPDATE meals.pairings SET name = %s WHERE id = %s", (name.strip(), pairing_id))
                cur.execute("DELETE FROM meals.pairing_items WHERE pairing_id = %s", (pairing_id,))
                pid = pairing_id
            else:
                cur.execute("INSERT INTO meals.pairings (name) VALUES (%s) RETURNING id", (name.strip(),))
                pid = cur.fetchone()[0]
            for rid in recipe_ids:
                cur.execute("INSERT INTO meals.pairing_items (pairing_id, recipe_id) VALUES (%s, %s)", (pid, rid))
            if side:
                cur.execute("INSERT INTO meals.pairing_items (pairing_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (pid, side[0], side[1], side[2]))
            return pid
    return _run(work)


def load_catalog():
    """Add (again) whatever is missing from the Ghanaian kitchen catalog, templates and pairings.
    Returns (recipes added, pairings added)."""
    from meals.catalog import CATALOG, TEMPLATES, add_items, add_pairings, add_recipes

    def work(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM categories WHERE kind = 'Expense' ORDER BY id")
            add_items(cur, CATALOG, [r[0] for r in cur.fetchall()])
            return add_recipes(cur, TEMPLATES), add_pairings(cur)
    return _run(work)


# ---- fridge and pantry -------------------------------------------------------------------------
def eat_portion(batch_id, amount=1.0):
    """One portion eaten from the fridge. Taken off what's there now, not what the screen showed, so two
    people tapping at once both count."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE meals.fridge SET portions = GREATEST(portions - %s, 0) WHERE id = %s",
                        (float(amount), batch_id))
    _run(work)


def adjust_stock(ing, base, delta):
    """Add to (or take from) what's in the pantry now: one more bottle, one roll used up."""
    def work(conn):
        with conn.cursor() as cur:
            _add_stock(cur, ing, base, float(delta))
    _run(work)


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
            cur.execute("UPDATE meals.fridge SET portions = GREATEST(portions - %s, 0) WHERE id = %s", (gone, batch_id))
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
    trip, changes = _run(work, money=True)  # the money side changed too
    return trip, {c: round(sum(i["price"] for i in items), 2) for c, items in by_cat.items()}, changes


def describe_short(short, names, usual=None):
    usual = usual or {}
    return ", ".join(f"{fmt(q, base, usual.get(ing))} {names.get(ing, '?')}".replace(" pcs", "") for ing, base, q in short)

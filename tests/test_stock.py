"""Pantry stock when meals are ticked off: what's taken, in which unit, what happens when there isn't enough,
and that it's saved for good. No browser needed."""
from datetime import datetime

import psycopg2
import pytest

from conftest import q


def _id(conn, table, name):
    return q(conn, f"SELECT id FROM meals.{table} WHERE name = %s", (name,))[0][0]


def _stock(conn, ing, base):
    row = q(conn, "SELECT qty FROM meals.pantry WHERE ingredient_id = %s AND unit = %s", (ing, base))
    return float(row[0][0]) if row else 0.0


@pytest.fixture
def kokonte_lunch(conn):
    """Kokonte + Groundnut soup planned for today's lunch, with 10 cups of kokonte powder and only 300 g of the
    500 g of groundnut paste the soup needs. Everything put back afterwards."""
    kp, gp = _id(conn, "ingredients", "Kokonte powder"), _id(conn, "ingredients", "Groundnut paste")
    saved = q(conn, "SELECT ingredient_id, unit, qty FROM meals.pantry WHERE ingredient_id IN (%s, %s)", (kp, gp))
    q(conn, "DELETE FROM meals.pantry WHERE ingredient_id IN (%s, %s)", (kp, gp))
    q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, 'ml', 2500), (%s, 'g', 300)", (kp, gp))
    aside = [r[0] for r in q(conn, "UPDATE meals.plan SET day = DATE '2000-01-01' WHERE day = CURRENT_DATE "
                                   "AND slot = 'Lunch' RETURNING id")]
    ids = [r[0] for r in q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES "
                                 "(CURRENT_DATE, 'Lunch', %s, 2), (CURRENT_DATE, 'Lunch', %s, 14) RETURNING id",
                           (_id(conn, "recipes", "Kokonte"), _id(conn, "recipes", "Groundnut soup")))]
    yield {"ids": ids, "kokonte": kp, "groundnut": gp}
    q(conn, "DELETE FROM meals.fridge WHERE plan_id = ANY(%s)", (ids,))
    q(conn, "DELETE FROM meals.plan WHERE id = ANY(%s)", (ids,))
    q(conn, "DELETE FROM meals.pantry WHERE ingredient_id IN (%s, %s)", (kp, gp))
    for ing, unit, qty in saved:
        q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, %s, %s)", (ing, unit, qty))
    if aside:
        q(conn, "UPDATE meals.plan SET day = CURRENT_DATE WHERE id = ANY(%s)", (aside,))


def _kitchen(conn):
    from meals.data import Kitchen, _load
    return Kitchen(_load(conn))


def test_ticking_a_combo_takes_each_dish_off_the_pantry_and_it_stays_saved(live_db, conn, db_url, kokonte_lunch):
    from meals.actions import mark_meal
    out = mark_meal(kokonte_lunch["ids"], household=2)
    assert sorted(out["cooked"]) == ["Groundnut soup", "Kokonte"]

    # read back on a brand-new connection: the change was committed, so a refresh can't undo it
    fresh = psycopg2.connect(db_url)
    try:
        assert _stock(fresh, kokonte_lunch["kokonte"], "ml") == 2125, \
            "the recipe's 1½ cups (375 ml) of kokonte powder came off the 10 cups (2,500 ml)"
        assert _stock(fresh, kokonte_lunch["groundnut"], "g") == 0, "all 300 g of the paste was used"
    finally:
        fresh.close()
    shown = _kitchen(conn)
    assert shown.pantry[(kokonte_lunch["kokonte"], "ml")] == 2125
    from meals.units import fmt
    assert fmt(2125, "ml", "cup") == "8½ cups", "the pantry shows it back in cups: 10 − 1½"


def test_what_the_pantry_didnt_have_is_flagged_until_it_is_bought(live_db, conn, kokonte_lunch):
    from meals.actions import mark_meal
    from meals.briefing import morning
    from meals.logic import shopping_list
    from meals.pages.shopping import ran_out_needs
    out = mark_meal(kokonte_lunch["ids"], household=2)
    gp = kokonte_lunch["groundnut"]
    assert (gp, "g", 200.0) in out["short"], "the soup needed 500 g; only 300 g was there"

    k = _kitchen(conn)
    short = k.ran_short()
    assert short[(gp, "g")]["short"] == 200 and short[(gp, "g")]["for"] == ["Kokonte + Groundnut soup"]
    assert (kokonte_lunch["kokonte"], "ml") not in short, "enough kokonte powder: nothing flagged"

    text = morning(k, None, datetime.now())
    lines = text.split("\n")
    assert not any("Ran out" in x for x in lines), "listed once, on the shopping line, not again as a heads-up"
    food = next(x for x in lines if x.startswith("• Pantry / Food: "))
    assert "Groundnut paste (200 g)" in food, "it goes on the morning shopping line"
    assert any("Ran out" in t for _, t in k.notes()), "and on the meal plan's reminders"

    rows = {r["ingredient_id"]: r for r in shopping_list(ran_out_needs(k, k.window()[0]), {}, packs=k.packs)}
    assert rows[gp]["reason"] == "Ran out when cooking Kokonte + Groundnut soup"
    assert rows[gp]["pack"] == "jar" and rows[gp]["packs"] == 1, "groundnut paste comes in 500 g jars"

    q(conn, "UPDATE meals.pantry SET qty = 500 WHERE ingredient_id = %s AND unit = 'g'", (gp,))  # bought a jar
    assert (gp, "g") not in _kitchen(conn).ran_short(), "restocked: the warning goes away by itself"


def test_unticking_puts_the_stock_back_and_clears_the_warning(live_db, conn, kokonte_lunch):
    from meals.actions import mark_meal, untick_meal
    mark_meal(kokonte_lunch["ids"], household=2)
    untick_meal(kokonte_lunch["ids"])
    assert _stock(conn, kokonte_lunch["kokonte"], "ml") == 2500 and _stock(conn, kokonte_lunch["groundnut"], "g") == 300
    assert (kokonte_lunch["groundnut"], "g") not in _kitchen(conn).ran_short()


def test_a_plain_item_says_when_it_wasnt_there(live_db, conn):
    from meals.actions import mark_done
    gari = _id(conn, "ingredients", "Gari")
    saved = q(conn, "SELECT unit, qty FROM meals.pantry WHERE ingredient_id = %s", (gari,))
    q(conn, "DELETE FROM meals.pantry WHERE ingredient_id = %s", (gari,))
    q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, 'ml', 250)", (gari,))  # 1 cup
    e = q(conn, "INSERT INTO meals.plan (day, slot, ingredient_id, qty, unit) VALUES (CURRENT_DATE - 1, 'Supper', %s, "
                "2, 'cup') RETURNING id", (gari,))[0][0]
    try:
        assert mark_done(e) == [(gari, "ml", 250.0)], "2 cups wanted, 1 cup there: 1 cup short"
        assert _stock(conn, gari, "ml") == 0
        assert _kitchen(conn).ran_short()[(gari, "ml")]["short"] == 250
    finally:
        q(conn, "DELETE FROM meals.plan WHERE id = %s", (e,))
        q(conn, "DELETE FROM meals.pantry WHERE ingredient_id = %s", (gari,))
        for unit, qty in saved:
            q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, %s, %s)", (gari, unit, qty))


def test_a_recipe_in_the_wrong_unit_is_named_not_silently_skipped(live_db, conn, kokonte_lunch):
    """Kokonte powder is counted in cups (ml). A recipe line in grams can't be converted, so cooking can't take
    it off: that must be said, and it mustn't be put on the shopping list as if it had run out."""
    from meals.actions import mark_cooked
    kp = kokonte_lunch["kokonte"]
    rid = q(conn, "INSERT INTO meals.recipes (name, portions) VALUES ('Test kokonte by weight', 2) RETURNING id")[0][0]
    q(conn, "INSERT INTO meals.recipe_items (recipe_id, ingredient_id, qty, unit) VALUES (%s, %s, 300, 'g')", (rid, kp))
    e = q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (CURRENT_DATE - 1, 'Breakfast', %s, 2) "
                "RETURNING id", (rid,))[0][0]
    try:
        assert mark_cooked(e, 2) == [(kp, "g", 300.0)]
        assert _stock(conn, kp, "ml") == 2500, "untouched: grams can't come off a stock kept in cups"
        k = _kitchen(conn)
        assert k.ran_short()[(kp, "g")]["mismatch"] == "ml"
        note = next(t for _, t in k.notes() if "wasn't taken off" in t)
        assert note == ("Kokonte powder wasn't taken off the pantry: the recipe uses g, the pantry uses cups. "
                        "Fix the unit in the recipe.")
        from meals.pages.shopping import ran_out_needs
        assert (kp, "g") not in ran_out_needs(k, k.window()[0]), "there's plenty in the pantry: nothing to buy"
    finally:
        q(conn, "DELETE FROM meals.plan WHERE id = %s", (e,))
        q(conn, "DELETE FROM meals.recipes WHERE id = %s", (rid,))

"""The meal planner end to end: recipes, the weekly plan, the shopping list, the pantry and fridge,
and groceries landing in the money tracker. Runs after test_app.py on the same database."""
from datetime import date, timedelta

import pytest

from conftest import OWNER, q
from core.auth import hash_password
from helpers import chip, go, no_errors, settle, sign_in, toasts

pytestmark = pytest.mark.browser
JOLLOF, REDRED = "Jollof rice with chicken", "Red red"


@pytest.fixture(scope="module", autouse=True)
def owner_exists(conn):
    """Lets this file run on its own too."""
    if not q(conn, "SELECT 1 FROM users WHERE username = %s", (OWNER[0],)):
        q(conn, "INSERT INTO users (username, display_name, password_hash, is_owner) VALUES (%s, %s, %s, TRUE)",
          (OWNER[0], OWNER[1], hash_password(OWNER[2])))


def recipe_id(conn, name):
    return q(conn, "SELECT id FROM meals.recipes WHERE name = %s", (name,))[0][0]


def ing_id(conn, name):
    return q(conn, "SELECT id FROM meals.ingredients WHERE name = %s", (name,))[0][0]


def stock(conn, name, unit):
    row = q(conn, "SELECT qty FROM meals.pantry WHERE ingredient_id = %s AND unit = %s", (ing_id(conn, name), unit))
    return float(row[0][0]) if row else 0.0


def pick(page, label, text):
    page.get_by_role("combobox", name=label).click()
    page.keyboard.type(text)
    page.keyboard.press("Enter")
    settle(page)


def add_to_plan(page, day, slot, recipe, portions=None):
    chip(page, "Today" if day == date.today() else f"{day:%a %d}", within=".st-key-card-meal-add").click()
    settle(page, 500)
    chip(page, slot, within=".st-key-card-meal-add").click()
    settle(page, 500)
    pick(page, "Recipe", recipe)
    if portions:
        n = page.get_by_role("spinbutton", name="Portions to cook")
        n.fill(str(portions))
        n.press("Enter")
        settle(page)
    page.locator(".st-key-card-meal-add").get_by_role("button", name="Add to").click()
    settle(page, 2000)
    no_errors(page)


def next7(page):
    page.locator('[data-testid="stButtonGroup"]').get_by_text("Next 7 days").click()
    settle(page, 1500)


def test_starter_recipes(desktop, app_url, conn):
    sign_in(desktop, app_url, path="recipes")
    desktop.get_by_role("button", name="Add starter recipes").click()
    settle(desktop, 2500)
    no_errors(desktop)
    assert q(conn, "SELECT count(*) FROM meals.recipes")[0][0] == 6
    body = desktop.inner_text("body")
    assert JOLLOF in body and "keeps 3 days" in body
    # each ingredient points at one of the family's money categories
    cats = {r[0] for r in q(conn, "SELECT name FROM categories WHERE kind = 'Expense'")}
    assert {r[0] for r in q(conn, "SELECT DISTINCT category FROM meals.ingredients")} <= cats


def test_plan_and_shopping_totals(desktop, app_url, conn):
    """Jollof (3 onions) + Red red doubled to 8 portions (2 x 2 onions) = 7 onions on the list."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    sign_in(desktop, app_url, path="meals")
    add_to_plan(desktop, today, "Supper", JOLLOF)
    if tomorrow.weekday() == 0:  # tomorrow is in next week's view
        desktop.locator('[data-testid="stButtonGroup"]').get_by_text("Next week").click()
        settle(desktop, 2000)
    add_to_plan(desktop, tomorrow, "Lunch", REDRED, portions=8)
    assert q(conn, "SELECT count(*) FROM meals.plan")[0][0] == 2

    q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, 'pcs', 2)", (ing_id(conn, "Onions"),))
    go(desktop, "Shopping list")
    next7(desktop)
    # the list itself is drawn on a canvas, so check the sums through the page's share text
    desktop.get_by_text("Share the list").click()
    settle(desktop, 600)
    share = desktop.locator('[data-testid="stCode"]').first.inner_text()
    assert "- Onions: 5" in share, share          # 3 + 4 needed, 2 already in the pantry
    assert "- Rice: 750 g" in share, share        # jollof's 750 g
    assert "- Black-eyed beans: 1 kg" in share, share  # 500 g doubled
    assert "- Palm oil: 300 ml" in share, share   # 150 ml doubled


def test_shopping_trip_becomes_expenses(desktop, app_url, conn):
    # remembered prices fill in the price column, so the whole list can be saved in one tap
    for name, per_unit in [("Onions", 2.0), ("Rice", 0.03), ("Black-eyed beans", 0.025), ("Palm oil", 0.04)]:
        q(conn, "INSERT INTO meals.prices (ingredient_id, unit, per_unit) SELECT id, CASE WHEN unit IN ('kg','g') "
                "THEN 'g' WHEN unit IN ('l','ml') THEN 'ml' ELSE unit END, %s FROM meals.ingredients WHERE name = %s",
          (per_unit, name))
    q(conn, "INSERT INTO meals.prices (ingredient_id, unit, per_unit) SELECT i.id, CASE WHEN i.unit IN ('kg','g') THEN 'g' "
            "WHEN i.unit IN ('l','ml','cup','tbsp','tsp') THEN 'ml' ELSE i.unit END, 1 FROM meals.ingredients i "
            "ON CONFLICT DO NOTHING")
    before_tx = q(conn, "SELECT count(*) FROM transactions")[0][0]
    sign_in(desktop, app_url, path="shopping")
    next7(desktop)
    btn = desktop.get_by_role("button", name="Save trip")
    assert btn.is_enabled()
    label = btn.inner_text()
    btn.click()
    settle(desktop, 3000)
    no_errors(desktop)
    trip_total = float(q(conn, "SELECT total FROM meals.trips ORDER BY id DESC LIMIT 1")[0][0])
    assert f"GH₵{trip_total:,.2f}" in label
    rows = q(conn, "SELECT category, amount, account, note FROM transactions WHERE note LIKE 'Groceries (trip%%' ")
    assert len(rows) == q(conn, "SELECT count(*) FROM transactions")[0][0] - before_tx
    assert len({r[0] for r in rows}) == len(rows), "one expense per category"
    assert round(sum(float(r[1]) for r in rows), 2) == trip_total
    assert {"Fruits/Veges", "Staples", "Oils"} <= {r[0] for r in rows}
    assert stock(conn, "Onions", "pcs") == 7, "bought 5 on top of the 2 we had"
    assert stock(conn, "Rice", "g") == 750
    msgs = toasts(desktop)  # the short "Saved" note may already have faded; budget warnings stay longer
    assert "Saved GH₵" in msgs or "budget" in msgs, msgs
    # what was bought is off the list now (only staples that are running low may remain)
    body = desktop.inner_text("body")
    if "the pantry already covers" not in body:
        desktop.get_by_text("Share the list").click()
        settle(desktop, 600)
        share = desktop.locator('[data-testid="stCode"]').first.inner_text()
        for bought in ("Onions", "Black-eyed beans", "Chicken", "Tomatoes"):
            assert f"- {bought}:" not in share, share


def test_cooking_uses_the_pantry_and_fills_the_fridge(desktop, app_url, conn):
    sign_in(desktop, app_url, path="meals")
    if (date.today() + timedelta(days=1)).weekday() == 0:
        desktop.locator('[data-testid="stButtonGroup"]').get_by_text("Next week").click()
        settle(desktop, 2000)
    red = q(conn, "SELECT id FROM meals.plan WHERE recipe_id = %s", (recipe_id(conn, REDRED),))[0][0]
    desktop.locator(f".st-key-meal-entry-{red}").locator("[data-testid=stCheckbox] label").click()
    settle(desktop, 2500)
    no_errors(desktop)
    assert q(conn, "SELECT status FROM meals.plan WHERE id = %s", (red,)) == [("cooked",)]
    assert stock(conn, "Black-eyed beans", "g") == 0, "1 kg used for 8 portions"
    assert stock(conn, "Onions", "pcs") == 3, "7 minus 4"
    portions, eat_by = q(conn, "SELECT portions, eat_by FROM meals.fridge WHERE plan_id = %s", (red,))[0]
    assert float(portions) == 4, "8 cooked, 4 eaten at the meal"
    assert eat_by == date.today() + timedelta(days=2), "red red keeps 2 days"

    # unticking puts everything back exactly
    desktop.locator(f".st-key-meal-entry-{red}").locator("[data-testid=stCheckbox] label").click()
    settle(desktop, 2500)
    assert q(conn, "SELECT status FROM meals.plan WHERE id = %s", (red,)) == [("planned",)]
    assert stock(conn, "Black-eyed beans", "g") == 1000 and stock(conn, "Onions", "pcs") == 7
    assert float(q(conn, "SELECT portions FROM meals.fridge WHERE plan_id = %s", (red,))[0][0]) == 0

    desktop.locator(f".st-key-meal-entry-{red}").locator("[data-testid=stCheckbox] label").click()
    settle(desktop, 2500)
    go(desktop, "Fridge & pantry")
    assert REDRED in desktop.inner_text("body")


def test_leftovers_cover_a_later_meal(desktop, app_url, conn):
    later = date.today() + timedelta(days=2)
    q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (%s, 'Supper', %s, 4)",
      (later, recipe_id(conn, REDRED)))
    sign_in(desktop, app_url, path="meals")
    if later > date.today() - timedelta(days=date.today().weekday()) + timedelta(days=6):
        desktop.locator('[data-testid="stButtonGroup"]').get_by_text("Next week").click()
        settle(desktop, 2000)
    entry = q(conn, "SELECT id FROM meals.plan WHERE day = %s AND slot = 'Supper'", (later,))[0][0]
    desktop.locator(f".st-key-meal-entry-{entry}").get_by_role("button", name="Fridge (4)").click()
    settle(desktop, 2500)
    no_errors(desktop)
    assert q(conn, "SELECT status FROM meals.plan WHERE id = %s", (entry,)) == [("from_fridge",)]
    assert float(q(conn, "SELECT coalesce(sum(portions), 0) FROM meals.fridge WHERE recipe_id = %s",
                   (recipe_id(conn, REDRED),))[0][0]) == 0


def test_dashboard_shows_todays_meals(phone, app_url, conn):
    q(conn, "INSERT INTO meals.fridge (label, portions, cooked_on, eat_by) VALUES ('Shito', 1, %s, %s)",
      (date.today() - timedelta(days=3), date.today()))
    sign_in(phone, app_url)
    panel = phone.locator(".st-key-draft_open_meals")
    text = panel.inner_text()
    assert "Today's meals" in text and "reminder" in text
    assert JOLLOF in text, "today's supper is listed"
    assert "Eat the 1 portion of Shito by today" in text
    # the money side is untouched by the kitchen
    tiles = phone.locator(".kpi-grid .kpi")
    assert tiles.count() == 3


def test_pantry_stocktake(desktop, app_url, conn):
    sign_in(desktop, app_url, path="fridge")
    desktop.get_by_role("tab", name="Pantry").click()
    settle(desktop)
    no_errors(desktop)
    body = desktop.inner_text("body")
    assert "Pantry" in body and ("low" in body.lower())

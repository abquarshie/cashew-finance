"""The meal planner end to end: recipes, the two-week plan, the shopping list, the pantry and fridge,
and groceries landing in the money tracker. Runs after test_app.py on the same database."""
import re
from datetime import date, timedelta

import pytest

from conftest import OWNER, q
from core.auth import hash_password
from helpers import chip, go, no_errors, open_app, settle, sign_in, tab, toasts

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


def show_day(page, day):
    """Days after this week sit in a folded "Next week" / "Week after" section."""
    monday = date.today() - timedelta(days=date.today().weekday())
    if day - timedelta(days=day.weekday()) != monday:
        name = "Next week" if day - timedelta(days=day.weekday()) == monday + timedelta(days=7) else "Week after"
        page.locator('[data-testid="stExpander"] summary').filter(has_text=name).first.click()
        settle(page, 800)


def day_chip(day):
    today = date.today()
    return "Today" if day == today else ("Tomorrow" if day == today + timedelta(days=1) else f"{day:%a %d}")


def add_to_plan(page, day, slot, recipe, portions=None):
    if (day - date.today()).days >= 7:
        chip(page, "Days 8 to 14", within=".st-key-card-meal-add").click()
        settle(page, 600)
    chip(page, day_chip(day), within=".st-key-card-meal-add").click()
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
    add_to_plan(desktop, tomorrow, "Lunch", REDRED, portions=8)
    assert q(conn, "SELECT count(*) FROM meals.plan")[0][0] == 2

    q(conn, "INSERT INTO meals.pantry (ingredient_id, unit, qty) VALUES (%s, 'pcs', 2)", (ing_id(conn, "Onions"),))
    go(desktop, "Shopping list")
    next7(desktop)
    # the list itself is drawn on a canvas, so check the sums through the page's share text
    desktop.get_by_text("Share the list").click()
    settle(desktop, 600)
    share = desktop.locator('[data-testid="stCode"]').first.inner_text()
    assert "- Onions: 5" in share, share            # 3 + 4 needed, 2 already in the pantry
    assert "- Rice: 1 bag" in share, share          # 750 g needed; rice comes in 5 kg bags
    assert "- Black-eyed beans: 1 bag" in share, share  # 500 g doubled = 1 kg = one 1 kg bag
    assert "- Palm oil: 1 bottle" in share, share   # 150 ml doubled = 300 ml; sold in 1 l bottles
    assert "- Garlic: 3" in share, share            # loose items stay as counted


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
    desktop.locator('[data-testid="stButtonGroup"]').get_by_text("Table").click()  # everything ticked at once
    settle(desktop, 1500)
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
    assert stock(conn, "Rice", "g") == 5000, "a whole 5 kg bag"
    assert stock(conn, "Palm oil", "ml") == 1000, "a whole 1 l bottle"
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
    show_day(desktop, date.today() + timedelta(days=1))
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
    tab(desktop, "Fridge")
    assert REDRED in desktop.inner_text("body")


def test_leftovers_cover_a_later_meal(desktop, app_url, conn):
    later = date.today() + timedelta(days=2)
    q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (%s, 'Supper', %s, 4)",
      (later, recipe_id(conn, REDRED)))
    sign_in(desktop, app_url, path="meals")
    show_day(desktop, later)
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
    card = phone.locator(".st-key-card-today").inner_text()
    assert JOLLOF in card and "Supper" in card, card
    assert any(tag in card for tag in ("all in", "missing", "from the fridge")), "each dish says if it's in stock"
    assert phone.locator(".kpi-grid .kpi").count() == 2, "the money side is untouched by the kitchen"
    phone.locator(".st-key-card-today a").click()
    settle(phone, 2500)
    assert "/meals" in phone.url
    assert "Eat the 1 portion of Shito by today" in phone.inner_text("body"), "every reminder shows on the plan"


def test_copy_last_week(desktop, app_url, conn):
    src = date.today() - timedelta(days=4)
    target = src + timedelta(days=7)
    q(conn, "DELETE FROM meals.plan WHERE day = %s", (target,))
    q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty, status) VALUES (%s, 'Breakfast', %s, 4, 'cooked'), "
            "(%s, 'Lunch', %s, 2.5, 'cooked')", (src, recipe_id(conn, REDRED), src, recipe_id(conn, JOLLOF)))
    sign_in(desktop, app_url, path="meals")
    desktop.get_by_role("button", name=re.compile("from the week before|Copy the week before")).click()
    settle(desktop, 2500)
    no_errors(desktop)
    rows = q(conn, "SELECT slot, qty, status FROM meals.plan WHERE day = %s ORDER BY slot", (target,))
    assert [(r[0], float(r[1]), r[2]) for r in rows] == [("Breakfast", 4.0, "planned"), ("Lunch", 2.5, "planned")], \
        "copied as not-yet-cooked, half portions kept"
    assert not desktop.get_by_role("button", name=re.compile("week before")).count(), "nothing left to copy"


def test_plan_two_weeks_ahead(desktop, app_url, conn):
    later = date.today() + timedelta(days=10)
    sign_in(desktop, app_url, path="meals")
    body = desktop.inner_text("body")
    assert "This week" in body and "Next week" in body, "the next 14 days, grouped by week"
    add_to_plan(desktop, later, "Breakfast", JOLLOF, portions=2.5)
    rows = q(conn, "SELECT qty FROM meals.plan WHERE day = %s AND slot = 'Breakfast' ORDER BY id DESC", (later,))
    assert rows and float(rows[0][0]) == 2.5


def test_pantry_stocktake(desktop, app_url, conn):
    sign_in(desktop, app_url, path="fridge")
    desktop.get_by_role("tab", name="Pantry").click()
    settle(desktop)
    no_errors(desktop)
    body = desktop.inner_text("body")
    assert "Pantry" in body and ("low" in body.lower())


def test_market_mode_shop_and_price_changes(phone, app_url, conn):
    """Bread, eggs and tea needs 4 eggs: the list says 1 crate. Ticking items at the stall, entering prices
    and where, then saving."""
    q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (CURRENT_DATE + 2, 'Breakfast', %s, 4)",
      (recipe_id(conn, "Bread, eggs and tea"),))
    q(conn, "UPDATE meals.pantry SET qty = 0 WHERE ingredient_id IN (%s, %s)",  # the earlier trip bought a crate
      (ing_id(conn, "Eggs"), ing_id(conn, "Bread")))
    eggs_before = 0
    sign_in(phone, app_url, path="shopping")
    next7(phone)
    rows = phone.locator('[class*="st-key-meal-mk-"]')
    texts = [rows.nth(i).inner_text() for i in range(rows.count())]
    egg_i = next(i for i, t in enumerate(texts) if t.startswith("Eggs"))
    bread_i = next(i for i, t in enumerate(texts) if t.startswith("Bread"))
    assert "Eggs · 1 crate" in texts[egg_i], texts[egg_i]

    for i, price in ((egg_i, "65"), (bread_i, "15")):
        row = phone.locator(f".st-key-meal-mk-{i}")
        row.locator("[data-testid=stCheckbox] label").click()
        settle(phone)
        paid = row.get_by_role("spinbutton", name="Paid (GH₵)")
        paid.fill(price)
        paid.press("Enter")
        settle(phone)
    phone.get_by_role("combobox", name="Where (optional)").click()
    phone.keyboard.type("Makola")
    phone.keyboard.press("Enter")
    settle(phone)
    phone.get_by_role("button", name="Save trip · GH₵80.00").click()
    settle(phone, 3000)
    no_errors(phone)
    shop, total = q(conn, "SELECT shop, total FROM meals.trips ORDER BY id DESC LIMIT 1")[0]
    assert shop == "Makola" and float(total) == 80
    assert stock(conn, "Eggs", "pcs") == eggs_before + 30, "a crate is 30 eggs"
    notes = [r[0] for r in q(conn, "SELECT note FROM transactions WHERE note LIKE 'Groceries at Makola%%'")]
    assert notes, "the expense says where"
    assert "more than last time" in toasts(phone), "eggs cost far more than the remembered GH₵1 each"


def test_week_cost_and_ideas(desktop, app_url, conn):
    sign_in(desktop, app_url, path="meals")
    body = desktop.inner_text("body")
    assert "still to cook" in body and "of ingredients" in body, "the week's cost shows above the plan"
    before = q(conn, "SELECT count(*) FROM meals.plan")[0][0]
    ideas = desktop.locator('[class*="st-key-meal-idea-"]')
    assert ideas.count() >= 1
    ideas.first.get_by_role("button", name="Add").click()
    settle(desktop, 2000)
    no_errors(desktop)
    assert q(conn, "SELECT count(*) FROM meals.plan")[0][0] == before + 1


def test_waste_is_logged(desktop, app_url, conn):
    q(conn, "INSERT INTO meals.fridge (recipe_id, label, portions, cooked_on, eat_by, unit) "
            "VALUES (%s, 'Light soup with chicken', 2, CURRENT_DATE - 4, CURRENT_DATE - 1, 'bowl')",
      (recipe_id(conn, "Light soup with chicken"),))
    sign_in(desktop, app_url, path="fridge")
    batch = q(conn, "SELECT id FROM meals.fridge WHERE label = 'Light soup with chicken' AND unit = 'bowl'")[0][0]
    row = desktop.locator(f".st-key-meal-fr-{batch}")
    assert "2 bowls" in row.inner_text()
    row.get_by_role("button").last.click()   # the bin
    settle(desktop, 2500)
    no_errors(desktop)
    amount, unit, value = q(conn, "SELECT amount, unit, value FROM meals.waste ORDER BY id DESC LIMIT 1")[0]
    assert (float(amount), unit) == (2, "bowl")
    assert value is not None and float(value) > 0, "valued from the recipe's ingredient prices"
    assert "of food thrown away" in desktop.inner_text("body")


def test_reminder_settings_preview(desktop, app_url):
    sign_in(desktop, app_url, path="settings?tab_settings=Reminders")
    body = desktop.inner_text("body")
    assert "What gets sent" in body and "Good morning!" in body
    desktop.get_by_role("tab", name="Monthly report").click()
    settle(desktop)
    assert "in Cashew" in desktop.inner_text("body")


def test_whatsapp_and_price_trends(phone, app_url, conn):
    eggs = ing_id(conn, "Eggs")
    trip = q(conn, "INSERT INTO meals.trips (date, account, total, shop) VALUES (CURRENT_DATE - 45, 'Cash', 55, 'Makola') "
                   "RETURNING id")[0][0]
    q(conn, "INSERT INTO meals.trip_items (trip_id, ingredient_id, name, qty, unit, price, category) "
            "VALUES (%s, %s, 'Eggs', 30, 'pcs', 55, 'Dairy/Cereal')", (trip, eggs))
    q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (CURRENT_DATE + 3, 'Supper', %s, 4)",
      (recipe_id(conn, JOLLOF),))
    sign_in(phone, app_url, path="shopping")
    link = phone.get_by_role("link", name="Send the list on WhatsApp")
    assert link.count() and link.get_attribute("href").startswith("https://wa.me/?text=")
    phone.locator('[data-testid="stButtonGroup"]').get_by_text("Prices").click()
    settle(phone, 2500)
    no_errors(phone)
    assert phone.locator('[data-testid="stVegaLiteChart"], .vega-embed').count() >= 1, "eggs bought in two months"
    assert "Eggs (per crate)" in phone.inner_text("body")


def test_household_supplies_have_their_own_budget(desktop, app_url, conn):
    sign_in(desktop, app_url, path="meals?tab_meals=Household")
    desktop.get_by_role("button", name="Add common household items").click()
    settle(desktop, 2500)
    no_errors(desktop)
    kinds = dict(q(conn, "SELECT name, kind FROM meals.ingredients WHERE name IN ('Bleach', 'Rice')"))
    assert kinds == {"Bleach": "household", "Rice": "food"}
    assert q(conn, "SELECT group_name FROM categories WHERE name = 'Cleaning supplies'") == [("Household",)]

    bleach = ing_id(conn, "Bleach")
    desktop.locator(f".st-key-supply-{bleach}").get_by_role("button").last.click()   # + one bottle
    settle(desktop, 2000)
    assert stock(conn, "Bleach", "ml") == 1000, "one tap adds one 1 l bottle"

    box = desktop.get_by_role("spinbutton", name="Monthly limit (GH₵)")
    box.fill("300")
    box.press("Enter")
    settle(desktop)
    desktop.get_by_role("button", name="Set budget").click()
    settle(desktop, 2000)
    assert q(conn, "SELECT monthly_limit FROM budgets WHERE category = 'Household'") == [(300,)], \
        "a budget of its own, not part of food"

    go(desktop, "Shopping list")
    body = desktop.inner_text("body")
    assert "Toilet roll" in body and "Household" in body, "low supplies go on the list, marked as household"
    open_app(desktop, app_url, "meals?tab_meals=Recipes")
    desktop.get_by_role("tab", name="Ingredients").click()
    settle(desktop)
    assert "Bleach" not in desktop.inner_text("body"), "supplies never show among food ingredients"

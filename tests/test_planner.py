"""Pots that would go to waste, people per meal, and auto payments already spoken for. No browser needed."""
from datetime import date, timedelta

import pandas as pd
import pytest

from conftest import q
from meals import logic as ml

D = date(2026, 10, 19)  # a Monday
SOUP = {7: {"name": "Palm nut soup", "portions": 14, "keeps_days": 7, "prep_note": None, "prep_hours": None,
            "role": "soup"}}
SOUP_ITEMS = {7: [(41, 800, "g")]}


def plan(*entries):
    return [dict(status="planned", **e) for e in entries]


# ---- 1. a pot bigger than the plan eats ---------------------------------------------------------------
def test_a_pot_that_will_partly_go_off_is_spotted():
    # Monday: a whole pot for 2 people; the soup comes back on Wednesday only, then not again before it goes off
    e = plan({"id": 1, "day": D, "slot": "Lunch", "recipe_id": 7, "qty": 14},
             {"id": 2, "day": D + timedelta(days=2), "slot": "Lunch", "recipe_id": 7, "qty": 2})
    alloc = ml.allocate(e, SOUP, SOUP_ITEMS, {}, [], 2, D)
    pot = alloc["pots"][1]
    assert (pot["cooked"], pot["eaten"], pot["left"]) == (14, 4, 10), "2 eaten Monday, 2 Wednesday: 10 thrown away"
    assert pot["eat_by"] == D + timedelta(days=7)
    waste = ml.pot_waste(alloc, until=D + timedelta(days=13))
    assert [p["entry_id"] for p in waste] == [1]
    assert ml.suggested_pot(waste[0]) == 4, "cook what's eaten before it goes off"


def test_a_pot_eaten_all_week_is_fine():
    week = [{"id": i + 1, "day": D + timedelta(days=i), "slot": "Lunch", "recipe_id": 7, "qty": 14 if i == 0 else 2}
            for i in range(7)]
    alloc = ml.allocate(plan(*week), SOUP, SOUP_ITEMS, {}, [], 2, D)
    assert alloc["pots"][1]["left"] == 0 and ml.pot_waste(alloc, D + timedelta(days=13)) == []


def test_a_pot_that_goes_off_after_the_planned_fortnight_isnt_judged_yet():
    """Cooked on day 10, it keeps until day 17: meals still to be planned could eat it."""
    e = plan({"id": 1, "day": D + timedelta(days=10), "slot": "Lunch", "recipe_id": 7, "qty": 14})
    alloc = ml.allocate(e, SOUP, SOUP_ITEMS, {}, [], 2, D)
    assert alloc["pots"][1]["left"] == 12 and ml.pot_waste(alloc, until=D + timedelta(days=13)) == []


def test_the_plan_warns_about_a_big_pot_and_one_tap_makes_it_smaller(live_db, conn):
    from meals.actions import set_plan_qty
    from meals.data import Kitchen, _load
    rid = q(conn, "INSERT INTO meals.recipes (name, portions, keeps_days, role) VALUES ('Test pepper soup', 10, 3, "
                  "'soup') RETURNING id")[0][0]
    e = q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty, people) VALUES (CURRENT_DATE + 1, 'Supper', %s, "
                "10, 2) RETURNING id", (rid,))[0][0]
    try:
        k = Kitchen(_load(conn))
        w = next(p for p in k.pot_warnings() if p["entry_id"] == e)
        when = date.today() + timedelta(days=1)
        assert w["text"] == (f"Test pepper soup on {when:%a %d}: 10 portions cooked, but only 2 portions eaten before "
                             f"it goes off on {when + timedelta(days=3):%a %d}, so 8 portions would be thrown away. "
                             "Cook 2 portions, or plan it for more meals that week.")
        assert any(w["text"] == t for _, t in k.notes()), "cooked tomorrow: a reminder on the plan and in the morning"
        assert w["text"] in k.urgent()
        set_plan_qty(e, w["suggest"])
        assert all(p["entry_id"] != e for p in Kitchen(_load(conn)).pot_warnings()), "2 cooked, 2 eaten: nothing left"
    finally:
        q(conn, "DELETE FROM meals.plan WHERE id = %s", (e,))
        q(conn, "DELETE FROM meals.recipes WHERE id = %s", (rid,))


# ---- 2. people per meal --------------------------------------------------------------------------------
def test_each_meal_has_its_own_number_of_people():
    usual = {"Breakfast": 3, "Lunch": 1, "Supper": 3}
    assert ml.eaters({"slot": "Lunch"}, usual) == 1, "lunch is usually eaten at work"
    assert ml.eaters({"slot": "Lunch", "people": 5}, usual) == 5, "guests on one day win"
    assert ml.eaters({"slot": "Supper"}, 2) == 2, "a plain number still works"


def test_leftovers_follow_the_people_at_each_meal():
    """4 portions at lunch for 1 person: 3 go into the fridge and cover Tuesday's and Wednesday's lunch."""
    soup = {7: dict(SOUP[7], portions=4, keeps_days=3)}
    e = plan({"id": 1, "day": D, "slot": "Lunch", "recipe_id": 7, "qty": 4},
             {"id": 2, "day": D + timedelta(days=1), "slot": "Lunch", "recipe_id": 7, "qty": 1},
             {"id": 3, "day": D + timedelta(days=2), "slot": "Lunch", "recipe_id": 7, "qty": 2, "people": 2})
    alloc = ml.allocate(e, soup, SOUP_ITEMS, {}, [], {"Breakfast": 3, "Lunch": 1, "Supper": 3}, D)
    assert alloc["meals"][2]["status"] == alloc["meals"][3]["status"] == "leftovers"
    assert alloc["pots"][1]["eaten"] == 4 and alloc["pots"][1]["left"] == 0, "1 + 1 + 2 (guests on Wednesday)"


def test_cooking_keeps_what_the_people_at_that_meal_dont_eat(live_db, conn):
    from meals.actions import mark_cooked, set_meal_people, set_slot_people
    from meals.data import Kitchen, _load, slot_key
    rid = q(conn, "INSERT INTO meals.recipes (name, portions, keeps_days) VALUES ('Test jollof', 4, 2) "
                  "RETURNING id")[0][0]
    saved = q(conn, "SELECT key, value FROM app_meta WHERE key LIKE 'meals_people_%%'")
    a, b = (r[0] for r in q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES "
                                  "(CURRENT_DATE - 1, 'Lunch', %s, 4), (CURRENT_DATE - 1, 'Supper', %s, 4) "
                                  "RETURNING id", (rid, rid)))
    try:
        set_slot_people({"Breakfast": 3, "Lunch": 1, "Supper": 3})
        k = Kitchen(_load(conn))
        assert k.slot_people == {"Breakfast": 3, "Lunch": 1, "Supper": 3}
        mark_cooked(a, k.slot_people)
        assert float(q(conn, "SELECT portions FROM meals.fridge WHERE plan_id = %s", (a,))[0][0]) == 3, \
            "1 eats lunch: 3 of 4 portions into the fridge"
        set_meal_people(date.today() - timedelta(days=1), "Supper", 4)  # a visitor at supper
        assert Kitchen(_load(conn)).meal_people(date.today() - timedelta(days=1), "Supper") == 4
        mark_cooked(b, k.slot_people)
        assert not q(conn, "SELECT 1 FROM meals.fridge WHERE plan_id = %s", (b,)), "4 cooked, 4 eaten: none left"
    finally:
        q(conn, "DELETE FROM meals.fridge WHERE plan_id IN (%s, %s)", (a, b))
        q(conn, "DELETE FROM meals.plan WHERE id IN (%s, %s)", (a, b))
        q(conn, "DELETE FROM meals.recipes WHERE id = %s", (rid,))
        q(conn, "DELETE FROM app_meta WHERE key LIKE 'meals_people_%%'")
        for key, value in saved:
            q(conn, "INSERT INTO app_meta VALUES (%s, %s)", (key, value))
    assert slot_key("Lunch") == "meals_people_lunch"


def test_copying_last_week_keeps_a_meals_own_number():
    old = plan({"day": D - timedelta(days=7), "slot": "Supper", "recipe_id": 7, "qty": 6, "people": 6})
    assert ml.repeat_plan(old, D, horizon=1)[0]["people"] == 6


# ---- 3. auto payments already spoken for ------------------------------------------------------------
def _fake(everyday, budget_left, committed=0.0, committed_budget=0.0):
    from test_logic import _book_with
    return _book_with(everyday, 5000, budget_left, committed, committed_budget)


def _book(*args):
    return _fake(*args).spending_power(date.today())


@pytest.mark.parametrize("everyday,budget_left,committed,committed_budget,state,left", [
    (800, 900, 300, 0, "capped", 500),         # budgets allow 900, but 300 of the 800 is already spoken for
    (2000, 300, 0, 60, "ok", 240),             # a data bundle still to come uses 60 of the budgets
    (200, 900, 300, 0, "committed", -100),     # the Susu transfer will take more than is there
    (800, None, 300, 0, "no_budget", 500),     # no budgets: what's left after auto payments
    (-50, 900, 300, 0, "debt", -50),           # already overdrawn: said as it is
])
def test_the_banner_leaves_out_money_already_spoken_for(everyday, budget_left, committed, committed_budget, state,
                                                        left):
    p = _book(everyday, budget_left, committed, committed_budget)
    assert (p["state"], p["left"]) == (state, left)
    assert p["committed"] == committed and p["everyday"] == everyday


def test_the_morning_message_says_what_is_set_aside():
    from meals.briefing import money_lines
    lines = money_lines(_fake(800, 900, 300), date.today())
    assert lines[0] == ("• Total Budget Left for the Month: GH₵500.00 (budgets allow GH₵900.00, but that's all the "
                        "everyday accounts will hold after auto payments)")
    assert lines[1] == "• Set aside for auto payments still due this month: GH₵300.00 (Monthly Susu)"
    assert money_lines(_fake(200, 900, 300), date.today())[0] == (
        "• Total Budget Left for the Month: GH₵0.00 (auto payments still due this month take all the everyday "
        "money, GH₵100.00 short)")


def test_whats_committed_comes_from_the_auto_transactions(conn):
    """The sample data: Monthly Susu (GCB → Susu, 500) and a weekly 60 data bundle from Cash, both starting
    3 days from now, and a Utility budget the data bundle falls under."""
    from auto_rules import occurrence
    from core.data import Book, _load_frames
    b = Book(_load_frames(conn))
    today = date.today()
    month_end = pd.Period(today, "M").end_time.date()
    rules = {r["name"]: r for _, r in b.rules.iterrows()}
    data_days = []
    n = int(rules["Data bundle"]["run_count"])
    while occurrence(rules["Data bundle"]["start_date"], "Weekly", n) <= month_end:
        data_days.append(occurrence(rules["Data bundle"]["start_date"], "Weekly", n))
        n += 1
    susu_day = rules["Monthly Susu"]["next_date"]
    c = b.committed(today)
    mine = [i for i in c["items"] if i["name"] in ("Monthly Susu", "Data bundle")]
    expected = ([{"name": "Monthly Susu", "date": susu_day, "amount": 500.0}] if susu_day <= month_end else []) + \
        [{"name": "Data bundle", "date": d, "amount": 60.0} for d in data_days]
    assert sorted(mine, key=lambda i: (i["date"], i["name"])) == sorted(expected, key=lambda i: (i["date"], i["name"]))
    p = b.spending_power(today)
    assert p["free"] == pytest.approx(p["everyday"] - c["cash"])
    assert c["budget"] >= 60 * len(data_days), "data bundles count against the Utility budget; the Susu move doesn't"


def test_the_home_screen_line_names_each_payment():
    from views.dashboard import committed_text
    p = {"committed": 620.0, "committed_items": [{"name": "Monthly Susu", "date": D, "amount": 500.0},
                                                 {"name": "Data bundle", "date": D, "amount": 60.0},
                                                 {"name": "Data bundle", "date": D + timedelta(days=7), "amount": 60.0}]}
    assert committed_text(p) == ("After GH₵620.00 set aside for auto payments still to come this month: Monthly Susu "
                                 "(Mon 19), Data bundle (Mon 19, Mon 26).")
    assert committed_text({"committed": 0.0, "committed_items": []}) == ""

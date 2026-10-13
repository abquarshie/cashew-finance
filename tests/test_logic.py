"""Fast checks of the logic behind the app: no browser needed."""
from datetime import date, timedelta

import psycopg2
import pytest

from conftest import q
from core import auth, momo
from core.backup import decrypt, encrypt, export_zip, restore_zip
from core.data import Book, _load_frames


# ---- MoMo texts ----------------------------------------------------------------------
MOMO_SAMPLES = [
    ("Payment made for GHS 50.00 to KOFI MENSAH. Current Balance: GHS 120.50. Available Balance: GHS 120.50. "
     "Reference: lunch. Transaction ID: 51234567890. Fee charged: GHS 0.50 TAX charged: GHS 0.00.",
     dict(kind="Expense", amount=50.0, fee=0.5, balance=120.5, party="Kofi Mensah", reference="lunch", txn_id="51234567890")),
    ("Payment received for GHS 100.00 from AMA SERWAA Current Balance: GHS 220.50 . Available Balance: GHS 220.50. "
     "Reference: rent share. Transaction ID: 51234567891. TRANSACTION FEE: 0.00",
     dict(kind="Income", amount=100.0, fee=0.0, balance=220.5, party="Ama Serwaa", reference="rent share")),
    ("Cash Out made for GHS 200.00 to AGENT XYZ ENTERPRISE. Current Balance: GHS 20.50. Financial Transaction Id: "
     "51234567892. Fee charged: GHS 2.00. E-Levy charged: GHS 0.00",
     dict(kind="Transfer", direction="cash_out", amount=200.0, fee=2.0, txn_id="51234567892")),
    ("000012345678 Confirmed. GHS30.00 sent to 0201234567 KWAME ASANTE on Telecel Cash on 2026-10-09 at 09:15:22. "
     "Your Telecel Cash balance is GHS150.25. You were charged GHS0.30. Your E-levy charge is GHS0.00.",
     dict(kind="Expense", amount=30.0, fee=0.3, balance=150.25, party="Kwame Asante", txn_id="000012345678",
          date=date(2026, 10, 9))),
    ("You have sent GHS 25.00 to 0571234567 ABENA. Fee: GHS 0.25. Your new balance is GHS 75.00. Trans ID: AT12345. "
     "11/10/2026 09:30",
     dict(kind="Expense", amount=25.0, fee=0.25, balance=75.0, party="Abena", txn_id="AT12345", date=date(2026, 10, 11))),
    ("Your payment of GHS 120.00 to ECG PREPAID has been completed at 2026-10-11 08:00:00. Your new balance: GHS 30.00. "
     "Fee was GHS 0.00, Tax was GHS 0.00. Financial Transaction Id: 51234567893.",
     dict(kind="Expense", amount=120.0, fee=0.0, party="ECG Prepaid", category_hints=["Electricity"])),
    ("000098765 Confirmed. You have received GHS200.00 from 0501234567 YAW BOATENG on 2026-10-10 at 18:02:11. "
     "Your Telecel Cash balance is GHS350.25.",
     dict(kind="Income", amount=200.0, party="Yaw Boateng", balance=350.25)),
    ("Cash In received for GHS 300.00 from AGENT KOJO. Current Balance: GHS 320.50. Transaction ID: 5555",
     dict(kind="Transfer", direction="cash_in", amount=300.0)),
    ("Payment made for GHS 1,250.00 to LANDLORD. Current Balance: GHS 10.00.", dict(amount=1250.0)),
]


@pytest.mark.parametrize("text,expected", MOMO_SAMPLES, ids=[f"sample{i}" for i in range(len(MOMO_SAMPLES))])
def test_momo_text_is_read(text, expected):
    found = momo.parse(text)
    assert found, "should be recognised as a money message"
    for key, value in expected.items():
        assert found[key] == value, f"{key}: {found[key]!r} != {value!r}"


@pytest.mark.parametrize("text", ["", "   ", "hello, are you coming tonight?", "Your OTP is 123456"])
def test_ordinary_texts_are_ignored(text):
    assert momo.parse(text) is None


def test_momo_summary_reads_naturally():
    found = momo.parse(MOMO_SAMPLES[0][0])
    assert momo.describe(found) == "Paid GH₵50.00 to Kofi Mensah, fee GH₵0.50"


def test_momo_account_is_found_by_name():
    assert momo.momo_account(["Cash", "GCB", "MTN MoMo"]) == "MTN MoMo"
    assert momo.momo_account(["Cash", "GCB"]) is None


# ---- passwords and usernames ---------------------------------------------------------------
def test_passwords_are_hashed_and_salted():
    h1, h2 = auth.hash_password("Kenkey and fish"), auth.hash_password("Kenkey and fish")
    assert h1.startswith("pbkdf2_sha256$600000$") and "Kenkey" not in h1
    assert h1 != h2, "each hash should use its own salt"
    assert auth.check_password("Kenkey and fish", h1)
    assert not auth.check_password("kenkey and fish", h1)
    assert not auth.check_password("anything", "not-a-hash")


@pytest.mark.parametrize("name,ok", [("xan", True), ("ama.serwaa", True), ("x", False), ("has space", False),
                                     ("-dash", False), ("a" * 31, False)])
def test_username_rules(name, ok):
    assert (auth.username_problem(name) is None) == ok


@pytest.mark.parametrize("pw,ok", [("short", False), ("password", False), ("xanxanxan", True),
                                   ("Kenkey and fish", True)])
def test_password_rules(pw, ok):
    problem = auth.password_problem(pw, "someone")
    assert (problem is None) == ok
    assert auth.password_problem("xanhann99", "xanhann99") is not None  # not the username


# ---- money sums --------------------------------------------------------------------------
@pytest.fixture
def book_now(conn):
    return Book(_load_frames(conn))


def test_safe_to_spend_adds_up(book_now):
    b = book_now
    s = b.safe_to_spend()
    assert set(s["accounts"]) == set(b.everyday_accounts)
    assert "Susu" not in s["accounts"] and "Fidelity - Emergency" not in s["accounts"], "savings stay out"
    assert s["money"] == pytest.approx(sum(b.balance(a) for a in s["accounts"]))
    assert s["safe"] == pytest.approx(s["money"] - s["bills"] - s["budget_left"])
    assert s["payday"] > date.today()
    # the monthly GCB -> Susu move (500) falls before payday, plus at least one weekly data bundle (60)
    assert s["bills"] >= 560
    assert s["per_day"] == pytest.approx(s["safe"] / s["days"])


def test_payday_follows_the_salary(book_now):
    pay, basis = book_now.payday()
    assert basis == "a month after the last salary"
    assert pay.day == 1 and pay > date.today()


def test_budget_warnings(book_now):
    from ui.entry import _budget_alerts
    b = book_now
    health = next(s for s in b.budget_status(__import__("pandas").Period(date.today(), "M")) if s["name"] == "Health")
    big = health["limit"] - health["spent"] + 10
    msgs = _budget_alerts(b, "Expense", "Medications", big, date.today())
    assert any("Health" in m and "over" in m for m in msgs), msgs
    assert _budget_alerts(b, "Income", "Salary", 99999, date.today()) == []


# ---- backups -------------------------------------------------------------------------------
@pytest.fixture
def restore_url(db_url):
    url = db_url.rsplit("/", 1)[0] + "/cashew_test_restore"
    admin = psycopg2.connect(db_url.rsplit("/", 1)[0] + "/postgres")
    admin.autocommit = True
    admin.cursor().execute("DROP DATABASE IF EXISTS cashew_test_restore")
    admin.cursor().execute("CREATE DATABASE cashew_test_restore")
    admin.close()
    return url


def test_backup_restores_exactly(conn, restore_url):
    data, counts = export_zip(conn)
    assert counts["transactions"] > 20
    locked = encrypt(data, "a long family phrase")
    assert b"Salary" not in locked
    with pytest.raises(ValueError):
        decrypt(locked, "wrong phrase")
    target = psycopg2.connect(restore_url)
    try:
        restored = restore_zip(target, decrypt(locked, "a long family phrase"))
        assert restored["transactions"] == counts["transactions"]
        summary = "SELECT count(*), sum(amount), max(id) FROM transactions"
        assert q(target, summary) == q(conn, summary)
        kitchen = "SELECT (SELECT count(*) FROM meals.recipe_items), (SELECT count(*) FROM meals.plan), " \
                  "(SELECT coalesce(sum(qty), 0) FROM meals.pantry)"
        assert q(target, kitchen) == q(conn, kitchen), "the kitchen is in the backup too"
        with pytest.raises(ValueError):  # won't overwrite without being told to
            restore_zip(target, data)
        target.rollback()
        restore_zip(target, data, replace=True)
        assert q(target, summary) == q(conn, summary)
        # new entries carry on numbering after the restored ones
        new_id = q(target, "INSERT INTO transactions (date, type, category, amount) VALUES (CURRENT_DATE, 'Expense', "
                           "'Staples', 1) RETURNING id")[0][0]
        target.commit()
        assert new_id == q(conn, "SELECT max(id) FROM transactions")[0][0] + 1
    finally:
        target.close()


def test_restore_rejects_other_files(restore_url):
    target = psycopg2.connect(restore_url)
    try:
        with pytest.raises(ValueError):
            restore_zip(target, b"not a zip at all")
    finally:
        target.close()


def test_payday_without_salary_is_next_month():
    import pandas as pd
    empty = {k: pd.DataFrame(columns=cols) for k, (cols, _) in __import__("core.data", fromlist=["SMALL"]).SMALL.items()}
    empty["tx"] = pd.DataFrame(columns=["id", "date", "type", "category", "amount", "note", "member", "account",
                                        "to_account", "created_by"])
    b = Book(empty)
    pay, basis = b.payday(date(2026, 3, 15))
    assert pay == date(2026, 4, 1) and basis == "the 1st of next month"
    assert b.safe_to_spend(date(2026, 3, 15))["safe"] == 0
    assert (pay - timedelta(days=1)).month == 3


# ---- kitchen arithmetic ------------------------------------------------------------------------
from meals import logic as ml  # noqa: E402
from meals.units import fmt as qfmt  # noqa: E402
from meals.units import to_base  # noqa: E402

RECIPES = {1: {"name": "Jollof", "portions": 4, "keeps_days": 3, "prep_note": None, "prep_hours": None},
           2: {"name": "Red red", "portions": 4, "keeps_days": 2, "prep_note": "Soak the beans", "prep_hours": 10}}
ITEMS = {1: [(10, 3, "pcs"), (11, 1, "kg")], 2: [(10, 3, "pcs"), (11, 500, "g"), (12, 2, "cup")]}
D = date(2026, 10, 12)


def plan(*entries):
    return [dict(status="planned", **e) for e in entries]


def test_ingredients_add_up_across_dishes():
    e = plan({"day": D, "slot": "Supper", "recipe_id": 1, "qty": 4}, {"day": D, "slot": "Lunch", "recipe_id": 2, "qty": 4})
    needs = ml.total_needs(e, RECIPES, ITEMS, lambda x: RECIPES[x["recipe_id"]]["name"])
    assert needs[(10, "pcs")]["qty"] == 6, "3 onions + 3 onions"
    assert needs[(11, "g")]["qty"] == 1500, "1 kg + 500 g"
    assert needs[(10, "pcs")]["for"] == ["Jollof", "Red red"]
    assert qfmt(needs[(11, "g")]["qty"], "g") == "1.5 kg"
    assert qfmt(needs[(12, "ml")]["qty"], "ml") == "500 ml", "2 cups"


def test_portions_scale_the_recipe():
    e = plan({"day": D, "slot": "Supper", "recipe_id": 1, "qty": 8})
    assert ml.total_needs(e, RECIPES, ITEMS)[(10, "pcs")]["qty"] == 6, "double portions, double onions"


def test_counts_and_weights_stay_apart():
    assert to_base(3, "pcs") == (3, "pcs") and to_base(0.5, "kg") == (500, "g")
    items = {1: [(10, 3, "pcs")], 2: [(10, 500, "g")]}
    e = plan({"day": D, "slot": "Supper", "recipe_id": 1, "qty": 4}, {"day": D, "slot": "Lunch", "recipe_id": 2, "qty": 4})
    needs = ml.total_needs(e, RECIPES, items)
    assert needs[(10, "pcs")]["qty"] == 3 and needs[(10, "g")]["qty"] == 500


def test_shopping_list_subtracts_the_pantry_and_adds_low_staples():
    needs = {(10, "pcs"): {"qty": 6.0, "for": ["Jollof"]}, (11, "g"): {"qty": 1500.0, "for": ["Jollof"]}}
    out = ml.shopping_list(needs, pantry={(11, "g"): 2000.0, (10, "pcs"): 2.0, (14, "ml"): 100.0},
                           low_levels={(14, "ml"): 250.0}, prices={(10, "pcs"): 1.5})
    rows = {(r["ingredient_id"], r["base"]): r for r in out}
    assert (11, "g") not in rows, "enough rice in the pantry"
    assert rows[(10, "pcs")]["to_buy"] == 4 and rows[(10, "pcs")]["est"] == 6.0
    assert rows[(14, "ml")]["reason"] == "Running low" and rows[(14, "ml")]["to_buy"] == 400


def test_pantry_never_goes_negative():
    new, short = ml.after_use({(10, "pcs"): 2.0}, [(10, "pcs", 3.0)])
    assert new[(10, "pcs")] == 0 and short == [(10, "pcs", 1.0)]


def test_leftovers_and_oldest_first():
    assert ml.leftovers(8, 4) == 4 and ml.leftovers(3, 4) == 0
    taken, missing = ml.take_portions([{"id": 1, "portions": 2, "eat_by": D + timedelta(days=2)},
                                       {"id": 2, "portions": 3, "eat_by": D}], 4)
    assert taken == [(2, 3.0), (1, 1.0)] and missing == 0


def test_cooking_reminders():
    from datetime import datetime
    e = plan({"day": D + timedelta(days=1), "slot": "Breakfast", "recipe_id": 2, "qty": 4})
    notes = ml.reminders(datetime(2026, 10, 12, 22, 0), e, RECIPES, ITEMS, {}, [], {10: "onions", 11: "rice", 12: "oil"}, 4)
    texts = " | ".join(t for _, t in notes)
    assert "Soak the beans now, for tomorrow's breakfast (Red red)" in texts
    assert "Buy before cooking: 3 onions, 500 g rice, 500 ml oil" in texts
    fridge = [{"recipe_id": 2, "label": "Red red", "portions": 4, "eat_by": D + timedelta(days=1)}]
    notes = ml.reminders(datetime(2026, 10, 12, 8, 0), e, RECIPES, ITEMS, {}, fridge, {}, 4)
    texts = " | ".join(t for _, t in notes)
    assert "already in the fridge, no need to cook" in texts and "Buy before cooking" not in texts
    assert "Eat the 4 portions of Red red by tomorrow" in texts


# ---- two-week planning: sharing out the stock, fractions, jokes and the budget guard ------------
def test_two_meals_cant_both_count_the_same_onions():
    e = plan({"id": 1, "day": D, "slot": "Lunch", "recipe_id": 1, "qty": 4},
             {"id": 2, "day": D + timedelta(days=1), "slot": "Supper", "recipe_id": 2, "qty": 4})
    pantry = {(10, "pcs"): 4.0, (11, "g"): 5000.0, (12, "ml"): 1000.0}
    alloc = ml.allocate(e, RECIPES, ITEMS, pantry, [], 4, D)
    assert alloc["meals"][1]["status"] == "ready", "the earlier meal gets first claim"
    assert alloc["meals"][2]["status"] == "short" and alloc["meals"][2]["missing"] == [(10, "pcs", 2.0)]
    short = ml.shortfall(alloc, e, lambda x: RECIPES[x["recipe_id"]]["name"])
    assert short == {(10, "pcs"): {"qty": 6.0, "short": 2.0, "for": ["Red red"]}}, "6 needed, 4 in stock: buy 2"
    rows = ml.shopping_list(short, {})
    assert rows[0]["to_buy"] == 2 and rows[0]["have"] == 4


def test_leftovers_cover_a_later_meal_and_need_no_ingredients():
    big = plan({"id": 1, "day": D, "slot": "Lunch", "recipe_id": 2, "qty": 8},
               {"id": 2, "day": D + timedelta(days=1), "slot": "Lunch", "recipe_id": 2, "qty": 4})
    alloc = ml.allocate(big, RECIPES, ITEMS, {}, [], 4, D)
    assert alloc["meals"][2]["status"] == "leftovers", "8 cooked, 4 eaten, 4 kept for tomorrow"
    assert ml.shortfall(alloc, big)[(10, "pcs")]["short"] == 6, "only the big pot needs shopping"
    too_late = plan({"id": 3, "day": D + timedelta(days=5), "slot": "Lunch", "recipe_id": 2, "qty": 4})
    fridge = [{"recipe_id": 2, "label": "Red red", "portions": 4, "eat_by": D + timedelta(days=1)}]
    assert ml.allocate(too_late, RECIPES, ITEMS, {}, fridge, 4, D)["meals"][3]["status"] == "short", \
        "leftovers past their eat-by date don't count"


def test_half_portions_and_fractions():
    from meals.units import frac
    e = plan({"id": 1, "day": D, "slot": "Supper", "recipe_id": 1, "qty": 2})
    assert ml.total_needs(e, RECIPES, ITEMS)[(10, "pcs")]["qty"] == 1.5, "half a pot, half the onions"
    assert [frac(x) for x in (1.5, 0.25, 2 / 3, 3, 1.2)] == ["1½", "¼", "⅔", "3", "1.2"]
    assert qfmt(1.5, "pcs") == "1½" and qfmt(0.5, "crate") == "½ crate" and qfmt(2.5, "bunch") == "2½ bunches"


def test_price_rises_compare_month_to_month():
    import pandas as pd
    from core.report import price_rises
    h = pd.DataFrame([{"ingredient_id": 1, "unit": "pcs", "per_unit": 2.0, "date": date(2026, 8, 5)},
                      {"ingredient_id": 1, "unit": "pcs", "per_unit": 2.5, "date": date(2026, 9, 3)},
                      {"ingredient_id": 2, "unit": "g", "per_unit": 0.02, "date": date(2026, 8, 5)},
                      {"ingredient_id": 2, "unit": "g", "per_unit": 0.0201, "date": date(2026, 9, 9)}])
    rises = price_rises(h, pd.Period("2026-09", "M"), {1: "Eggs", 2: "Rice"})
    assert [(n, round(c, 2)) for n, _, _, c in rises] == [("Eggs", 0.25)], "rice barely moved"


def test_shopping_amounts_you_can_actually_buy():
    needs = {(10, "pcs"): {"qty": 5.88, "short": 5.88, "for": []}, (11, "g"): {"qty": 38.75, "short": 38.75, "for": []},
             (12, "g"): {"qty": 1625.0, "short": 1625.0, "for": []}}
    got = {r["ingredient_id"]: r["to_buy"] for r in ml.shopping_list(needs, {})}
    assert got == {10: 6, 11: 40, 12: 1650}


def test_jokes_stay_the_same_all_day_and_keep_the_facts():
    from meals.quips import joke, with_joke
    assert joke("missing", D) == joke("missing", D), "no change on every redraw"
    text = with_joke("missing", "Buy before cooking: 3 onions.", D)
    assert text.endswith("Buy before cooking: 3 onions.") and len(text) > 30
    assert with_joke("missing", "Buy 3 onions.", D, on=False) == "Buy 3 onions."
    from datetime import datetime
    e = plan({"day": D + timedelta(days=1), "slot": "Breakfast", "recipe_id": 2, "qty": 4})
    notes = ml.reminders(datetime(2026, 10, 12, 22, 0), e, RECIPES, ITEMS, {}, [], {10: "onions"}, 4, fun=True)
    assert any("Soak the beans now" in t and not t.startswith("Soak") for _, t in notes)


def test_repeating_last_week_fills_both_weeks_once():
    old = plan({"day": D - timedelta(days=7), "slot": "Supper", "recipe_id": 1, "qty": 2.5},
               {"day": D - timedelta(days=6), "slot": "Lunch", "recipe_id": 2, "qty": 4},
               {"day": D + timedelta(days=1), "slot": "Lunch", "recipe_id": 1, "qty": 4})  # already planned
    new = ml.repeat_plan(old, D)
    got = {(e["day"], e["slot"]): e["qty"] for e in new}
    assert got[(D, "Supper")] == 2.5 and got[(D + timedelta(days=7), "Supper")] == 2.5, "carries into week two"
    assert (D + timedelta(days=1), "Lunch") not in got, "a planned meal is left alone"
    assert got[(D + timedelta(days=8), "Lunch")] == 4, "...and repeated a week later"
    assert ml.repeat_plan(old + plan(*new), D) == [], "nothing left to copy afterwards"


def test_jokes_name_whats_actually_short():
    from datetime import datetime
    from meals.quips import LINES, joke
    for kind in LINES:  # every line works with the names given, and none is left with a {placeholder}
        for i in range(30):
            j = joke(kind, D + timedelta(days=i), dish="light soup", item="tomatoes", what="food")
            assert j and "{" not in j
    assert "{" not in joke("missing", D), "lines that need a name are skipped when there isn't one"
    e = plan({"id": 1, "day": D, "slot": "Supper", "recipe_id": 2, "qty": 4})
    notes = ml.reminders(datetime(2026, 10, 12, 8, 0), e, RECIPES, ITEMS, {}, [], {10: "Onions"}, 4, fun=True)
    buy = next(t for _, t in notes if "Buy before cooking" in t)
    assert "jollof" not in buy.lower(), "the joke never names a dish that isn't short"


def test_month_so_far_compares_the_same_days(book_now):
    b = book_now
    import pandas as pd
    this = pd.Period(date.today(), "M")
    full = b.month_totals(this - 1)
    part = b.month_totals(this - 1, upto_day=1)
    assert part[1] <= full[1]
    from ui.components import change_pill
    assert "▲ 20% vs 1–13 Sep" in change_pill(120, 100, versus="1–13 Sep")


def test_household_budget_words():
    g = ml.budget_guard(300, 280, 50, what="household")
    assert g["level"] == "will_go_over" and g["text"].startswith("The planned shopping") and "household spending" in g["text"]
    assert "swapping a dish" not in g["text"], "no dish to swap for bleach"
    from meals.quips import joke
    assert "food" not in joke("budget_75", D, "household", what="household")


def test_bought_food_needs_no_ingredients():
    from datetime import datetime
    recipes = dict(RECIPES)
    recipes[3] = {"name": "Kenkey", "portions": 1, "keeps_days": 1, "prep_note": None, "prep_hours": None,
                  "bought": True, "price": 5.0, "count_unit": "ball", "shop": "Auntie Ama"}
    e = plan({"id": 1, "day": D, "slot": "Supper", "recipe_id": 3, "qty": 6},
             {"id": 2, "day": D, "slot": "Supper", "label": "Fried fish", "qty": 2, "unit": "piece", "price": 15.0},
             {"id": 3, "day": D, "slot": "Supper", "recipe_id": 1, "qty": 4})
    alloc = ml.allocate(e, recipes, ITEMS, {}, [], 4, D)
    assert alloc["meals"][1]["status"] == alloc["meals"][2]["status"] == "bought"
    assert alloc["meals"][3]["status"] == "short", "the home-cooked dish in the same meal still needs shopping"
    assert ml.bought_cost(e, recipes) == (60.0, 0), "6 kenkey at 5 + 2 fish at 15"
    assert set(ml.shortfall(alloc, e)) == {(10, "pcs"), (11, "g")}, "only jollof's ingredients go on the list"
    notes = " | ".join(t for _, t in ml.reminders(datetime(2026, 10, 12, 8, 0), e, recipes, ITEMS, {}, [], {}, 4))
    assert "Pick up 6 balls of Kenkey from Auntie Ama for today's supper (about GH₵30.00)" in notes
    assert "Pick up 2 pieces of Fried fish for today's supper (about GH₵30.00)" in notes
    copied = ml.repeat_plan(e, D + timedelta(days=7))
    fish = [c for c in copied if c.get("label") == "Fried fish"]
    assert len(copied) == 6 and fish and fish[0]["price"] == 15.0, "the whole meal repeats (both weeks), one-offs with their price"


def test_budget_guard_looks_ahead():
    assert ml.budget_guard(1000, 500, 100) is None, "60% is fine"
    assert ml.budget_guard(1000, 600, 200)["level"] == "75"
    assert ml.budget_guard(1000, 800, 150)["level"] == "90"
    g = ml.budget_guard(1000, 800, 300)
    assert g["level"] == "will_go_over" and "GH₵100.00 over" in g["text"]
    assert ml.budget_guard(1000, 1200, 0)["level"] == "over"
    assert ml.budget_guard(0, 500, 100) is None, "no budget, no guard"


# ---- containers, costs, ideas, waste and phone messages -----------------------------------------
from meals.units import fmt_stock, packs_for  # noqa: E402

EGG_CRATE, RICE_BAG = ("crate", 30, "pcs"), ("bag", 5000, "g")


def test_containers_convert_and_display():
    assert to_base(2, "crate", EGG_CRATE) == (60, "pcs")
    assert to_base(1, "bag", RICE_BAG) == (5000, "g")
    assert fmt_stock(36, "pcs", EGG_CRATE) == "1 crate + 6"
    assert fmt_stock(7500, "g", RICE_BAG) == "1.5 bags (7.5 kg)"
    assert fmt_stock(12, "pcs", EGG_CRATE) == "12", "less than a crate shows as loose"
    assert packs_for(12, EGG_CRATE) == 1 and packs_for(31, EGG_CRATE) == 2


def test_recipes_can_use_containers():
    recipes = {1: {"name": "Party jollof", "portions": 20, "keeps_days": 3, "prep_note": None, "prep_hours": None}}
    items = {1: [(20, 1, "bag"), (21, 1, "crate")]}
    needs = ml.total_needs(plan({"day": D, "slot": "Lunch", "recipe_id": 1, "qty": 20}), recipes, items,
                           packs={20: RICE_BAG, 21: EGG_CRATE})
    assert needs[(20, "g")]["qty"] == 5000 and needs[(21, "pcs")]["qty"] == 30


def test_shopping_rounds_up_to_whole_containers():
    needs = {(21, "pcs"): {"qty": 12.0, "for": ["Eggs"]}, (20, "g"): {"qty": 6000.0, "for": ["Rice"]}}
    out = {r["ingredient_id"]: r for r in ml.shopping_list(needs, {}, prices={(21, "pcs"): 2.0},
                                                            packs={21: EGG_CRATE, 20: RICE_BAG})}
    assert (out[21]["packs"], out[21]["pack"], out[21]["buy_qty"]) == (1, "crate", 30)
    assert out[21]["est"] == 60, "priced for the whole crate you'll bring home"
    assert out[20]["packs"] == 2, "6 kg needs two 5 kg bags"


def test_recipe_and_week_costs():
    prices = {(10, "pcs"): 2.0, (11, "g"): 0.02}
    batch, each, unknown = ml.recipe_cost(1, RECIPES, ITEMS, prices)
    assert (batch, each, unknown) == (26.0, 6.5, 0), "3 onions at 2 + 1 kg rice at 0.02/g, for 4 portions"
    needs = ml.total_needs(plan({"day": D, "slot": "Supper", "recipe_id": 2, "qty": 4}), RECIPES, ITEMS)
    assert ml.cost_of(needs, prices) == (16.0, 1), "oil has no price yet"


def test_price_changes_are_flagged():
    lines = [{"ingredient_id": 10, "name": "Tomatoes", "qty": 10, "base": "pcs", "price": 28},
             {"ingredient_id": 11, "name": "Rice", "qty": 5000, "base": "g", "price": 100}]
    changes = ml.price_changes(lines, {(10, "pcs"): 2.0, (11, "g"): 0.02})
    assert [c[0] for c in changes] == ["Tomatoes"] and round(changes[0][3], 2) == 0.4


def test_ideas_use_leftovers_and_avoid_repeats():
    pantry = {(10, "pcs"): 10, (11, "g"): 2000, (12, "ml"): 1000}
    fridge = [{"recipe_id": 2, "portions": 3, "eat_by": D + timedelta(days=1)}]
    recent = plan({"day": D - timedelta(days=1), "slot": "Supper", "recipe_id": 1, "qty": 4})
    ideas = ml.suggest(RECIPES, ITEMS, pantry, fridge, recent, D)
    assert ideas[0]["recipe_id"] == 2 and "3 portions already in the fridge" in ideas[0]["reasons"]
    assert all(i["recipe_id"] != 1 for i in ideas), "jollof was had yesterday"


def test_phone_messages(conn):
    from datetime import datetime

    from core.data import Book
    from core.data import _load_frames as money_frames
    from meals.briefing import evening, morning
    from meals.data import Kitchen
    from meals.data import _load as kitchen_frames
    k, b = Kitchen(kitchen_frames(conn)), Book(money_frames(conn))
    text = morning(k, b, datetime.now(), 480.0)
    assert text.startswith("☀️ <b>Good morning!") and "Safe to spend until payday" in text
    assert "Food budget left: GH₵480.00" in text
    assert "<script" not in text
    msg = evening(k, datetime.now())
    assert msg is None or msg.startswith("🌙 <b>For tomorrow")
    from core.report import monthly
    report = monthly(b, k, date.today())
    assert "Bleach" not in " ".join(k.food_names.values()), "household supplies aren't food"
    assert report.startswith("📊 <b>") and "In GH₵" in report and "Budgets" in report and "<script" not in report


def test_notify_sends_to_every_chat():
    """A stand-in for Telegram on this machine, to check what notify.py sends."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import notify
    got = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        n = notify.send("Hello <b>family</b>", "123:ABC", "111, 222", api=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    assert n == 2
    assert got[0][0] == "/bot123:ABC/sendMessage"
    assert [g[1]["chat_id"] for g in got] == ["111", "222"] and got[0][1]["parse_mode"] == "HTML"


def test_notify_explains_telegram_errors():
    """A bad chat ID gives a plain explanation, and the other chats still get the message."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import notify
    got = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            chat = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["chat_id"]
            if chat == "999":
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"ok": false, "error_code": 400, "description": "Bad Request: chat not found"}')
                return
            got.append(chat)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(notify.SendError) as err:
            notify.send("Hi", "123:ABC", "111,999", api=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    assert got == ["111"], "the good chat still got it"
    msg = str(err.value)
    assert "Sent to 1 of 2 chats" in msg and "chat not found" in msg and "minus sign" in msg


# ---- meals of several dishes, the Ghanaian kitchen catalog, and kitchen units ----------------------------
from meals.units import fmt_stock as qfmt_stock  # noqa: E402
from meals.units import from_base, plural, units_for  # noqa: E402

ONION_BAG = ("bag", 40, "pcs", True, {})                     # sold loose
GARLIC_BULB = ("bulb", 6, "clove", False, {})
SANKOFA = ("sachet", 25.0, "ml", False, {"container": 400.0})  # 5 tsp sachet, 80 tsp container
MARGARINE = ("tub", 900.0, "g", False, {"tbsp": 15.0})


def test_kitchen_measures_read_naturally():
    assert qfmt(750, "ml", "cup") == "3 cups" and qfmt(15, "ml", "tbsp") == "1 tbsp"
    assert qfmt(375, "ml", "cup") == "1½ cups", "cups are shown in cups, not millilitres"
    assert qfmt(750, "ml") == "750 ml", "without the item's own unit nothing changes"
    assert plural("cup") == "cups" and plural("tbsp") == "tbsp" and plural("finger", 3) == "fingers"
    assert qfmt_stock(6250 + 1250, "ml", ("bag", 6250, "ml"), "cup") == "1.2 bags (30 cups)"


def test_other_units_convert():
    assert to_base(1, "container", SANKOFA) == (400.0, "ml"), "80 tsp container"
    assert to_base(2, "sachet", SANKOFA) == (50.0, "ml"), "a sachet is 5 tsp"
    assert to_base(2, "tbsp", MARGARINE) == (30.0, "g"), "margarine by the spoon, kept in grams"
    assert from_base(400, "ml", "container", SANKOFA) == 1
    assert "container" in units_for("tsp", SANKOFA) and units_for("tsp", SANKOFA)[0] == "sachet"


def test_loose_items_are_bought_by_the_piece():
    needs = {(30, "pcs"): {"qty": 5.0, "for": []}, (31, "clove"): {"qty": 3.0, "for": []}}
    out = {r["ingredient_id"]: r for r in ml.shopping_list(needs, {}, packs={30: ONION_BAG, 31: GARLIC_BULB})}
    assert (out[30]["to_buy"], out[30]["pack"]) == (5, None), "5 onions, not a 40-onion bag"
    assert (out[31]["packs"], out[31]["pack"], out[31]["buy_qty"]) == (1, "bulb", 6), "garlic comes by the bulb"


SOUP_WEEK = {5: {"name": "Kokonte", "portions": 2, "keeps_days": 1, "prep_note": None, "prep_hours": None,
                 "role": "starch"},
             6: {"name": "Palm nut soup", "portions": 14, "keeps_days": 7, "prep_note": None, "prep_hours": None,
                 "role": "soup"}}
SOUP_ITEMS = {5: [(40, 1.5, "cup")], 6: [(41, 800, "g"), (42, 1, "kg")]}


def test_a_pot_of_soup_lasts_the_week():
    """Kokonte + Palm nut soup on Monday cooks the whole pot; on Tuesday only the kokonte needs cooking."""
    mon = plan({"id": 1, "day": D, "slot": "Lunch", "recipe_id": 5, "qty": 2},
               {"id": 2, "day": D, "slot": "Lunch", "recipe_id": 6, "qty": 14})
    assert ml.from_leftovers(mon, SOUP_WEEK, SOUP_ITEMS, {}, [], 2, D, D + timedelta(days=1), "Lunch", 6), \
        "Tuesday's soup can come from Monday's pot"
    assert not ml.from_leftovers([], SOUP_WEEK, SOUP_ITEMS, {}, [], 2, D, D, "Lunch", 6), "no pot yet: cook one"
    assert not ml.from_leftovers(mon, SOUP_WEEK, SOUP_ITEMS, {}, [], 2, D, D, "Lunch", 6), \
        "checking a dish for a meal that already has dishes in it"
    tue = plan({"id": 3, "day": D + timedelta(days=1), "slot": "Lunch", "recipe_id": 5, "qty": 2},
               {"id": 4, "day": D + timedelta(days=1), "slot": "Lunch", "recipe_id": 6, "qty": 2})
    alloc = ml.allocate(mon + tue, SOUP_WEEK, SOUP_ITEMS, {}, [], 2, D)
    assert alloc["meals"][4]["status"] == "leftovers" and alloc["meals"][3]["status"] == "short"
    need = ml.shortfall(alloc, mon + tue)
    assert need[(40, "ml")]["short"] == 750, "kokonte powder for both days: 2 x 1.5 cups"
    assert need[(41, "g")]["short"] == 800, "palm nut cream for one pot only"


def test_a_meal_has_one_status():
    assert ml.meal_status([("done", []), ("done", [])]) == "done"
    assert ml.meal_status([("ready", []), ("short", ["Okro"])]) == "short", "anything missing makes the meal short"
    assert ml.meal_status([("leftovers", []), ("ready", [])]) == "ready", "kokonte to cook, soup from the fridge"
    assert ml.meal_status([("leftovers", []), ("done", [])]) == "leftovers"
    assert ml.meal_status([("bought", []), ("done", [])]) == "bought"


def test_the_catalog_is_in_a_new_database(conn):
    rows = dict(q(conn, "SELECT name, pack_size FROM meals.ingredients WHERE name IN ('Lele Gold evaporated milk "
                        "(400g)', 'A55 Gold jasmine rice (5kg)', 'Yam', 'Eggs', 'Sankofa Fish')"))
    assert float(rows["Lele Gold evaporated milk (400g)"]) == 16 * 15, "1 tin = 16 tbsp"
    assert float(rows["A55 Gold jasmine rice (5kg)"]) == 25 * 250, "1 bag = 25 cups"
    assert float(rows["Yam"]) == 8 and float(rows["Eggs"]) == 30 and float(rows["Sankofa Fish"]) == 25
    assert q(conn, "SELECT count(*) FROM meals.ingredients WHERE name LIKE 'Sankofa %%'")[0][0] == 10
    roles = dict(q(conn, "SELECT name, role FROM meals.recipes WHERE name IN ('Palm nut soup', 'Kokonte', 'Tomato stew')"))
    assert roles == {"Palm nut soup": "soup", "Kokonte": "starch", "Tomato stew": "stew"}
    assert q(conn, "SELECT portions FROM meals.recipes WHERE name = 'Light soup'")[0][0] == 14, "2 people, 7 days"
    names = {r[0] for r in q(conn, "SELECT name FROM meals.pairings")}
    assert {"Kokonte + Palm nut soup", "Fufu + Light soup", "Banku + Okra soup", "Waakye + Stew + Gari"} <= names
    from meals.data import Kitchen
    from meals.data import _load as kitchen_frames
    k = Kitchen(kitchen_frames(conn))
    waakye = next(p for p in k.pairings.values() if p["name"] == "Waakye + Stew + Gari")
    assert [k.recipes[x["recipe_id"]]["name"] for x in waakye["parts"] if x.get("recipe_id")] == ["Waakye", "Tomato stew"]
    assert [(k.names[x["ingredient_id"]], x["qty"], x["unit"]) for x in waakye["parts"] if x.get("ingredient_id")] == \
        [("Gari", 0.5, "cup")], "gari, half a cup a person"


def test_the_catalog_is_added_only_once(conn):
    from meals.catalog import TEMPLATES, add_recipes, seed
    with conn.cursor() as cur:
        assert seed(cur) is False, "already there"
        assert add_recipes(cur, TEMPLATES) == 0, "names already used are skipped"


def test_starting_up_skips_work_when_up_to_date(conn):
    from core.schema import SCHEMA_KEY, _version, ensure_schema
    assert q(conn, "SELECT value FROM app_meta WHERE key = %s", (SCHEMA_KEY,)) == [(_version(),)]
    c = psycopg2.connect(conn.dsn)
    try:
        ensure_schema(c)  # one read, nothing else
        assert q(c, "SELECT count(*) FROM meals.recipes")[0][0] >= 13
    finally:
        c.close()


def test_a_paired_meal_is_one_meal(conn):
    from datetime import datetime

    from core.report import monthly
    from meals.briefing import today_summary
    from meals.data import Kitchen
    from meals.data import _load as kitchen_frames
    ids = dict(q(conn, "SELECT name, id FROM meals.recipes WHERE name IN ('Kokonte', 'Palm nut soup')"))
    made = q(conn, "INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES (CURRENT_DATE, 'Breakfast', %s, 14), "
                   "(CURRENT_DATE, 'Breakfast', %s, 2) RETURNING id", (ids["Palm nut soup"], ids["Kokonte"]))
    try:
        k = Kitchen(kitchen_frames(conn))
        parts = [e for e in k.entries(date.today()) if e["slot"] == "Breakfast"]
        assert k.meal_name(parts) == "Kokonte + Palm nut soup", "the starch comes first"
        assert k.meal_count(parts) == 1
        s = today_summary(k, datetime.now())
        assert [m[1] for m in s["meals"] if m[0] == "Breakfast"] == ["Kokonte + Palm nut soup"], "one line, not two"
        # the soup's shopping is labelled with the meal it's for
        needs = ml.shortfall(k.allocation(), parts, names_for_entry=k.meal_name_of)
        assert all(n["for"] == ["Kokonte + Palm nut soup"] for n in needs.values())
        q(conn, "UPDATE meals.plan SET status = 'cooked' WHERE id IN %s", (tuple(r[0] for r in made),))
        k = Kitchen(kitchen_frames(conn))
        first_next = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
        report = monthly(Book(_load_frames(conn)), k, first_next)
        meals = q(conn, "SELECT count(DISTINCT (day, slot)) FROM meals.plan WHERE status <> 'planned' "
                        "AND date_trunc('month', day) = date_trunc('month', CURRENT_DATE)")[0][0]
        assert f"🍳 {meals} planned meal" in report, "kokonte + palm nut soup counts as one meal"
    finally:
        q(conn, "DELETE FROM meals.plan WHERE id IN %s", (tuple(r[0] for r in made),))

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

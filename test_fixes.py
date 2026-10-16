"""Fixes from the October 2026 review. Each test is a bug that existed. No browser needed."""
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import psycopg2
import pytest

from conftest import q


@pytest.fixture
def live_db(monkeypatch, db_url):
    """core.db talking to the test database outside a running app (no st.secrets, no Streamlit caches)."""
    from core import auth, db
    monkeypatch.setattr(db, "st", SimpleNamespace(secrets={"DATABASE_URL": db_url}))
    monkeypatch.setattr(db, "invalidate", lambda: None)
    monkeypatch.setattr(auth, "invalidate", lambda: None)  # auth imports it by name
    return db


# ---- a dropped connection must never save a write twice -------------------------------------------
class FakeConn:
    def __init__(self, fail_on_commit=False):
        self.fail_on_commit, self.closed, self.autocommit, self.commits = fail_on_commit, 0, False, 0

    def commit(self):
        if self.fail_on_commit:
            self.closed = 2
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.commits += 1

    def rollback(self):
        pass


class FakePool:
    def __init__(self, conns):
        self.conns = list(conns)

    def getconn(self):
        return self.conns.pop(0)

    def putconn(self, conn, close=False):
        pass


def _fake_db(monkeypatch, conns):
    from core import db
    monkeypatch.setattr(db, "st", SimpleNamespace(secrets={"DATABASE_URL": "fake"}))
    monkeypatch.setattr(db, "_pool", lambda dsn: FakePool(conns))
    return db


def test_a_write_is_not_repeated_when_the_commit_fails(monkeypatch):
    db = _fake_db(monkeypatch, [FakeConn(fail_on_commit=True), FakeConn()])
    calls = []
    with pytest.raises(psycopg2.OperationalError):
        db.transact(lambda conn: calls.append(1))
    assert calls == [1], "the commit may have landed, so running the insert again could save it twice"


def test_a_write_is_retried_when_the_connection_was_already_dead(monkeypatch):
    fresh = FakeConn()
    db = _fake_db(monkeypatch, [FakeConn(), fresh])
    calls = []

    def work(conn):
        calls.append(conn)
        if len(calls) == 1:
            raise psycopg2.OperationalError("SSL connection has been closed unexpectedly")  # before any commit
        return "saved"

    assert db.transact(work) == "saved"
    assert len(calls) == 2 and fresh.commits == 1, "nothing was committed the first time, so trying again is safe"


# ---- leftovers from a meal ticked late -------------------------------------------------------------------
def test_ticking_an_old_meal_dates_its_leftovers_from_the_meal(db_url):
    """The plan's "Past 2 weeks" view asks people to tick meals they forgot. Leftovers must be dated from the
    meal: a pot cooked 10 days ago isn't fresh, and one cooked 2 days ago has 2 fewer days left."""
    from meals.actions import _cook, _entry, _packs
    c = psycopg2.connect(db_url)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id FROM meals.recipes WHERE name = 'Light soup'")  # 14 portions, keeps 7 days
            rid = cur.fetchone()[0]
            cur.execute("INSERT INTO meals.plan (day, slot, recipe_id, qty) VALUES "
                        "(CURRENT_DATE - 10, 'Supper', %s, 14), (CURRENT_DATE - 2, 'Supper', %s, 14) RETURNING id",
                        (rid, rid))
            old, recent = (r[0] for r in cur.fetchall())
            packs = _packs(cur)
            for pid in (old, recent):
                _cook(cur, _entry(cur, pid), 2, packs)
            cur.execute("SELECT plan_id, cooked_on, eat_by, portions FROM meals.fridge WHERE plan_id IN (%s, %s)",
                        (old, recent))
            rows = {r[0]: r[1:] for r in cur.fetchall()}
            assert old not in rows, "10 days ago, keeps 7: already past its eat-by date, so not put in the fridge"
            cooked_on, eat_by, portions = rows[recent]
            assert cooked_on == date.today() - timedelta(days=2) and eat_by == date.today() + timedelta(days=5)
            assert float(portions) == 12
            cur.execute("SELECT status, undo->'fridge_made' FROM meals.plan WHERE id = %s", (old,))
            assert cur.fetchone() == ("cooked", None), "still ticked as cooked, and unticking has nothing to take back"
    finally:
        c.rollback()
        c.close()


# ---- changing your password signs out your other devices ------------------------------------------------
def test_changing_your_password_signs_out_your_other_devices(live_db, conn):
    from core import auth
    uid = q(conn, "INSERT INTO users (username, display_name, password_hash) VALUES ('pwtest', 'Pw', %s) "
                  "RETURNING id", (auth.hash_password("old password 1"),))[0][0]
    try:
        here, _ = auth.start_session(uid, remember=True)
        lost_phone, _ = auth.start_session(uid, remember=True)
        assert auth.change_password(uid, "wrong", "new password 2", keep_token=here) == \
            "Your current password isn't right."
        assert auth.user_for_token(lost_phone), "a wrong current password changes nothing"

        assert auth.change_password(uid, "old password 1", "new password 2", keep_token=here) is None
        assert auth.user_for_token(here), "the browser that made the change stays signed in"
        assert auth.user_for_token(lost_phone) is None, "every other device is signed out"
        assert auth.sign_in("pwtest", "new password 2")[0] and not auth.sign_in("pwtest", "old password 1")[0]
    finally:
        q(conn, "DELETE FROM users WHERE id = %s", (uid,))


def test_registering_still_works_with_the_hash_made_before_the_lock(live_db, conn):
    from core import auth
    temp_owner = None
    if not q(conn, "SELECT 1 FROM users"):  # this file run on its own: make sure joining needs a code
        temp_owner = q(conn, "INSERT INTO users (username, display_name, password_hash, is_owner) "
                             "VALUES ('tmpowner', 'Tmp', 'x', TRUE) RETURNING id")[0][0]
    code = auth.invite_code() or auth.new_invite_code()
    try:
        user, err = auth.register("joiner", "Joiner", "a long family phrase", code)
        assert err is None and user["username"] == "joiner" and not user["is_owner"]
        assert auth.sign_in("joiner", "a long family phrase")[0], "the stored hash is the right one"
    finally:
        q(conn, "DELETE FROM users WHERE username = 'joiner'")
        if temp_owner:
            q(conn, "DELETE FROM users WHERE id = %s", (temp_owner,))


# ---- the monthly report with nothing but zero-amount expenses ----------------------------------------
def test_the_monthly_report_survives_a_month_of_zero_expenses():
    from core.report import monthly
    spent = pd.DataFrame({"group": ["Food"], "category": ["Staples"], "amount": [0.0]})
    book = SimpleNamespace(month_totals=lambda p: (0.0, 0.0), budget_status=lambda p: [],
                           month_expenses=lambda p: spent,
                           contribs=pd.DataFrame(columns=["date", "amount"]))
    text = monthly(book, today=date(2026, 11, 1))  # used to stop with ZeroDivisionError, so no Telegram message
    assert text.startswith("📊 <b>October 2026 in Cashew</b>") and "Where most of it went" not in text


# ---- deleting a category that's still in use ---------------------------------------------------------
def test_deleting_a_category_moves_what_still_uses_it(conn):
    from core.schema import category_delete_statements, category_uses
    q(conn, "INSERT INTO categories (name, group_name, kind) VALUES ('Test snacks', 'Food', 'Expense')")
    rule = q(conn, "INSERT INTO recurring_rules (name, type, amount, category, account, frequency, start_date, "
                   "next_date) VALUES ('Test biscuits', 'Expense', 10, 'Test snacks', 'Cash', 'Weekly', "
                   "CURRENT_DATE + 30, CURRENT_DATE + 30) RETURNING id")[0][0]
    ing = q(conn, "INSERT INTO meals.ingredients (name, unit, category) VALUES ('Test chin chin', 'pcs', "
                  "'Test snacks') RETURNING id")[0][0]
    q(conn, "INSERT INTO budgets VALUES ('Test snacks', 80)")
    try:
        with conn.cursor() as cur:
            assert category_uses(cur, "Test snacks") == {"auto transactions": 1, "budgets": 1, "kitchen items": 1}
            assert category_uses(cur, "Firewood") == {}, "an unused category can just go"
        assert not q(conn, "SELECT 1 FROM budgets WHERE category = 'Staples'"), "the sample data has no Staples budget"
        for sql, params in category_delete_statements("Test snacks", "Staples"):
            q(conn, sql, params)
        assert q(conn, "SELECT category FROM recurring_rules WHERE id = %s", (rule,)) == [("Staples",)], \
            "the auto transaction goes on adding entries under a category that exists"
        assert q(conn, "SELECT category FROM meals.ingredients WHERE id = %s", (ing,)) == [("Staples",)]
        assert q(conn, "SELECT monthly_limit FROM budgets WHERE category = 'Staples'") == [(80,)], "the budget moves"
        assert not q(conn, "SELECT 1 FROM categories WHERE name = 'Test snacks'")
        assert not q(conn, "SELECT 1 FROM budgets WHERE category = 'Test snacks'")
    finally:
        q(conn, "DELETE FROM recurring_rules WHERE id = %s", (rule,))
        q(conn, "DELETE FROM meals.ingredients WHERE id = %s", (ing,))
        q(conn, "DELETE FROM budgets WHERE category IN ('Staples', 'Test snacks')")
        q(conn, "DELETE FROM categories WHERE name = 'Test snacks'")


def test_a_budget_never_overwrites_the_one_it_moves_onto(conn):
    from core.schema import category_delete_statements
    q(conn, "INSERT INTO categories (name, group_name, kind) VALUES ('Test drinks', 'Food', 'Expense')")
    q(conn, "INSERT INTO budgets VALUES ('Test drinks', 40)")
    before = q(conn, "SELECT monthly_limit FROM budgets WHERE category = 'Dining Out'")
    try:
        for sql, params in category_delete_statements("Test drinks", "Dining Out"):
            q(conn, sql, params)
        assert q(conn, "SELECT monthly_limit FROM budgets WHERE category = 'Dining Out'") == before, \
            "Dining Out keeps its own budget"
        assert not q(conn, "SELECT 1 FROM budgets WHERE category = 'Test drinks'"), "the old one goes"
    finally:
        q(conn, "DELETE FROM budgets WHERE category = 'Test drinks'")
        q(conn, "DELETE FROM categories WHERE name = 'Test drinks'")

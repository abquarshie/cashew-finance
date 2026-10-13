"""Loading the family's data and the questions every page asks of it.

Everything is read in one database trip and prepared once, then shared by every
open session until something is saved (or for a minute, to pick up entries the
daily job adds). Pages only read from it; they never change it in place.
"""
import os
from datetime import date, timedelta
from functools import cached_property

import pandas as pd
import streamlit as st

from auto_rules import occurrence
from core.db import transact

CURRENCY = "GH₵"
SHARED = "Household"  # used when a transaction isn't tied to one family member
KINDS = ["Expense", "Income", "Transfer"]
FREQUENCIES = ["Weekly", "Every 2 weeks", "Monthly", "Yearly"]
FEE_CATEGORY = "Charges"
AUTO_PREFIX = "Auto · "
FEE_PREFIX = "Fee · "
TTL = int(os.environ.get("CASHEW_CACHE_SECONDS", "60"))  # tests shorten this

TX_COLS = ["id", "date", "type", "category", "amount", "note", "member", "account", "to_account", "created_by"]
TX_SQL = ("SELECT id, date, type, category, amount, note, member, account, to_account, created_by "
          "FROM transactions ORDER BY date DESC, id DESC")

# Every table, each as (columns, query). They all come back together in ONE round trip
# (as JSON), instead of one trip per table: on a distant database each trip costs ~0.1-0.2 s.
SMALL = {
    "tx": (TX_COLS, TX_SQL),
    "budgets": (["category", "monthly_limit"], "SELECT category, monthly_limit FROM budgets ORDER BY category"),
    "cats": (["name", "group_name", "kind"], "SELECT name, group_name, kind FROM categories ORDER BY id"),
    "accts": (["name", "opening_balance", "spendable"],
              "SELECT name, opening_balance, COALESCE(spendable, TRUE) AS spendable FROM accounts ORDER BY id"),
    "rules": (["id", "name", "type", "amount", "fee", "category", "account", "to_account", "member", "note", "frequency",
               "start_date", "next_date", "run_count", "end_date", "active", "last_run"],
              "SELECT id, name, type, amount, fee, category, account, to_account, member, note, frequency, start_date, "
              "next_date, run_count, end_date, active, last_run FROM recurring_rules ORDER BY id"),
    "goals": (["id", "name", "target", "deadline", "saved"],
              "SELECT g.id, g.name, g.target, g.deadline, COALESCE(SUM(c.amount), 0) AS saved "
              "FROM goals g LEFT JOIN goal_contributions c ON c.goal_id = g.id "
              "GROUP BY g.id, g.name, g.target, g.deadline ORDER BY g.id"),
    "contribs": (["id", "date", "goal_id", "goal", "amount", "note", "created_by"],
                 "SELECT c.id, c.date, c.goal_id, g.name AS goal, c.amount, c.note, c.created_by "
                 "FROM goal_contributions c JOIN goals g ON g.id = c.goal_id ORDER BY c.date DESC, c.id DESC LIMIT 200"),
    "users": (["id", "username", "display_name", "is_owner", "last_login", "created_at"],
              "SELECT id, username, display_name, is_owner, last_login, created_at FROM users ORDER BY id"),
    "features": (["key", "value"], "SELECT key, value FROM app_meta WHERE key LIKE 'feature_%'"),
}
SMALL_SQL = "SELECT " + ", ".join(
    f"(SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t) AS {name}" for name, (_, sql) in SMALL.items())
DATE_COLS = {"rules": ["start_date", "next_date", "end_date", "last_run"], "goals": ["deadline"], "contribs": ["date"]}


def _as_dates(df, cols):
    for c in cols:
        d = pd.to_datetime(df[c], errors="coerce")
        df[c] = [x.date() if pd.notna(x) else None for x in d]
    return df


def _load_frames(conn):
    out = {}
    with conn.cursor() as cur:
        cur.execute(SMALL_SQL)
        row = cur.fetchone()
    for (name, (cols, _)), records in zip(SMALL.items(), row):
        df = pd.DataFrame(records or [], columns=cols)
        out[name] = _as_dates(df, DATE_COLS.get(name, []))
    return out


@st.cache_resource(ttl=TTL, show_spinner=False)
def load_book():
    """All data, from one database round of queries on one connection."""
    return Book(transact(_load_frames, read_only=True))


def book():
    return load_book()


def _floats(df, *cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float) if len(df) else pd.Series(dtype=float)
    return df


def _text(df, *cols):
    for c in cols:
        df[c] = df[c].astype(object).where(df[c].notna(), "") if len(df) else pd.Series(dtype=object)
    return df


class Book:
    """Everything the pages need. Built once per data change and shared, so treat it as read-only."""

    def __init__(self, f):
        cats = f["cats"]
        self.cats = cats
        self.budgets = _floats(f["budgets"], "monthly_limit")
        self.accts = _floats(f["accts"], "opening_balance")
        self.account_names = self.accts["name"].tolist()
        self.group_of = dict(zip(cats["name"], cats["group_name"]))
        self.kind_of = dict(zip(cats["name"], cats["kind"]))
        self.groups = list(dict.fromkeys(cats["group_name"].tolist()))
        self.users = f["users"]
        self.name_of_user = dict(zip(self.users["username"], self.users["display_name"]))

        tx = _text(_floats(f["tx"], "amount"), "note", "member", "account", "to_account", "created_by")
        if len(tx):
            tx["member"] = tx["member"].replace("", SHARED)
            tx["date"] = pd.to_datetime(tx["date"]).dt.date
            tx["month"] = pd.to_datetime(tx["date"]).dt.to_period("M")
            tx["group"] = tx["category"].map(self.group_of).fillna(tx["category"])
            tx["is_auto"] = tx["note"].str.startswith(AUTO_PREFIX)
            tx["is_fee"] = tx["note"].str.startswith(FEE_PREFIX)
        else:
            for c in ("month", "group", "is_auto", "is_fee"):
                tx[c] = pd.Series(dtype=object)
        self.tx = tx

        rules = f["rules"]
        self.rules = _text(_floats(rules, "amount", "fee"), "note", "to_account", "member") if len(rules) else rules
        self.goals = _floats(f["goals"], "target", "saved")
        self.contribs = _text(_floats(f["contribs"], "amount"), "note", "created_by")
        feats = f.get("features")
        self._features = dict(zip(feats["key"], feats["value"])) if feats is not None and len(feats) else {}

    def feature(self, name):
        """Parts of the app that can be switched off in Settings (kitchen, goals, reminders). On unless turned off."""
        return self._features.get(f"feature_{name}", "on") != "off"

    # ---- categories -------------------------------------------------------
    def category_names(self, kind=None):
        """Category names in the order they were set up, kept together by group."""
        return list(self._category_names.get(kind, []))

    @cached_property
    def _category_names(self):
        out = {}
        for kind in [None] + KINDS:
            d = self.cats if kind is None else self.cats[self.cats["kind"] == kind]
            names = []
            for _, grp in d.groupby("group_name", sort=False):
                names.extend(grp["name"].tolist())
            out[kind] = names
        return out

    def cat_label(self, name):
        group = self.group_of.get(name)
        return f"{group} › {name}" if group and group != name else name

    @cached_property
    def _manual(self):
        """Entries people typed in themselves (not auto entries or fees): the basis for smart defaults."""
        if not len(self.tx):
            return self.tx
        return self.tx[~self.tx["is_auto"] & ~self.tx["is_fee"]]

    def top_categories(self, kind, n=6):
        """The categories used most for this type over the last 90 days, then the rest in set-up order."""
        names = self.category_names(kind)
        ranked = []
        m = self._manual
        if len(m):
            recent = m[(m["type"] == kind) & (m["date"] >= date.today() - timedelta(days=90))]
            ranked = [c for c in recent["category"].value_counts().index if c in names]
        return (ranked + [c for c in names if c not in ranked])[:n]

    def default_category(self, kind):
        top = self.top_categories(kind, 1)
        return top[0] if top else None

    def last_amount(self, kind, category):
        """What was last entered for this category, for the one-tap 'same as last time' button."""
        m = self._manual
        if not len(m):
            return None
        hit = m[(m["type"] == kind) & (m["category"] == category)]
        return float(hit["amount"].iloc[0]) if len(hit) else None

    # ---- people and accounts ---------------------------------------------
    @cached_property
    def _members(self):
        others = set(self.tx["member"]) - {SHARED} if len(self.tx) else set()
        return [SHARED] + sorted(others)

    def members(self):
        return list(self._members)

    @cached_property
    def multi_member(self):
        return len(self.tx) > 0 and self.tx["member"].nunique() > 1

    @cached_property
    def _balances(self):
        bal = self.accts.set_index("name")["opening_balance"].astype(float)
        t = self.tx
        if not len(t):
            return bal

        def total(kind, col):
            return t[t["type"] == kind].groupby(col)["amount"].sum().reindex(bal.index, fill_value=0.0)

        return (
            bal
            + total("Income", "account")
            - total("Expense", "account")
            - total("Transfer", "account")
            + total("Transfer", "to_account")
        )

    def balances(self):
        return self._balances.copy()

    def balance(self, account):
        return float(self._balances.get(account, 0.0))

    @cached_property
    def unassigned(self):
        if not len(self.tx):
            return 0
        return int(((self.tx["account"] == "") & (self.tx["type"] != "Transfer")).sum())

    def unassigned_count(self):
        return self.unassigned

    def default_account(self, kind, col="account"):
        """The account last used for this type of entry, so the usual choice is already picked."""
        m = self._manual
        if len(m):
            used = m[(m["type"] == kind) & (m[col] != "")]
            for name in used[col].head(20):
                if name in self.account_names:
                    return name
        if col == "account" and "Cash" in self.account_names:
            return "Cash"
        return self.account_names[0] if self.account_names else None

    # ---- months -----------------------------------------------------------
    def months(self):
        """Months with entries, newest first, always including this month."""
        this = pd.Period(date.today(), "M")
        found = set(self.tx["month"]) if len(self.tx) else set()
        return sorted(found | {this}, reverse=True)

    @cached_property
    def _month_totals(self):
        t = self.tx
        if not len(t):
            return {}
        sums = t[t["type"].isin(["Income", "Expense"])].groupby(["month", "type"])["amount"].sum()
        return sums.to_dict()

    def month_totals(self, period, upto_day=None):
        """(income, expenses) for a month. upto_day=12 counts only the 1st to the 12th, so this month so far
        can be compared fairly with the same days of last month."""
        if upto_day is None:
            mt = self._month_totals
            return float(mt.get((period, "Income"), 0.0)), float(mt.get((period, "Expense"), 0.0))
        t = self.tx
        if not len(t):
            return 0.0, 0.0
        t = t[(t["month"] == period) & (pd.to_datetime(t["date"]).dt.day <= upto_day)]
        return (float(t.loc[t["type"] == "Income", "amount"].sum()),
                float(t.loc[t["type"] == "Expense", "amount"].sum()))

    def month_expenses(self, period):
        if not len(self.tx):
            return self.tx
        return self.tx[(self.tx["month"] == period) & (self.tx["type"] == "Expense")]

    def budget_status(self, period):
        """Each budget with what was spent in that month, worst first."""
        if not len(self.budgets):
            return []
        d = self.month_expenses(period)
        by_group = d.groupby("group")["amount"].sum() if len(d) else pd.Series(dtype=float)
        by_cat = d.groupby("category")["amount"].sum() if len(d) else pd.Series(dtype=float)
        groups = set(self.cats["group_name"])
        out = []
        for key, limit in zip(self.budgets["category"], self.budgets["monthly_limit"]):
            limit = float(limit)
            spent = float((by_group if key in groups else by_cat).get(key, 0.0))
            pct = spent / limit * 100 if limit > 0 else 0.0
            out.append({"name": key, "limit": limit, "spent": spent, "pct": pct, "is_group": key in groups})
        return sorted(out, key=lambda b: b["pct"], reverse=True)

    # ---- safe to spend ---------------------------------------------------------
    @cached_property
    def everyday_accounts(self):
        return [n for n, sp in zip(self.accts["name"], self.accts["spendable"]) if bool(sp)]

    def payday(self, today=None):
        """When money next comes in: the next auto income entry, or a month after the last salary,
        or the 1st of next month if neither is known."""
        today = today or date.today()
        if len(self.rules):
            inc = self.rules[self.rules["active"] & (self.rules["type"] == "Income")]
            upcoming = [d for d in inc["next_date"] if d and d > today]
            if upcoming:
                return min(upcoming), "next auto income"
        m = self._manual
        if len(m):
            sal = m[(m["type"] == "Income") & m["category"].str.contains("salary", case=False, regex=False)]
            if len(sal):
                last = sal["date"].iloc[0]
                n = 1
                while occurrence(last, "Monthly", n) <= today and n < 600:
                    n += 1
                return occurrence(last, "Monthly", n), "a month after the last salary"
        first_next = (pd.Period(today, "M") + 1).start_time.date()
        return first_next, "the 1st of next month"

    def safe_to_spend(self, today=None):
        """Everyday money, minus bills that auto transactions will take before payday,
        minus what's still unspent in this month's budgets."""
        today = today or date.today()
        everyday = set(self.everyday_accounts)
        money = sum(self.balance(a) for a in everyday)
        pay, pay_basis = self.payday(today)

        bills, bills_by_cat = 0.0, {}
        if len(self.rules):
            for _, r in self.rules[self.rules["active"]].iterrows():
                n, guard = int(r["run_count"]), 0
                d = occurrence(r["start_date"], r["frequency"], n)
                while d < pay and guard < 400 and (r["end_date"] is None or pd.isna(r["end_date"]) or d <= r["end_date"]):
                    cost = 0.0
                    fee = float(r["fee"]) if pd.notna(r["fee"]) else 0.0
                    if r["type"] == "Expense" and r["account"] in everyday:
                        cost = float(r["amount"])
                    elif r["type"] == "Transfer":
                        out_of = r["account"] in everyday
                        into = r["to_account"] in everyday
                        if out_of and not into:
                            cost = float(r["amount"]) + fee   # e.g. the monthly move into Susu
                        elif out_of:
                            cost = fee
                        elif into:
                            cost = -float(r["amount"])         # money coming back into everyday accounts
                    if cost:
                        bills += cost
                        if d.month == today.month and d.year == today.year and r["type"] == "Expense":
                            bills_by_cat[r["category"]] = bills_by_cat.get(r["category"], 0.0) + cost
                    n += 1
                    guard += 1
                    d = occurrence(r["start_date"], r["frequency"], n)

        budget_left = 0.0
        period = pd.Period(today, "M")
        status = self.budget_status(period)
        group_budgets = {b["name"] for b in status if b["is_group"]}
        for b in status:
            if not b["is_group"] and self.group_of.get(b["name"]) in group_budgets:
                continue  # already covered by its group's budget
            # don't count an upcoming auto bill twice if it falls inside this budget
            already = sum(v for c, v in bills_by_cat.items()
                          if c == b["name"] or (b["is_group"] and self.group_of.get(c) == b["name"]))
            budget_left += max(b["limit"] - b["spent"] - already, 0.0)

        safe = money - bills - budget_left
        days = max((pay - today).days, 1)
        return {"safe": safe, "money": money, "bills": bills, "budget_left": budget_left, "payday": pay,
                "basis": pay_basis, "days": days, "per_day": safe / days, "accounts": sorted(everyday)}

    def next_auto(self):
        if not len(self.rules):
            return None
        active = self.rules[self.rules["active"]]
        if not len(active):
            return None
        return active.sort_values(["next_date", "id"]).iloc[0]

    def auto_due(self, today=None):
        """True when an auto transaction is due, so the app only asks the database when there's work to do."""
        if not len(self.rules):
            return False
        today = today or date.today()
        active = self.rules[self.rules["active"]]
        return bool(len(active) and (pd.to_datetime(active["next_date"]).dt.date <= today).any())


FEATURES = {
    "kitchen": ("Kitchen", "Meal plan, recipes, fridge, pantry and shopping list"),
    "goals": ("Savings goals", "Saving towards school fees, rent, a car and so on"),
    "reminders": ("Phone reminders", "The morning and evening Telegram messages"),
    "fun": ("Fun reminders", "A joke in front of each kitchen reminder. Off means plain reminders"),
}


def set_feature(name, on):
    from core.db import execute
    execute("INSERT INTO app_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (f"feature_{name}", "on" if on else "off"))


def money(x, signed=False):
    sign = ("−" if x < 0 else "+") if signed else ("−" if x < 0 else "")
    return f"{sign}{CURRENCY}{abs(x):,.2f}"


def clean_note(note):
    for p in (AUTO_PREFIX, FEE_PREFIX):
        if note.startswith(p):
            return note[len(p):]
    return note

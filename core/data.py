"""Cached data loading and the questions every page asks of it.

Loads are cached for a minute and cleared after every save, so clicking around
the app no longer hits the database each time.
"""
from datetime import date

import pandas as pd
import streamlit as st

from core.db import query

CURRENCY = "GH₵"
SHARED = "Household"  # used when a transaction isn't tied to one family member
KINDS = ["Expense", "Income", "Transfer"]
FREQUENCIES = ["Weekly", "Every 2 weeks", "Monthly", "Yearly"]
FEE_CATEGORY = "Charges"
AUTO_PREFIX = "Auto · "
FEE_PREFIX = "Fee · "
TTL = 60


@st.cache_data(ttl=TTL, show_spinner=False)
def _transactions():
    return query(
        "SELECT id, date, type, category, amount, note, member, account, to_account "
        "FROM transactions ORDER BY date DESC, id DESC"
    )


@st.cache_data(ttl=TTL, show_spinner=False)
def _setup():
    budgets = query("SELECT category, monthly_limit FROM budgets ORDER BY category")
    cats = query("SELECT name, group_name, kind FROM categories ORDER BY id")
    accts = query("SELECT name, opening_balance FROM accounts ORDER BY id")
    return budgets, cats, accts


@st.cache_data(ttl=TTL, show_spinner=False)
def _rules():
    return query("SELECT * FROM recurring_rules ORDER BY id")


@st.cache_data(ttl=TTL, show_spinner=False)
def _goals():
    goals = query(
        """
        SELECT g.id, g.name, g.target, g.deadline, COALESCE(SUM(c.amount), 0) AS saved
        FROM goals g LEFT JOIN goal_contributions c ON c.goal_id = g.id
        GROUP BY g.id, g.name, g.target, g.deadline
        ORDER BY g.id
        """
    )
    contribs = query(
        """
        SELECT c.id, c.date, c.goal_id, g.name AS goal, c.amount, c.note
        FROM goal_contributions c JOIN goals g ON g.id = c.goal_id
        ORDER BY c.date DESC, c.id DESC LIMIT 200
        """
    )
    return goals, contribs


def _floats(df, *cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float) if len(df) else pd.Series(dtype=float)
    return df


def _text(df, *cols):
    for c in cols:
        df[c] = df[c].astype(object).where(df[c].notna(), "") if len(df) else pd.Series(dtype=object)
    return df


class Book:
    """Everything the pages need, loaded once per run."""

    def __init__(self):
        budgets, cats, accts = _setup()
        self.cats = cats
        self.budgets = _floats(budgets, "monthly_limit")
        self.accts = _floats(accts, "opening_balance")
        self.account_names = self.accts["name"].tolist()
        self.group_of = dict(zip(cats["name"], cats["group_name"]))
        self.kind_of = dict(zip(cats["name"], cats["kind"]))
        self.groups = list(dict.fromkeys(cats["group_name"].tolist()))

        tx = _text(_floats(_transactions(), "amount"), "note", "member", "account", "to_account")
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

        rules = _rules()
        self.rules = _text(_floats(rules, "amount", "fee"), "note", "to_account", "member") if len(rules) else rules

        goals, contribs = _goals()
        self.goals = _floats(goals, "target", "saved")
        self.contribs = _text(_floats(contribs, "amount"), "note")

    # ---- categories -------------------------------------------------------
    def category_names(self, kind=None):
        """Category names in the order they were set up, kept together by group."""
        d = self.cats if kind is None else self.cats[self.cats["kind"] == kind]
        names = []
        for _, grp in d.groupby("group_name", sort=False):
            names.extend(grp["name"].tolist())
        return names

    def cat_label(self, name):
        group = self.group_of.get(name)
        return f"{group} › {name}" if group and group != name else name

    # ---- people and accounts ---------------------------------------------
    def members(self):
        others = set(self.tx["member"]) - {SHARED} if len(self.tx) else set()
        return [SHARED] + sorted(others)

    @property
    def multi_member(self):
        return len(self.tx) > 0 and self.tx["member"].nunique() > 1

    def balances(self):
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

    def unassigned_count(self):
        if not len(self.tx):
            return 0
        return int(((self.tx["account"] == "") & (self.tx["type"] != "Transfer")).sum())

    # ---- smart defaults ---------------------------------------------------
    def default_account(self, kind, col="account"):
        """The account last used for this type of entry, so the usual choice is already picked."""
        if len(self.tx):
            used = self.tx[(self.tx["type"] == kind) & (self.tx[col] != "") & ~self.tx["is_auto"]]
            for name in used[col]:
                if name in self.account_names:
                    return name
        if col == "account" and "Cash" in self.account_names:
            return "Cash"
        return self.account_names[0] if self.account_names else None

    def default_category(self, kind):
        """The category used most often for this type over the last 60 days."""
        names = self.category_names(kind)
        if not names:
            return None
        if len(self.tx):
            recent = self.tx[(self.tx["type"] == kind) & ~self.tx["is_auto"] & ~self.tx["is_fee"]]
            recent = recent[recent["date"] >= date.today() - pd.Timedelta(days=60)]
            for name in recent["category"].value_counts().index:
                if name in names:
                    return name
        return names[0]

    # ---- months -----------------------------------------------------------
    def months(self):
        """Months with entries, newest first, always including this month."""
        this = pd.Period(date.today(), "M")
        found = set(self.tx["month"]) if len(self.tx) else set()
        return sorted(found | {this}, reverse=True)

    def month_totals(self, period):
        d = self.tx[self.tx["month"] == period] if len(self.tx) else self.tx
        inc = float(d.loc[d["type"] == "Income", "amount"].sum()) if len(d) else 0.0
        exp = float(d.loc[d["type"] == "Expense", "amount"].sum()) if len(d) else 0.0
        return inc, exp

    def budget_status(self, period):
        """Each budget with what was spent in that month, worst first."""
        if not len(self.budgets):
            return []
        d = self.tx[(self.tx["month"] == period) & (self.tx["type"] == "Expense")] if len(self.tx) else self.tx
        by_group = d.groupby("group")["amount"].sum() if len(d) else pd.Series(dtype=float)
        by_cat = d.groupby("category")["amount"].sum() if len(d) else pd.Series(dtype=float)
        groups = set(self.cats["group_name"])
        out = []
        for _, row in self.budgets.iterrows():
            key, limit = row["category"], float(row["monthly_limit"])
            spent = float((by_group if key in groups else by_cat).get(key, 0.0))
            pct = spent / limit * 100 if limit > 0 else 0.0
            out.append({"name": key, "limit": limit, "spent": spent, "pct": pct, "is_group": key in groups})
        return sorted(out, key=lambda b: b["pct"], reverse=True)

    def next_auto(self):
        if not len(self.rules):
            return None
        active = self.rules[self.rules["active"]]
        if not len(active):
            return None
        return active.sort_values(["next_date", "id"]).iloc[0]


def book():
    return Book()


def money(x, signed=False):
    sign = ("−" if x < 0 else "+") if signed else ("−" if x < 0 else "")
    return f"{sign}{CURRENCY}{abs(x):,.2f}"


def clean_note(note):
    for p in (AUTO_PREFIX, FEE_PREFIX):
        if note.startswith(p):
            return note[len(p):]
    return note

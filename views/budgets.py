from datetime import date

import pandas as pd
import streamlit as st

from core.data import CURRENCY, book, money
from core.db import execute
from ui.components import budget_html, card, confirm, empty, field_msg, flash, page_header, section


def _targets(b):
    """Every expense group, then its categories, as budget choices."""
    targets = {}
    for g, grp in b.cats[b.cats["kind"] == "Expense"].groupby("group_name", sort=False):
        targets[g] = f"{g} (whole group)"
        for n in grp["name"]:
            if n != g:
                targets[n] = f"{g} › {n}"
    return targets


def render():
    ss = st.session_state
    b = book()
    period = pd.Period(date.today(), "M")
    page_header("Budgets", "A monthly limit for a whole group, like Food, or for one category")
    status = b.budget_status(period)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("budget-progress"):
            section("This month", period.strftime("%B %Y"))
            if status:
                st.html(f'<div class="prog-list">{"".join(budget_html(s) for s in status)}</div>')
            else:
                empty("No budgets yet. Set your first one on this page.")

    with right:
        with card("budget-set"):
            section("Set a budget")
            targets = _targets(b)
            if not targets:
                empty("Add expense categories first in Settings → Accounts.")
            else:
                key = st.selectbox("Budget for", list(targets), format_func=lambda k: targets[k], key="draft_b_key",
                                   help="Pick a whole group like Food, or a single category.")
                current = dict(zip(b.budgets["category"], b.budgets["monthly_limit"])).get(key)
                limit = st.number_input(f"Monthly limit ({CURRENCY})", min_value=0.0, value=None, step=50.0,
                                        format="%.2f", placeholder="0.00", key="draft_b_limit")
                if current is not None:
                    field_msg(f"Currently {money(current)}. Saving replaces it.", "hint")
                spent = next((s["spent"] for s in b.budget_status(period) if s["name"] == key), None)
                if spent is None and len(b.tx):
                    month_exp = b.tx[(b.tx["month"] == period) & (b.tx["type"] == "Expense")]
                    col = "group" if key in set(b.cats["group_name"]) else "category"
                    spent = float(month_exp.loc[month_exp[col] == key, "amount"].sum())
                if limit and spent and limit < spent:
                    field_msg(f"You've already spent {money(spent)} on this in {period.strftime('%B')}.", "warn")
                overlap = None
                if key in set(b.cats["group_name"]):
                    inside = set(b.cats.loc[b.cats["group_name"] == key, "name"]) & set(b.budgets["category"])
                    if inside:
                        overlap = f"{', '.join(sorted(inside))} also {'has' if len(inside) == 1 else 'have'} their own budget inside this group."
                elif b.group_of.get(key) in set(b.budgets["category"]):
                    overlap = f"The whole {b.group_of[key]} group already has a budget that includes this."
                if overlap:
                    field_msg(overlap, "hint")
                if st.button("Save budget", type="primary", width="stretch", disabled=not limit, key="btn_b_save",
                             icon=":material/check:"):
                    execute(
                        "INSERT INTO budgets (category, monthly_limit) VALUES (%s, %s) "
                        "ON CONFLICT (category) DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit",
                        (key, limit),
                    )
                    ss.pop("draft_b_limit", None)
                    flash(f"Budget for {key} set to {money(limit)} a month")
                    st.rerun()
                if not limit:
                    field_msg("Enter a monthly limit to save.", "hint")

        if len(b.budgets):
            with card("budget-remove"):
                section("Remove a budget")
                pick = st.selectbox("Budget", b.budgets["category"].tolist(), key="budget_remove",
                                    label_visibility="collapsed")
                if st.button("Remove", icon=":material/delete:", key="btn_b_remove"):
                    confirm(f"Remove the budget for **{pick}**? Your spending records aren't affected.",
                            [("DELETE FROM budgets WHERE category = %s", (pick,))], f"Removed the budget for {pick}",
                            button="Remove")

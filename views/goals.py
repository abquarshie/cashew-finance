from datetime import date

import pandas as pd
import streamlit as st

from core.data import CURRENCY, book, money
from core.db import execute
from ui.components import card, confirm, empty, field_msg, flash, page_header, pill, progress_html, section
from ui.entry import goal_form


def _goal_html(g):
    today = date.today()
    target, saved = g["target"], g["saved"]
    pct = saved / target * 100 if target > 0 else 0.0
    remaining = max(target - saved, 0.0)
    deadline = pd.to_datetime(g["deadline"]).date() if pd.notna(g["deadline"]) else None
    right = f'<span class="num">{money(saved)} of {money(target)}</span>'
    if saved >= target:
        return progress_html(g["name"], 100, "ok", pill("Reached", "in"), "Goal reached", right)
    if deadline and deadline < today:
        return progress_html(g["name"], pct, "over", pill("Past date", "out"),
                             f"{money(remaining)} still to go", right, foot_over=True)
    if deadline:
        months_left = max((deadline.year - today.year) * 12 + (deadline.month - today.month), 1)
        return progress_html(g["name"], pct, "ok", pill(f"Due {deadline:%d %b %Y}", "accent"),
                             f"About {money(remaining / months_left)} a month", right)
    return progress_html(g["name"], pct, "ok", pill(f"{pct:.0f}%", "neutral"), f"{money(remaining)} to go", right)


def render():
    ss = st.session_state
    b = book()
    page_header("Savings goals", "Save together for school fees, rent, a car or anything else")

    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("goal-progress"):
            section("Progress")
            if len(b.goals):
                st.html(f'<div class="prog-list">{"".join(_goal_html(g) for _, g in b.goals.iterrows())}</div>')
            else:
                empty("No goals yet. Create your first one on this page.")
        if len(b.contribs):
            with card("goal-history"):
                section("Recent savings")
                st.dataframe(
                    b.contribs[["date", "goal", "amount", "note"]].head(30), hide_index=True, width="stretch",
                    column_config={
                        "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                        "goal": "Goal",
                        "amount": st.column_config.NumberColumn(f"Amount ({CURRENCY})", format="%.2f"),
                        "note": "Note",
                    },
                )

    with right, card("goal-actions"):
        tab_add, tab_new, tab_manage = st.tabs(["Add money", "New goal", "Manage"])
        with tab_add:
            goal_form(b)
        with tab_new:
            name = st.text_input("Goal name", placeholder="e.g. School fees", key="draft_ng_name")
            n1, n2 = st.columns(2)
            target = n1.number_input(f"Target ({CURRENCY})", min_value=0.0, value=None, step=100.0, format="%.2f",
                                     placeholder="0.00", key="draft_ng_target")
            deadline = n2.date_input("Deadline (optional)", value=None, key="draft_ng_deadline", format="DD/MM/YYYY")
            taken = {n.strip().lower() for n in b.goals["name"]} if len(b.goals) else set()
            if name.strip().lower() in taken:
                field_msg("You already have a goal with this name.", "warn")
            bad_date = deadline is not None and deadline <= date.today()
            if bad_date:
                field_msg("Pick a deadline after today, or leave it empty.")
            ready = bool(name.strip()) and bool(target) and not bad_date
            if st.button("Create goal", type="primary", width="stretch", disabled=not ready, key="btn_ng_create",
                         icon=":material/flag:"):
                execute("INSERT INTO goals (name, target, deadline) VALUES (%s, %s, %s)", (name.strip(), target, deadline))
                for k in ("draft_ng_name", "draft_ng_target", "draft_ng_deadline"):
                    ss.pop(k, None)
                flash(f"Created the goal '{name.strip()}'", ":material/flag:")
                st.rerun()
            if not ready and not bad_date:
                field_msg("Add a name and a target to create it.", "hint")
        with tab_manage:
            if not len(b.goals) and not len(b.contribs):
                empty("Nothing to manage yet.")
            if len(b.contribs):
                labels = {int(r["id"]): f"{r['date']:%d %b %Y}, {r['goal']}, {money(r['amount'])}" for _, r in b.contribs.iterrows()}
                c_pick = st.selectbox("Remove a saving", list(labels), format_func=lambda i: labels[i], key="contrib_pick")
                if st.button("Remove saving", icon=":material/delete:", key="btn_contrib_remove"):
                    confirm(f"Remove **{labels[c_pick]}**?", [("DELETE FROM goal_contributions WHERE id = %s", (int(c_pick),))],
                            "Saving removed", button="Remove")
            if len(b.goals):
                names = {int(r["id"]): r["name"] for _, r in b.goals.iterrows()}
                g_pick = st.selectbox("Delete a goal", list(names), format_func=lambda i: names[i], key="goal_delete")
                if st.button("Delete goal", icon=":material/delete:", key="btn_goal_delete"):
                    confirm(f"Delete **{names[g_pick]}** and all the savings recorded for it?",
                            [("DELETE FROM goals WHERE id = %s", (int(g_pick),))], f"Deleted '{names[g_pick]}'")

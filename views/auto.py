from datetime import date

import pandas as pd
import streamlit as st

from auto_rules import catch_up, occurrence
from core.data import CURRENCY, FEE_CATEGORY, FREQUENCIES, KINDS, SHARED, book, money
from core.db import execute
from ui.components import card, confirm, empty, esc, field_msg, flash, page_header, pill, section


def _status(r):
    finished = (not r["active"]) and pd.notna(r["end_date"]) and r["next_date"] > r["end_date"]
    if r["active"]:
        return "Active", "in"
    return ("Finished", "neutral") if finished else ("Paused", "warn")


def _rule_html(b, r):
    status, tone = _status(r)
    if r["type"] == "Transfer":
        what = f"{r['account']} to {r['to_account']}"
        if r["fee"] and r["fee"] > 0:
            what += f", {money(r['fee'])} fee"
    else:
        what = f"{b.cat_label(r['category'])}, from {r['account']}" if r["type"] == "Expense" else f"{b.cat_label(r['category'])}, into {r['account']}"
    if r["active"]:
        days = (r["next_date"] - date.today()).days
        nxt = "Next: today" if days <= 0 else f"Next: {r['next_date']:%a %d %b}"
    elif status == "Finished":
        nxt = f"Ended {r['end_date']:%d %b %Y}"
    else:
        nxt = "Not running"
    ends = f", until {r['end_date']:%d %b %Y}" if pd.notna(r["end_date"]) and r["active"] else ""
    return (
        f'<div class="rule"><div style="min-width:0"><div class="rule-name">{esc(r["name"])}{pill(status, tone)}</div>'
        f'<div class="rule-meta">{esc(r["frequency"])} {esc(r["type"].lower())}{esc(ends)}. {esc(what)}</div></div>'
        f'<div class="rule-right"><div class="amt">{money(r["amount"])}</div><div class="rule-next">{esc(nxt)}</div></div></div>'
    )


def _manage(b):
    rules = b.rules
    names = {int(r["id"]): r["name"] for _, r in rules.iterrows()}
    pick = st.selectbox("Auto transaction", list(names), format_func=lambda i: names[i], key="rule_pick")
    rule = rules[rules["id"] == pick].iloc[0]
    status, _ = _status(rule)

    c1, c2 = st.columns(2)
    new_amount = c1.number_input(f"Amount ({CURRENCY})", min_value=0.01, value=float(rule["amount"]), format="%.2f",
                                 key=f"rule_amt_{pick}")
    new_fee = None
    if rule["type"] == "Transfer":
        new_fee = c2.number_input(f"Fee ({CURRENCY})", min_value=0.0,
                                  value=float(rule["fee"]) if pd.notna(rule["fee"]) else 0.0, format="%.2f",
                                  key=f"rule_fee_{pick}")
    new_end = (c2 if rule["type"] != "Transfer" else st).date_input(
        "Stop after (optional)", value=rule["end_date"] if pd.notna(rule["end_date"]) else None,
        key=f"rule_end_{pick}", format="DD/MM/YYYY")
    end_bad = new_end is not None and new_end < rule["start_date"]
    if end_bad:
        field_msg("The stop date is before the first run.")
    old_fee = float(rule["fee"]) if pd.notna(rule["fee"]) else 0.0
    changed = (round(new_amount, 2) != round(float(rule["amount"]), 2)
               or (new_fee is not None and round(new_fee, 2) != round(old_fee, 2))
               or new_end != (rule["end_date"] if pd.notna(rule["end_date"]) else None))

    row = st.container(horizontal=True)
    if row.button("Save changes", type="primary", disabled=not changed or end_bad, key=f"rule_save_{pick}",
                  icon=":material/check:"):
        active = bool(rule["active"])
        n, nxt = int(rule["run_count"]), rule["next_date"]
        if status == "Finished" and (new_end is None or new_end >= date.today()):
            # running again after it finished: carry on from today, not with every date it missed meanwhile
            n = catch_up(rule["start_date"], rule["frequency"], n)
            nxt = occurrence(rule["start_date"], rule["frequency"], n)
            active = new_end is None or nxt <= new_end
        elif status == "Finished" and nxt <= new_end:
            active = True  # the end was moved to a date already past: fill in the runs up to it, as recorded
        elif new_end is not None and nxt > new_end:
            active = False
        execute("UPDATE recurring_rules SET amount=%s, fee=%s, end_date=%s, active=%s, run_count=%s, next_date=%s "
                "WHERE id=%s", (new_amount, new_fee if new_fee else None, new_end, active, n, nxt, int(pick)))
        flash("Saved. Changes apply to future runs.")
        st.rerun()
    if status == "Active":
        if row.button("Pause", icon=":material/pause:", key=f"rule_pause_{pick}"):
            execute("UPDATE recurring_rules SET active=FALSE WHERE id=%s", (int(pick),))
            flash(f"Paused '{rule['name']}'", ":material/pause:")
            st.rerun()
    elif status == "Paused":
        if row.button("Resume", icon=":material/play_arrow:", key=f"rule_resume_{pick}",
                      help="Skips the dates it was paused for, instead of adding them all at once."):
            n = catch_up(rule["start_date"], rule["frequency"], int(rule["run_count"]))
            execute("UPDATE recurring_rules SET active=TRUE, run_count=%s, next_date=%s WHERE id=%s",
                    (n, occurrence(rule["start_date"], rule["frequency"], n), int(pick)))
            flash(f"Resumed '{rule['name']}'", ":material/play_arrow:")
            st.rerun()
    if row.button("Delete", icon=":material/delete:", key=f"rule_del_{pick}"):
        confirm(f"Delete **{rule['name']}**? Entries it already added stay in your transactions.",
                [("DELETE FROM recurring_rules WHERE id=%s", (int(pick),))], f"Deleted '{rule['name']}'")


def _new_rule(b):
    ss = st.session_state
    # starting values live in session state (not widget defaults) so half-filled forms survive page changes
    if ss.get("draft_r_kind") not in KINDS:
        ss["draft_r_kind"] = "Transfer"
    ss.setdefault("draft_r_freq", "Monthly")
    ss.setdefault("draft_r_start", date.today())
    kind = st.segmented_control("Type", KINDS, key="draft_r_kind", label_visibility="collapsed",
                                width="stretch") or "Transfer"
    names = b.category_names(kind)
    if not names:
        st.warning(f"There are no {kind.lower()} categories yet. Add one in **Settings → Accounts**.")
        return
    q1, q2 = st.columns(2)
    name = q1.text_input("Name", placeholder="e.g. Monthly Susu", key="draft_r_name")
    amount = q2.number_input(f"Amount ({CURRENCY})", min_value=0.0, value=None, step=10.0, format="%.2f",
                             placeholder="0.00", key="draft_r_amount")
    errors = []
    taken = {n.strip().lower() for n in b.rules["name"]} if len(b.rules) else set()
    if name.strip().lower() in taken:
        with q1:
            field_msg("You already have one with this name.", "warn")

    fee, to_acct, member = None, None, SHARED
    if kind == "Transfer":
        a1, a2 = st.columns(2)
        account = a1.selectbox("From", b.account_names, key="draft_r_from")
        if ss.get("draft_r_to") not in b.account_names:
            ss["draft_r_to"] = next((a for a in b.account_names if a != account), account)
        to_acct = a2.selectbox("To", b.account_names, key="draft_r_to")
        if account == to_acct:
            errors.append("same")
            with a2:
                field_msg("Pick a different account to move the money into.")
        p1, p2 = st.columns(2)
        category = p1.selectbox("Purpose", names, key="draft_r_cat_t")
        fee = p2.number_input(f"Fee ({CURRENCY}), optional", min_value=0.0, value=None, step=0.5, format="%.2f",
                              placeholder="0.00", key="draft_r_fee",
                              help=f"Added as a separate {FEE_CATEGORY} expense each time.")
    else:
        a1, a2 = st.columns(2)
        category = a1.selectbox("Category", names, format_func=b.cat_label, key=f"draft_r_cat_{kind}")
        account = a2.selectbox("Account", b.account_names, key="draft_r_acct")
        member = st.selectbox("Who", b.members(), key="draft_r_who")

    freq = st.selectbox("Repeats", FREQUENCIES, key="draft_r_freq")
    s2, s3 = st.columns(2)
    start = s2.date_input("First run", key="draft_r_start", format="DD/MM/YYYY")
    end = s3.date_input("Stop after (optional)", value=None, key="draft_r_end", format="DD/MM/YYYY")
    if start and start < date.today():
        missed = 0
        while occurrence(start, freq, missed) <= date.today() and (end is None or occurrence(start, freq, missed) <= end) and missed < 400:
            missed += 1
        field_msg(f"This start date is in the past, so {missed} entr{'ies' if missed != 1 else 'y'} will be added straight away.", "warn")
    if end is not None and start and end < start:
        errors.append("end")
        field_msg("The stop date is before the first run.")
    note = st.text_input("Note (optional)", key="draft_r_note")

    if not name.strip():
        errors.append("name")
    if not amount:
        errors.append("amount")
    blocking = [e for e in errors if e not in ("name", "amount")]
    if st.button("Create auto transaction", type="primary", width="stretch", disabled=bool(blocking),
                 key="btn_r_create", icon=":material/autorenew:"):
        if not name.strip() or not amount:
            st.error("Give it a name and an amount.")
        else:
            execute(
                "INSERT INTO recurring_rules (name, type, amount, fee, category, account, to_account, member, note, "
                "frequency, start_date, next_date, run_count, end_date, active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, TRUE)",
                (name.strip(), kind, amount, fee if fee else None, category, account, to_acct, member, note.strip(),
                 freq, start, start, end),
            )
            for k in ("draft_r_name", "draft_r_amount", "draft_r_fee", "draft_r_note"):
                ss.pop(k, None)
            # past start dates are filled in on the next visit check
            ss.pop("auto_checked", None)
            flash(f"Created '{name.strip()}'", ":material/autorenew:")
            st.rerun()
    elif errors and set(errors) <= {"name", "amount"}:
        field_msg("Add a name and an amount to create it.", "hint")


def render():
    b = book()
    page_header("Repeats", "Salary, rent, Susu and other entries that add themselves on a schedule")
    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("rules"):
            section("Your auto transactions")
            if not len(b.rules):
                empty("None yet. Create one on this page, for example a monthly move from GCB to Susu.")
            else:
                order = b.rules.assign(_s=b.rules["active"].map({True: 0, False: 1})).sort_values(["_s", "next_date"])
                st.html("".join(_rule_html(b, r) for _, r in order.iterrows()))
                st.caption("They're added each day, and whenever the app opens. "
                           "If a day is missed, the entry is added with its original date.")
        if len(b.rules):
            with card("rule-manage"):
                section("Change, pause or delete")
                _manage(b)
    with right:
        with card("rule-new"):
            section("New auto transaction")
            if not b.account_names:
                st.warning("Add an account first in **Settings → Accounts**.")
            else:
                _new_rule(b)

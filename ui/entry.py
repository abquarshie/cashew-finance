"""The add-transaction form, used on its own page and in the quick-add pop-up.

Fields are checked as you fill them in. What you type is kept in session state
(keys starting with "draft_"), so switching type or visiting another page doesn't
clear it.
"""
from datetime import date

import streamlit as st

from core.data import CURRENCY, FEE_CATEGORY, KINDS, SHARED, money
from core.db import execute, run_many
from ui.components import field_msg, flash

SAVE_LABEL = {"Expense": "Save expense", "Income": "Save income", "Transfer": "Save transfer"}


def _k(prefix, name):
    return f"draft_{prefix}_{name}"


def set_kind(prefix, kind):
    """Pre-select the type before the form is drawn (used by the quick-action buttons)."""
    st.session_state[_k(prefix, "kind")] = kind


def _keep_kind(prefix):
    key = _k(prefix, "kind")
    if st.session_state.get(key) is None:  # tapping the selected option again would clear it
        st.session_state[key] = st.session_state.get(_k(prefix, "last_kind"), "Expense")
    st.session_state[_k(prefix, "last_kind")] = st.session_state[key]


def _ensure(key, options, default):
    """Make sure a remembered choice still exists (a category may have been renamed)."""
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default in options else (options[0] if options else None)


def _collect(prefix):
    """Read the form straight from session state, so a value typed just before tapping Save is included."""
    ss = st.session_state
    kind = ss.get(_k(prefix, "kind")) or "Expense"
    v = {"kind": kind, "amount": ss.get(_k(prefix, "amount")), "date": ss.get(_k(prefix, "date")) or date.today(),
         "note": (ss.get(_k(prefix, "note")) or "").strip(), "fee": None, "to": None, "who": SHARED}
    if kind == "Transfer":
        v.update(account=ss.get(_k(prefix, "from")), to=ss.get(_k(prefix, "to")),
                 category=ss.get(_k(prefix, "cat_Transfer")), fee=ss.get(_k(prefix, "fee")))
    else:
        v.update(account=ss.get(_k(prefix, f"acct_{kind}")), category=ss.get(_k(prefix, f"cat_{kind}")),
                 who=(ss.get(_k(prefix, "who")) or SHARED).strip() or SHARED)
    return v


def _save(prefix):
    ss = st.session_state
    values = _collect(prefix)
    kind = values["kind"]
    if not values["amount"]:
        ss[_k(prefix, "error")] = "Enter an amount first."
        return
    if kind == "Transfer" and values["account"] == values["to"]:
        ss[_k(prefix, "error")] = "Pick two different accounts."
        return
    if not values["category"] or not values["account"]:
        ss[_k(prefix, "error")] = "Pick a category and an account."
        return
    try:
        stmts = [(
            "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (values["date"], kind, values["category"], values["amount"], values["note"],
             values["who"], values["account"], values["to"]),
        )]
        fee = values.get("fee") or 0
        if kind == "Transfer" and fee > 0:
            stmts.append((
                "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                "VALUES (%s, 'Expense', %s, %s, %s, %s, %s, NULL)",
                (values["date"], FEE_CATEGORY, fee, f"Fee · {values['account']} to {values['to']}", SHARED, values["account"]),
            ))
        run_many(stmts)
    except Exception as exc:
        ss[_k(prefix, "error")] = f"That didn't save: {exc}"
        return
    if kind == "Transfer":
        extra = f" plus {money(fee)} fee" if fee > 0 else ""
        flash(f"Moved {money(values['amount'])} from {values['account']} to {values['to']}{extra}", ":material/swap_horiz:")
    else:
        flash(f"Saved {money(values['amount'])} {kind.lower()} to {values['category']}")
    # clear what changes every time; keep type, date, accounts and category for the next entry
    ss[_k(prefix, "amount")] = None
    ss[_k(prefix, "fee")] = None
    ss[_k(prefix, "note")] = ""
    ss[_k(prefix, "saved")] = True


def entry_form(book, prefix, in_dialog=False):
    ss = st.session_state
    if not book.account_names:
        st.warning("Add an account first in **Categories & accounts**.")
        return

    kind_key = _k(prefix, "kind")
    if ss.get(kind_key) not in KINDS:
        ss[kind_key] = "Expense"
    kind = st.segmented_control("Type", KINDS, key=kind_key, on_change=_keep_kind, args=(prefix,),
                                label_visibility="collapsed", width="stretch") or "Expense"

    names = book.category_names(kind)
    if not names:
        st.warning(f"There are no {kind.lower()} categories yet. Add one in **Categories & accounts**.")
        return

    if _k(prefix, "date") not in ss:
        ss[_k(prefix, "date")] = date.today()

    errors, warnings = [], []
    c1, c2 = st.columns(2)
    amount = c1.number_input(f"Amount ({CURRENCY})", min_value=0.0, value=None, step=1.0, format="%.2f",
                             placeholder="0.00", key=_k(prefix, "amount"))
    when = c2.date_input("Date", key=_k(prefix, "date"), format="DD/MM/YYYY")
    if when and when > date.today():
        with c2:
            field_msg("This date is in the future.", "warn")

    fee, to_acct, who = None, None, SHARED
    if kind == "Transfer":
        from_key, to_key = _k(prefix, "from"), _k(prefix, "to")
        _ensure(from_key, book.account_names, book.default_account("Transfer"))
        others = [a for a in book.account_names if a != ss[from_key]] or book.account_names
        _ensure(to_key, book.account_names, book.default_account("Transfer", "to_account") or others[0])
        a1, a2 = st.columns(2)
        account = a1.selectbox("From", book.account_names, key=from_key)
        to_acct = a2.selectbox("To", book.account_names, key=to_key)
        if account == to_acct:
            errors.append("same")
            with a2:
                field_msg("Pick a different account to move the money into.")
        cat_key = _k(prefix, "cat_Transfer")
        _ensure(cat_key, names, book.default_category("Transfer"))
        p1, p2 = st.columns(2)
        p1.selectbox("Purpose", names, key=cat_key)
        fee = p2.number_input(f"Fee ({CURRENCY}), optional", min_value=0.0, value=None, step=0.5, format="%.2f",
                              placeholder="0.00", key=_k(prefix, "fee"),
                              help=f"MoMo or bank charges. Saved as a separate {FEE_CATEGORY} expense.")
    else:
        cat_key, acct_key = _k(prefix, f"cat_{kind}"), _k(prefix, f"acct_{kind}")
        _ensure(cat_key, names, book.default_category(kind))
        _ensure(acct_key, book.account_names, book.default_account(kind))
        r1, r2 = st.columns(2)
        r1.selectbox("Category", names, key=cat_key, format_func=book.cat_label)
        account = r2.selectbox("Account", book.account_names, key=acct_key)
        who_key = _k(prefix, "who")
        members = book.members()
        if ss.get(who_key) and ss[who_key] not in members:
            members = members + [ss[who_key]]
        _ensure(who_key, members, SHARED)
        who = st.selectbox("Who", members, key=who_key, accept_new_options=True,
                           help=f"{SHARED} means shared by everyone. Type a name to add someone.")
        who = (who or SHARED).strip() or SHARED

    st.text_input("Note", key=_k(prefix, "note"), placeholder="Optional, e.g. Makola market")

    if amount and fee and fee >= amount:
        warnings.append("The fee is as big as the amount moved. Check both figures.")
    if amount and kind in ("Expense", "Transfer") and account in book.balances().index:
        left = float(book.balances()[account]) - amount - (fee or 0)
        if left < 0:
            warnings.append(f"This leaves {account} at {money(left)}.")
    for w in warnings:
        field_msg(w, "warn")

    if ss.get(_k(prefix, "error")):
        st.error(ss.pop(_k(prefix, "error")))

    clicked = st.button(SAVE_LABEL[kind], type="primary", disabled=bool(errors), width="stretch",
                        key=f"btn_{prefix}_save", on_click=_save, args=(prefix,), icon=":material/check:")
    if not amount and not errors:
        field_msg("Enter an amount to save.", "hint")
    if clicked and ss.pop(_k(prefix, "saved"), False) and in_dialog:
        st.rerun()


@st.dialog("Add transaction")
def quick_add_dialog(book):
    entry_form(book, "q", in_dialog=True)


# ---- savings goals ------------------------------------------------------------
def _save_goal(goal_names):
    ss = st.session_state
    values = {"goal": ss.get("draft_g_goal"), "amount": ss.get("draft_g_amount"),
              "date": ss.get("draft_g_date") or date.today(), "note": (ss.get("draft_g_note") or "").strip()}
    if not values["amount"]:
        ss["draft_g_error"] = "Enter an amount first."
        return
    try:
        execute("INSERT INTO goal_contributions (goal_id, date, amount, note) VALUES (%s, %s, %s, %s)",
                (int(values["goal"]), values["date"], values["amount"], values["note"]))
    except Exception as exc:
        st.session_state["draft_g_error"] = f"That didn't save: {exc}"
        return
    flash(f"Added {money(values['amount'])} to {goal_names[values['goal']]}", ":material/savings:")
    st.session_state["draft_g_amount"] = None
    st.session_state["draft_g_note"] = ""
    st.session_state["draft_g_saved"] = True


def goal_form(book, in_dialog=False):
    ss = st.session_state
    if not len(book.goals):
        st.info("Create a savings goal first, on the **Savings goals** page.")
        return
    goal_names = {int(r["id"]): r["name"] for _, r in book.goals.iterrows()}
    _ensure("draft_g_goal", list(goal_names), next(iter(goal_names)))
    goal = st.selectbox("Goal", list(goal_names), format_func=lambda i: goal_names[i], key="draft_g_goal")
    row = book.goals[book.goals["id"] == goal].iloc[0]
    left = max(row["target"] - row["saved"], 0)
    if "draft_g_date" not in ss:
        ss["draft_g_date"] = date.today()
    c1, c2 = st.columns(2)
    amount = c1.number_input(f"Amount ({CURRENCY})", min_value=0.0, value=None, step=10.0, format="%.2f",
                             placeholder="0.00", key="draft_g_amount")
    c2.date_input("Date", key="draft_g_date", format="DD/MM/YYYY")
    if left == 0:
        field_msg("This goal is already reached.", "hint")
    elif amount and amount > left:
        field_msg(f"That's {money(amount - left)} more than the goal still needs.", "warn")
    st.text_input("Note", placeholder="Optional, e.g. Ama's contribution", key="draft_g_note")
    if ss.get("draft_g_error"):
        st.error(ss.pop("draft_g_error"))
    clicked = st.button("Add to goal", type="primary", width="stretch", key="btn_g_save",
                        on_click=_save_goal, args=(goal_names,), icon=":material/savings:")
    if not amount:
        field_msg("Enter an amount to save.", "hint")
    else:
        field_msg("Goal savings are tracked separately. They don't change your income or expenses.", "hint")
    if clicked and ss.pop("draft_g_saved", False) and in_dialog:
        st.rerun()


@st.dialog("Add to a savings goal")
def goal_dialog(book):
    goal_form(book, in_dialog=True)

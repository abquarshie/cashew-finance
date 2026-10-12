"""The add-entry form. It opens as a pop-up from the Add button on Home and on Money.

Built for speed on a phone: type the amount, tap a category, tap Save.
- Three things up front: amount, category and account. The category and account you
  used last are already picked, and your most-used ones are one-tap chips.
- Date, note, who it was for and any fee sit under "More details". The date is Today
  unless you change it there.
- After a category is picked, "Same as last time" fills in the last amount used.
- The form runs as a fragment, so typing and tapping only redraw the form.
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import momo
from core.data import CURRENCY, FEE_CATEGORY, KINDS, SHARED, book, money
from core.db import execute, fetch_one, run_many
from ui.components import field_msg, flash

SAVE_LABEL = {"Expense": "Save expense", "Income": "Save income", "Transfer": "Save transfer"}
WHEN = ["Today", "Yesterday", "Other day"]
TOP_N = 6


def _k(prefix, name):
    return f"draft_{prefix}_{name}"


def _me():
    user = st.session_state.get("user") or {}
    return user.get("username")


def _sticky(key):
    """Tapping the selected chip again would clear it; keep the choice instead."""
    ss = st.session_state
    if ss.get(key) is None:
        ss[key] = ss.get(key + "__last")
    ss[key + "__last"] = ss[key]


def _ensure(key, options, default):
    """Make sure a remembered choice still exists (a category may have been renamed)."""
    ss = st.session_state
    if ss.get(key) not in options:
        ss[key] = default if default in options else (options[0] if options else None)
    ss[key + "__last"] = ss[key]


def _from_search(search_key, target_key):
    ss = st.session_state
    if ss.get(search_key):
        ss[target_key] = ss[search_key]
        ss[target_key + "__last"] = ss[search_key]
    ss[search_key] = None


def _fill_amount(prefix, value):
    st.session_state[_k(prefix, "amount")] = value


def _chips(label, options, key, all_options=None, format_func=str, search_label="Search all"):
    """One-tap chips for the usual choices, plus a search box for the rest."""
    ss = st.session_state
    current = ss.get(key)
    shown = list(options)
    if current is not None and current not in shown:
        shown = [current] + shown[: max(len(shown) - 1, 0)]
    st.pills(label, shown, key=key, on_change=_sticky, args=(key,), format_func=format_func)
    if all_options and len(all_options) > len(shown):
        search_key = key + "_search"
        if search_key not in ss:
            ss[search_key] = None
        st.selectbox(search_label, all_options, key=search_key, placeholder=f"{search_label}…",
                     format_func=format_func, on_change=_from_search, args=(search_key, key),
                     label_visibility="collapsed")
    return ss.get(key)


def _account_chips(b, label, key, exclude=None):
    names = [a for a in b.account_names if a != exclude]
    if len(names) <= 6:
        return _chips(label, names, key)
    return _chips(label, names[:5], key, all_options=names, search_label="Other account")


def _entry_date(prefix):
    ss = st.session_state
    when_key = _k(prefix, "when")
    if ss.get(when_key) not in WHEN:
        ss[when_key] = "Today"
    ss[when_key + "__last"] = ss[when_key]
    st.pills("When", WHEN, key=when_key, on_change=_sticky, args=(when_key,))
    when = ss[when_key]
    if when == "Today":
        return date.today()
    if when == "Yesterday":
        return date.today() - timedelta(days=1)
    date_key = _k(prefix, "date")
    if not isinstance(ss.get(date_key), date):
        ss[date_key] = date.today() - timedelta(days=2)
    picked = st.date_input("Date", key=date_key, format="DD/MM/YYYY", label_visibility="collapsed")
    if picked and picked > date.today():
        field_msg("This date is in the future.", "warn")
    return picked or date.today()


def _set_choice(key, value):
    st.session_state[key] = value
    st.session_state[key + "__last"] = value


def _apply_momo(prefix):
    """Fill the form from a pasted MoMo text."""
    ss = st.session_state
    text = ss.get(_k(prefix, "momo_text")) or ""
    if not text.strip():
        ss[_k(prefix, "momo_info")] = None
        return
    found = momo.parse(text)
    if not found:
        ss[_k(prefix, "momo_info")] = [("error", "That doesn't look like a mobile money message. "
                                                 "Copy the whole text, including the GHS amount.")]
        return
    b = book()
    acct = momo.momo_account(b.account_names)
    kind = found["kind"]
    _set_choice(_k(prefix, "kind"), kind)
    ss[_k(prefix, "amount")] = found["amount"]
    ss[_k(prefix, "fee")] = found["fee"] or None
    note = found["party"] or ""
    if found["reference"]:
        note = f"{note} – {found['reference']}" if note else found["reference"]
    ss[_k(prefix, "note")] = note
    ss[_k(prefix, "momo_id")] = found["txn_id"]

    d = found["date"] or date.today()
    if d == date.today():
        _set_choice(_k(prefix, "when"), "Today")
    elif d == date.today() - timedelta(days=1):
        _set_choice(_k(prefix, "when"), "Yesterday")
    else:
        _set_choice(_k(prefix, "when"), "Other day")
        ss[_k(prefix, "date")] = d

    if kind == "Transfer":
        cash = "Cash" if "Cash" in b.account_names else None
        src, dst = (acct, cash) if found["direction"] == "cash_out" else (cash, acct)
        if src:
            _set_choice(_k(prefix, "from"), src)
        if dst:
            _set_choice(_k(prefix, "to"), dst)
    else:
        if acct:
            _set_choice(_k(prefix, f"acct_{kind}"), acct)
        names = b.category_names(kind)
        cat = next((h for h in found["category_hints"] if h in names), None)
        if not cat and found["party"] and len(b._manual):
            # the category used last time for this person or shop
            m = b._manual
            prev = m[(m["type"] == kind) & m["note"].str.contains(found["party"], case=False, regex=False)]
            if len(prev) and prev["category"].iloc[0] in names:
                cat = prev["category"].iloc[0]
        if cat:
            _set_choice(_k(prefix, f"cat_{kind}"), cat)

    tips = [("ok", momo.describe(found) + ". Check the details, then save.")]
    if not acct:
        tips.append(("hint", "Tip: add an account called MoMo in Settings → Accounts and these will go there "
                             "automatically."))
    elif found["balance"] is not None:
        sign = 1 if kind == "Income" or found["direction"] == "cash_in" else -1
        after = b.balance(acct) + sign * found["amount"] - (found["fee"] or 0)
        if abs(after - found["balance"]) >= 0.01:
            tips.append(("warn", f"Your MoMo balance is {money(found['balance'])}; Cashew will show {money(after)} "
                                 f"for {acct} after this, so an earlier entry may be missing."))
    ss[_k(prefix, "momo_info")] = tips
    ss[_k(prefix, "dup")] = None


def _clear_momo(prefix):
    ss = st.session_state
    for name in ("momo_text", "momo_info", "momo_id"):
        ss[_k(prefix, name)] = "" if name == "momo_text" else None


def _find_duplicate(b, kind, category, amount, when, momo_id):
    """Something that looks like this entry, already saved by anyone in the family."""
    if momo_id:
        row = fetch_one("SELECT created_by, created_at, date FROM transactions WHERE note LIKE %s ORDER BY id DESC LIMIT 1",
                        (f"%MoMo ID {momo_id}%",))
        if row:
            who = _who(b, row[0])
            return f"This MoMo payment is already saved ({who} added it for {row[2]:%d %b}). Save it again?"
    row = fetch_one(
        "SELECT created_by, created_at, date FROM transactions WHERE type = %s AND category = %s AND amount = %s "
        "AND (created_at > now() - interval '1 day' OR date = %s) ORDER BY id DESC LIMIT 1",
        (kind, category, amount, when))
    if not row:
        return None
    who = _who(b, row[0])
    if row[1] is not None:
        local = pd.Timestamp(row[1]).tz_convert("Africa/Accra")
        at = f"today at {local:%H:%M}" if local.date() == date.today() else f"on {local:%a %d %b} at {local:%H:%M}"
    else:
        at = f"for {row[2]:%d %b}"
    return f"{who} already added {money(amount)} for {category} {at}. Save another one?"


def _who(b, username):
    if not username:
        return "Someone"
    if username == _me():
        return "You"
    return b.name_of_user.get(username, username)


def _budget_alerts(b, kind, category, amount, when):
    """Budgets this entry pushes near or over the limit."""
    if kind != "Expense":
        return []
    out = []
    for s in b.budget_status(pd.Period(when, "M")):
        if not (s["name"] == category or (s["is_group"] and b.group_of.get(category) == s["name"])) or s["limit"] <= 0:
            continue
        before, after = s["spent"] / s["limit"] * 100, (s["spent"] + amount) / s["limit"] * 100
        if after > 100:
            out.append(f"{s['name']} is {money(s['spent'] + amount - s['limit'])} over its {money(s['limit'])} budget")
        elif (after >= 75 > before) or (after >= 90 > before):
            out.append(f"{s['name']} is now at {after:.0f}% of its {money(s['limit'])} budget")
    return out


def _save(prefix, values, confirmed=False):
    ss = st.session_state
    b = book()
    kind = values["kind"]
    amount = ss.get(_k(prefix, "amount"))  # read fresh, in case it was typed just before tapping Save
    fee = ss.get(_k(prefix, "fee"))
    note = (ss.get(_k(prefix, "note")) or "").strip()
    momo_id = ss.get(_k(prefix, "momo_id"))
    who = values["who"]
    if kind != "Transfer":
        who = (ss.get(_k(prefix, "who")) or SHARED).strip() or SHARED
    if not amount:
        ss[_k(prefix, "error")] = "Enter an amount first."
        return
    if kind == "Transfer" and values["account"] == values["to"]:
        ss[_k(prefix, "error")] = "Pick two different accounts."
        return
    if not values["category"] or not values["account"]:
        ss[_k(prefix, "error")] = "Pick a category and an account."
        return
    if not confirmed:
        try:
            dup = _find_duplicate(b, kind, values["category"], amount, values["date"], momo_id)
        except Exception:
            dup = None  # never block saving because the check itself failed
        if dup:
            ss[_k(prefix, "dup")] = {"msg": dup, "sig": (kind, amount, values["category"], values["date"])}
            return
    if momo_id:
        note = f"{note} · MoMo ID {momo_id}" if note else f"MoMo ID {momo_id}"

    stmts = [(
        "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (values["date"], kind, values["category"], amount, note, who, values["account"], values["to"], _me()),
    )]
    if fee and fee > 0:
        fee_note = f"Fee · {values['account']} to {values['to']}" if kind == "Transfer" else f"Fee · {values['category']}"
        stmts.append((
            "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account, created_by) "
            "VALUES (%s, 'Expense', %s, %s, %s, %s, %s, NULL, %s)",
            (values["date"], FEE_CATEGORY, fee, fee_note, SHARED, values["account"], _me()),
        ))
    alerts = _budget_alerts(b, kind, values["category"], amount, values["date"])
    try:
        run_many(stmts)
    except Exception as exc:
        ss[_k(prefix, "error")] = f"That didn't save: {exc}"
        return
    extra = f" plus {money(fee)} fee" if fee and fee > 0 else ""
    if kind == "Transfer":
        flash(f"Moved {money(amount)} from {values['account']} to {values['to']}{extra}", ":material/swap_horiz:")
    else:
        flash(f"Saved {money(amount)} {kind.lower()} to {values['category']}{extra}")
    for a in alerts:
        flash(a, ":material/warning:")
    # clear what changes every time; keep type, date, accounts and category for the next entry
    ss[_k(prefix, "amount")] = None
    ss[_k(prefix, "fee")] = None
    ss[_k(prefix, "note")] = ""
    ss[_k(prefix, "dup")] = None
    _set_choice(_k(prefix, "when"), "Today")  # the date is tucked away, so never carry an old one over silently
    _clear_momo(prefix)
    ss[_k(prefix, "saved")] = True


def _cancel_dup(prefix):
    st.session_state[_k(prefix, "dup")] = None


def _momo_box(prefix):
    ss = st.session_state
    info = ss.get(_k(prefix, "momo_info"))
    with st.expander("Paste a MoMo text", icon=":material/sms:", expanded=bool(info)):
        st.text_area("MoMo text", key=_k(prefix, "momo_text"), height=96, label_visibility="collapsed",
                     placeholder="Paste the whole message, e.g. Payment made for GHS 50.00 to …",
                     on_change=_apply_momo, args=(prefix,))
        row = st.container(horizontal=True)
        row.button("Fill in the form", key=f"{prefix}_momo_go", icon=":material/auto_fix_high:",
                   on_click=_apply_momo, args=(prefix,))
        if info:
            row.button("Clear", key=f"{prefix}_momo_clear", type="tertiary", on_click=_clear_momo, args=(prefix,))
            for tone, text in info:
                field_msg(text, tone)


@st.fragment
def entry_form(prefix):
    ss = st.session_state
    b = book()
    if not b.account_names:
        st.warning("Add an account first in **Settings → Accounts**.")
        return

    _momo_box(prefix)

    kind_key = _k(prefix, "kind")
    if ss.get(kind_key) not in KINDS:
        ss[kind_key] = "Expense"
    ss[kind_key + "__last"] = ss[kind_key]
    kind = st.segmented_control("Type", KINDS, key=kind_key, on_change=_sticky, args=(kind_key,),
                                label_visibility="collapsed", width="stretch") or "Expense"

    names = b.category_names(kind)
    if not names:
        st.warning(f"There are no {kind.lower()} categories yet. Add one in **Settings → Accounts**.")
        return

    amount = st.number_input(f"Amount ({CURRENCY})", min_value=0.0, value=None, step=1.0, format="%.2f",
                             placeholder="0.00", key=_k(prefix, "amount"))
    errors = []
    fee, to_acct, who = None, None, SHARED

    if kind == "Transfer":
        from_key, to_key = _k(prefix, "from"), _k(prefix, "to")
        _ensure(from_key, b.account_names, b.default_account("Transfer"))
        account = _account_chips(b, "From", from_key)
        others = [a for a in b.account_names if a != account] or b.account_names
        default_to = b.default_account("Transfer", "to_account")
        if ss.get(to_key) == account or ss.get(to_key) not in others:
            ss[to_key] = None
        _ensure(to_key, others, default_to if default_to != account else others[0])
        to_acct = _account_chips(b, "To", to_key, exclude=account)
        cat_key = _k(prefix, "cat_Transfer")
        _ensure(cat_key, names, b.default_category("Transfer"))
        category = _chips("Purpose", names[:TOP_N], cat_key, all_options=names, search_label="Other purpose")
    else:
        cat_key, acct_key = _k(prefix, f"cat_{kind}"), _k(prefix, f"acct_{kind}")
        _ensure(cat_key, names, b.default_category(kind))
        _ensure(acct_key, b.account_names, b.default_account(kind))
        category = _chips("Category", b.top_categories(kind, TOP_N), cat_key, all_options=names,
                          format_func=lambda n: n, search_label="Search all categories")
        last = b.last_amount(kind, category) if category else None
        if last and not amount:
            st.button(f"Same as last time: {money(last)}", key=f"{prefix}_last_{kind}", type="tertiary",
                      icon=":material/history:", on_click=_fill_amount, args=(prefix, last))
        account = _account_chips(b, "Account", acct_key)

    when = _details(prefix, b, kind)
    who = SHARED if kind == "Transfer" else ((ss.get(_k(prefix, "who")) or SHARED).strip() or SHARED)
    fee = ss.get(_k(prefix, "fee"))

    if kind == "Transfer" and account == to_acct:
        errors.append("same")
        field_msg("Pick a different account to move the money into.")
    if amount and fee and fee >= amount:
        field_msg("The fee is as big as the amount moved. Check both figures.", "warn")
    if amount and kind in ("Expense", "Transfer") and account in b.account_names:
        left = b.balance(account) - amount - (fee or 0)
        if left < 0:
            field_msg(f"This leaves {account} at {money(left)}.", "warn")
    if ss.get(_k(prefix, "error")):
        st.error(ss.pop(_k(prefix, "error")))

    values = {"kind": kind, "date": when, "category": category, "account": account, "to": to_acct, "who": who}
    dup = ss.get(_k(prefix, "dup"))
    if dup and dup["sig"] == (kind, amount, category, when):
        with st.container(key=f"{prefix}-dup"):
            field_msg(dup["msg"], "warn")
            row = st.container(horizontal=True)
            row.button("Save anyway", type="primary", key=f"btn_{prefix}_dup_yes", icon=":material/check:",
                       on_click=_save, args=(prefix, values, True))
            row.button("Don't save", key=f"btn_{prefix}_dup_no", on_click=_cancel_dup, args=(prefix,))
    else:
        st.button(SAVE_LABEL[kind], type="primary", disabled=bool(errors), width="stretch",
                  key=f"btn_{prefix}_save", on_click=_save, args=(prefix, values), icon=":material/check:")
        if not amount and not errors:
            field_msg("Enter an amount to save.", "hint")

    if ss.pop(_k(prefix, "saved"), False):
        st.rerun()  # closes the pop-up and refreshes the page, so totals include the new entry


def _details(prefix, b, kind):
    """Date, note, who it was for and fee: folded away unless one of them is already filled in."""
    ss = st.session_state
    when_now = ss.get(_k(prefix, "when")) or "Today"
    note_now = (ss.get(_k(prefix, "note")) or "").strip()
    who_now = ss.get(_k(prefix, "who")) or SHARED
    fee_now = ss.get(_k(prefix, "fee"))
    bits = [when_now if when_now != "Other day" else "another day"]
    if note_now:
        bits.append("note")
    if kind != "Transfer" and who_now != SHARED:
        bits.append(f"for {who_now}")
    if fee_now:
        bits.append(f"{money(fee_now)} fee")
    busy = when_now != "Today" or bool(note_now) or bool(fee_now) or (kind != "Transfer" and who_now != SHARED)
    with st.expander(f"More details · {', '.join(bits)}", icon=":material/tune:", expanded=busy):
        when = _entry_date(prefix)
        st.text_input("Note", key=_k(prefix, "note"), placeholder="Optional, e.g. Makola market")
        if kind == "Transfer" or fee_now:
            st.number_input(f"Fee ({CURRENCY}), optional", min_value=0.0, value=None, step=0.5, format="%.2f",
                            placeholder="0.00", key=_k(prefix, "fee"),
                            help=f"MoMo or bank charges. Saved as a separate {FEE_CATEGORY} expense.")
        if kind != "Transfer":
            who_key = _k(prefix, "who")
            members = b.members()
            if ss.get(who_key) and ss[who_key] not in members:
                members = members + [ss[who_key]]
            _ensure(who_key, members, SHARED)
            st.selectbox("Who was it for?", members, key=who_key, accept_new_options=True,
                         help=f"Leave as {SHARED} unless you track spending per person. Type a name to add someone.")
    return when


@st.dialog("Add an entry", width="small")
def _add_dialog():
    entry_form("q")


def add_button(where):
    """The one way to add money in, money out or a move. Opens the form as a pop-up."""
    if not book().account_names:
        return
    if st.button("Add an entry", type="primary", icon=":material/add:", width="stretch", key=f"add_open_{where}"):
        _add_dialog()


# ---- savings goals ------------------------------------------------------------
def _save_goal(goal_names):
    ss = st.session_state
    values = {"goal": ss.get("draft_g_goal"), "amount": ss.get("draft_g_amount"),
              "date": ss.get("draft_g_date") or date.today(), "note": (ss.get("draft_g_note") or "").strip()}
    if not values["amount"]:
        ss["draft_g_error"] = "Enter an amount first."
        return
    try:
        execute("INSERT INTO goal_contributions (goal_id, date, amount, note, created_by) VALUES (%s, %s, %s, %s, %s)",
                (int(values["goal"]), values["date"], values["amount"], values["note"], _me()))
    except Exception as exc:
        ss["draft_g_error"] = f"That didn't save: {exc}"
        return
    flash(f"Added {money(values['amount'])} to {goal_names[values['goal']]}", ":material/savings:")
    ss["draft_g_amount"] = None
    ss["draft_g_note"] = ""


def goal_form(b):
    ss = st.session_state
    if not len(b.goals):
        st.info("Create a savings goal first, under **New goal**.")
        return
    goal_names = {int(r["id"]): r["name"] for _, r in b.goals.iterrows()}
    _ensure("draft_g_goal", list(goal_names), next(iter(goal_names)))
    goal = st.selectbox("Goal", list(goal_names), format_func=lambda i: goal_names[i], key="draft_g_goal")
    row = b.goals[b.goals["id"] == goal].iloc[0]
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
    st.button("Add to goal", type="primary", width="stretch", key="btn_g_save",
              on_click=_save_goal, args=(goal_names,), icon=":material/savings:")
    if not amount:
        field_msg("Enter an amount to save.", "hint")
    else:
        field_msg("Goal savings are tracked separately. They don't change your income or expenses.", "hint")

"""The add-transaction form, shown on the dashboard and on the Add transaction page.

Built for speed on a phone: type the amount, tap a category, tap Save.
- Your most-used categories and accounts are one-tap chips; everything else is
  one search away.
- The date is Today unless you tap Yesterday or pick another day.
- After a category is picked, "Same as last time" fills in the last amount used.
- The form runs as a fragment, so typing and tapping only redraw the form,
  not the charts around it. What you've typed is kept if you switch pages.
"""
from datetime import date, timedelta

import streamlit as st

from core.data import CURRENCY, FEE_CATEGORY, KINDS, SHARED, book, money
from core.db import execute, run_many
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


def _focus_amount(prefix):
    """Put the cursor in the amount box and ask phones for the number keypad."""
    st.html(
        f"""<script>
        (() => {{
          // money boxes get the decimal keypad, including when Streamlit redraws them
          if (!window.__cashewKeypad) {{
            window.__cashewKeypad = true;
            const mark = () => document.querySelectorAll('[class*="st-key-draft_"][class*="_amount"] input, '
              + '[class*="st-key-draft_"][class*="_fee"] input').forEach(i => {{
                if (i.getAttribute('inputmode') !== 'decimal') i.setAttribute('inputmode', 'decimal');
              }});
            new MutationObserver(mark).observe(document.body, {{childList: true, subtree: true}});
            mark();
          }}
          let tries = 0;
          const go = () => {{
            const el = document.querySelector('.st-key-{_k(prefix, "amount")} input');
            if (!el) {{ if (tries++ < 40) setTimeout(go, 50); return; }}  // the box may not be drawn yet
            const a = document.activeElement;
            if (!a || a === document.body) el.focus({{preventScroll: true}});
          }};
          go();
        }})();
        </script>""",
        unsafe_allow_javascript=True,
        width="content",
    )


def _save(prefix, values):
    ss = st.session_state
    kind = values["kind"]
    amount = ss.get(_k(prefix, "amount"))  # read fresh, in case it was typed just before tapping Save
    fee = ss.get(_k(prefix, "fee")) if kind == "Transfer" else None
    note = (ss.get(_k(prefix, "note")) or "").strip()
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
    stmts = [(
        "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (values["date"], kind, values["category"], amount, note, who, values["account"], values["to"], _me()),
    )]
    if kind == "Transfer" and fee and fee > 0:
        stmts.append((
            "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account, created_by) "
            "VALUES (%s, 'Expense', %s, %s, %s, %s, %s, NULL, %s)",
            (values["date"], FEE_CATEGORY, fee, f"Fee · {values['account']} to {values['to']}", SHARED,
             values["account"], _me()),
        ))
    try:
        run_many(stmts)
    except Exception as exc:
        ss[_k(prefix, "error")] = f"That didn't save: {exc}"
        return
    if kind == "Transfer":
        extra = f" plus {money(fee)} fee" if fee and fee > 0 else ""
        flash(f"Moved {money(amount)} from {values['account']} to {values['to']}{extra}", ":material/swap_horiz:")
    else:
        flash(f"Saved {money(amount)} {kind.lower()} to {values['category']}")
    # clear what changes every time; keep type, date, accounts and category for the next entry
    ss[_k(prefix, "amount")] = None
    ss[_k(prefix, "fee")] = None
    ss[_k(prefix, "note")] = ""
    ss[_k(prefix, "saved")] = True
    ss[_k(prefix, "focus")] = True


@st.fragment
def entry_form(prefix):
    ss = st.session_state
    b = book()
    if not b.account_names:
        st.warning("Add an account first in **Categories & accounts**.")
        return

    kind_key = _k(prefix, "kind")
    if ss.get(kind_key) not in KINDS:
        ss[kind_key] = "Expense"
    ss[kind_key + "__last"] = ss[kind_key]
    kind = st.segmented_control("Type", KINDS, key=kind_key, on_change=_sticky, args=(kind_key,),
                                label_visibility="collapsed", width="stretch") or "Expense"

    names = b.category_names(kind)
    if not names:
        st.warning(f"There are no {kind.lower()} categories yet. Add one in **Categories & accounts**.")
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
        fee = st.number_input(f"Fee ({CURRENCY}), optional", min_value=0.0, value=None, step=0.5, format="%.2f",
                              placeholder="0.00", key=_k(prefix, "fee"),
                              help=f"MoMo or bank charges. Saved as a separate {FEE_CATEGORY} expense.")
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

    when = _entry_date(prefix)
    st.text_input("Note", key=_k(prefix, "note"), placeholder="Optional, e.g. Makola market",
                  label_visibility="collapsed")

    if kind != "Transfer":
        who_key = _k(prefix, "who")
        members = b.members()
        if ss.get(who_key) and ss[who_key] not in members:
            members = members + [ss[who_key]]
        _ensure(who_key, members, SHARED)
        with st.expander(f"For: {ss[who_key]}", icon=":material/person:"):
            who = st.selectbox("Who is this for?", members, key=who_key, accept_new_options=True,
                               help=f"{SHARED} means shared by everyone. Type a name to add someone.")
        who = (who or SHARED).strip() or SHARED

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
    st.button(SAVE_LABEL[kind], type="primary", disabled=bool(errors), width="stretch",
              key=f"btn_{prefix}_save", on_click=_save, args=(prefix, values), icon=":material/check:")
    if not amount and not errors:
        field_msg("Enter an amount to save.", "hint")

    if ss.pop(_k(prefix, "focus"), _k(prefix, "seen") not in ss):
        _focus_amount(prefix)
    ss[_k(prefix, "seen")] = True
    if ss.pop(_k(prefix, "saved"), False):
        st.rerun()  # refresh the whole page so totals and recent activity include the new entry


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

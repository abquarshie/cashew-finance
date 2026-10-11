from datetime import date

import pandas as pd
import streamlit as st

from core.data import CURRENCY, KINDS, SHARED, book, money
from core.db import run_many
from ui.components import (activity_items, card, confirm, empty, feed_html, flash, page_header, pill, section)
from ui.entry import entry_form
from ui.nav import link

EDIT_COLS = ["date", "category", "amount", "type", "account", "to_account", "member", "note"]
NO_ACCOUNT = "—"
TX_FIELDS = ["id", "date", "type", "category", "amount", "note", "member", "account", "to_account", "created_by"]


# ---- Add transaction page ------------------------------------------------------
def render_add():
    b = book()
    page_header("Add transaction", "Record money in, money out, or a move between accounts")
    form_col, recent_col = st.columns([3, 2], gap="medium")
    with form_col:
        with card("add-form"):
            entry_form("p")
    with recent_col:
        with card("add-recent"):
            section("Latest entries")
            items = activity_items(b, limit=6)
            if items:
                st.html(feed_html(items, show_who=b.multi_member, names=b.name_of_user if len(b.users) > 1 else None))
            else:
                empty("Your latest entries will show up here.")
        st.caption("Need a new category or account? Add it in **Categories & accounts**.")


# ---- Transactions page ----------------------------------------------------------
def _blank(v):
    return v is None or v == NO_ACCOUNT or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT or (isinstance(v, str) and not v.strip())


def _norm(v):
    if _blank(v):
        return ""
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v.strip() if isinstance(v, str) else v


def _row_name(r):
    when = _norm(r["date"])
    return f"{when:%d %b}, {r['category'] or 'no category'}" if when else str(r["category"])


def _undo_banner():
    ss = st.session_state
    undo = ss.get("_undo")
    if not undo:
        return
    with st.container(key="card-undo", horizontal=True, vertical_alignment="center"):
        st.markdown(f"**{undo['message']}**", width="stretch")
        if st.button("Undo", icon=":material/undo:", key="undo_go"):
            stmts = [(
                f"INSERT INTO transactions ({', '.join(TX_FIELDS)}) VALUES ({', '.join(['%s'] * len(TX_FIELDS))}) "
                "ON CONFLICT (id) DO NOTHING",
                tuple(r[f] for f in TX_FIELDS),
            ) for r in undo["rows"]]
            run_many(stmts)
            ss.pop("_undo")
            flash(f"Restored {len(undo['rows'])} transaction{'s' if len(undo['rows']) != 1 else ''}", ":material/undo:")
            st.rerun()
        if st.button("Dismiss", key="undo_dismiss", type="tertiary"):
            ss.pop("_undo")
            st.rerun()


def _bump():
    st.session_state["tx_ver"] = st.session_state.get("tx_ver", 0) + 1


def render():
    ss = st.session_state
    b = book()
    page_header("Transactions", "Tap any cell to change it. Nothing is saved until you press Save.")
    _undo_banner()

    if not len(b.tx):
        empty("No transactions yet.")
        st.page_link(link("add"), label="Add your first transaction", icon=":material/add_circle:")
        return

    prev_key = ss.get("tx_editor_key")
    pending = bool(prev_key and prev_key in ss and (ss[prev_key].get("edited_rows")))

    months = sorted(set(b.tx["month"]), reverse=True)
    month_opts = ["All"] + months
    if "tx_month" not in ss:
        this = pd.Period(date.today(), "M")
        ss["tx_month"] = this if this in months else months[0]
    f1, f2 = st.columns([1, 1])
    month = f1.selectbox("Month", month_opts, key="tx_month", disabled=pending,
                         format_func=lambda p: "All months" if p == "All" else p.strftime("%B %Y"))
    kinds = f2.pills("Type", KINDS, selection_mode="multi", key="tx_kinds", disabled=pending)
    search = st.text_input("Search", placeholder="Search notes, categories or people", key="tx_search",
                           disabled=pending, label_visibility="collapsed", icon=":material/search:")
    if pending:
        st.caption("Save or discard your changes before changing the filters.")

    view = b.tx if month == "All" else b.tx[b.tx["month"] == month]
    if kinds:
        view = view[view["type"].isin(kinds)]
    if search:
        q = search.strip()
        view = view[view["note"].str.contains(q, case=False, regex=False)
                    | view["category"].str.contains(q, case=False, regex=False)
                    | view["group"].str.contains(q, case=False, regex=False)
                    | view["member"].str.contains(q, case=False, regex=False)]

    inc = view.loc[view["type"] == "Income", "amount"].sum()
    out = view.loc[view["type"] == "Expense", "amount"].sum()
    st.html(
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin:.1rem 0 .2rem">'
        f'{pill(f"{len(view)} entr" + ("ies" if len(view) != 1 else "y"), "neutral")}'
        f'{pill("In " + money(inc), "in")}{pill("Out " + money(out), "out")}</div>'
    )
    if not len(view):
        empty("Nothing matches these filters.")
        return

    base = view[EDIT_COLS].copy().astype(object)
    base["note"] = base["note"].fillna("")
    for c in ("account", "to_account"):  # the table can't show a blank choice, so "none" gets a visible mark
        base[c] = base[c].replace("", NO_ACCOUNT).fillna(NO_ACCOUNT)
    base.insert(0, "delete", False)
    base.index = view["id"].astype(int).tolist()

    cats = b.category_names()
    cats += sorted(set(base["category"]) - set(cats))
    accts = list(b.account_names)
    accts += sorted({a for a in pd.concat([base["account"], base["to_account"]]).dropna()} - set(accts))

    ver = ss.get("tx_ver", 0)
    ek = f"tx_editor_{hash((str(month), tuple(kinds or ()), search))}_{ver}"
    ss["tx_editor_key"] = ek
    edited = st.data_editor(
        base, key=ek, hide_index=True, width="stretch", num_rows="fixed",
        height=min(36 * (len(base) + 1) + 4, 560),
        column_order=["delete", "date", "category", "amount", "type", "account", "to_account", "member", "note"],
        column_config={
            "delete": st.column_config.CheckboxColumn("Delete", width=84, help="Tick, then Save to delete"),
            "date": st.column_config.DateColumn("Date", format="DD MMM YYYY", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=cats, required=True),
            "amount": st.column_config.NumberColumn(f"Amount ({CURRENCY})", min_value=0.01, format="%.2f", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=KINDS, required=True, width="small"),
            "account": st.column_config.SelectboxColumn("Account", options=[NO_ACCOUNT] + accts),
            "to_account": st.column_config.SelectboxColumn("To (transfers)", options=[NO_ACCOUNT] + accts),
            "member": st.column_config.TextColumn("Who", help=f"Leave as {SHARED} for shared spending"),
            "note": st.column_config.TextColumn("Note", width="large"),
        },
    )

    # ---- work out what changed, and check it ----
    updates, deletes, errors, warnings = [], [], [], []
    for tid in base.index:
        old, new = base.loc[tid], edited.loc[tid]
        if bool(new["delete"]):
            deletes.append(tid)
            continue
        if all(_norm(old[c]) == _norm(new[c]) for c in EDIT_COLS):
            continue
        name = _row_name(new)
        kind = new["type"]
        if _blank(new["amount"]) or float(new["amount"]) <= 0:
            errors.append(f"{name}: enter an amount above zero.")
        if _blank(new["date"]):
            errors.append(f"{name}: pick a date.")
        if _blank(new["category"]):
            errors.append(f"{name}: pick a category.")
        if kind == "Transfer":
            if _blank(new["account"]) or _blank(new["to_account"]):
                errors.append(f"{name}: a transfer needs both a from and a to account.")
            elif new["account"] == new["to_account"]:
                errors.append(f"{name}: a transfer needs two different accounts.")
        cat_kind = b.kind_of.get(new["category"])
        if cat_kind and cat_kind != kind:
            warnings.append(f"{name}: {new['category']} is usually {cat_kind.lower()}, but this is marked {kind.lower()}.")
        updates.append((
            "UPDATE transactions SET date=%s, type=%s, category=%s, amount=%s, note=%s, member=%s, account=%s, "
            "to_account=%s WHERE id=%s",
            (_norm(new["date"]) or None, kind, new["category"], float(new["amount"] or 0), _norm(new["note"]),
             _norm(new["member"]) or SHARED, _norm(new["account"]) or None,
             (_norm(new["to_account"]) or None) if kind == "Transfer" else None, int(tid)),
        ))

    if updates or deletes:
        with st.container(key="card-savebar"):
            parts = []
            if updates:
                parts.append(f"{len(updates)} change{'s' if len(updates) != 1 else ''}")
            if deletes:
                parts.append(f"{len(deletes)} to delete")
            st.markdown(f"**{' and '.join(parts)} not saved yet**")
            for e in errors:
                st.html(f'<div class="field-msg error" style="margin:0">{e}</div>')
            for w in warnings:
                st.html(f'<div class="field-msg warn" style="margin:0">{w}</div>')
            row = st.container(horizontal=True)
            save = row.button("Save changes", type="primary", disabled=bool(errors), icon=":material/check:", key="tx_save")
            row.button("Discard", on_click=_bump, key="tx_discard")
        if save:
            if deletes:
                rows = b.tx[b.tx["id"].isin(deletes)][TX_FIELDS].to_dict("records")
                for r in rows:
                    r["id"] = int(r["id"])
                    r["account"] = r["account"] or None
                    r["to_account"] = r["to_account"] or None
                    r["created_by"] = r["created_by"] or None
                n = len(deletes)
                undo = {"message": f"Deleted {n} transaction{'s' if n != 1 else ''}.", "rows": rows}
                stmts = updates + [("DELETE FROM transactions WHERE id = ANY(%s)", ([int(i) for i in deletes],))]
                extra = f" and save {len(updates)} other change{'s' if len(updates) != 1 else ''}" if updates else ""
                confirm(f"Delete {n} transaction{'s' if n != 1 else ''}{extra}? You can undo this straight after.",
                        stmts, f"Deleted {n} transaction{'s' if n != 1 else ''}", undo=undo, after=_bump)
            else:
                try:
                    run_many(updates)
                except Exception as exc:
                    st.error(f"That didn't save: {exc}")
                else:
                    _bump()
                    flash(f"Saved {len(updates)} change{'s' if len(updates) != 1 else ''}")
                    st.rerun()

    with st.expander("Download as a spreadsheet"):
        cols = ["id", "date", "type", "group", "category", "account", "to_account", "member", "amount", "note"]
        st.write(f"These {len(view)} entries, as a CSV file that opens in Excel or Google Sheets.")
        st.download_button("Download CSV", view[cols].to_csv(index=False).encode("utf-8"),
                           file_name=f"cashew_transactions_{date.today():%Y-%m-%d}.csv", mime="text/csv",
                           icon=":material/download:")

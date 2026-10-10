import pandas as pd
import streamlit as st

from core.data import CURRENCY, KINDS, book
from core.db import execute, run_many
from ui.components import card, confirm, empty, field_msg, flash, page_header, section


def _choose(label, options, key):
    st.session_state.setdefault(key, options[0])
    if st.session_state.get(key) is None:
        st.session_state[key] = options[0]
    return st.pills(label, options, key=key, label_visibility="collapsed") or options[0]


def _categories(b):
    ss = st.session_state
    with card("cat-list"):
        section("Your categories", f"{len(b.cats)} in {len(b.groups)} groups")
        st.dataframe(
            b.cats.rename(columns={"group_name": "Group", "name": "Category", "kind": "Type"})[["Group", "Category", "Type"]],
            hide_index=True, width="stretch", height=300,
        )

    action = _choose("Action", ["Add", "Edit", "Rename a group", "Delete", "Move past entries"], "cat_action")
    names = b.cats["name"].tolist()
    lower = [x.lower() for x in names]
    group_kind = dict(zip(b.cats["group_name"], b.cats["kind"]))

    with card("cat-action"):
        if action == "Add":
            section("Add a category")
            c1, c2 = st.columns(2)
            name = c1.text_input("Category name", max_chars=50, key="cat_add_name")
            group = c2.selectbox("Group", b.groups + ["New group…"], key="cat_add_group")
            new_group, kind = "", None
            if group == "New group…":
                g1, g2 = st.columns(2)
                new_group = g1.text_input("New group name", max_chars=60, key="cat_add_newgroup", placeholder="e.g. School")
                kind = g2.selectbox("Type", KINDS, key="cat_add_kind")
                if new_group.strip().lower() in [g.lower() for g in b.groups]:
                    field_msg("That group already exists. Pick it from the list instead.")
            else:
                kind = group_kind.get(group)
            final_group = new_group.strip() if group == "New group…" else group
            clash = name.strip().lower() in lower
            if clash:
                field_msg(f"'{name.strip()}' already exists.")
            ready = name.strip() and final_group and not clash and final_group.lower() not in (
                [g.lower() for g in b.groups] if group == "New group…" else [])
            if st.button("Add category", type="primary", disabled=not ready, key="cat_add_btn", icon=":material/add:"):
                execute("INSERT INTO categories (name, group_name, kind) VALUES (%s, %s, %s)", (name.strip(), final_group, kind))
                for k in ("cat_add_name", "cat_add_newgroup"):
                    ss.pop(k, None)
                flash(f"Added '{name.strip()}' to {final_group}")
                st.rerun()

        elif action == "Edit":
            section("Edit a category")
            sel = st.selectbox("Category", names, format_func=b.cat_label, key="cat_edit_sel")
            e1, e2 = st.columns(2)
            new_name = e1.text_input("Name", value=sel, key=f"cat_name_{sel}", max_chars=50).strip()
            new_group = e2.selectbox("Group", b.groups, index=b.groups.index(b.group_of[sel]), key=f"cat_grp_{sel}")
            clash = new_name.lower() in [x.lower() for x in names if x != sel]
            if not new_name:
                field_msg("The name can't be empty.")
            elif clash:
                field_msg(f"'{new_name}' already exists.")
            used = int((b.tx["category"] == sel).sum()) if len(b.tx) else 0
            if new_name and new_name != sel and used:
                field_msg(f"{used} past entr{'ies' if used != 1 else 'y'} will be renamed too.", "hint")
            changed = new_name != sel or new_group != b.group_of[sel]
            if st.button("Save changes", type="primary", disabled=not changed or not new_name or clash, key="cat_edit_save",
                         icon=":material/check:"):
                kind = group_kind.get(new_group, b.kind_of[sel])
                stmts = [("UPDATE categories SET name=%s, group_name=%s, kind=%s WHERE name=%s", (new_name, new_group, kind, sel))]
                if new_name != sel:
                    stmts += [
                        ("UPDATE transactions SET category=%s WHERE category=%s", (new_name, sel)),
                        ("UPDATE recurring_rules SET category=%s WHERE category=%s", (new_name, sel)),
                        ("UPDATE budgets SET category=%s WHERE category=%s "
                         "AND NOT EXISTS (SELECT 1 FROM budgets WHERE category=%s)", (new_name, sel, new_name)),
                    ]
                run_many(stmts)
                flash(f"Saved '{new_name}'")
                st.rerun()

        elif action == "Rename a group":
            section("Rename a group")
            g_pick = st.selectbox("Group", b.groups, key="grp_pick")
            g_name = st.text_input("New name", value=g_pick, key=f"grp_name_{g_pick}", max_chars=60).strip()
            clash = g_name != g_pick and g_name.lower() in [x.lower() for x in b.groups]
            if clash:
                field_msg(f"A group called '{g_name}' already exists.")
            if st.button("Rename group", type="primary", disabled=not g_name or g_name == g_pick or clash, key="grp_save"):
                run_many([
                    ("UPDATE categories SET group_name=%s WHERE group_name=%s", (g_name, g_pick)),
                    ("UPDATE budgets SET category=%s WHERE category=%s "
                     "AND NOT EXISTS (SELECT 1 FROM budgets WHERE category=%s)", (g_name, g_pick, g_name)),
                ])
                flash(f"Renamed the group to '{g_name}'")
                st.rerun()

        elif action == "Delete":
            section("Delete a category")
            d_sel = st.selectbox("Category", names, format_func=b.cat_label, key="cat_del_sel")
            used = int((b.tx["category"] == d_sel).sum()) if len(b.tx) else 0
            if used:
                field_msg(f"{used} past entr{'ies use' if used != 1 else 'y uses'} it. They keep the name, or you can "
                          "move them first with Move past entries.", "hint")
            if st.button("Delete category", icon=":material/delete:", key="cat_del_btn"):
                confirm(f"Delete the category **{d_sel}**?", [("DELETE FROM categories WHERE name=%s", (d_sel,))],
                        f"Deleted '{d_sel}'")

        else:
            section("Move past entries")
            used_cats = sorted(set(b.tx["category"])) if len(b.tx) else []
            if not used_cats:
                empty("There are no past entries to move yet.")
            else:
                st.caption("Useful for entries made before a category existed, like an old 'Food & Dining'.")
                m1, m2 = st.columns(2)
                from_cat = m1.selectbox("From", used_cats, key="move_from")
                to_cat = m2.selectbox("To", b.category_names(), format_func=b.cat_label, key="move_to")
                count = int((b.tx["category"] == from_cat).sum())
                if from_cat == to_cat:
                    field_msg("Pick two different categories.")
                if st.button(f"Move {count} entr{'ies' if count != 1 else 'y'}", type="primary", disabled=from_cat == to_cat,
                             key="move_btn"):
                    confirm(f"Move all {count} entr{'ies' if count != 1 else 'y'} from **{from_cat}** to **{to_cat}**?",
                            [("UPDATE transactions SET category=%s WHERE category=%s", (to_cat, from_cat))],
                            f"Moved {count} entr{'ies' if count != 1 else 'y'} to '{to_cat}'", button="Move",
                            icon=":material/drive_file_move:")


def _accounts(b):
    ss = st.session_state
    bal = b.balances()
    with card("acct-list"):
        section("Your accounts")
        if not len(b.accts):
            empty("No accounts yet. Add your first one on this page.")
        else:
            st.dataframe(
                pd.DataFrame({"Account": b.accts["name"], "Opening balance": b.accts["opening_balance"],
                              "Balance now": [bal[n] for n in b.accts["name"]]}),
                hide_index=True, width="stretch",
                column_config={"Opening balance": st.column_config.NumberColumn(format=f"{CURRENCY}%.2f"),
                               "Balance now": st.column_config.NumberColumn(format=f"{CURRENCY}%.2f")},
            )

    action = _choose("Action", ["Add", "Edit", "Delete", "Assign older entries"], "acct_action")
    lower = [x.lower() for x in b.account_names]
    with card("acct-action"):
        if action == "Add":
            section("Add an account")
            a1, a2 = st.columns(2)
            name = a1.text_input("Account name", max_chars=50, placeholder="e.g. MoMo", key="acct_add_name").strip()
            opening = a2.number_input(f"Opening balance ({CURRENCY})", value=0.0, step=10.0, format="%.2f", key="acct_add_open",
                                      help="What the account held before your first entry here.")
            if name.lower() in lower:
                field_msg(f"'{name}' already exists.")
            if st.button("Add account", type="primary", disabled=not name or name.lower() in lower, key="acct_add_btn",
                         icon=":material/add:"):
                execute("INSERT INTO accounts (name, opening_balance) VALUES (%s, %s)", (name, opening))
                ss.pop("acct_add_name", None)
                ss.pop("acct_add_open", None)
                flash(f"Added the account '{name}'")
                st.rerun()

        elif action == "Edit":
            section("Edit an account")
            if not b.account_names:
                empty("No accounts yet.")
                return
            sel = st.selectbox("Account", b.account_names, key="acct_edit_sel")
            cur_open = float(b.accts.loc[b.accts["name"] == sel, "opening_balance"].iloc[0])
            e1, e2 = st.columns(2)
            new_name = e1.text_input("Name", value=sel, key=f"acct_name_{sel}", max_chars=50).strip()
            new_open = e2.number_input(f"Opening balance ({CURRENCY})", value=cur_open, step=10.0, format="%.2f",
                                       key=f"acct_open_{sel}")
            clash = new_name.lower() in [x.lower() for x in b.account_names if x != sel]
            if not new_name:
                field_msg("The name can't be empty.")
            elif clash:
                field_msg(f"'{new_name}' already exists.")
            if new_open != cur_open:
                field_msg(f"Balance now becomes {CURRENCY}{bal[sel] + new_open - cur_open:,.2f}.", "hint")
            changed = new_name != sel or new_open != cur_open
            if st.button("Save changes", type="primary", disabled=not changed or not new_name or clash, key="acct_edit_save",
                         icon=":material/check:"):
                stmts = [("UPDATE accounts SET name=%s, opening_balance=%s WHERE name=%s", (new_name, new_open, sel))]
                if new_name != sel:
                    stmts += [
                        ("UPDATE transactions SET account=%s WHERE account=%s", (new_name, sel)),
                        ("UPDATE transactions SET to_account=%s WHERE to_account=%s", (new_name, sel)),
                        ("UPDATE recurring_rules SET account=%s WHERE account=%s", (new_name, sel)),
                        ("UPDATE recurring_rules SET to_account=%s WHERE to_account=%s", (new_name, sel)),
                    ]
                run_many(stmts)
                flash(f"Saved '{new_name}'")
                st.rerun()

        elif action == "Delete":
            section("Delete an account")
            if not b.account_names:
                empty("No accounts yet.")
                return
            d_acct = st.selectbox("Account", b.account_names, key="acct_del_sel")
            tx_used = int(((b.tx["account"] == d_acct) | (b.tx["to_account"] == d_acct)).sum()) if len(b.tx) else 0
            rules_used = int(((b.rules["account"] == d_acct) | (b.rules["to_account"] == d_acct)).sum()) if len(b.rules) else 0
            if tx_used or rules_used:
                field_msg(f"'{d_acct}' is used by {tx_used} transaction{'s' if tx_used != 1 else ''} and {rules_used} auto "
                          f"transaction{'s' if rules_used != 1 else ''}, so it can't be deleted. You can rename it instead.", "warn")
            if st.button("Delete account", icon=":material/delete:", disabled=bool(tx_used or rules_used), key="acct_del_btn"):
                confirm(f"Delete the account **{d_acct}**?", [("DELETE FROM accounts WHERE name=%s", (d_acct,))],
                        f"Deleted '{d_acct}'")

        else:
            section("Assign older entries")
            n = b.unassigned_count()
            if not n:
                empty("Every income and expense entry already has an account.")
            elif not b.account_names:
                st.warning("Add an account first.")
            else:
                st.caption(f"{n} older entr{'ies have' if n != 1 else 'y has'} no account. Put them all in one account so "
                           "balances add up. You can still change single ones on the Transactions page.")
                ss.setdefault("assign_acct", "Cash" if "Cash" in b.account_names else b.account_names[0])
                acct = st.selectbox("Account", b.account_names, key="assign_acct")
                if st.button(f"Assign {n} to {acct}", type="primary", key="assign_btn"):
                    execute("UPDATE transactions SET account=%s WHERE (account IS NULL OR account = '') AND type <> 'Transfer'",
                            (acct,))
                    flash(f"Assigned {n} entr{'ies' if n != 1 else 'y'} to {acct}")
                    st.rerun()


def render():
    b = book()
    page_header("Categories & accounts", "Shape the app around how your family handles money")
    tab_cats, tab_accts = st.tabs(["Categories", "Accounts"])
    with tab_cats:
        _categories(b)
    with tab_accts:
        _accounts(b)

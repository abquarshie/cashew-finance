from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.data import CURRENCY, money
from core.data import book as money_book
from meals import actions
from meals.data import kitchen
from meals.logic import shopping_list, total_needs
from meals.units import UNITS, base_of, fmt, from_base, to_base
from ui.components import card, empty, field_msg, flash, page_header, section
from ui.entry import _budget_alerts

SCOPES = ["Rest of this week", "Next week", "Next 7 days"]


def _range(scope, today):
    monday = today - timedelta(days=today.weekday())
    if scope == "Next week":
        return monday + timedelta(days=7), monday + timedelta(days=13)
    if scope == "Next 7 days":
        return today, today + timedelta(days=6)
    return today, monday + timedelta(days=6)


def _display(k, ing, base, qty):
    """Show an amount in the ingredient's usual unit when it's the same kind (1.3 kg rather than 1300 g)."""
    usual = k.unit_of.get(ing, base)
    if base_of(usual) == base:
        return round(from_base(qty, base, usual), 3), usual
    return round(qty, 3), base


def _rows(k, items, cats, fallback):
    rows = []
    for r in items:
        amount, unit = _display(k, r["ingredient_id"], r["base"], r["to_buy"])
        why = r["reason"]
        if r["have"] > 0:
            why += f" (have {fmt(r['have'], r['base'])})"
        cat = k.category_of.get(r["ingredient_id"])
        rows.append({"Buy": True, "Item": k.names.get(r["ingredient_id"], "?"), "Amount": amount, "Unit": unit,
                     f"Price ({CURRENCY})": r["est"], "Category": cat if cat in cats else fallback, "Why": why,
                     "_ing": r["ingredient_id"]})
    return rows


def _share_text(table):
    lines = []
    for _, r in table.iterrows():
        q = fmt(*to_base(float(r["Amount"]), r["Unit"])) if r["Unit"] in UNITS else f"{r['Amount']:g} {r['Unit']}"
        lines.append(f"- {r['Item']}: {q}")
    return "Shopping list\n" + "\n".join(lines)


def render():
    ss = st.session_state
    k = kitchen()
    b = money_book()
    cats = b.category_names("Expense")
    fallback = "Staples" if "Staples" in cats else (cats[0] if cats else None)
    today = date.today()
    page_header("Shopping list", "Everything this week's meals need, minus what's already in the pantry")

    scope = st.segmented_control("For", SCOPES, default=SCOPES[0], key="meal_shop_scope",
                                 label_visibility="collapsed") or SCOPES[0]
    start, end = _range(scope, today)
    entries = k.open_entries(start, end)
    needs = total_needs(entries, k.recipes, k.items,
                        names_for_entry=lambda e: f"{k.entry_name(e)} ({e['day']:%a})")
    items = shopping_list(needs, k.pantry, k.low_levels, k.prices)
    items.sort(key=lambda r: (r["low"], k.names.get(r["ingredient_id"], "").lower()))
    extras = ss.setdefault("meal_extra", [])

    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("meal-shop-list"):
            planned = len(entries)
            section("To buy")
            st.caption(f"{start:%a %d} to {end:%a %d %b}: {planned} meal{'s' if planned != 1 else ''} not cooked yet")
            rows = _rows(k, items, cats, fallback)
            for x in extras:
                rows.append({"Buy": True, "Item": k.names.get(x["ing"], "?"), "Amount": x["qty"], "Unit": x["unit"],
                             f"Price ({CURRENCY})": None, "Category": k.category_of.get(x["ing"]) or fallback,
                             "Why": "Added by you", "_ing": x["ing"]})
            if not rows:
                empty("Nothing to buy: the pantry already covers the planned meals." if entries else
                      "No meals planned for these days yet. Plan some on the Meal plan page.")
                return
            base_df = pd.DataFrame(rows)
            sig = hash((scope, tuple((r["_ing"], r["Amount"]) for r in rows)))
            ver = ss.get("meal_shop_ver", 0)
            price_col = f"Price ({CURRENCY})"
            edited = st.data_editor(
                base_df.drop(columns=["_ing"]), key=f"meal_shop_{sig}_{ver}", hide_index=True, width="stretch",
                disabled=["Item", "Unit", "Why"],
                column_config={
                    "Buy": st.column_config.CheckboxColumn("Bought", width="small"),
                    "Amount": st.column_config.NumberColumn("Amount", min_value=0.0, format="%g"),
                    price_col: st.column_config.NumberColumn(price_col, min_value=0.0, format="%.2f",
                                                             help="What you paid for this line. Filled in from last "
                                                                  "time where known."),
                    "Category": st.column_config.SelectboxColumn("Logged under", options=cats, required=True),
                    "Why": st.column_config.TextColumn("Why", width="medium"),
                })
            bought = edited[edited["Buy"]]
            unpriced = [r["Item"] for _, r in bought.iterrows() if not r[price_col] or pd.isna(r[price_col])]
            total = float(bought[price_col].fillna(0).sum())
            est_known = [r["est"] for r in items if r["est"] is not None]
            if est_known:
                st.caption(f"Estimated cost of the full list from past prices: about {money(sum(est_known))}"
                           + (f" (no price yet for {len(items) - len(est_known)} item"
                              f"{'s' if len(items) - len(est_known) != 1 else ''})" if len(est_known) < len(items) else ""))
            with st.expander("Share the list", icon=":material/share:"):
                st.code(_share_text(edited), language=None)
                st.caption("Tap the copy icon, then paste into WhatsApp or a note.")

    with right:
        with card("meal-shop-save"):
            section("Save the shopping trip")
            if not len(bought):
                field_msg("Tick what you bought.", "hint")
                return
            accounts = b.account_names
            ss.setdefault("meal_trip_acct", b.default_account("Expense"))
            if ss.get("meal_trip_acct") not in accounts:
                ss["meal_trip_acct"] = accounts[0] if accounts else None
            st.pills("Paid from", accounts, key="meal_trip_acct")
            ss.setdefault("meal_trip_date", today)
            day = st.date_input("Date", key="meal_trip_date", format="DD/MM/YYYY")
            by_cat = bought.groupby("Category")[price_col].sum().sort_values(ascending=False)
            st.html("".join(f'<div class="prog-head"><span>{c}</span><b class="num">{money(float(v or 0))}</b></div>'
                            for c, v in by_cat.items()))
            if unpriced:
                field_msg("Enter what you paid for: " + ", ".join(unpriced[:6]) + ("…" if len(unpriced) > 6 else ""))
            zero = [r["Item"] for _, r in bought.iterrows() if not r["Amount"] or pd.isna(r["Amount"])]
            if zero:
                field_msg("Enter how much you bought of: " + ", ".join(zero[:6]))
            account = ss.get("meal_trip_acct")
            ready = not unpriced and not zero and account and total > 0
            if st.button(f"Save trip · {money(total)}", type="primary", disabled=not ready, width="stretch",
                         key="meal_trip_save", icon=":material/shopping_cart_checkout:"):
                lines = []
                for i, r in bought.iterrows():  # the row number matches the list it came from
                    q, base = to_base(float(r["Amount"]), r["Unit"]) if r["Unit"] in UNITS else (float(r["Amount"]), r["Unit"])
                    lines.append({"ingredient_id": rows[i]["_ing"], "name": r["Item"], "qty": q, "base": base,
                                  "price": float(r[price_col]), "category": r["Category"]})
                alerts = []
                for cat, amount in by_cat.items():
                    alerts += _budget_alerts(b, "Expense", cat, float(amount), day)
                _, split = actions.save_trip(day, account, lines)
                ss["meal_shop_ver"] = ss.get("meal_shop_ver", 0) + 1
                ss["meal_extra"] = []
                flash(f"Saved {money(total)} of shopping from {account}: " +
                      ", ".join(f"{c} {money(v)}" for c, v in split.items()), ":material/shopping_cart:")
                for a in alerts:
                    flash(a, ":material/warning:")
                st.rerun()
            st.caption("Saving puts what you bought into the pantry, remembers the prices, and logs the cost as "
                       "expenses, one per category.")

        with card("meal-shop-extra"):
            section("Add something not on the list")
            if k.names:
                ing = st.selectbox("Item", list(k.names), index=None, format_func=lambda i: k.names[i],
                                   key="meal_extra_ing", placeholder="Choose an item")
                c1, c2 = st.columns(2)
                qty = c1.number_input("Amount", min_value=0.0, value=None, format="%g", key="meal_extra_qty")
                unit = c2.selectbox("Unit", UNITS, index=UNITS.index(k.unit_of[ing]) if ing else UNITS.index("pcs"),
                                    key=f"meal_extra_unit_{ing}")
                if st.button("Add to list", disabled=not (ing and qty), key="meal_extra_add", icon=":material/add:"):
                    extras.append({"ing": ing, "qty": qty, "unit": unit})
                    ss.pop("meal_extra_ing", None)
                    ss.pop("meal_extra_qty", None)
                    st.rerun()
            else:
                empty("Add ingredients on the Recipes page first.")

        if len(k.trips):
            with card("meal-shop-trips"):
                section("Recent trips")
                t = k.trips
                st.html("".join(
                    f'<div class="prog-head"><span>{d:%a %d %b}, {acct}, {n} item{"s" if n != 1 else ""}</span>'
                    f'<b class="num">{money(float(v))}</b></div>'
                    for d, acct, n, v in zip(t["date"], t["account"], t["items"], t["total"])))

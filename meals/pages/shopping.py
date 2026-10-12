from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.data import CURRENCY, money
from core.data import book as money_book
from meals import actions
from meals.data import kitchen
from meals.logic import shopping_list, total_needs
from meals.units import UNITS, base_of, fmt, from_base, plural, to_base
from ui.components import card, empty, esc, field_msg, flash, page_header, section
from ui.entry import _budget_alerts

SCOPES = ["Rest of this week", "Next week", "Next 7 days"]
VIEWS = ["Market mode", "Table", "Prices"]


def _range(scope, today):
    monday = today - timedelta(days=today.weekday())
    if scope == "Next week":
        return monday + timedelta(days=7), monday + timedelta(days=13)
    if scope == "Next 7 days":
        return today, today + timedelta(days=6)
    return today, monday + timedelta(days=6)


def _amount(k, r):
    """What to pick up, in the way it's sold: 1 crate of eggs, 1.3 kg of rice, 3 onions."""
    ing, base = r["ingredient_id"], r["base"]
    if r["pack"]:
        return float(r["packs"]), r["pack"]
    usual = k.unit_of.get(ing, base)
    if base_of(usual) == base:
        return round(from_base(r["to_buy"], base, usual), 3), usual
    return round(r["to_buy"], 3), base


def _qty_label(amount, unit):
    if unit in ("pcs",):
        return f"{amount:g}"
    return f"{amount:g} {plural(unit, amount)}"


def _rows(k, items, extras, cats, fallback):
    rows = []
    for r in items:
        amount, unit = _amount(k, r)
        why = r["reason"]
        if r["pack"]:
            why += f"{'; ' if why else ''}need {fmt(r['to_buy'], r['base'])}"
        if r["have"] > 0:
            why += f" (have {fmt(r['have'], r['base'])})"
        cat = k.category_of.get(r["ingredient_id"])
        rows.append({"ing": r["ingredient_id"], "name": k.names.get(r["ingredient_id"], "?"), "amount": amount,
                     "unit": unit, "est": r["est"], "category": cat if cat in cats else fallback, "why": why})
    for x in extras:
        cat = k.category_of.get(x["ing"])
        per = k.prices.get((x["ing"], to_base(1, x["unit"], k.pack(x["ing"]))[1]))
        est = round(per * to_base(x["qty"], x["unit"], k.pack(x["ing"]))[0], 2) if per else None
        rows.append({"ing": x["ing"], "name": k.names.get(x["ing"], "?"), "amount": x["qty"], "unit": x["unit"],
                     "est": est, "category": cat if cat in cats else fallback, "why": "Added by you"})
    return rows


def _share_text(rows):
    return "Shopping list\n" + "\n".join(f"- {r['name']}: {_qty_label(r['amount'], r['unit'])}" for r in rows)


def _line(k, row, amount, price, category):
    q, base = to_base(float(amount), row["unit"], k.pack(row["ing"]))
    return {"ingredient_id": row["ing"], "name": row["name"], "qty": q, "base": base, "price": float(price),
            "category": category}


# ---- market mode: big tick boxes, one item at a time ---------------------------------------------
def _market(k, rows, sig):
    ss = st.session_state
    lines, missing = [], []
    for i, row in enumerate(rows):
        key = f"mk_{sig}_{i}"
        with st.container(key=f"meal-mk-{i}"):
            got = st.checkbox(f"{row['name']} · {_qty_label(row['amount'], row['unit'])}", key=key + "_got",
                              help=row["why"] or None)
            if row["why"] and not got:
                st.html(f'<div class="mk-why">{esc(row["why"])}</div>')
            if got:
                c1, c2 = st.columns(2)
                amount = c1.number_input(f"How many ({plural(row['unit'])})" if row["unit"] != "pcs" else "How many",
                                         min_value=0.0, value=float(row["amount"]), step=1.0, format="%g",
                                         key=key + "_amt")
                if key + "_price" not in ss and row["est"] is not None:
                    ss[key + "_price"] = round(row["est"] * (amount / row["amount"] if row["amount"] else 1), 2)
                price = c2.number_input(f"Paid ({CURRENCY})", min_value=0.0, value=None, step=1.0, format="%.2f",
                                        key=key + "_price", placeholder="0.00")
                if not price:
                    missing.append(row["name"])
                elif amount:
                    lines.append(_line(k, row, amount, price, row["category"]))
    return lines, missing


# ---- table: everything at once (handier on a computer) ----------------------------------------------
def _table(k, rows, sig, cats):
    ss = st.session_state
    price_col = f"Price ({CURRENCY})"
    df = pd.DataFrame([{"Bought": True, "Item": r["name"], "Amount": r["amount"], "Unit": r["unit"],
                        price_col: r["est"], "Category": r["category"], "Why": r["why"]} for r in rows])
    edited = st.data_editor(
        df, key=f"meal_shop_{sig}_{ss.get('meal_shop_ver', 0)}", hide_index=True, width="stretch",
        disabled=["Item", "Unit", "Why"],
        column_config={
            "Bought": st.column_config.CheckboxColumn("Bought", width="small"),
            "Amount": st.column_config.NumberColumn("Amount", min_value=0.0, format="%g"),
            price_col: st.column_config.NumberColumn(price_col, min_value=0.0, format="%.2f",
                                                     help="What you paid. Filled in from last time where known."),
            "Category": st.column_config.SelectboxColumn("Logged under", options=cats, required=True),
            "Why": st.column_config.TextColumn("Why", width="medium"),
        })
    lines, missing = [], []
    for i, r in edited.iterrows():  # the row number matches the list it came from
        if not r["Bought"]:
            continue
        if not r[price_col] or pd.isna(r[price_col]):
            missing.append(r["Item"])
        elif r["Amount"] and not pd.isna(r["Amount"]):
            lines.append(_line(k, rows[i], r["Amount"], r[price_col], r["Category"]))
    return lines, missing


# ---- prices: what things cost, and where it's cheaper ------------------------------------------------
def _prices(k):
    h = k.history
    if not len(h):
        empty("Prices show here after your first saved shopping trip.")
        return
    out = []
    for (ing, base), g in h.groupby(["ingredient_id", "unit"]):
        pack = k.pack(ing)
        per_label = pack[0] if pack and pack[2] == base else k.unit_of.get(ing, base)
        scale = pack[1] if pack and pack[2] == base else to_base(1, per_label)[0]
        last = float(g["per_unit"].iloc[-1]) * scale
        prev = float(g["per_unit"].iloc[-2]) * scale if len(g) > 1 else None
        shops = g.dropna(subset=["shop"]).groupby("shop")["per_unit"].mean() * scale
        cheapest = f"{shops.idxmin()} ({money(shops.min())})" if len(shops) > 1 else ""
        change = (last - prev) / prev * 100 if prev else None
        out.append({"Item": k.names.get(int(ing), "?"), "Last price": f"{money(last)} / {per_label}",
                    "Change": f"{change:+.0f}%" if change is not None and abs(change) >= 1 else "",
                    "Cheapest at": cheapest, "Bought": len(g)})
    st.dataframe(pd.DataFrame(out).sort_values("Item"), hide_index=True, width="stretch",
                 column_config={"Bought": st.column_config.NumberColumn("Times bought", format="%d")})
    st.caption("Change compares the last two trips. Cheapest at needs the same item bought at two or more places.")


def render():
    ss = st.session_state
    k = kitchen()
    b = money_book()
    cats = b.category_names("Expense")
    fallback = "Staples" if "Staples" in cats else (cats[0] if cats else None)
    today = date.today()
    page_header("Shopping list", "What the planned meals need, minus what's already in the pantry")

    view = st.segmented_control("View", VIEWS, default=VIEWS[0], key="meal_shop_view",
                                label_visibility="collapsed") or VIEWS[0]
    if view == "Prices":
        with card("meal-prices"):
            section("What things cost")
            _prices(k)
        return
    scope = st.segmented_control("For", SCOPES, default=SCOPES[0], key="meal_shop_scope",
                                 label_visibility="collapsed") or SCOPES[0]
    start, end = _range(scope, today)
    entries = k.open_entries(start, end)
    needs = total_needs(entries, k.recipes, k.items, names_for_entry=lambda e: f"{k.entry_name(e)} ({e['day']:%a})",
                        packs=k.packs)
    items = shopping_list(needs, k.pantry, k.low_levels, k.prices, k.packs)
    items.sort(key=lambda r: (r["low"], k.names.get(r["ingredient_id"], "").lower()))
    extras = ss.setdefault("meal_extra", [])
    rows = _rows(k, items, extras, cats, fallback)
    sig = abs(hash((scope, tuple((r["ing"], r["amount"], r["unit"]) for r in rows), ss.get("meal_shop_ver", 0))))

    left, right = st.columns([3, 2], gap="medium")
    with left:
        with card("meal-shop-list"):
            planned = len(entries)
            section("To buy")
            st.caption(f"{start:%a %d} to {end:%a %d %b}: {planned} meal{'s' if planned != 1 else ''} not cooked yet")
            if not rows:
                empty("Nothing to buy: the pantry already covers the planned meals." if entries else
                      "No meals planned for these days yet. Plan some on the Meal plan page.")
                lines, missing = [], []
            elif view == "Market mode":
                lines, missing = _market(k, rows, sig)
            else:
                lines, missing = _table(k, rows, sig, cats)
            known = [r["est"] for r in rows if r["est"] is not None]
            if known:
                st.caption(f"Estimated cost of the whole list from past prices: about {money(sum(known))}"
                           + (f" (no price yet for {len(rows) - len(known)})" if len(known) < len(rows) else ""))
            if rows:
                with st.expander("Share the list", icon=":material/share:"):
                    st.code(_share_text(rows), language=None)
                    st.caption("Tap the copy icon, then paste into WhatsApp or a note.")

    with right:
        with card("meal-shop-save"):
            section("Save the shopping trip")
            total = round(sum(ln["price"] for ln in lines), 2)
            if not lines and not missing:
                field_msg("Tick what you bought." if rows else "Nothing ticked yet.", "hint")
            else:
                accounts = b.account_names
                ss.setdefault("meal_trip_acct", b.default_account("Expense"))
                if ss.get("meal_trip_acct") not in accounts:
                    ss["meal_trip_acct"] = accounts[0] if accounts else None
                st.pills("Paid from", accounts, key="meal_trip_acct")
                shops = k.shops()
                shop = st.selectbox("Where (optional)", shops, index=None, accept_new_options=True, key="meal_trip_shop",
                                    placeholder="e.g. Makola, Shoprite")
                ss.setdefault("meal_trip_date", today)
                day = st.date_input("Date", key="meal_trip_date", format="DD/MM/YYYY")
                by_cat = {}
                for ln in lines:
                    by_cat[ln["category"]] = by_cat.get(ln["category"], 0) + ln["price"]
                st.html("".join(f'<div class="prog-head"><span>{esc(c)}</span><b class="num">{money(v)}</b></div>'
                                for c, v in sorted(by_cat.items(), key=lambda x: -x[1])))
                if missing:
                    field_msg("Enter what you paid for: " + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""))
                account = ss.get("meal_trip_acct")
                ready = bool(lines) and not missing and account and total > 0
                if st.button(f"Save trip · {money(total)}", type="primary", disabled=not ready, width="stretch",
                             key="meal_trip_save", icon=":material/shopping_cart_checkout:"):
                    alerts = []
                    for cat, amount in by_cat.items():
                        alerts += _budget_alerts(b, "Expense", cat, float(amount), day)
                    _, split, changes = actions.save_trip(day, account, lines, shop)
                    ss["meal_shop_ver"] = ss.get("meal_shop_ver", 0) + 1
                    ss["meal_extra"] = []
                    ss.pop("meal_trip_shop", None)
                    where = f" at {shop}" if shop else ""
                    flash(f"Saved {money(total)} of shopping{where} from {account}: " +
                          ", ".join(f"{c} {money(v)}" for c, v in split.items()), ":material/shopping_cart:")
                    for name, old, new, ch in changes[:4]:
                        word = "more" if ch > 0 else "less"
                        flash(f"{name} cost {abs(ch) * 100:.0f}% {word} than last time", ":material/trending_up:"
                              if ch > 0 else ":material/trending_down:")
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
                pack = k.pack(ing) if ing else None
                c1, c2 = st.columns(2)
                qty = c1.number_input("Amount", min_value=0.0, value=None, format="%g", key="meal_extra_qty")
                options = ([pack[0]] if pack else []) + UNITS
                default = pack[0] if pack else (k.unit_of[ing] if ing else "pcs")
                unit = c2.selectbox("Unit", list(dict.fromkeys(options)), index=list(dict.fromkeys(options)).index(default),
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
                    f'<div class="prog-head"><span>{d:%a %d %b}{", " + esc(sh) if isinstance(sh, str) and sh else ""}, '
                    f'{n} item{"s" if n != 1 else ""}</span><b class="num">{money(float(v))}</b></div>'
                    for d, sh, n, v in zip(t["date"], t["shop"], t["items"], t["total"])))

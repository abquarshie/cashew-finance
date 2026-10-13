"""Household supplies: washing powder, bleach, toilet roll and the like.

They share the pantry and the shopping list with food (low ones are added to the list, and a shopping
trip logs them under their own money category), but they have their own budget and never appear in
recipes or meal ideas.
"""
from datetime import date

import streamlit as st

from core.data import CURRENCY, money
from core.data import book as money_book
from meals import actions
from meals.briefing import guard
from meals.data import kitchen
from meals.logic import food_budget
from meals.units import CONTAINERS, base_of, fmt_stock, to_base
from ui.components import card, empty, esc, field_msg, flash, page_header, pill, section

UNITS = ["pcs", "ml", "l", "g", "kg"]


def _step(k, ing):
    """What one tap of + or − moves: one bottle, one pack, one roll…"""
    base = base_of(k.unit_of.get(ing, "pcs"))
    pack = k.pack(ing)
    if pack and pack[2] == base:
        return pack[1], pack[0]
    usual = k.unit_of.get(ing, "pcs")
    return to_base(1, usual)[0], usual


def _bump(ing, base, have, delta):
    actions.set_stock([(ing, base, max(have + delta, 0))])


def _budget_card(k, b):
    today = date.today()
    cats = {c for c in k.supply_categories if c}
    fb = food_budget(b, cats, today) if cats else None
    with card("supplies-budget"):
        section("Household budget", today.strftime("%B"))
        if fb:
            pct = fb["spent"] / fb["limit"] * 100 if fb["limit"] else 0
            st.html(f'<div class="prog-head"><span>{esc(" and ".join(fb["names"]))}</span>'
                    f'<b class="num">{money(fb["spent"])} of {money(fb["limit"])}</b></div>'
                    f'<div class="bar"><div class="fill {"over" if pct > 100 else "warn" if pct >= 75 else "ok"}" '
                    f'style="width:{min(pct, 100):.0f}%"></div></div>')
            g = guard(k, b, today, "household")
            if g:
                field_msg(g[1], g[0])
            st.caption("Change it under Budgets & goals.")
            return
        group = actions.SUPPLIES_GROUP if actions.SUPPLIES_GROUP in b.groups else None
        target = group or (sorted(cats)[0] if cats else actions.SUPPLIES_CATEGORY)
        st.write(f"No budget for household supplies yet. Set a monthly limit for **{target}**, kept separate "
                 "from food.")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        limit = c1.number_input(f"Monthly limit ({CURRENCY})", min_value=0.0, value=None, step=50.0, format="%.2f",
                                placeholder="e.g. 300", key="supplies_budget")
        if c2.button("Set budget", type="primary", disabled=not limit, key="supplies_budget_go"):
            actions.set_budget(target, limit)
            flash(f"{target} budget set to {money(limit)} a month", ":material/donut_small:")
            st.rerun()


def _items(k):
    with card("supplies-list"):
        section("What's in the house", f"{len(k.supplies)} item{'s' if len(k.supplies) != 1 else ''}")
        for ing in sorted(k.supplies, key=lambda i: k.names.get(i, "").lower()):
            base = base_of(k.unit_of.get(ing, "pcs"))
            have = float(k.pantry.get((ing, base), 0.0))
            level = k.low_levels.get((ing, base))
            step, step_name = _step(k, ing)
            if have <= 0:
                state = pill("Out", "out")
            elif level is not None and have <= level:
                state = pill("Low", "warn")
            else:
                state = ""
            shelf = fmt_stock(have, base, k.pack(ing), k.unit_of.get(ing)) if have > 0 else "none"
            row = st.container(horizontal=True, vertical_alignment="center", key=f"supply-{ing}")
            row.html(f'<div style="min-width:0"><div class="rule-name">{esc(k.names.get(ing, "?"))}{state}</div>'
                     f'<div class="rule-meta">{esc(shelf)}</div></div>', width="stretch")
            row.button("", key=f"supply_minus_{ing}", icon=":material/remove:", disabled=have <= 0,
                       on_click=_bump, args=(ing, base, have, -step), help=f"One {step_name} used up")
            row.button("", key=f"supply_plus_{ing}", icon=":material/add:", on_click=_bump, args=(ing, base, have, step),
                       help=f"One more {step_name}")
        st.caption("Tap − when one runs out and + when you bring one home. Shopping trips add to these by "
                   "themselves; anything low goes on the shopping list.")


def _add(k, b):
    ss = st.session_state
    cats = b.category_names("Expense")
    with card("supplies-add"):
        section("Add a household item")
        name = st.text_input("Name", key="supply_name", max_chars=60, placeholder="e.g. Mosquito coil").strip()
        c1, c2 = st.columns(2)
        unit = c1.selectbox("Counted in", UNITS, key="supply_unit")
        default = actions.SUPPLIES_CATEGORY if actions.SUPPLIES_CATEGORY in cats else (cats[0] if cats else None)
        options = list(dict.fromkeys([actions.SUPPLIES_CATEGORY] + cats))
        cat = c2.selectbox("Money category", options, index=options.index(default) if default in options else 0,
                           key="supply_cat", help="Where its cost is logged when you save a shopping trip.")
        p1, p2 = st.columns(2)
        pack = p1.selectbox("Bought in", [None] + CONTAINERS, key="supply_pack",
                            format_func=lambda x: "Loose / as counted" if x is None else x)
        size = p2.number_input(f"Each {pack or 'one'} holds ({unit})", min_value=0.0, value=None, format="%g",
                               key="supply_size", disabled=pack is None)
        low = st.number_input(f"Warn me when down to ({unit})", min_value=0.0, value=None, format="%g", key="supply_low")
        clash = name.lower() in {n.lower() for n in k.names.values()}
        if clash:
            field_msg(f"{name} is already in your list.")
        if pack and not size:
            field_msg(f"Say how much one {pack} holds.", "hint")
        if st.button("Add item", type="primary", disabled=not name or clash or bool(pack and not size),
                     key="supply_add", icon=":material/add:"):
            actions.add_supply(name, unit, cat, to_base(low, unit)[0] if low else None, pack,
                               to_base(size, unit)[0] if pack and size else None)
            for key in ("supply_name", "supply_low", "supply_pack", "supply_size"):
                ss.pop(key, None)
            flash(f"Added {name}", ":material/cleaning_services:")
            st.rerun()


def render():
    k = kitchen()
    b = money_book()
    page_header("Household supplies", "Washing powder, bleach, toilet roll… with their own budget, kept apart from food")
    if not k.supplies:
        with card("supplies-start"):
            section("Start your list")
            st.write("Add the everyday things most homes keep: washing powder, dishwashing liquid, bleach, "
                     "disinfectant, toilet roll, bathing soap, bar soap, sponges and bin bags. Change anything after.")
            if st.button("Add common household items", type="primary", icon=":material/cleaning_services:",
                         key="supplies_starter"):
                n = actions.load_supplies_starter()
                flash(f"Added {n} household items. Count what you have with + and −.", ":material/cleaning_services:")
                st.rerun()
    left, right = st.columns([3, 2], gap="medium")
    with left:
        if k.supplies:
            _items(k)
        else:
            empty("No household items yet.")
    with right:
        _budget_card(k, b)
        _add(k, b)


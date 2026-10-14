from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.data import money
from meals import actions
from meals.data import kitchen
from meals.logic import fridge_flags, recipe_cost
from meals.units import LEFTOVER_UNITS, base_of, fmt, fmt_stock, frac, from_base, loose, plural, to_base
from ui.components import card, empty, esc, field_msg, flash, page_header, pill, section

FLAG = {"past": ("Past eat-by", "out"), "soon": ("Eat soon", "warn"), "low": ("Running low", "warn"),
        None: ("Fresh", "in")}


def _ate_one(batch_id, portions):
    actions.eat_portion(batch_id, min(1.0, portions))


def _bin(batch_id, label, value_each):
    gone = actions.throw_away(batch_id, value_each)
    flash(f"Logged {gone:g} of {label} as thrown away" + (f" (about {money(value_each * gone)})" if value_each else ""),
          ":material/delete:")


def _set(batch_id, key):
    actions.set_portions(batch_id, st.session_state.get(key) or 0)


def _fridge(k):
    ss = st.session_state
    today = date.today()
    with card("meal-fridge"):
        section("In the fridge", f"{len(k.fridge)} item{'s' if len(k.fridge) != 1 else ''}")
        if not k.fridge:
            empty("Nothing in the fridge. Leftovers land here when you tick a meal as cooked.")
        for b in k.fridge:
            flag = fridge_flags(b, today)
            text, tone = FLAG[flag]
            eat_by = "today" if b["eat_by"] == today else ("tomorrow" if b["eat_by"] == today + timedelta(days=1)
                                                            else f"{b['eat_by']:%a %d %b}")
            row = st.container(horizontal=True, vertical_alignment="center", key=f"meal-fr-{b['id']}")
            unit = b["unit"]
            row.html(f'<div style="min-width:0"><div class="rule-name">{esc(b["label"])}{pill(text, tone)}</div>'
                     f'<div class="rule-meta">{frac(b["portions"])} {plural(unit, b["portions"])}, cooked '
                     f'{b["cooked_on"]:%a %d %b}, eat by {eat_by}</div></div>', width="stretch")
            key = f"meal_fr_n_{b['id']}_{b['portions']}"
            row.number_input("Portions", min_value=0.0, value=b["portions"], step=0.5, format="%g", key=key,
                             label_visibility="collapsed", width=110, on_change=_set, args=(b["id"], key))
            row.button("Ate 1" if b["portions"] >= 1 else "Ate the rest", key=f"meal_fr_ate_{b['id']}",
                       on_click=_ate_one, args=(b["id"], b["portions"]), disabled=b["portions"] <= 0,
                       help=f"One {unit} eaten")
            each = recipe_cost(b["recipe_id"], k.recipes, k.items, k.prices, k.packs)[1] if b["recipe_id"] else None
            row.button("", key=f"meal_fr_bin_{b['id']}", icon=":material/delete:", type="tertiary",
                       help="Thrown away: logged as food waste", on_click=_bin, args=(b["id"], b["label"], each or None))

    with card("meal-fridge-add"):
        section("Put something in the fridge")
        options = [None] + list(k.recipes)
        rid = st.selectbox("Dish", options, format_func=lambda i: "Something else" if i is None else k.recipes[i]["name"],
                           key="meal_fr_add_recipe")
        label = k.recipes[rid]["name"] if rid else st.text_input("What is it?", key="meal_fr_add_label",
                                                                 placeholder="e.g. Shito").strip()
        c1, c0, c2 = st.columns(3)
        portions = c1.number_input("How many", min_value=1.0, value=2.0, step=1.0, format="%g", key="meal_fr_add_n")
        unit = c0.selectbox("Counted in", LEFTOVER_UNITS, key="meal_fr_add_unit")
        keeps = k.recipes[rid]["keeps_days"] if rid else 3
        eat_by = c2.date_input("Eat by", value=today + timedelta(days=keeps), key=f"meal_fr_add_by_{rid}",
                               format="DD/MM/YYYY")
        if eat_by < today:
            field_msg("That eat-by date has already passed.", "warn")
        if st.button("Add to fridge", type="primary", disabled=not label, key="meal_fr_add_go", icon=":material/add:"):
            actions.add_to_fridge(label, portions, eat_by, rid, unit)
            ss.pop("meal_fr_add_label", None)
            flash(f"Added {portions:g} {plural(unit, portions)} of {label}")
            st.rerun()


def pantry_table(k):
    ss = st.session_state
    keys = {(int(i), base_of(u)) for i, u in zip(k.ingredients["id"], k.ingredients["unit"])} | set(k.pantry)
    keys = {key for key in keys if key[0] not in k.supplies}  # household supplies have their own tab
    if not keys:
        with card("meal-pantry"):
            empty("No ingredients yet. Add them under Meals → Recipes.")
        return
    rows = []
    for ing, base in sorted(keys, key=lambda x: k.names.get(x[0], "").lower()):
        usual = k.unit_of.get(ing, base)
        unit = usual if base_of(usual) == base else base
        have = k.pantry.get((ing, base), 0.0)
        low = k.low_levels.get((ing, base))
        # an item only counts as "out" once it has been stocked or has a warning level: the catalog's many
        # never-bought items aren't all "out"
        tracked = (ing, base) in k.pantry or low is not None
        status = ("Out" if tracked else "") if have <= 0 else ("Low" if low is not None and have <= low else "")
        per = k.prices.get((ing, base))
        rows.append({"Item": k.names.get(ing, "?"), "In stock": round(from_base(have, base, unit), 3), "Unit": unit,
                     "On the shelf": fmt_stock(have, base, k.pack(ing), usual) if have > 0 else "",
                     "Status": status,
                     "Warn at": fmt(low, base, usual) if low is not None else "",
                     "Last price": (f"{money(per * k.pack(ing)[1])} / {k.pack(ing)[0]}" if per and k.pack(ing)
                                    and k.pack(ing)[2] == base and not loose(k.pack(ing)) else
                                    f"{money(per * to_base(1, unit)[0])} / {unit}" if per else ""),
                     "_ing": ing, "_base": base})
    table = pd.DataFrame(rows)
    only_low = st.toggle("Only show what's low or out", key="meal_pantry_low")
    view = table[table["Status"] != ""] if only_low else table
    with card("meal-pantry"):
        section("Pantry", f"{(table['Status'] == 'Low').sum()} low, {(table['Status'] == 'Out').sum()} out")
        if not len(view):
            empty("Nothing is low. Good stocking!")
            return
        ver = ss.get("meal_pantry_ver", 0)
        edited = st.data_editor(
            view.drop(columns=["_ing", "_base"]), key=f"meal_pantry_{ver}_{only_low}", hide_index=True, width="stretch",
            disabled=["Item", "Unit", "On the shelf", "Status", "Warn at", "Last price"],
            column_config={"In stock": st.column_config.NumberColumn("In stock", min_value=0.0, format="%g",
                                                                     help="Type what you actually have to correct it")})
        changes = []
        for i in view.index:
            new = edited.loc[i, "In stock"]
            if new is not None and not pd.isna(new) and abs(float(new) - float(view.loc[i, "In stock"])) > 1e-9:
                changes.append((int(view.loc[i, "_ing"]), view.loc[i, "_base"],
                                to_base(float(new), view.loc[i, "Unit"])[0] if view.loc[i, "Unit"] != view.loc[i, "_base"]
                                else float(new)))
        if changes:
            if st.button(f"Save {len(changes)} stock change{'s' if len(changes) != 1 else ''}", type="primary",
                         key="meal_pantry_save", icon=":material/check:"):
                actions.set_stock(changes)
                ss["meal_pantry_ver"] = ver + 1
                flash("Pantry updated")
                st.rerun()
        st.caption("Shopping adds to these amounts and cooking takes from them. Correct a number any time; "
                   "set warning levels under Meals → Recipes → Ingredients.")


def render():
    k = kitchen()
    page_header("Fridge & pantry", "Cooked food waiting to be eaten, and the raw ingredients you have")
    tab_f, tab_p, tab_s = st.tabs(["Fridge", "Pantry", "Settings"])
    with tab_f:
        amount, value, n = k.waste_this_month()
        if n:
            st.html(f'<div class="field-msg hint" style="margin:0 0 .6rem">This month: {n} lot{"s" if n != 1 else ""} '
                    f'of food thrown away ({amount:g} portions{f", about {money(value)}" if value else ""}).</div>')
        _fridge(k)
    with tab_p:
        pantry_table(k)
    with tab_s:
        with card("meal-settings"):
            section("People eating at each meal")
            n = st.number_input("People", 1, 30, k.household, key="meal_household", label_visibility="collapsed")
            st.caption("When a dish is cooked, this many portions are eaten at that meal and the rest go into the fridge.")
            if n != k.household and st.button("Save", type="primary", key="meal_household_save"):
                actions.set_household(n)
                flash(f"Set to {n} people per meal")
                st.rerun()

import pandas as pd
import streamlit as st

from core.data import book as money_book
from core.data import money
from core.db import transact
from meals import actions
from meals.data import invalidate_kitchen, kitchen
from meals.starter import load_starter
from meals.logic import recipe_cost
from meals.units import CONTAINERS, UNITS, base_of, fmt, from_base, plural, to_base
from ui.components import card, confirm, empty, esc, field_msg, flash, page_header, pill, section

NEW = 0


def _expense_categories():
    return money_book().category_names("Expense")


def cost_text(k, rid):
    """'GH₵14.50 a portion' (or 'at least…' when some prices aren't known yet)."""
    batch, each, unknown = recipe_cost(rid, k.recipes, k.items, k.prices, k.packs)
    if not batch:
        return "cost known after your first shop"
    return f"{'at least ' if unknown else 'about '}{money(each)} a portion"


def _line(k, ing, qty, unit):
    pack = k.pack(ing)
    if pack and unit == pack[0]:
        return f"{qty:g} {plural(unit, qty)} {k.names.get(ing, '?')}"
    return f"{fmt(*to_base(qty, unit))} {k.names.get(ing, '?')}"


def _recipe_card(k, rid):
    r = k.recipes[rid]
    lines = k.items.get(rid, [])
    cost_txt = cost_text(k, rid)
    ings = ", ".join(_line(k, i, q, u) for i, q, u in lines)
    prep = f'<div class="rule-meta">Ahead: {esc(r["prep_note"])} ({r["prep_hours"]} h before)</div>' \
        if r["prep_note"] and r["prep_hours"] else ""
    return (f'<div class="rule"><div style="min-width:0"><div class="rule-name">{esc(r["name"])}'
            f'{pill(str(r["portions"]) + " portions", "neutral")}{pill("keeps " + str(r["keeps_days"]) + " days", "accent")}'
            f'</div><div class="rule-meta">{esc(ings) or "No ingredients yet"}</div>{prep}</div>'
            f'<div class="rule-right"><div class="rule-next">{esc(cost_txt)}</div></div></div>')


def _editor(k):
    ss = st.session_state
    options = [NEW] + list(k.recipes)
    if ss.get("meal_recipe_pick") not in options:
        ss["meal_recipe_pick"] = NEW
    rid = st.selectbox("Recipe", options, key="meal_recipe_pick",
                       format_func=lambda i: "＋ New recipe" if i == NEW else k.recipes[i]["name"])
    r = k.recipes.get(rid, {"name": "", "portions": max(k.household, 1), "keeps_days": 3, "prep_note": "",
                            "prep_hours": None, "method": ""})
    ver = ss.get(f"meal_recipe_ver_{rid}", 0)
    pre = f"meal_r{rid}_{ver}_"

    name = st.text_input("Name", value=r["name"], key=pre + "name", max_chars=80,
                         placeholder="e.g. Groundnut soup").strip()
    c1, c2 = st.columns(2)
    portions = c1.number_input("Portions it makes", 1, 100, int(r["portions"]), key=pre + "portions")
    keeps = c2.number_input("Keeps in the fridge (days)", 0, 30, int(r["keeps_days"]), key=pre + "keeps")
    p1, p2 = st.columns([2, 1])
    prep_note = p1.text_input("Prep ahead (optional)", value=r["prep_note"] or "", key=pre + "prep",
                              placeholder="e.g. Soak the beans").strip()
    prep_hours = p2.number_input("Hours before", 0, 72, int(r["prep_hours"] or 0), key=pre + "prep_h",
                                 help="How long before the meal the reminder should show.")

    st.html('<div class="section-title" style="margin-top:.4rem">Ingredients</div>')
    if not len(k.ingredients):
        field_msg("Add ingredients first, under the Ingredients tab.", "hint")
        return
    names = sorted(k.names.values(), key=str.lower)
    id_of = {v: i for i, v in k.names.items()}
    rows = [{"Ingredient": k.names.get(i), "Amount": float(q), "Unit": u} for i, q, u in k.items.get(rid, [])]
    lines = st.data_editor(
        pd.DataFrame(rows, columns=["Ingredient", "Amount", "Unit"]), key=pre + "lines", num_rows="dynamic",
        hide_index=True, width="stretch",
        column_config={
            "Ingredient": st.column_config.SelectboxColumn("Ingredient", options=names, required=True, width="medium"),
            "Amount": st.column_config.NumberColumn("Amount", min_value=0.0, format="%g", required=True),
            "Unit": st.column_config.SelectboxColumn("Unit", options=UNITS, help="Leave empty to use the item's usual unit"),
        })
    method = st.text_area("Method (optional)", value=r["method"] or "", key=pre + "method", height=90)

    clean, problems = [], []
    for _, row in lines.iterrows():
        ing = row["Ingredient"]
        if not isinstance(ing, str) or not ing:
            continue
        qty = row["Amount"]
        if qty is None or pd.isna(qty) or qty <= 0:
            problems.append(f"Give {ing} an amount.")
            continue
        unit = row["Unit"] if isinstance(row["Unit"], str) and row["Unit"] else k.unit_of[id_of[ing]]
        pack = k.pack(id_of[ing])
        if base_of(unit) != base_of(k.unit_of[id_of[ing]]) and not (pack and unit == pack[0]):
            field_msg(f"{ing} is usually counted in {k.unit_of[id_of[ing]]}; {unit} won't add up with it "
                      "on the shopping list.", "warn")
        clean.append((id_of[ing], float(qty), unit))
    dupes = {k.names[i] for i, _, _ in clean if sum(1 for j, _, _ in clean if j == i) > 1}
    if dupes:
        field_msg(f"{', '.join(sorted(dupes))} is listed twice; the amounts will be added together.", "hint")
    taken = {v["name"].lower() for i, v in k.recipes.items() if i != rid}
    if name.lower() in taken:
        problems.append("You already have a recipe with this name.")
    for p in problems:
        field_msg(p)
    ready = bool(name) and bool(clean) and not problems
    row = st.container(horizontal=True)
    if row.button("Save recipe", type="primary", disabled=not ready, icon=":material/check:", key=pre + "save"):
        new_id = actions.save_recipe(rid or None, name, portions, keeps, prep_note, prep_hours, method, clean)
        ss[f"meal_recipe_ver_{rid}"] = ver + 1
        ss["meal_recipe_pick"] = new_id
        flash(f"Saved {name}")
        st.rerun()
    if rid and row.button("Delete", icon=":material/delete:", key=pre + "del"):
        def _after():
            st.session_state["meal_recipe_pick"] = NEW
        confirm(f"Delete **{r['name']}**? It comes off any days it's planned for that haven't been cooked yet.",
                [("DELETE FROM meals.plan WHERE recipe_id = %s AND status = 'planned'", (rid,)),
                 ("DELETE FROM meals.recipes WHERE id = %s", (rid,))],
                f"Deleted {r['name']}", after=lambda: (_after(), invalidate_kitchen()))
    if not ready and not problems:
        field_msg("Add a name and at least one ingredient to save.", "hint")


def _ingredients(k):
    ss = st.session_state
    cats = _expense_categories()
    with card("meal-ing-add"):
        section("Add an ingredient")
        name = st.text_input("Name", key="meal_ing_name", max_chars=60, placeholder="e.g. Groundnut paste").strip()
        c1, c2 = st.columns(2)
        unit = c1.selectbox("Usually counted in", UNITS, index=UNITS.index("pcs"), key="meal_ing_unit")
        default_cat = "Staples" if "Staples" in cats else (cats[0] if cats else None)
        cat = c2.selectbox("Money category", cats, index=cats.index(default_cat) if default_cat in cats else 0,
                           key="meal_ing_cat", help="Where its cost is logged when you save a shopping trip.")
        busy = bool(ss.get("meal_ing_pack") or ss.get("meal_ing_low"))
        with st.expander("Bought in a crate, bag or bottle? Low-stock warning?", icon=":material/inventory_2:",
                         expanded=busy):
            p1, p2 = st.columns(2)
            pack = p1.selectbox("Bought in", [None] + CONTAINERS, key="meal_ing_pack",
                                format_func=lambda x: "Loose / as counted" if x is None else x,
                                help="E.g. eggs in a crate, rice in a bag, oil in a bottle. Then you can say "
                                     "\"2 crates\" and Cashew does the sums.")
            size = p2.number_input(f"Each {pack or 'container'} holds ({unit})", min_value=0.0, value=None,
                                   format="%g", key="meal_ing_pack_size", disabled=pack is None,
                                   placeholder="e.g. 30" if unit == "pcs" else "e.g. 5")
            low = st.number_input(f"Warn me when stock is down to ({unit})", min_value=0.0, value=None,
                                  key="meal_ing_low", format="%g")
        clash = name.lower() in {n.lower() for n in k.names.values()}
        if clash:
            field_msg(f"{name} is already in your list.")
        if pack and not size:
            field_msg(f"Say how much one {pack} holds, so Cashew can count in {plural(pack)}.", "hint")
        if pack and pack == unit:
            field_msg("Pick a different container from the usual unit, or leave it as loose.")
        bad_pack = bool(pack) and (not size or pack == unit)
        if st.button("Add ingredient", type="primary", disabled=not name or clash or bad_pack, key="meal_ing_add",
                     icon=":material/add:"):
            actions.add_ingredient(name, unit, cat, to_base(low, unit)[0] if low else None,
                                   pack, to_base(size, unit)[0] if pack and size else None)
            for key in ("meal_ing_name", "meal_ing_low", "meal_ing_pack", "meal_ing_pack_size"):
                ss.pop(key, None)
            flash(f"Added {name}")
            st.rerun()

    with card("meal-ing-list"):
        section("Your ingredients", f"{len(k.ingredients)}")
        if not len(k.ingredients):
            empty("Nothing yet. Add one above, or load the starter recipes.")
            return
        ing = k.ingredients
        table = pd.DataFrame({
            "Name": ing["name"], "Unit": ing["unit"], "Category": ing["category"],
            "Low at": [from_base(float(v), base_of(u), u) if v is not None and not pd.isna(v) else None
                       for v, u in zip(ing["low_level"], ing["unit"])],
            "Bought in": [p if isinstance(p, str) and p else None for p in ing["pack_name"]],
            "Holds": [from_base(float(v), base_of(u), u) if v is not None and not pd.isna(v) else None
                      for v, u in zip(ing["pack_size"], ing["unit"])],
        })
        table.index = ing["id"].astype(int).tolist()
        ver = ss.get("meal_ing_ver", 0)
        edited = st.data_editor(table, key=f"meal_ing_edit_{ver}", hide_index=True, width="stretch",
                                column_config={
                                    "Name": st.column_config.TextColumn("Name", required=True),
                                    "Unit": st.column_config.SelectboxColumn("Usual unit", options=UNITS, required=True),
                                    "Category": st.column_config.SelectboxColumn("Money category", options=cats),
                                    "Low at": st.column_config.NumberColumn("Warn when down to", min_value=0.0,
                                                                           format="%g"),
                                    "Bought in": st.column_config.SelectboxColumn("Bought in", options=CONTAINERS,
                                                                                  help="Crate, bag, bottle…"),
                                    "Holds": st.column_config.NumberColumn("Each holds (usual unit)", min_value=0.0,
                                                                          format="%g"),
                                })
        changed = [i for i in table.index if not table.loc[i].equals(edited.loc[i])]
        if changed:
            names = [str(n).strip().lower() for n in edited["Name"]]
            no_size = [r["Name"] for _, r in edited.iterrows()
                       if isinstance(r["Bought in"], str) and r["Bought in"] and (r["Holds"] is None or pd.isna(r["Holds"])
                                                                                   or r["Holds"] <= 0)]
            if len(set(names)) != len(names) or "" in names:
                field_msg("Each ingredient needs its own name.")
            elif no_size:
                field_msg("Say how much each container holds for: " + ", ".join(no_size))
            elif st.button(f"Save {len(changed)} change{'s' if len(changed) != 1 else ''}", type="primary",
                           key="meal_ing_save", icon=":material/check:"):
                for i in changed:
                    row = edited.loc[i]
                    low = row["Low at"]
                    low_base = to_base(float(low), row["Unit"])[0] if low is not None and not pd.isna(low) else None
                    pack = row["Bought in"] if isinstance(row["Bought in"], str) and row["Bought in"] else None
                    size = to_base(float(row["Holds"]), row["Unit"])[0] if pack else None
                    actions.update_ingredient(int(i), str(row["Name"]), row["Unit"], row["Category"], low_base, pack, size)
                ss["meal_ing_ver"] = ver + 1
                flash("Ingredients saved")
                st.rerun()
        unused = [i for i in k.names if i not in k.used_ingredients]
        if unused:
            with st.expander("Remove an ingredient"):
                pick = st.selectbox("Not used in any recipe or plan", unused, format_func=lambda i: k.names[i],
                                    key="meal_ing_del")
                if st.button("Remove", key="meal_ing_del_go", icon=":material/delete:"):
                    confirm(f"Remove **{k.names[pick]}**? Its pantry stock and prices go too.",
                            [("DELETE FROM meals.ingredients WHERE id = %s", (pick,))], f"Removed {k.names[pick]}",
                            button="Remove", after=invalidate_kitchen)


def render():
    k = kitchen()
    page_header("Recipes", "Your recipe book and the ingredients it uses")
    tab_r, tab_i = st.tabs(["Recipes", "Ingredients"])
    with tab_r:
        if not k.recipes:
            with card("meal-starter"):
                section("Start your recipe book")
                st.write("Add six everyday dishes (jollof, red red, kontomire stew, okro stew with banku, light soup, "
                         "and bread with eggs) with their ingredients. Change anything to suit how you cook.")
                if st.button("Add starter recipes", type="primary", icon=":material/menu_book:", key="meal_starter"):
                    n = transact(lambda conn: load_starter(conn, _expense_categories()))
                    invalidate_kitchen()
                    flash(f"Added {n} recipes", ":material/menu_book:")
                    st.rerun()
        left, right = st.columns([3, 2], gap="medium")
        with left:
            with card("meal-recipe-edit"):
                section("Add or change a recipe")
                _editor(k)
        with right:
            with card("meal-recipe-list"):
                section("Recipe book", f"{len(k.recipes)}")
                if k.recipes:
                    st.html("".join(_recipe_card(k, rid) for rid in k.recipes))
                else:
                    empty("No recipes yet.")
    with tab_i:
        _ingredients(k)

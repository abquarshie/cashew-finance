import pandas as pd
import streamlit as st

from core.data import book as money_book
from core.data import money
from core.db import transact
from meals import actions
from core.db import invalidate
from meals.data import kitchen
from meals.catalog import SECTIONS
from meals.logic import ROLES, recipe_cost
from meals.starter import RECIPES as STARTER_RECIPES
from meals.starter import load_starter
from meals.units import CONTAINERS, UNITS, alts, base_of, fmt, frac, from_base, plural, to_base
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
    if (pack and unit == pack[0]) or unit in alts(pack):
        return f"{frac(qty)} {plural(unit, qty)} {k.names.get(ing, '?')}"
    return f"{fmt(*to_base(qty, unit), unit)} {k.names.get(ing, '?')}"


def _recipe_card(k, rid):
    r = k.recipes[rid]
    if r["bought"]:
        price = f"{money(r['price'])} a {r['count_unit']}" if r["price"] else "price known after the first time"
        where = f"Bought at {r['shop']}" if r["shop"] else "Bought ready-made"
        return (f'<div class="rule"><div style="min-width:0"><div class="rule-name">{esc(r["name"])}'
                f'{pill("🛍️ bought", "accent")}</div><div class="rule-meta">{esc(where)}'
                f'{", logged under " + esc(r["category"]) if r["category"] else ""}</div></div>'
                f'<div class="rule-right"><div class="rule-next">{esc(price)}</div></div></div>')
    lines = k.items.get(rid, [])
    cost_txt = cost_text(k, rid)
    ings = ", ".join(_line(k, i, q, u) for i, q, u in lines)
    prep = f'<div class="rule-meta">Ahead: {esc(r["prep_note"])} ({r["prep_hours"]} h before)</div>' \
        if r["prep_note"] and r["prep_hours"] else ""
    role = pill(r["role"], "neutral") if r["role"] in ("starch", "soup", "stew", "sauce", "side") else ""
    return (f'<div class="rule"><div style="min-width:0"><div class="rule-name">{esc(r["name"])}{role}'
            f'{pill(frac(r["portions"]) + " " + plural("portion", r["portions"]), "neutral")}{pill("keeps " + str(r["keeps_days"]) + " days", "accent")}'
            f'</div><div class="rule-meta">{esc(ings) or "No ingredients yet"}</div>{prep}</div>'
            f'<div class="rule-right"><div class="rule-next">{esc(cost_txt)}</div></div></div>')


BOUGHT_UNITS = ["ball", "portion", "piece", "pack", "plate", "bowl", "loaf", "bottle", "sachet"]


def _bought_editor(k, rid, r, pre, ver):
    """A dish bought ready-made: its unit, usual price, where from, and the money category it's paid under."""
    from core.data import book as money_book
    ss = st.session_state
    b = money_book()
    name = st.text_input("Name", value=r["name"], key=pre + "bname", max_chars=80, placeholder="e.g. Kenkey").strip()
    c1, c2 = st.columns(2)
    unit_now = r.get("count_unit") or "ball"
    units = list(dict.fromkeys([unit_now] + BOUGHT_UNITS))
    unit = c1.selectbox("Counted in", units, key=pre + "bunit")
    price = c2.number_input(f"Usual price for one {unit} (GH₵)", min_value=0.0, step=0.5, format="%.2f",
                            value=float(r["price"]) if r.get("price") else None, key=pre + "bprice",
                            help="Updated each time you tick it off with what you actually paid.")
    shop = st.text_input("Where you buy it (optional)", value=r.get("shop") or "", key=pre + "bshop", max_chars=60,
                         placeholder="e.g. Auntie Ama, Dansoman").strip()
    cats = b.category_names("Expense")
    default = r.get("category") or ("Dining Out" if "Dining Out" in cats else (cats[0] if cats else None))
    cat = st.selectbox("Paid under", cats, index=cats.index(default) if default in cats else 0, key=pre + "bcat")
    taken = {v["name"].lower() for i, v in k.recipes.items() if i != rid}
    clash = name.lower() in taken
    if clash:
        field_msg("You already have a dish with this name.")
    row = st.container(horizontal=True)
    if row.button("Save", type="primary", disabled=not name or clash, icon=":material/check:", key=pre + "bsave"):
        new_id = actions.save_bought_dish(rid or None, name, unit, price, shop, cat)
        ss[f"meal_recipe_ver_{rid}"] = ver + 1
        ss["_meal_recipe_next"] = new_id
        flash(f"Saved {name}", ":material/shopping_bag:")
        st.rerun()
    if rid and row.button("Delete", icon=":material/delete:", key=pre + "bdel"):
        def _after():
            st.session_state["_meal_recipe_next"] = NEW
        confirm(f"Delete **{r['name']}**? It comes off any days it's planned for that haven't been bought yet; "
                "days it was already bought stay in the history.",
                actions.recipe_delete_statements(rid, r["name"]), f"Deleted {r['name']}", after=_after)


def _editor(k):
    ss = st.session_state
    options = [NEW] + list(k.recipes)
    if "_meal_recipe_next" in ss:  # set after saving or deleting; a widget's value can only change before it's drawn
        ss["meal_recipe_pick"] = ss.pop("_meal_recipe_next")
    if ss.get("meal_recipe_pick") not in options:
        ss["meal_recipe_pick"] = NEW
    rid = st.selectbox("Recipe", options, key="meal_recipe_pick",
                       format_func=lambda i: "＋ New recipe" if i == NEW else k.recipes[i]["name"])
    r = k.recipes.get(rid, {"name": "", "portions": max(k.household, 1), "keeps_days": 3, "prep_note": "",
                            "prep_hours": None, "method": "", "role": "main"})
    ver = ss.get(f"meal_recipe_ver_{rid}", 0)
    pre = f"meal_r{rid}_{ver}_"

    bought = st.toggle("Bought outside, ready-made", value=bool(r.get("bought")), key=pre + "bought",
                       help="Kenkey, waakye, bread from the corner… No ingredients: you pay for it on the day.")
    if bought:
        _bought_editor(k, rid, r, pre, ver)
        return
    name = st.text_input("Name", value=r["name"], key=pre + "name", max_chars=80,
                         placeholder="e.g. Groundnut soup").strip()
    c1, c2 = st.columns(2)
    portions = c1.number_input("Portions it makes", min_value=0.5, max_value=100.0, value=float(r["portions"]),
                               step=0.5, format="%g", key=pre + "portions")
    keeps = c2.number_input("Keeps in the fridge (days)", 0, 30, int(r["keeps_days"]), key=pre + "keeps")
    roles = list(ROLES)
    role = st.selectbox("Kind of dish", roles, index=roles.index(r.get("role", "main")) if r.get("role") in roles else 4,
                        format_func=ROLES.get, key=pre + "role",
                        help="A starch (kokonte, fufu, banku…) planned with a soup or stew makes one meal, named "
                             "starch first: Kokonte + Palm nut soup.")
    p1, p2 = st.columns([2, 1])
    prep_note = p1.text_input("Prep ahead (optional)", value=r["prep_note"] or "", key=pre + "prep",
                              placeholder="e.g. Soak the beans").strip()
    prep_hours = p2.number_input("Hours before", 0, 72, int(r["prep_hours"] or 0), key=pre + "prep_h",
                                 help="How long before the meal the reminder should show.")

    st.html('<div class="section-title" style="margin-top:.4rem">Ingredients</div>')
    if not len(k.ingredients):
        field_msg("Add ingredients first, under the Ingredients tab.", "hint")
        return
    names = sorted(k.food_names.values(), key=str.lower)  # household supplies never go in a recipe
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
        if base_of(unit) != base_of(k.unit_of[id_of[ing]]) and not (pack and unit == pack[0]) and unit not in alts(pack):
            field_msg(f"{ing} is counted in {k.unit_of[id_of[ing]]} in the pantry, and {unit} doesn't convert to "
                      "that: cooking this recipe can't take it off the pantry, and it won't add up on the shopping "
                      f"list. Use {k.unit_of[id_of[ing]]} here.", "warn")
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
        new_id = actions.save_recipe(rid or None, name, portions, keeps, prep_note, prep_hours, method, clean, role)
        ss[f"meal_recipe_ver_{rid}"] = ver + 1
        ss["_meal_recipe_next"] = new_id
        flash(f"Saved {name}")
        st.rerun()
    if rid and row.button("Delete", icon=":material/delete:", key=pre + "del"):
        def _after():
            st.session_state["_meal_recipe_next"] = NEW
        confirm(f"Delete **{r['name']}**? It comes off any days it's planned for that haven't been cooked yet; "
                "meals already cooked stay in the history.",
                actions.recipe_delete_statements(rid, r["name"]), f"Deleted {r['name']}", after=_after)
    if not ready and not problems:
        field_msg("Add a name and at least one ingredient to save.", "hint")


def _alts_text(k, i, unit):
    """Other units an item can be measured in, e.g. "container = 80 tsp"."""
    pack = k.pack(i)
    return ", ".join(f"{u} = {from_base(v, base_of(unit), unit):g} {plural(unit)}" for u, v in alts(pack).items())


def _ingredients(k):
    ss = st.session_state
    cats = _expense_categories()
    with card("meal-ing-add"):
        section("Add an ingredient")
        name = st.text_input("Name", key="meal_ing_name", max_chars=60, placeholder="e.g. Groundnut paste").strip()
        c1, c2 = st.columns(2)
        unit = c1.selectbox("Base unit (counted and used in)", UNITS, index=UNITS.index("pcs"), key="meal_ing_unit",
                            help="What recipes and the pantry count in: cups of rice, slices of yam, tsp of spice.")
        default_cat = "Staples" if "Staples" in cats else (cats[0] if cats else None)
        cat = c2.selectbox("Money category", cats, index=cats.index(default_cat) if default_cat in cats else 0,
                           key="meal_ing_cat", help="Where its cost is logged when you save a shopping trip.")
        busy = bool(ss.get("meal_ing_pack") or ss.get("meal_ing_low"))
        with st.expander("Bought in a crate, bag or tin? Low-stock warning?", icon=":material/inventory_2:",
                         expanded=busy):
            p1, p2 = st.columns(2)
            pack = p1.selectbox("Purchase unit", [None] + CONTAINERS, key="meal_ing_pack",
                                format_func=lambda x: "Loose / as counted" if x is None else x,
                                help="E.g. eggs in a crate, rice in a bag, oil in a bottle. Then you can say "
                                     "\"2 crates\" and Cashew does the sums.")
            size = p2.number_input(f"1 {pack or 'purchase unit'} = how many {plural(unit)}", min_value=0.0, value=None,
                                   format="%g", key="meal_ing_pack_size", disabled=pack is None,
                                   placeholder="e.g. 30" if unit == "pcs" else "e.g. 5")
            loose_buy = st.checkbox("Also sold loose", key="meal_ing_loose", disabled=pack is None,
                                    help="Like onions: the bag holds 40, but you buy just the 5 you need.")
            low = st.number_input(f"Warn me when stock is down to ({unit})", min_value=0.0, value=None,
                                  key="meal_ing_low", format="%g")
        clash = name.lower() in {n.lower() for n in k.names.values()}
        if clash:
            field_msg(f"{name} is already in your list.")
        if pack and not size:
            field_msg(f"Say how much one {pack} holds, so Cashew can count in {plural(pack)}.", "hint")
        if pack and pack == unit:
            field_msg("Pick a different container from the base unit, or leave it as loose.")
        bad_pack = bool(pack) and (not size or pack == unit)
        if st.button("Add ingredient", type="primary", disabled=not name or clash or bad_pack, key="meal_ing_add",
                     icon=":material/add:"):
            actions.add_ingredient(name, unit, cat, to_base(low, unit)[0] if low else None,
                                   pack, to_base(size, unit)[0] if pack and size else None,
                                   loose=bool(pack and loose_buy))
            for key in ("meal_ing_name", "meal_ing_low", "meal_ing_pack", "meal_ing_pack_size", "meal_ing_loose"):
                ss.pop(key, None)
            flash(f"Added {name}")
            st.rerun()

    with card("meal-ing-list"):
        ing = k.ingredients[k.ingredients["kind"] != "household"]  # supplies are under Meals → Household
        section("Your ingredients", f"{len(ing)}")
        if not len(ing):
            empty("Nothing yet. Add one above, or load the starter recipes.")
            return
        shelves = [x for x in SECTIONS if (ing["section"] == x).any()]
        if shelves:
            shelf = st.pills("Shelf", ["All"] + shelves + ["Other"], key="meal_ing_shelf", default="All",
                             label_visibility="collapsed") or "All"
            if shelf == "Other":
                ing = ing[~ing["section"].isin(SECTIONS)]
            elif shelf != "All":
                ing = ing[ing["section"] == shelf]
        if not len(ing):
            empty("Nothing on this shelf.")
            return
        table = pd.DataFrame({
            "Name": ing["name"], "Unit": ing["unit"], "Category": ing["category"],
            "Bought in": [p if isinstance(p, str) and p else None for p in ing["pack_name"]],
            "Holds": [from_base(float(v), base_of(u), u) if v is not None and not pd.isna(v) else None
                      for v, u in zip(ing["pack_size"], ing["unit"])],
            "Loose": [bool(x) for x in ing["loose"]],
            "Low at": [from_base(float(v), base_of(u), u) if v is not None and not pd.isna(v) else None
                       for v, u in zip(ing["low_level"], ing["unit"])],
            "Other units": [_alts_text(k, int(i), u) for i, u in zip(ing["id"], ing["unit"])],
        })
        table.index = ing["id"].astype(int).tolist()
        ver = ss.get("meal_ing_ver", 0)
        edited = st.data_editor(table, key=f"meal_ing_edit_{ver}_{ss.get('meal_ing_shelf')}", hide_index=True,
                                width="stretch", disabled=["Other units"],
                                column_config={
                                    "Name": st.column_config.TextColumn("Name", required=True),
                                    "Unit": st.column_config.SelectboxColumn("Base unit", options=UNITS, required=True),
                                    "Category": st.column_config.SelectboxColumn("Money category", options=cats),
                                    "Bought in": st.column_config.SelectboxColumn("Purchase unit", options=CONTAINERS,
                                                                                  help="Crate, bag, tin…"),
                                    "Holds": st.column_config.NumberColumn("1 purchase unit = (base units)",
                                                                          min_value=0.0, format="%g"),
                                    "Loose": st.column_config.CheckboxColumn(
                                        "Sold loose", help="Bought by the piece too: the list asks for 5 onions, "
                                                           "not a whole bag"),
                                    "Low at": st.column_config.NumberColumn("Warn when down to", min_value=0.0,
                                                                           format="%g"),
                                    "Other units": st.column_config.TextColumn("Other units"),
                                })
        changed = [i for i in table.index if not table.loc[i].equals(edited.loc[i])]
        if changed:
            names = [str(n).strip().lower() for n in edited["Name"]]
            no_size = [r["Name"] for _, r in edited.iterrows()
                       if isinstance(r["Bought in"], str) and r["Bought in"] and (r["Holds"] is None or pd.isna(r["Holds"])
                                                                                   or r["Holds"] <= 0)]
            for i in changed:  # cups and grams don't convert: say what a unit change leaves behind
                before, after = table.loc[i, "Unit"], edited.loc[i, "Unit"]
                if base_of(before) != base_of(after):
                    stock = k.pantry.get((int(i), base_of(before)), 0)
                    in_recipes = sum(1 for lines in k.items.values() for ing, _, _ in lines if ing == int(i))
                    if stock or in_recipes:
                        field_msg(f"{table.loc[i, 'Name']}: {before} and {after} don't convert, so "
                                  + ", ".join(x for x in (f"its {fmt(stock, base_of(before), before)} in the pantry"
                                                          if stock else "",
                                                          f"{in_recipes} recipe line{'s' if in_recipes != 1 else ''}"
                                                          if in_recipes else "") if x)
                                  + f" will still be in {before}. Update them after saving.", "warn")
            if len(set(names)) != len(names) or "" in names:
                field_msg("Each ingredient needs its own name.")
            elif no_size:
                field_msg("Say how much each purchase unit holds for: " + ", ".join(no_size))
            elif st.button(f"Save {len(changed)} change{'s' if len(changed) != 1 else ''}", type="primary",
                           key="meal_ing_save", icon=":material/check:"):
                for i in changed:
                    row = edited.loc[i]
                    low = row["Low at"]
                    low_base = to_base(float(low), row["Unit"])[0] if low is not None and not pd.isna(low) else None
                    pack = row["Bought in"] if isinstance(row["Bought in"], str) and row["Bought in"] else None
                    size = to_base(float(row["Holds"]), row["Unit"])[0] if pack else None
                    actions.update_ingredient(int(i), str(row["Name"]), row["Unit"], row["Category"], low_base, pack, size,
                                              loose=bool(row["Loose"]) and bool(pack))
                ss["meal_ing_ver"] = ver + 1
                flash("Ingredients saved")
                st.rerun()
        st.caption("Base unit is what recipes and the pantry count in; the purchase unit is what you bring home. "
                   "A tin of Lele Gold milk is 16 tbsp, a bag of A55 rice is 25 cups.")
        unused = [i for i in k.food_names if i not in k.used_ingredients]
        if unused:
            with st.expander("Remove an ingredient"):
                pick = st.selectbox("Not used in any recipe or plan", unused, format_func=lambda i: k.names[i],
                                    key="meal_ing_del")
                if st.button("Remove", key="meal_ing_del_go", icon=":material/delete:"):
                    confirm(f"Remove **{k.names[pick]}**? Its pantry stock and prices go too. Meals it was part "
                            "of stay in the history.",
                            actions.ingredient_delete_statements(pick, k.names[pick]), f"Removed {k.names[pick]}",
                            button="Remove")


def _pairing_text(k, p):
    out = []
    for part in p["parts"]:
        if part.get("recipe_id"):
            out.append(k.recipes[part["recipe_id"]]["name"])
        else:
            out.append(f"{k.names.get(part['ingredient_id'], '?')} ({frac(part['qty'])} {plural(part['unit'], part['qty'])} "
                       "a person)")
    return " + ".join(out)


def _pairings(k):
    """Ready-made meals for the planner, like Kokonte + Palm nut soup."""
    ss = st.session_state
    left, right = st.columns([3, 2], gap="medium")
    with left, card("meal-pairings"):
        section("Pairings", f"{len(k.pairings)}")
        if not k.pairings:
            empty("No pairings yet. Make one on this page.")
        rows = []
        for p in k.pairings.values():
            parts = _pairing_text(k, p)  # only worth showing when it says more than the name
            meta = f'<div class="rule-meta">{esc(parts)}</div>' if parts.lower() != p["name"].lower() else ""
            rows.append(f'<div class="rule"><div style="min-width:0"><div class="rule-name">🍲 {esc(p["name"])}</div>'
                        f'{meta}</div></div>')
        st.html("".join(rows))
        st.caption("Pick one under Meals → Plan → Dishes. It's planned as one meal: the starch is cooked fresh, and "
                   "the soup comes from the fridge when this week's pot is already there.")
    with right:
        with card("meal-pairing-new"):
            section("Make a pairing")
            ver = ss.get("meal_pair_ver", 0)
            dishes = [i for i, r in sorted(k.recipes.items(), key=lambda x: (x[1]["role"] != "starch", x[1]["name"].lower()))
                      if not r["bought"]]
            picked = st.multiselect("Dishes eaten together", dishes, key=f"meal_pair_dishes_{ver}",
                                    format_func=lambda i: k.recipes[i]["name"], placeholder="e.g. Banku, Okra soup")
            side = st.selectbox("Eaten with (optional)", [None] + sorted(k.food_names, key=lambda i: k.food_names[i].lower()),
                                format_func=lambda i: "Nothing else" if i is None else k.food_names[i],
                                key=f"meal_pair_side_{ver}")
            side_qty = side_unit = None
            if side:
                c1, c2 = st.columns(2)
                side_qty = c1.number_input("How much a person", min_value=0.0, value=0.5, step=0.25, format="%g",
                                           key=f"meal_pair_sq_{ver}")
                from meals.units import units_for
                side_unit = c2.selectbox("Unit", units_for(k.unit_of[side], k.pack(side)), key=f"meal_pair_su_{ver}")
            fake = [{"recipe_id": i, "id": n} for n, i in enumerate(picked)] + (
                [{"ingredient_id": side, "id": 99}] if side else [])
            auto = k.meal_name(fake) if fake else ""
            name = st.text_input("Name", key=f"meal_pair_name_{ver}", max_chars=120, placeholder=auto or "e.g. Banku + Okra soup")
            final = (name or auto).strip()
            clash = final.lower() in {p["name"].lower() for p in k.pairings.values()}
            if clash:
                field_msg("You already have a pairing with this name.")
            if st.button("Save pairing", type="primary", disabled=len(picked) + bool(side) < 2 or clash or not final,
                         key="meal_pair_save", icon=":material/check:"):
                actions.save_pairing(None, final, picked, (side, side_qty, side_unit) if side and side_qty else None)
                ss["meal_pair_ver"] = ver + 1
                flash(f"Saved {final}", ":material/restaurant:")
                st.rerun()
            if len(picked) + bool(side) < 2:
                field_msg("Pick at least two things eaten together.", "hint")
        if k.pairings:
            with card("meal-pairing-del"):
                section("Remove a pairing")
                pick = st.selectbox("Pairing", list(k.pairings), format_func=lambda i: k.pairings[i]["name"],
                                    key="meal_pair_del", label_visibility="collapsed")
                if st.button("Remove", key="meal_pair_del_go", icon=":material/delete:"):
                    confirm(f"Remove **{k.pairings[pick]['name']}**? Its dishes stay in the recipe book.",
                            [("DELETE FROM meals.pairings WHERE id = %s", (pick,))], f"Removed {k.pairings[pick]['name']}",
                            button="Remove")
        with card("meal-catalog"):
            section("Ghanaian kitchen catalog")
            st.caption("Everyday ingredients with their purchase units, six soup and stew templates for a week, "
                       "the starches, and the pairings above. Anything you deleted can be added back here; "
                       "nothing you changed is touched.")
            if st.button("Add back anything missing", key="meal_catalog_go", icon=":material/library_add:"):
                recipes, pairings = actions.load_catalog()
                flash(f"Catalog checked: {recipes} recipe{'s' if recipes != 1 else ''} and {pairings} "
                      f"pairing{'s' if pairings != 1 else ''} added back", ":material/library_add:")
                st.rerun()


def render():
    k = kitchen()
    page_header("Recipes", "Your recipe book, the ingredients it uses, and the pairings you plan with")
    tab_r, tab_i, tab_p = st.tabs(["Recipes", "Ingredients", "Pairings"])
    with tab_r:
        starter_names = {r[0].lower() for r in STARTER_RECIPES}
        if not starter_names & {r["name"].lower() for r in k.recipes.values()}:
            with card("meal-starter"):
                section("Add the everyday starter dishes")
                st.write("Six everyday dishes (jollof, red red, kontomire stew, okro stew with banku, light soup with "
                         "chicken, and bread with eggs) with their ingredients. Change anything to suit how you cook.")
                if st.button("Add starter recipes", type="primary", icon=":material/menu_book:", key="meal_starter"):
                    n = transact(lambda conn: load_starter(conn, _expense_categories()))
                    invalidate()
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
    with tab_p:
        _pairings(k)

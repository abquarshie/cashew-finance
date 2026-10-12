from datetime import date, datetime, timedelta

import streamlit as st

from meals import actions
from meals.data import kitchen
import pandas as pd

from core.data import book as money_book
from core.data import money
from meals.logic import OPEN, SLOTS, cost_of, recipe_cost, reminders, shopping_list, suggest, total_needs
from meals.units import fmt, units_for, plural, to_base
from ui.components import card, empty, esc, field_msg, flash, page_header, pill
from ui.nav import go

WEEKS = {-1: "Last week", 0: "This week", 1: "Next week", 2: "In 2 weeks"}
DONE_LABEL = {"cooked": "Cooked", "from_fridge": "From the fridge", "done": "Eaten"}


def _next_slot(now=None):
    h = (now or datetime.now()).hour
    return "Breakfast" if h < 10 else ("Lunch" if h < 15 else "Supper")


def _week_start():
    off = st.session_state.get("meal_week", 0) or 0
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=off)


def _toggle(entry_id, kind, status):
    """The checkbox next to a planned dish: ticking it means cooked (or eaten, for a plain item)."""
    k = kitchen()
    if status != OPEN:
        actions.untick(entry_id)
        flash("Unticked. The pantry and fridge are back as they were.", ":material/undo:")
        return
    if kind == "recipe":
        short = actions.mark_cooked(entry_id, k.household)
        e = next((x for x in k.plan if x["id"] == entry_id), None)
        left = max(e["qty"] - min(k.household, e["qty"]), 0) if e else 0
        msg = "Cooked" + (f". {left:g} portion{'s' if left != 1 else ''} put in the fridge." if left else ".")
        flash(msg, ":material/skillet:")
        if short:
            flash("Not in the pantry, so not taken off: " + actions.describe_short(short, k.names) +
                  ". Update the pantry if you had them.", ":material/warning:")
    else:
        actions.mark_done(entry_id)
        flash("Ticked off", ":material/check:")


def _from_fridge(entry_id):
    k = kitchen()
    missing = actions.mark_from_fridge(entry_id, k.household)
    flash("Eaten from the fridge" + (f" ({missing:g} portions short)" if missing else ""), ":material/kitchen:")


def _remove(entry_id):
    actions.remove_from_plan(entry_id)
    flash("Removed from the plan", ":material/delete:")


def _entry_row(k, e, today):
    kind = "recipe" if e["recipe_id"] else "item"
    name = k.entry_name(e)
    if kind == "recipe":
        detail = f"{e['qty']:g} portions"
    else:
        pack = k.pack(e["ingredient_id"])
        unit = e["unit"] or "pcs"
        detail = f"{e['qty']:g} {plural(unit, e['qty'])}" if pack and unit == pack[0] else fmt(*to_base(e["qty"], unit))
    done = e["status"] != OPEN
    label = f"{name} · {detail}" + (f" · {DONE_LABEL[e['status']]}" if done else "")
    row = st.container(horizontal=True, vertical_alignment="center", key=f"meal-entry-{e['id']}")
    row.checkbox(label, value=done, key=f"meal_e{e['id']}_{e['status']}", on_change=_toggle,
                 args=(e["id"], kind, e["status"]), width="stretch",
                 help="Tick when it's cooked (or eaten, for fruit and other items). Untick to undo.")
    if not done and kind == "recipe":
        have = k.fridge_portions(e["recipe_id"], today)
        if have > 0:
            row.button(f"Fridge ({have:g})", key=f"meal_ff_{e['id']}", type="tertiary", icon=":material/kitchen:",
                       on_click=_from_fridge, args=(e["id"],), help="Eat leftovers instead of cooking")
    row.button("", key=f"meal_rm_{e['id']}", type="tertiary", icon=":material/close:", on_click=_remove,
               args=(e["id"],), help="Remove from the plan")


@st.fragment
def _add_form(start):
    ss = st.session_state
    k = kitchen()
    days = [start + timedelta(days=i) for i in range(7)]
    today = date.today()
    if ss.get("meal_add_day") not in days:
        ss["meal_add_day"] = today if today in days else days[0]
    ss.setdefault("meal_add_slot", _next_slot())
    st.pills("Day", days, key="meal_add_day", format_func=lambda d: "Today" if d == today else f"{d:%a %d}")
    st.pills("Meal", SLOTS, key="meal_add_slot")
    what = st.segmented_control("What", ["Recipe", "Fruit or other item"], default="Recipe", key="meal_add_what",
                                label_visibility="collapsed") or "Recipe"
    day, slot = ss.get("meal_add_day") or days[0], ss.get("meal_add_slot") or "Supper"

    if what == "Recipe":
        if not k.recipes:
            field_msg("Add a recipe first, under Meals → Recipes.", "hint")
            go("meals", "Recipes", label="Open recipes", icon=":material/menu_book:")
            return
        rid = st.selectbox("Recipe", list(k.recipes), index=None, placeholder="Choose a dish",
                           format_func=lambda i: k.recipes[i]["name"], key="meal_add_recipe")
        portions = st.number_input("Portions to cook", 1, 100,
                                   int(k.recipes[rid]["portions"]) if rid else max(k.household, 1),
                                   key=f"meal_add_portions_{rid}")
        if rid:
            batch, each, unknown = recipe_cost(rid, k.recipes, k.items, k.prices, k.packs)
            if batch:
                field_msg(f"{'At least' if unknown else 'About'} {money(each)} a portion, "
                          f"{money(each * portions)} for {portions}.", "hint")
            have = k.fridge_portions(rid)
            if have:
                field_msg(f"There are {have:g} portions of this in the fridge already.", "hint")
            left = portions - min(k.household, portions)
            if left > 0:
                field_msg(f"{k.household} eat at the meal; {left:g} portion{'s' if left != 1 else ''} will go into "
                          "the fridge.", "hint")
        ok = rid is not None
        args = dict(recipe_id=rid, qty=portions)
    else:
        if not k.names:
            field_msg("Add ingredients first, under Meals → Recipes.", "hint")
            return
        ing = st.selectbox("Item", list(k.names), index=None, placeholder="e.g. Bananas",
                           format_func=lambda i: k.names[i], key="meal_add_item")
        c1, c2 = st.columns(2)
        qty = c1.number_input("How much", min_value=0.0, value=None, placeholder="0", key="meal_add_qty", format="%g")
        units = units_for(k.unit_of[ing], k.pack(ing)) if ing else ["pcs"]
        unit = c2.selectbox("Unit", units, key=f"meal_add_unit_{ing}")
        ok = ing is not None and bool(qty)
        args = dict(ingredient_id=ing, qty=qty or 0, unit=unit)

    when = "today" if day == today else f"{day:%a %d}"
    if st.button(f"Add to {when}, {slot.lower()}", type="primary", disabled=not ok, width="stretch",
                 key="meal_add_go", icon=":material/add:"):
        actions.add_to_plan(day, slot, **args)
        ss.pop("meal_add_recipe", None)
        ss.pop("meal_add_item", None)
        ss.pop("meal_add_qty", None)
        flash(f"Added to {when}, {slot.lower()}")
        st.rerun()


def render():
    ss = st.session_state
    k = kitchen()
    if ss.get("meal_week") not in WEEKS:
        ss["meal_week"] = 0
    start = _week_start()
    end = start + timedelta(days=6)
    page_header("Meal plan", f"{start:%a %d %b} to {end:%a %d %b} · {k.household} people per meal")
    st.segmented_control("Week", list(WEEKS), key="meal_week", format_func=WEEKS.get, label_visibility="collapsed")
    start = _week_start()
    today = date.today()

    _copy_offer(k, start, today)
    if start <= today <= start + timedelta(days=6):
        _reminders(k, today)
    _week_cost(k, start, today)

    days_col, add_col = st.columns([3, 2], gap="medium")  # on a phone the days come first, the form after
    with days_col:
        days = [start + timedelta(days=i) for i in range(7)]
        past = [d for d in days if d < today]
        if past:  # days already gone fold away, so today is at the top
            n = len(k.entries(past[0], past[-1]))
            with st.expander(f"Earlier this week ({past[0]:%a} to {past[-1]:%a}, {n} meal{'s' if n != 1 else ''})",
                             icon=":material/history:"):
                for d in past:
                    _day_card(k, d, today)
        for d in days:
            if d >= today:
                _day_card(k, d, today)
    with add_col:
        with card("meal-add"):
            st.html('<div class="section-title">Add to the plan</div>')
            _add_form(start)
        _suggestions(k, today)


def _reminders(k, today):
    """Soak the beans, defrost the fish, eat the leftovers: what needs doing today and tomorrow."""
    notes = reminders(datetime.now(), k.entries(today, today + timedelta(days=1)), k.recipes, k.items, k.pantry,
                      k.fridge, k.names, k.household, packs=k.packs)
    for tone, text in notes:
        field_msg(text, {"warn": "warn", "info": "hint", "ok": "ok"}[tone])


def _copy_offer(k, start, today):
    """Most weeks look like the last one: copy it in one tap, then change what's different."""
    if start + timedelta(days=6) < today:
        return
    have = {(e["day"], e["slot"]) for e in k.entries(start, start + timedelta(days=6))}
    prev = k.entries(start - timedelta(days=7), start - timedelta(days=1))
    fits = [e for e in prev if e["day"] + timedelta(days=7) >= today
            and (e["day"] + timedelta(days=7), e["slot"]) not in have]
    if not fits:
        return
    n = len(fits)
    label = (f"Copy the week before ({n} meal{'s' if n != 1 else ''})" if not have else
             f"Fill the empty meals from the week before ({n})")
    if st.button(label, icon=":material/content_copy:", key="meal_copy", width="stretch",
                 type="primary" if not have else "secondary",
                 help="Meals you've already planned this week stay as they are."):
        copied = actions.copy_week(start - timedelta(days=7), start, not_before=today)
        flash(f"Copied {copied} meal{'s' if copied != 1 else ''}. Change anything that's different this week.",
              ":material/content_copy:")
        st.rerun()


def _day_card(k, d, today):
    entries = k.entries(d)
    with card(f"meal-day-{d:%Y%m%d}"):
        tag = pill("Today", "accent") if d == today else ""
        st.html(f'<div class="section"><span class="section-title">{d:%A %d %b}</span>{tag}</div>')
        if not entries:
            empty("Nothing planned.")
            return
        for slot in SLOTS:
            slot_entries = [e for e in entries if e["slot"] == slot]
            if not slot_entries:
                continue
            st.html(f'<div class="meal-slot">{esc(slot)}</div>')
            for e in slot_entries:
                _entry_row(k, e, today)


def _food_budget_left(cats, today):
    """What's left this month in the budgets that cover the kitchen's money categories."""
    b = money_book()
    status = b.budget_status(pd.Period(today, "M"))
    groups = {b.group_of.get(c) for c in cats}
    covered, left, names = set(), 0.0, []
    for s_ in status:
        if s_["is_group"] and s_["name"] in groups:
            left += max(s_["limit"] - s_["spent"], 0)
            covered.add(s_["name"])
            names.append(s_["name"])
    for s_ in status:
        if not s_["is_group"] and s_["name"] in cats and b.group_of.get(s_["name"]) not in covered:
            left += max(s_["limit"] - s_["spent"], 0)
            names.append(s_["name"])
    return (left, names) if names else (None, [])


def _week_cost(k, start, today):
    """What the rest of the week's meals cost, what's still to buy, and how that sits against the Food budget."""
    first = max(start, today)
    end = start + timedelta(days=6)
    entries = k.open_entries(first, end)
    if not entries:
        return
    needs = total_needs(entries, k.recipes, k.items, packs=k.packs)
    meals_cost, unknown = cost_of(needs, k.prices)
    to_buy = shopping_list(needs, k.pantry, prices=k.prices, packs=k.packs)
    buy_cost = sum(r["est"] or 0 for r in to_buy)
    buy_unknown = sum(1 for r in to_buy if r["est"] is None)
    if not meals_cost and not buy_cost:
        st.caption("Costs show here once you've saved a shopping trip and Cashew knows your prices.")
        return
    cats = {k.category_of.get(r["ingredient_id"]) for r in to_buy} | set(k.category_of.values())
    left, names = _food_budget_left({c for c in cats if c}, today)
    n = len(entries)
    parts = [f"<b>{n} meal{'s' if n != 1 else ''}</b> still to cook {'this week' if start <= today else 'that week'}: "
             f"about <b>{money(meals_cost)}</b> of ingredients"
             + (f" (no price yet for {unknown})" if unknown else "") + "."]
    if to_buy:
        parts.append(f"Still to buy: about <b>{money(buy_cost)}</b>"
                     + (f" plus {buy_unknown} item{'s' if buy_unknown != 1 else ''} with no price yet" if buy_unknown else "")
                     + ".")
    tone = "hint"
    if left is not None:
        parts.append(f"{' and '.join(names)} budget left this month: <b>{money(left)}</b>.")
        if buy_cost > left:
            tone = "warn"
            parts.append("The shopping would take you over, so consider swapping a dish.")
    st.html(f'<div class="week-cost {tone}">{" ".join(parts)}</div>')


def _add_suggestion(rid):
    ss = st.session_state
    k = kitchen()
    day = ss.get("meal_add_day") or date.today()
    slot = ss.get("meal_add_slot") or _next_slot()
    actions.add_to_plan(day, slot, recipe_id=rid, qty=k.recipes[rid]["portions"])
    flash(f"Added {k.recipes[rid]['name']} to {'today' if day == date.today() else f'{day:%a %d}'}, {slot.lower()}")


def _suggestions(k, today):
    if not k.recipes:
        return
    recent = [e for e in k.plan if e["day"] >= today - timedelta(days=21)]
    ideas = suggest(k.recipes, k.items, k.pantry, k.fridge, recent, today, packs=k.packs)
    if not ideas:
        return
    ss = st.session_state
    day = ss.get("meal_add_day") or today
    slot = (ss.get("meal_add_slot") or _next_slot()).lower()
    when = "today" if day == today else f"{day:%a %d}"
    with card("meal-ideas"):
        st.html('<div class="section-title">Ideas to use things up</div>')
        for idea in ideas:
            rid = idea["recipe_id"]
            row = st.container(horizontal=True, vertical_alignment="center", key=f"meal-idea-{rid}")
            why = "; ".join(idea["reasons"]).capitalize()
            row.html(f'<div style="min-width:0"><div class="rule-name">{esc(k.recipes[rid]["name"])}</div>'
                     f'<div class="rule-meta">{esc(why)}</div></div>', width="stretch")
            row.button("Add", key=f"meal_idea_add_{rid}", icon=":material/add:", on_click=_add_suggestion, args=(rid,),
                       help=f"Add to {when}, {slot}")
        st.caption(f"Add puts it on {when}, {slot}: the day and meal picked above.")

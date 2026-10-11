from datetime import date, datetime, timedelta

import streamlit as st

from meals import actions
from meals.data import kitchen
from meals.logic import OPEN, SLOTS
from meals.units import UNITS, fmt, to_base
from ui.components import card, empty, esc, field_msg, flash, page_header, pill
from ui.nav import link

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
        detail = fmt(*to_base(e["qty"], e["unit"] or "pcs"))
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
            field_msg("Add a recipe first, on the Recipes page.", "hint")
            st.page_link(link("recipes"), label="Open recipes", icon=":material/menu_book:")
            return
        rid = st.selectbox("Recipe", list(k.recipes), index=None, placeholder="Choose a dish",
                           format_func=lambda i: k.recipes[i]["name"], key="meal_add_recipe")
        portions = st.number_input("Portions to cook", 1, 100,
                                   int(k.recipes[rid]["portions"]) if rid else max(k.household, 1),
                                   key=f"meal_add_portions_{rid}")
        if rid:
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
            field_msg("Add ingredients first, on the Recipes page.", "hint")
            return
        ing = st.selectbox("Item", list(k.names), index=None, placeholder="e.g. Bananas",
                           format_func=lambda i: k.names[i], key="meal_add_item")
        c1, c2 = st.columns(2)
        qty = c1.number_input("How much", min_value=0.0, value=None, placeholder="0", key="meal_add_qty", format="%g")
        units = UNITS
        unit = c2.selectbox("Unit", units, index=units.index(k.unit_of[ing]) if ing else units.index("pcs"),
                            key=f"meal_add_unit_{ing}")
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

    left, right = st.columns([2, 3], gap="medium")
    with left:
        with card("meal-add"):
            st.html('<div class="section-title">Add to the plan</div>')
            _add_form(start)
        week = k.entries(start, start + timedelta(days=6))
        if not week:
            prev = k.entries(start - timedelta(days=7), start - timedelta(days=1))
            if prev and st.button(f"Copy the week before ({len(prev)} meals)", icon=":material/content_copy:",
                                  key="meal_copy"):
                n = actions.copy_week(start - timedelta(days=7), start)
                flash(f"Copied {n} meals")
                st.rerun()
    with right:
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

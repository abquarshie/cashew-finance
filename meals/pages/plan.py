from datetime import date, datetime, timedelta

import streamlit as st

from core.data import book as money_book
from core.data import money
from meals import actions
from meals.briefing import entry_status, guard
from meals.data import kitchen
from meals.logic import (OPEN, SLOTS, cost_of, recipe_cost, repeat_plan, shopping_list, shortfall, suggest,
                          total_needs)
from meals.units import QUICK, fmt, frac, plural, to_base, units_for
from meals.widget import today_card
from ui.components import card, empty, esc, field_msg, flash, page_header, pill
from ui.nav import go

VIEWS = ["Next 2 weeks", "Past 2 weeks"]
DONE_LABEL = {"cooked": "Cooked", "from_fridge": "From the fridge", "done": "Eaten"}
SPANS = ["Next 7 days", "Days 8 to 14"]


def _next_slot(now=None):
    h = (now or datetime.now()).hour
    return "Breakfast" if h < 10 else ("Lunch" if h < 15 else "Supper")


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
        detail = f"{frac(e['qty'])} {plural('portion', e['qty'])}"
    else:
        unit = e["unit"] or "pcs"
        detail = fmt(*to_base(e["qty"], unit))  # 1.5 kg, 2½ bunches, ½ crate
    done = e["status"] != OPEN
    if done:
        label = f"{name} · {detail} · {DONE_LABEL[e['status']]}"
    elif e["day"] >= today:
        status, _ = entry_status(k, e, today)
        m = k.meal_status(e["id"], today) or {}
        short = len(m.get("missing", []))
        tag = {"ready": "✅", "leftovers": "🥡 fridge", "short": f"🛒 {short} to buy"}.get(status, "")
        label = f"{name} · {detail} {tag}".rstrip()
    else:
        label = f"{name} · {detail}"
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


def _quick_qty():
    q = st.session_state.get("meal_add_quick")
    if q is not None:
        st.session_state["meal_add_qty"] = float(q)
    st.session_state["meal_add_quick"] = None


@st.fragment
def _add_form():
    ss = st.session_state
    k = kitchen()
    today = date.today()
    span = st.segmented_control("Days", SPANS, default=SPANS[0], key="meal_add_span", required=True,
                                label_visibility="collapsed")
    first = today + timedelta(days=0 if span == SPANS[0] else 7)
    days = [first + timedelta(days=i) for i in range(7)]
    if ss.get("meal_add_day") not in days:
        ss["meal_add_day"] = days[0]
    ss.setdefault("meal_add_slot", _next_slot())
    st.pills("Day", days, key="meal_add_day", required=True, format_func=lambda d: "Today" if d == today else (
        "Tomorrow" if d == today + timedelta(days=1) else f"{d:%a %d}"))
    st.pills("Meal", SLOTS, key="meal_add_slot", required=True)  # tapping the picked one again keeps it
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
        portions = st.number_input("Portions to cook", min_value=0.25, max_value=100.0, step=0.5, format="%g",
                                   value=float(k.recipes[rid]["portions"]) if rid else float(max(k.household, 1)),
                                   key=f"meal_add_portions_{rid}", help="Halves and quarters are fine: 2.5, 0.5…")
        if rid:
            batch, each, unknown = recipe_cost(rid, k.recipes, k.items, k.prices, k.packs)
            if batch:
                field_msg(f"{'At least' if unknown else 'About'} {money(each)} a portion, "
                          f"{money(each * portions)} for {frac(portions)}.", "hint")
            have = k.fridge_portions(rid)
            if have:
                field_msg(f"There are {frac(have)} portions of this in the fridge already.", "hint")
            left = portions - min(k.household, portions)
            if left > 0:
                field_msg(f"{k.household} eat at the meal; {frac(left)} {plural('portion', left)} will go into "
                          "the fridge.", "hint")
        ok = rid is not None
        args = dict(recipe_id=rid, qty=portions)
    else:
        if not k.names:
            field_msg("Add ingredients first, under Meals → Recipes.", "hint")
            return
        ing = st.selectbox("Item", list(k.names), index=None, placeholder="e.g. Bananas",
                           format_func=lambda i: k.names[i], key="meal_add_item")
        st.pills("Quick amount", QUICK, key="meal_add_quick", format_func=frac, on_change=_quick_qty,
                 label_visibility="collapsed")
        c1, c2 = st.columns(2)
        qty = c1.number_input("How much", min_value=0.0, value=None, step=0.25, placeholder="0", key="meal_add_qty",
                              format="%g")
        units = units_for(k.unit_of[ing], k.pack(ing)) if ing else ["pcs"]
        unit = c2.selectbox("Unit", units, key=f"meal_add_unit_{ing}")
        ok = ing is not None and bool(qty)
        args = dict(ingredient_id=ing, qty=qty or 0, unit=unit)

    when = "today" if day == today else ("tomorrow" if day == today + timedelta(days=1) else f"{day:%a %d}")
    if st.button(f"Add to {when}, {slot.lower()}", type="primary", disabled=not ok, width="stretch",
                 key="meal_add_go", icon=":material/add:"):
        actions.add_to_plan(day, slot, **args)
        ss.pop("meal_add_recipe", None)
        ss.pop("meal_add_item", None)
        ss.pop("meal_add_qty", None)
        flash(f"Added to {when}, {slot.lower()}")
        st.rerun()


def render():
    k = kitchen()
    today = date.today()
    start, end = k.window(today)
    page_header("Meal plan", f"Today to {end:%a %d %b} · {k.household} people per meal")
    view = st.segmented_control("Show", VIEWS, default=VIEWS[0], key="meal_view", required=True,
                                label_visibility="collapsed")
    if view == VIEWS[1]:
        st.caption("Tick anything that was cooked but never ticked off, so the pantry stays right.")
        for i in range(1, 15):
            _day_card(k, today - timedelta(days=i), today)
        return

    today_card(link_to_plan=False)
    _copy_offer(k, today)
    _cost_line(k, today)

    days_col, add_col = st.columns([3, 2], gap="medium")  # on a phone the days come first, the form after
    with days_col:
        monday = today - timedelta(days=today.weekday())
        past = [monday + timedelta(days=i) for i in range(today.weekday())]
        if past and k.entries(past[0], past[-1]):  # earlier this week folds away, so today is at the top
            n = len(k.entries(past[0], past[-1]))
            with st.expander(f"Earlier this week ({past[0]:%a} to {past[-1]:%a}, {n} meal{'s' if n != 1 else ''})",
                             icon=":material/history:"):
                for d in past:
                    _day_card(k, d, today)
        days = [start + timedelta(days=i) for i in range(k.HORIZON)]
        weeks = {}
        for d in days:
            weeks.setdefault(d - timedelta(days=d.weekday()), []).append(d)
        for i, (wk, wdays) in enumerate(weeks.items()):
            name = "This week" if wk == monday else ("Next week" if wk == monday + timedelta(days=7) else "Week after")
            n = len([e for e in k.entries(wdays[0], wdays[-1])])
            head = f"{name} · {wdays[0]:%a %d} to {wdays[-1]:%a %d %b} · {n} meal{'s' if n != 1 else ''}"
            if i == 0:
                st.html(f'<div class="week-head">{esc(head)}</div>')
                for d in wdays:
                    _day_card(k, d, today)
            else:
                with st.expander(head, icon=":material/date_range:"):
                    for d in wdays:
                        _day_card(k, d, today)
    with add_col:
        with card("meal-add"):
            st.html('<div class="section-title">Add to the plan</div>')
            _add_form()
        _suggestions(k, today)


def _copy_offer(k, today):
    """Most weeks look like the one before: repeat it into the empty meals of the next two weeks."""
    start, end = k.window(today)
    new = repeat_plan(k.plan, today, k.HORIZON)
    if not new:
        return
    n = len(new)
    first_time = not k.entries(start, end)
    label = (f"Copy the week before ({n} meal{'s' if n != 1 else ''})" if first_time else
             f"Fill the empty meals from the week before ({n})")
    if st.button(label, icon=":material/content_copy:", key="meal_copy", width="stretch",
                 type="primary" if first_time else "secondary",
                 help="Each empty breakfast, lunch or supper in the next two weeks gets what was planned 7 days "
                      "earlier. Meals already planned stay as they are."):
        copied = actions.add_many(new)
        flash(f"Copied {copied} meal{'s' if copied != 1 else ''}. Change anything that's different.",
              ":material/content_copy:")
        st.rerun()


def _day_card(k, d, today):
    entries = k.entries(d)
    with card(f"meal-day-{d:%Y%m%d}"):
        tag = pill("Today", "accent") if d == today else (pill("Tomorrow", "neutral")
                                                           if d == today + timedelta(days=1) else "")
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


def _cost_line(k, today):
    """What the next two weeks' meals cost, what's still to buy, and the food budget guard."""
    start, end = k.window(today)
    entries = k.open_entries(start, end)
    if not entries:
        return
    needs = total_needs(entries, k.recipes, k.items, packs=k.packs)
    meals_cost, unknown = cost_of(needs, k.prices)
    to_buy = shopping_list(shortfall(k.allocation(today), entries), {}, prices=k.prices, packs=k.packs)
    buy_cost = sum(r["est"] or 0 for r in to_buy)
    buy_unknown = sum(1 for r in to_buy if r["est"] is None)
    n = len(entries)
    if not meals_cost and not buy_cost:
        st.caption("Costs show here once you've saved a shopping trip and Cashew knows your prices.")
    else:
        parts = [f"<b>{n} meal{'s' if n != 1 else ''}</b> still to cook in the next two weeks: "
                 f"about <b>{money(meals_cost)}</b> of ingredients"
                 + (f" (no price yet for {unknown})" if unknown else "") + "."]
        if to_buy:
            parts.append(f"After what's in the pantry and fridge, still to buy: about <b>{money(buy_cost)}</b>"
                         + (f" plus {buy_unknown} item{'s' if buy_unknown != 1 else ''} with no price yet"
                            if buy_unknown else "") + ".")
        else:
            parts.append("Everything is already in the pantry or fridge.")
        st.html(f'<div class="week-cost hint">{" ".join(parts)}</div>')
    g = guard(k, money_book(), today)
    if g:
        field_msg(g[1], g[0])


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

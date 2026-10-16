from datetime import date, datetime, timedelta

import streamlit as st

from core.data import book as money_book
from core.data import CURRENCY, money
from meals import actions
from meals.briefing import entry_status, guard
from meals.data import kitchen
from meals.briefing import meal_state
from meals.logic import (OPEN, SLOTS, bought_cost, cost_of, from_leftovers, recipe_cost, repeat_plan, shopping_list,
                          shortfall, suggest, total_needs)
from meals.units import fmt, frac, plural, to_base, units_for
from meals.widget import today_card
from ui.components import card, empty, esc, field_msg, flash, page_header, pill
from ui.nav import go

VIEWS = ["Next 2 weeks", "Past 2 weeks"]
DONE_LABEL = {"cooked": "Cooked", "from_fridge": "From the fridge", "done": "Eaten", "bought": "Bought"}
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
        keeps = k.recipes.get(e["recipe_id"], {}).get("keeps_days", 3) if e else 3
        if left and e and e["day"] + timedelta(days=keeps) < date.today():
            msg = "Cooked. It was too long ago for leftovers to still be good, so nothing went into the fridge."
        else:
            msg = "Cooked" + (f". {left:g} portion{'s' if left != 1 else ''} put in the fridge." if left else ".")
        flash(msg, ":material/skillet:")
        if short:
            flash("Not in the pantry, so not taken off: " + actions.describe_short(short, k.names, k.unit_of) +
                  ". Update the pantry if you had them.", ":material/warning:")
    else:
        actions.mark_done(entry_id)
        flash("Ticked off", ":material/check:")


def _toggle_meal(ids, done):
    """The one tick box for a meal of several dishes (Kokonte + Palm nut soup)."""
    k = kitchen()
    if done:
        actions.untick_meal(list(ids))
        flash("Unticked. The pantry, fridge and any payment are back as they were.", ":material/undo:")
        return
    out = actions.mark_meal(list(ids), k.household)
    bits = []
    if out["cooked"]:
        bits.append("cooked " + " and ".join(out["cooked"]))
    if out["fridge"]:
        bits.append(" and ".join(out["fridge"]) + " from the fridge")
    flash(("Ticked off: " + "; ".join(bits) + ".") if bits else "Ticked off.", ":material/skillet:")
    if out["short"]:
        flash("Not in the pantry, so not taken off: " + actions.describe_short(out["short"], k.names, k.unit_of) +
              ". Update the pantry if you had them.", ":material/warning:")


def _from_fridge(entry_id):
    k = kitchen()
    missing = actions.mark_from_fridge(entry_id, k.household)
    flash("Eaten from the fridge" + (f" ({missing:g} portions short)" if missing else ""), ":material/kitchen:")


def _remove(entry_id):
    actions.remove_from_plan(list(entry_id) if isinstance(entry_id, tuple) else entry_id)
    flash("Removed from the plan", ":material/delete:")


def _detail(k, e):
    if k.is_bought(e):
        _, unit = k.bought_price(e)
        return f"{frac(e['qty'])} {plural(unit, e['qty'])}"
    if e["recipe_id"]:
        return f"{frac(e['qty'])} {plural('portion', e['qty'])}"
    return fmt(*to_base(e["qty"], e["unit"] or "pcs"), e["unit"])  # 1.5 kg, 2½ bunches, ½ crate, 1 cup


def _food_category(k, b, e):
    """Where a payment for bought food is logged: the dish's own category, else Dining Out, else any food one."""
    cats = b.category_names("Expense")
    own = k.recipes.get(e.get("recipe_id"), {}).get("category") if e.get("recipe_id") else None
    for c in (own, "Dining Out", *sorted(k.food_categories)):
        if c and c in cats:
            return c
    return cats[0] if cats else None


@st.dialog("Bought it", width="small")
def _pay(entry_id):
    """Ticking bought food: what was paid and from which account. It's saved as one expense, even when a meal
    has several bought dishes (kenkey and fried fish)."""
    k, b = kitchen(), money_book()
    ids = list(entry_id) if isinstance(entry_id, tuple) else [entry_id]
    entries = [e for e in k.plan if e["id"] in ids and e["status"] == OPEN]
    if not entries:
        st.rerun()
    expected, known = 0.0, True
    for e in entries:
        price, _ = k.bought_price(e)
        known = known and bool(price)
        expected += float(price or 0) * float(e["qty"])
    sig = "_".join(str(i) for i in ids)
    st.markdown(" + ".join(f"**{k.entry_name(e)}** · {_detail(k, e)}" for e in entries))
    paid = st.number_input(f"Paid ({CURRENCY})", min_value=0.0, step=1.0, format="%.2f", key=f"meal_pay_amt_{sig}",
                           value=round(expected, 2) if known and expected else None, placeholder="0.00")
    accounts = b.account_names
    key = f"meal_pay_acct_{sig}"
    if st.session_state.get(key) not in accounts:
        st.session_state[key] = b.default_account("Expense") if b.default_account("Expense") in accounts else (
            accounts[0] if accounts else None)
    st.pills("Paid from", accounts, key=key, required=True)
    cats = b.category_names("Expense")
    default = _food_category(k, b, entries[0])
    cat = st.selectbox("Logged under", cats, index=cats.index(default) if default in cats else 0,
                       key=f"meal_pay_cat_{sig}")
    if st.button("Save", type="primary", width="stretch", disabled=not paid, key=f"meal_pay_go_{sig}",
                 icon=":material/check:"):
        actions.mark_bought(ids if len(ids) > 1 else ids[0], paid, st.session_state.get(key), cat)
        flash(f"Saved {money(paid)} for {k.meal_name(entries)} under {cat}", ":material/shopping_bag:")
        st.rerun()
    st.caption("Saved as one expense, so there's no need to add it again. Untick the meal to take it back out.")


def _entry_row(k, e, today):
    bought = k.is_bought(e)
    kind = "bought" if bought else ("recipe" if e["recipe_id"] else "item")
    name = k.entry_name(e)
    detail = _detail(k, e)
    done = e["status"] != OPEN
    row = st.container(horizontal=True, vertical_alignment="center", key=f"meal-entry-{e['id']}")
    if bought and not done:
        _, tag = entry_status(k, e, today)
        row.html(f'<div class="bought-row">{esc(name)} · {esc(detail)} <span class="muted">🛍️ {esc(tag)}</span></div>',
                 width="stretch")
        if row.button("Bought", key=f"meal_buy_{e['id']}", icon=":material/shopping_bag:",
                      help="Say what you paid; it's saved as an expense"):
            _pay(e["id"])
    else:
        if done:
            label = f"{name} · {detail} · {DONE_LABEL.get(e['status'], 'Done')}"
        elif e["day"] >= today:
            status, _ = entry_status(k, e, today)
            m = k.meal_status(e["id"], today) or {}
            short = len(m.get("missing", []))
            tag = {"ready": "✅", "leftovers": "🥡 fridge", "short": f"🛒 {short} to buy"}.get(status, "")
            label = f"{name} · {detail} {tag}".rstrip()
        else:
            label = f"{name} · {detail}"
        row.checkbox(label, value=done, key=f"meal_e{e['id']}_{e['status']}", on_change=_toggle,
                     args=(e["id"], kind, e["status"]), width="stretch",
                     help="Untick to take the payment back out." if bought else
                     "Tick when it's cooked (or eaten, for fruit and other items). Untick to undo.")
    if not done and kind == "recipe":
        have = k.fridge_portions(e["recipe_id"], today)
        if have > 0:
            row.button(f"Fridge ({have:g})", key=f"meal_ff_{e['id']}", type="tertiary", icon=":material/kitchen:",
                       on_click=_from_fridge, args=(e["id"],), help="Eat leftovers instead of cooking")
    row.button("", key=f"meal_rm_{e['id']}", type="tertiary", icon=":material/close:", on_click=_remove,
               args=(e["id"],), help="Remove from the plan")


def _part_note(k, e, today):
    """One dish of a meal, in a few words: "Palm nut soup 14 portions (12 into the fridge), from the fridge"."""
    text = f"{k.entry_name(e)} {_detail(k, e)}"
    if e["status"] != OPEN:
        return text + f" ({DONE_LABEL.get(e['status'], 'done').lower()})"
    if e.get("recipe_id") and not k.is_bought(e):
        extra = e["qty"] - min(k.household, e["qty"])
        if extra > 1e-9:
            text += f" ({frac(extra)} into the fridge)"
    if e["day"] >= today:
        status, label = entry_status(k, e, today)
        text += {"leftovers": " 🥡", "short": f" 🛒 {label}", "bought": " 🛍️"}.get(status, "")
    return text


def _meal_row(k, parts, today):
    """A meal of several dishes, e.g. Kokonte + Palm nut soup: one line, one tick box, one payment."""
    home = [e for e in parts if not k.is_bought(e)]
    bought_open = [e for e in parts if k.is_bought(e) and e["status"] == OPEN]
    ids = tuple(e["id"] for e in parts)
    name = k.meal_name(parts)
    d, slot = parts[0]["day"], parts[0]["slot"]
    done = all(e["status"] != OPEN for e in parts)
    home_done = bool(home) and all(e["status"] != OPEN for e in home)
    row = st.container(horizontal=True, vertical_alignment="center", key=f"meal-combo-{d:%Y%m%d}-{slot}")
    if d >= today and not done:
        status, _ = meal_state(k, parts, today)
        missing = {ing for e in parts for ing, _, _ in (k.meal_status(e["id"], today) or {}).get("missing", [])}
        tag = {"ready": "✅", "leftovers": "🥡 fridge", "short": f"🛒 {len(missing)} to buy",
               "bought": "🛍️"}.get(status, "")
    else:
        tag = "· Done" if done else ""
    who = f"{k.household} {'person' if k.household == 1 else 'people'}"
    if home or done:
        ticked = home_done if home else done
        row.checkbox(f"{name} · {who} {tag}".rstrip(), value=ticked,
                     key=f"meal_c_{'_'.join(map(str, ids))}_{ticked}", on_change=_toggle_meal,
                     args=(tuple(e["id"] for e in (parts if ticked else home)), ticked), width="stretch",
                     help="One tick for the whole meal: dishes with leftovers in the fridge come from there, the rest "
                          "are cooked from the pantry. Untick to undo.")
    else:
        row.html(f'<div class="bought-row">{esc(name)} · {esc(who)} <span class="muted">{esc(tag)}</span></div>',
                 width="stretch")
    if bought_open:
        if row.button("Bought", key=f"meal_buy_{'_'.join(str(e['id']) for e in bought_open)}",
                      icon=":material/shopping_bag:", help="Say what you paid for the bought food; it's one expense"):
            _pay(tuple(e["id"] for e in bought_open))
    with row.popover("", icon=":material/tune:", help="The dishes in this meal"):
        for e in sorted(parts, key=k._part_order):
            r = st.container(horizontal=True, vertical_alignment="center", key=f"meal-part-{e['id']}")
            r.markdown(_part_note(k, e, today), width="stretch")
            r.button("", key=f"meal_rm_part_{e['id']}", type="tertiary", icon=":material/close:", on_click=_remove,
                     args=(e["id"],), disabled=e["status"] != OPEN, help="Take this dish out of the meal")
    row.button("", key=f"meal_rm_{'_'.join(map(str, ids))}", type="tertiary", icon=":material/close:", on_click=_remove,
               args=(ids,), help="Remove the whole meal from the plan")
    brief = []
    for e in sorted(parts, key=k._part_order):
        bit = f"{k.entry_name(e)} {_detail(k, e)}"
        if e["status"] == OPEN and e["day"] >= today and (k.meal_status(e["id"], today) or {}).get("status") == "leftovers":
            bit += " from the fridge"
        brief.append(bit)
    st.html(f'<div class="meal-parts">{esc(" · ".join(brief))}</div>')


ONE_OFF_UNITS = ["portion", "piece", "ball", "pack", "plate", "bowl", "loaf", "bottle", "sachet"]


def _option_label(k, key):
    kind, i = key.split(":")
    i = int(i)
    if kind == "p":
        return f"🍲 {k.pairings[i]['name']}"
    if kind == "r":
        return k.recipes[i]["name"] + (" 🛍️" if k.recipes[i]["bought"] else "")
    return f"{k.names.get(i, '?')} (item)"


@st.fragment
def _add_form():
    """Pick the day and meal once, then one or more dishes, each with its own amount, and add them together."""
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
    day, slot = ss.get("meal_add_day") or days[0], ss.get("meal_add_slot") or "Supper"

    options = ([f"p:{i}" for i in k.pairings]
               + [f"r:{i}" for i in sorted(k.recipes, key=lambda i: k.recipes[i]["name"].lower())]
               + [f"i:{i}" for i in sorted(k.food_names, key=lambda i: k.food_names[i].lower())])
    if not options:
        field_msg("Add a recipe or an ingredient first, under Meals → Recipes.", "hint")
        go("meals", "Recipes", label="Open recipes", icon=":material/menu_book:")
    ver = ss.get("meal_add_ver", 0)  # a fresh form after each add (clearing a widget's value isn't reliable)
    picked = st.multiselect("Dishes", options, key=f"meal_add_pick_{ver}", format_func=lambda x: _option_label(k, x),
                            placeholder="A pairing (🍲 Kokonte + Palm nut soup), dishes, or items…",
                            help="🍲 is a ready-made pairing; 🛍️ means bought ready-made. Everything picked for one "
                                 "meal is eaten together as one meal.")
    # a pairing stands for its dishes; a dish picked twice is planned once
    expanded, sides = [], {}
    for key in picked:
        kind, i = key.split(":")
        if kind == "p":
            for part in k.pairings[int(i)]["parts"]:
                if part.get("recipe_id"):
                    expanded.append(f"r:{part['recipe_id']}")
                else:
                    expanded.append(f"i:{part['ingredient_id']}")
                    sides[f"i:{part['ingredient_id']}"] = part
        else:
            expanded.append(key)
    expanded = list(dict.fromkeys(expanded))
    planned_here = [e for e in k.entries(day) if e["slot"] == slot]
    lines = []
    for key in expanded:
        kind, i = key.split(":")
        i = int(i)
        name = _option_label(k, key).replace(" 🛍️", "").replace(" (item)", "")
        if kind == "r" and k.recipes[i]["bought"]:
            r = k.recipes[i]
            unit = r["count_unit"]
            qty = st.number_input(f"{name} ({plural(unit)})", min_value=0.25, step=0.5, format="%g",
                                  value=float(max(k.household, 1)), key=f"meal_add_q_{ver}_{key}")
            if r["price"]:
                field_msg(f"About {money(r['price'] * qty)}, paid on the day" + (f" at {r['shop']}" if r["shop"] else "")
                          + ".", "hint")
            lines.append(dict(recipe_id=i, qty=qty))
        elif kind == "r":
            r = k.recipes[i]
            # the week's soup is already in the fridge (or a big pot is planned earlier): plan just enough for
            # this meal; otherwise the whole pot, and what isn't eaten goes into the fridge
            leftover = r["role"] != "starch" and from_leftovers(
                k.open_entries(*k.window(today)), k.recipes, k.items, k.pantry, k.fridge, k.household, today, day,
                slot, i, k.packs)
            if r["role"] == "starch":  # cooked fresh for everyone eating
                default = float(k.household)
            elif leftover:
                default = float(min(k.household, r["portions"]))
            else:
                default = float(r["portions"])
            qty = st.number_input(f"{name} (portions to cook)", min_value=0.25, max_value=100.0, step=0.5, format="%g",
                                  value=default, key=f"meal_add_q_{ver}_{key}",
                                  help="Halves and quarters are fine: 2.5, 0.5…")
            left = qty - min(k.household, qty)
            notes = []
            if leftover and qty <= k.household:
                notes.append("comes from the leftovers in the fridge, no need to cook")
            else:
                batch, each, unknown = recipe_cost(i, k.recipes, k.items, k.prices, k.packs)
                if batch:
                    notes.append(f"{'at least' if unknown else 'about'} {money(each * qty)}")
                have = k.fridge_portions(i)
                if have:
                    notes.append(f"{frac(have)} already in the fridge")
                if left > 0:
                    notes.append(f"{frac(left)} {plural('portion', left)} will go into the fridge")
            if notes:
                field_msg(notes[0][0].upper() + "; ".join(notes)[1:] + ".", "hint")
            lines.append(dict(recipe_id=i, qty=qty))
        else:
            side = sides.get(key)
            units = units_for(k.unit_of[i], k.pack(i))
            c1, c2 = st.columns(2)
            qty = c1.number_input(f"{name} (how much)", min_value=0.0, step=0.5, format="%g",
                                  value=float(side["qty"]) * k.household if side else 1.0, key=f"meal_add_q_{ver}_{key}")
            if side and side["unit"] in units and f"meal_add_u_{ver}_{key}" not in ss:
                ss[f"meal_add_u_{ver}_{key}"] = side["unit"]
            unit = c2.selectbox(f"{name} unit", units, key=f"meal_add_u_{ver}_{key}", label_visibility="collapsed")
            if qty:
                lines.append(dict(ingredient_id=i, qty=qty, unit=unit))

    if st.toggle("Add something bought outside, just this once", key=f"meal_add_once_{ver}",
                 help="Fried yam from the roadside, a plate of waakye… without saving it as a dish."):
        once = st.text_input("What", key=f"meal_add_once_name_{ver}", max_chars=80,
                             placeholder="e.g. Fried yam from the roadside").strip()
        c1, c2 = st.columns(2)
        once_qty = c1.number_input("How many", min_value=0.25, value=1.0, step=0.5, format="%g", key=f"meal_add_once_qty_{ver}")
        once_unit = c2.selectbox("Counted in", ONE_OFF_UNITS, key=f"meal_add_once_unit_{ver}")
        once_price = st.number_input(f"Price for one {once_unit} ({CURRENCY}), if you know it", min_value=0.0,
                                     value=None, step=1.0, format="%.2f", key=f"meal_add_once_price_{ver}")
        if once:
            lines.append(dict(label=once, qty=once_qty, unit=once_unit, price=once_price or None))

    when = "today" if day == today else ("tomorrow" if day == today + timedelta(days=1) else f"{day:%a %d}")
    n = len(lines)
    if lines:  # everything in one breakfast, lunch or supper is one meal
        meal = planned_here + [dict(ln, day=day, slot=slot, id=None) for ln in lines]
        if len(meal) > 1:
            joins = f" (with what's already planned for {when}'s {slot.lower()})" if planned_here else ""
            field_msg(f"One meal: {k.meal_name(meal)}{joins}.", "hint")
    label = f"Add {n} to {when}, {slot.lower()}" if n > 1 else f"Add to {when}, {slot.lower()}"
    if st.button(label, type="primary", disabled=not n, width="stretch", key="meal_add_go", icon=":material/add:"):
        actions.add_many([{"day": day, "slot": slot, "recipe_id": ln.get("recipe_id"),
                           "ingredient_id": ln.get("ingredient_id"), "qty": ln["qty"], "unit": ln.get("unit"),
                           "label": ln.get("label"), "price": ln.get("price")} for ln in lines])
        for key in [x for x in ss.keys() if str(x).startswith(("meal_add_q_", "meal_add_u_", "meal_add_once_",
                                                               "meal_add_pick_"))]:
            ss.pop(key, None)
        ss["meal_add_ver"] = ver + 1
        flash(f"Added {n} to {when}, {slot.lower()}" if n > 1 else f"Added to {when}, {slot.lower()}")
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
            n = k.meal_count(k.entries(past[0], past[-1]))
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
            n = k.meal_count(k.entries(wdays[0], wdays[-1]))  # kokonte + soup is one meal
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
    n = k.meal_count(new)
    first_time = not k.entries(start, end)
    label = (f"Copy the week before ({n} meal{'s' if n != 1 else ''})" if first_time else
             f"Fill the empty meals from the week before ({n})")
    if st.button(label, icon=":material/content_copy:", key="meal_copy", width="stretch",
                 type="primary" if first_time else "secondary",
                 help="Each empty breakfast, lunch or supper in the next two weeks gets what was planned 7 days "
                      "earlier. Meals already planned stay as they are."):
        actions.add_many(new)
        flash(f"Copied {n} meal{'s' if n != 1 else ''}. Change anything that's different.",
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
            if len(slot_entries) == 1:
                _entry_row(k, slot_entries[0], today)
            else:  # several dishes in one meal: one line, one tick
                _meal_row(k, slot_entries, today)


def _cost_line(k, today):
    """What the next two weeks' meals cost, what's still to buy, and the food budget guard."""
    start, end = k.window(today)
    entries = k.open_entries(start, end)
    if not entries:
        return
    needs = total_needs(entries, k.recipes, k.items, packs=k.packs)
    meals_cost, unknown = cost_of(needs, k.prices)
    bought, bought_unknown = bought_cost(entries, k.recipes)  # kenkey and other food bought on the day
    meals_cost, unknown = meals_cost + bought, unknown + bought_unknown
    to_buy = shopping_list(shortfall(k.allocation(today), entries), {}, prices=k.prices, packs=k.packs)
    buy_cost = sum(r["est"] or 0 for r in to_buy)
    buy_unknown = sum(1 for r in to_buy if r["est"] is None)
    n = k.meal_count(entries)
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
    # ideas are about using up what's at home; a starch on its own isn't a meal idea
    home = {i: r for i, r in k.recipes.items() if not r["bought"] and r["role"] not in ("starch", "side")}
    ideas = suggest(home, k.items, k.pantry, k.fridge, recent, today, packs=k.packs)
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

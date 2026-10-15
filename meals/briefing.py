"""Today's summary and the morning and evening messages sent to the family's phones (via Telegram).

No Streamlit here, so notify.py can build them on its own in the daily GitHub job, and the app
shows exactly the same thing on Home, on the meal plan and in the preview.
"""
from datetime import date, timedelta
from html import escape

import pandas as pd

from meals.logic import (GUARD_JOKE, OPEN, SLOTS, bought_cost, budget_guard, food_budget, meal_status,
                          shopping_list, shortfall)
from meals.quips import with_joke
from meals.units import base_of, fmt, plural, to_base

ICON = {"warn": "⚠️", "info": "•", "ok": "✅"}
STATUS_ICON = {"ready": "✅", "leftovers": "🥡", "short": "🛒", "done": "✔️", "bought": "🛍️"}


def entry_status(k, e, today):
    """(status, short label) for one planned dish: ready / leftovers / short / done."""
    if e["status"] != OPEN:
        return "done", "done"
    m = k.meal_status(e["id"], today)
    if not m:
        return "ready", ""
    if m["status"] == "leftovers":
        return "leftovers", "from the fridge"
    if m["status"] == "bought":
        price, _ = k.bought_price(e)
        return "bought", "buy on the day" + (f", about GH₵{float(price) * float(e['qty']):,.0f}" if price else "")
    if m["status"] == "short":
        return "short", "missing " + missing_text(k, m["missing"])
    return "ready", "all in"


def missing_text(k, missing, most=3):
    """What a meal is short of, with amounts: '2 cups Kokonte powder, 3 Onions +1'.
    missing: [(ingredient, base unit, quantity)]; the same item from two dishes is added up."""
    total = {}
    for ing, base, q in missing:
        total[(ing, base)] = total.get((ing, base), 0.0) + float(q)
    parts = [f"{fmt(q, base, k.unit_of.get(ing))} {k.names.get(ing, '?')}".strip() for (ing, base), q in total.items()]
    return ", ".join(parts[:most]) + (f" +{len(parts) - most}" if len(parts) > most else "")


def meal_state(k, parts, today):
    """(status, short label) for a whole meal, e.g. Kokonte + Palm nut soup: the soup from the fridge and the
    kokonte to cook counts as all in; anything missing for either dish makes the meal short."""
    if len(parts) == 1:
        return entry_status(k, parts[0], today)
    states, missing = [], []
    for e in parts:
        status, label = entry_status(k, e, today)
        short = (k.meal_status(e["id"], today) or {}).get("missing", []) if status == "short" else []
        missing += short
        states.append((status, [k.names.get(ing, "?") for ing, _, _ in short]))
    status = meal_status(states)
    if status == "done":
        return "done", "done"
    if status == "short":
        return "short", "missing " + missing_text(k, missing)
    if status == "leftovers":
        return "leftovers", "from the fridge"
    if status == "bought":
        return "bought", "buy on the day"
    fridge = [k.entry_name(e) for e, (s, _) in zip(parts, states) if s == "leftovers"]
    to_buy = [k.entry_name(e) for e, (s, _) in zip(parts, states) if s == "bought"]
    extra = ([f"{', '.join(fridge)} from the fridge"] if fridge else []) + ([f"buy {', '.join(to_buy)}"] if to_buy else [])
    return "ready", "all in" + (f" ({'; '.join(extra)})" if extra else "")


def today_summary(k, now):
    """What to cook today and whether it's all in, plus the one reminder that matters most.

    Returns {"day", "meals": [(slot, name, status, label)], "note": (tone, text) or None,
             "notes": every reminder for today and tomorrow (or the cheerful line when there are none),
             "reminders": only the real reminders}."""
    today = now.date()
    meals = []
    for slot in SLOTS:
        parts = [e for e in k.entries(today) if e["slot"] == slot]
        if parts:
            status, label = meal_state(k, parts, today)
            meals.append((slot, k.meal_name(parts), status, label))
    notes = k.notes(now)
    if notes:
        note = notes[0]
    elif not meals:
        note = ("info", with_joke("nothing_planned", "Nothing planned for today yet.", today, "", k.fun))
    elif all(m[2] in ("ready", "leftovers", "done", "bought") for m in meals):
        note = ("ok", with_joke("all_ready", "Everything for today's meals is in.", today, "", k.fun))
    else:
        note = None
    return {"day": today, "meals": meals, "note": note, "notes": notes or ([note] if note else []), "reminders": notes}


def planned_cost(k, today, until=None):
    """Estimated cost of what the plan still needs bought, from today up to `until` (default: end of month,
    within the two-week window)."""
    start, end = k.window(today)
    month_end = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1))
    end = min(end, until or month_end)
    entries = k.open_entries(start, end)
    items = shopping_list(shortfall(k.allocation(today), entries), {}, prices=k.prices, packs=k.packs)
    bought, bought_unknown = bought_cost(entries, k.recipes)  # kenkey, waakye… paid for on the day
    return (round(sum(r["est"] or 0 for r in items) + bought, 2),
            sum(1 for r in items if r["est"] is None) + bought_unknown)


def supplies_cost(k):
    """Estimated cost of topping up the household supplies that are low."""
    low = {key: v for key, v in k.low_levels.items() if key[0] in k.supplies}
    out = [r for r in shopping_list({}, k.pantry, low, k.prices, k.packs)]
    # items that are simply out (no warning level set) still need buying
    for i in k.supplies:
        base = base_of(k.unit_of.get(i, "pcs"))
        if (i, base) not in low and float(k.pantry.get((i, base), 0)) <= 0:
            pack = k.pack(i)
            q = pack[1] if pack and pack[2] == base else to_base(1, k.unit_of.get(i, "pcs"))[0]
            out += shopping_list({(i, base): {"qty": q, "short": q, "for": []}}, {}, prices=k.prices, packs=k.packs)
    return round(sum(r["est"] or 0 for r in out), 2)


def guard(k, book, today, kind="food"):
    """The budget guard for food (looking ahead at the meal plan's shopping) or household supplies
    (looking ahead at topping up what's low): (tone, text) or None."""
    cats = k.food_categories if kind == "food" else k.supply_categories
    fb = food_budget(book, {c for c in cats if c}, today) if book is not None and cats else None
    if not fb:
        return None
    planned = planned_cost(k, today)[0] if kind == "food" else supplies_cost(k)
    g = budget_guard(fb["limit"], fb["spent"], planned, what=kind)
    if not g:
        return None
    tone = "hint" if g["level"] == "75" else "warn"
    return tone, with_joke(GUARD_JOKE[g["level"]], g["text"], today, kind, k.fun, what=kind)


def _menu(k, day):
    lines = []
    for slot in SLOTS:
        parts = [e for e in k.entries(day) if e["slot"] == slot]
        if parts:
            status, label = meal_state(k, parts, day)
            text = f"{k.meal_name(parts)} {STATUS_ICON[status]}" + (f" ({label})" if status == "short" else "")
            lines.append(f"<b>{slot}:</b> {escape(text)}")
    return lines


def _today_shopping(k, today):
    """What today's meals are short of, added up: [(name, amount)], e.g. [("Kokonte powder", "2 cups")]."""
    total = {}
    for e in k.entries(today):
        if e["status"] != OPEN:
            continue
        for ing, base, q in (k.meal_status(e["id"], today) or {}).get("missing", []):
            total[(ing, base)] = total.get((ing, base), 0.0) + float(q)
    return [(k.names.get(ing, "?"), fmt(q, base, k.unit_of.get(ing))) for (ing, base), q in total.items()]


def morning(k, book, now):
    """The morning message: today's meals, what to buy, and what's left of the month's budgets.
    Returns HTML text for Telegram, e.g.

        ☀️ Wednesday, 14 Oct
        🍽️ Today's Meals
        • Breakfast: Lipton tea + Round sugar bread ✔️
        • Lunch: Kokonte + Groundnut soup 🛒 (Missing: 2 cups Kokonte powder)
        ⚠️ Heads-up                       (only when something is urgent)
        • Eat the 2 portions of Light soup by today.
        🛒 Things to Buy
        • Pantry / Food: Kokonte powder (2 cups), Eggs, Lipton
        • Household: Bar soap, Bin bags
        💰 Financial Standing
        • Total Budget Left for the Month: GH₵-2,072.55
    """
    today = now.date()
    out = [f"☀️ <b>{today:%A}, {today.day} {today:%b}</b>", "", "🍽️ <b>Today's Meals</b>"]
    meals = []
    for slot in SLOTS:
        parts = [e for e in k.entries(today) if e["slot"] == slot]
        if parts:
            status, label = meal_state(k, parts, today)
            note = f" (Missing: {label[len('missing '):]})" if status == "short" else ""
            meals.append(f"• {slot}: {escape(k.meal_name(parts))} {STATUS_ICON[status]}{escape(note)}")
    out += meals or ["• Nothing planned yet."]

    urgent = k.urgent(now)
    if urgent:
        out += ["", "⚠️ <b>Heads-up</b>"] + [f"• {escape(text)}" for text in urgent[:4]]

    food = [f"{name} ({amount})" if amount else name for name, amount in _today_shopping(k, today)]
    named = {f.split(" (")[0] for f in food}
    food += [n for n in k.food_low() if n not in named]
    household = k.supplies_low()
    if food or household:
        out += ["", "🛒 <b>Things to Buy</b>"]
        if food:
            out.append("• Pantry / Food: " + escape(", ".join(food)))
        if household:
            out.append("• Household: " + escape(", ".join(household)))

    if book is not None:
        try:
            t = book.budget_total(pd.Period(today, "M"))
            line = f"GH₵{t['left']:,.2f}" if t else "no monthly budgets set"
            out += ["", "💰 <b>Financial Standing</b>", f"• Total Budget Left for the Month: {line}"]
        except Exception:
            pass
    return "\n".join(out)


def stocktake(k, now):
    """Sunday evening: the pantry items used most this week, to count and correct. HTML text, or None
    when nothing was cooked this week."""
    items = k.stocktake(now.date())
    if not items:
        return None
    out = ["🧮 <b>Sunday stock check</b>", "",
           "These were used most this week. Check how much is really left, and fix any that are off in "
           "Cashew → Pantry / Inventory:", ""]
    out += [f"• {escape(name)}: {escape(have)}" for name, have in items]
    out += ["", "Two minutes now keeps the shopping list and the morning message right."]
    return "\n".join(out)


def evening(k, now):
    """Only sent when something needs doing tonight or early tomorrow. Returns HTML text, or None."""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    notes = [(t, x) for t, x in k.notes(now) if t == "warn" or "tomorrow" in x.lower()]
    open_tomorrow = [e for e in k.entries(tomorrow) if e["status"] == OPEN]
    to_buy = shopping_list(shortfall(k.allocation(today), open_tomorrow), {}, packs=k.packs)
    if not notes and not to_buy:
        return None
    out = [f"🌙 <b>For tomorrow, {tomorrow:%A %d %b}</b>"]
    menu = _menu(k, tomorrow)
    if menu:
        out += [""] + menu
    if notes:
        out += [""] + [f"{ICON[t]} {escape(x)}" for t, x in notes]
    elif to_buy:
        items = ", ".join(
            (f"{r['packs']} {plural(r['pack'], r['packs'])} " if r["pack"] else f"{fmt(r['to_buy'], r['base'], k.unit_of.get(r['ingredient_id']))} ")
            .replace("pcs ", "") + k.names.get(r["ingredient_id"], "?") for r in to_buy[:8])
        out += ["", f"🛒 Buy for tomorrow: {escape(items)}"]
    return "\n".join(out)

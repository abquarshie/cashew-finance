"""Today's summary and the morning and evening messages sent to the family's phones (via Telegram).

No Streamlit here, so notify.py can build them on its own in the daily GitHub job, and the app
shows exactly the same thing on Home, on the meal plan and in the preview.
"""
from datetime import date, timedelta
from html import escape

from meals.logic import (GUARD_JOKE, OPEN, SLOTS, budget_guard, food_budget, shopping_list, shortfall)
from meals.quips import with_joke
from meals.units import base_of, fmt, plural, to_base

ICON = {"warn": "⚠️", "info": "•", "ok": "✅"}
STATUS_ICON = {"ready": "✅", "leftovers": "🥡", "short": "🛒", "done": "✔️"}


def entry_status(k, e, today):
    """(status, short label) for one planned dish: ready / leftovers / short / done."""
    if e["status"] != OPEN:
        return "done", "done"
    m = k.meal_status(e["id"], today)
    if not m:
        return "ready", ""
    if m["status"] == "leftovers":
        return "leftovers", "from the fridge"
    if m["status"] == "short":
        names = [k.names.get(ing, "?") for ing, _, _ in m["missing"]]
        listed = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
        return "short", f"missing {listed}"
    return "ready", "all in"


def today_summary(k, now):
    """What to cook today and whether it's all in, plus the one reminder that matters most.

    Returns {"day", "meals": [(slot, name, status, label)], "note": (tone, text) or None,
             "notes": every reminder for today and tomorrow}."""
    today = now.date()
    meals = []
    for slot in SLOTS:
        for e in k.entries(today):
            if e["slot"] == slot:
                status, label = entry_status(k, e, today)
                meals.append((slot, k.entry_name(e), status, label))
    notes = k.notes(now)
    if notes:
        note = notes[0]
    elif not meals:
        note = ("info", with_joke("nothing_planned", "Nothing planned for today yet.", today, "", k.fun))
    elif all(m[2] in ("ready", "leftovers", "done") for m in meals):
        note = ("ok", with_joke("all_ready", "Everything for today's meals is in.", today, "", k.fun))
    else:
        note = None
    return {"day": today, "meals": meals, "note": note, "notes": notes or ([note] if note else [])}


def planned_cost(k, today, until=None):
    """Estimated cost of what the plan still needs bought, from today up to `until` (default: end of month,
    within the two-week window)."""
    start, end = k.window(today)
    month_end = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1))
    end = min(end, until or month_end)
    entries = k.open_entries(start, end)
    items = shopping_list(shortfall(k.allocation(today), entries), {}, prices=k.prices, packs=k.packs)
    return round(sum(r["est"] or 0 for r in items), 2), sum(1 for r in items if r["est"] is None)


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
        entries = [e for e in k.entries(day) if e["slot"] == slot]
        if entries:
            parts = []
            for e in entries:
                status, label = entry_status(k, e, day)
                parts.append(f"{k.entry_name(e)} {STATUS_ICON[status]}" + (f" ({label})" if status == "short" else ""))
            lines.append(f"<b>{slot}:</b> {escape(', '.join(parts))}")
    return lines


def morning(k, book, now, budget_left=None):
    """Today's menu with what's in stock, what needs doing, and money. Returns HTML text for Telegram."""
    today = now.date()
    out = [f"☀️ <b>Good morning! {today:%A %d %b}</b>", ""]
    menu = _menu(k, today)
    out += (["<b>Today's meals</b>"] + menu) if menu else [
        escape(with_joke("nothing_planned", "No meals planned for today.", today, "", k.fun))]

    notes = k.notes(now)
    if notes:
        out += ["", "<b>To do</b>"] + [f"{ICON[t]} {escape(x)}" for t, x in notes]
    low = k.supplies_low()
    if low:
        text = "Household running low: " + ", ".join(low[:6]) + (f" and {len(low) - 6} more" if len(low) > 6 else "") + "."
        out += ["", "🧽 " + escape(with_joke("supplies_low", text, today, "", k.fun))]

    if book is not None:
        try:
            s = book.safe_to_spend(today)
            money_line = (f"💰 Safe to spend until payday ({s['payday']:%a %d %b}): GH₵{s['safe']:,.2f}, "
                          f"about GH₵{max(s['per_day'], 0):,.2f} a day.")
            if budget_left is not None:
                money_line += f" Food budget left: GH₵{budget_left:,.2f}."
            out += ["", escape(money_line)]
            for kind in ("food", "household"):
                g = guard(k, book, today, kind)
                if g:
                    out.append(f"⚠️ {escape(g[1])}")
        except Exception:
            pass
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
            (f"{r['packs']} {plural(r['pack'], r['packs'])} " if r["pack"] else f"{fmt(r['to_buy'], r['base'])} ")
            .replace("pcs ", "") + k.names.get(r["ingredient_id"], "?") for r in to_buy[:8])
        out += ["", f"🛒 Buy for tomorrow: {escape(items)}"]
    return "\n".join(out)

"""Today's summary and the morning and evening messages sent to the family's phones (via Telegram).

No Streamlit here, so notify.py can build them on its own in the daily GitHub job, and the app
shows exactly the same thing on Home, on the meal plan and in the preview.
"""
from datetime import date, timedelta
from html import escape

from meals.logic import (GUARD_JOKE, OPEN, SLOTS, budget_guard, food_budget, shopping_list, shortfall)
from meals.quips import with_joke
from meals.units import fmt, plural

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


def guard(k, book, today):
    """The food budget guard: (tone, text) or None. Looks ahead at the planned shopping."""
    cats = {c for c in k.category_of.values() if c}
    fb = food_budget(book, cats, today) if book is not None else None
    if not fb:
        return None
    planned, _ = planned_cost(k, today)
    g = budget_guard(fb["limit"], fb["spent"], planned)
    if not g:
        return None
    tone = "hint" if g["level"] == "75" else "warn"
    return tone, with_joke(GUARD_JOKE[g["level"]], g["text"], today, "", k.fun)


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

    if book is not None:
        try:
            s = book.safe_to_spend(today)
            money_line = (f"💰 Safe to spend until payday ({s['payday']:%a %d %b}): GH₵{s['safe']:,.2f}, "
                          f"about GH₵{max(s['per_day'], 0):,.2f} a day.")
            if budget_left is not None:
                money_line += f" Food budget left: GH₵{budget_left:,.2f}."
            out += ["", escape(money_line)]
            g = guard(k, book, today)
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

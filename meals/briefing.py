"""The morning and evening messages sent to the family's phones (via Telegram).

No Streamlit here, so notify.py can build them on its own in the daily GitHub job,
and the app can show a preview.
"""
from datetime import timedelta
from html import escape

from meals.logic import OPEN, SLOTS, reminders, shopping_list, total_needs
from meals.units import fmt, plural

ICON = {"warn": "⚠️", "info": "•", "ok": "✅"}


def _menu(k, day):
    lines = []
    for slot in SLOTS:
        entries = [e for e in k.entries(day) if e["slot"] == slot]
        if entries:
            dishes = ", ".join(k.entry_name(e) + ("" if e["status"] == OPEN else " ✓") for e in entries)
            lines.append(f"<b>{slot}:</b> {escape(dishes)}")
    return lines


def _low_stock(k):
    low = []
    for (ing, base), level in k.low_levels.items():
        if float(k.pantry.get((ing, base), 0)) <= float(level):
            low.append(k.names.get(ing, "?"))
    return sorted(low)


def morning(k, book, now, budget_left=None):
    """Today's menu, what needs doing, and a money line. Returns HTML text for Telegram."""
    today = now.date()
    out = [f"☀️ <b>Good morning! {today:%A %d %b}</b>", ""]
    menu = _menu(k, today)
    out += (["<b>Today's meals</b>"] + menu) if menu else ["No meals planned for today."]

    soon = k.entries(today, today + timedelta(days=1))
    notes = reminders(now, soon, k.recipes, k.items, k.pantry, k.fridge, k.names, k.household, packs=k.packs)
    if notes:
        out += ["", "<b>To do</b>"] + [f"{ICON[t]} {escape(x)}" for t, x in notes]
    low = _low_stock(k)
    if low:
        out += ["", f"🧺 Running low: {escape(', '.join(low[:8]))}" + (f" and {len(low) - 8} more" if len(low) > 8 else "")]

    if book is not None:
        try:
            s = book.safe_to_spend(today)
            money_line = (f"💰 Safe to spend until payday ({s['payday']:%a %d %b}): GH₵{s['safe']:,.2f}, "
                          f"about GH₵{max(s['per_day'], 0):,.2f} a day.")
            if budget_left is not None:
                money_line += f" Food budget left: GH₵{budget_left:,.2f}."
            out += ["", escape(money_line)]
        except Exception:
            pass
    return "\n".join(out)


def evening(k, now):
    """Only sent when something needs doing tonight or early tomorrow. Returns HTML text, or None."""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    soon = k.entries(today, tomorrow)
    notes = [(t, x) for t, x in reminders(now, soon, k.recipes, k.items, k.pantry, k.fridge, k.names, k.household,
                                          packs=k.packs)
             if t == "warn" or "tomorrow" in x]
    open_tomorrow = [e for e in k.entries(tomorrow) if e["status"] == OPEN]
    to_buy = shopping_list(total_needs(open_tomorrow, k.recipes, k.items, packs=k.packs), k.pantry, packs=k.packs)
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

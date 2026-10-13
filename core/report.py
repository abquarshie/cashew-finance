"""The monthly report, sent to Telegram on the 1st and previewed in Settings → Reminders.

No Streamlit here, so the daily GitHub job can build it on its own.
"""
from datetime import date
from html import escape

import pandas as pd


def gh(x):
    return f"GH₵{x:,.2f}"


def price_rises(history, period, names, limit=3, at_least=0.05):
    """Items whose average price went up most from the month before to `period`:
    [(name, before, after, change)], prices per base unit. history: rows with ingredient_id, unit, per_unit, date."""
    if history is None or not len(history):
        return []
    h = history.assign(month=pd.to_datetime(history["date"]).dt.to_period("M"))
    now = h[h["month"] == period].groupby(["ingredient_id", "unit"])["per_unit"].mean()
    before = h[h["month"] == period - 1].groupby(["ingredient_id", "unit"])["per_unit"].mean()
    out = []
    for key, after in now.items():
        if key in before.index and before[key] > 0:
            change = (after - before[key]) / before[key]
            if change >= at_least:
                out.append((names.get(int(key[0]), "?"), float(before[key]), float(after), float(change)))
    return sorted(out, key=lambda x: -x[3])[:limit]


def monthly(book, kitchen=None, today=None):
    """Last month in a few lines: money in and out, budgets, where it went, savings, and the kitchen.
    Returns HTML text for Telegram."""
    today = today or date.today()
    period = pd.Period(today, "M") - 1
    inc, exp = book.month_totals(period)
    p_inc, p_exp = book.month_totals(period - 1)
    out = [f"📊 <b>{period.strftime('%B %Y')} in Cashew</b>", ""]
    kept = inc - exp
    line = f"💵 In {gh(inc)} · out {gh(exp)} · "
    line += f"kept {gh(kept)}" + (f" ({kept / inc * 100:.0f}% of income)" if inc > 0 and kept > 0 else "")
    if kept < 0:
        line = f"💵 In {gh(inc)} · out {gh(exp)} · spent {gh(-kept)} more than came in"
    out.append(escape(line))
    if p_exp > 0:
        ch = (exp - p_exp) / p_exp * 100
        if abs(ch) >= 1:
            out.append(escape(f"Spending was {abs(ch):.0f}% {'higher' if ch > 0 else 'lower'} than "
                              f"{(period - 1).strftime('%B')}."))

    status = book.budget_status(period)
    if status:
        out += ["", "<b>Budgets</b>"]
        for s in status:
            if s["spent"] > s["limit"]:
                mark = f"⚠️ {gh(s['spent'] - s['limit'])} over"
            elif s["pct"] >= 90:
                mark = "🟡 just in"
            else:
                mark = "✅"
            out.append(escape(f"{s['name']}: {gh(s['spent'])} of {gh(s['limit'])} {mark}"))

    spent = book.month_expenses(period)
    if len(spent):
        top = spent.groupby("group")["amount"].sum().sort_values(ascending=False).head(3)
        out += ["", "<b>Where most of it went</b>"]
        out += [escape(f"{g}: {gh(v)} ({v / exp * 100:.0f}%)") for g, v in top.items()]

    if len(book.contribs):
        c = book.contribs
        saved = c[pd.to_datetime(c["date"]).dt.to_period("M") == period]["amount"].sum()
        if saved > 0:
            out += ["", escape(f"🎯 Saved towards goals: {gh(float(saved))}")]

    if kitchen is not None:
        out += _kitchen(book, kitchen, period, spent)
    return "\n".join(out)


def _kitchen(book, k, period, spent):
    lines = []
    cats = {c for c in k.food_categories if c}
    food = float(spent[spent["category"].isin(cats)]["amount"].sum()) if len(spent) and cats else 0.0
    if food > 0:
        per_day = food / max(k.household, 1) / period.days_in_month
        lines.append(escape(f"🍲 Food: {gh(food)}, about {gh(per_day)} a person a day ({k.household} people)."))
    supplies = {c for c in k.supply_categories if c}
    house = float(spent[spent["category"].isin(supplies)]["amount"].sum()) if len(spent) and supplies else 0.0
    if house > 0:
        lines.append(escape(f"🧽 Household supplies: {gh(house)}."))
    cooked = [e for e in k.plan if pd.Period(e["day"], "M") == period and e["status"] != "planned"]
    if cooked:
        lines.append(escape(f"🍳 {len(cooked)} planned meals ticked off."))
    w = k.waste
    if len(w):
        w = w[pd.to_datetime(w["date"]).dt.to_period("M") == period]
        if len(w):
            value = float(w["value"].fillna(0).astype(float).sum())
            lines.append(escape(f"🗑️ Food thrown away: {len(w)} time{'s' if len(w) != 1 else ''}"
                                + (f", about {gh(value)}" if value else "") + "."))
    rises = price_rises(k.history, period, k.names)
    if rises:
        lines.append("📈 " + escape("Prices up: " + ", ".join(f"{n} +{c * 100:.0f}%" for n, _, _, c in rises) + "."))
    return (["", "<b>Kitchen</b>"] + lines) if lines else []

"""The meal planner's arithmetic, kept apart from the screens so it can be tested on its own.

Everything works on plain data:
- plan entries: dicts with day, slot, recipe_id or ingredient_id, qty, unit, status
- recipes: {id: {"name", "portions", "keeps_days", "prep_note", "prep_hours"}}
- recipe items: {recipe_id: [(ingredient_id, qty, unit), ...]}
- pantry: {(ingredient_id, base_unit): qty}
"""
from collections import defaultdict
from datetime import datetime, timedelta

from meals.units import fmt, frac, packs_for, plural, to_base

SLOTS = ["Breakfast", "Lunch", "Supper"]
MEAL_HOUR = {"Breakfast": 7, "Lunch": 13, "Supper": 19}
OPEN = "planned"


def entry_needs(entry, recipes, items, packs=None):
    """What one plan entry uses: [(ingredient_id, base_unit, qty)]. A recipe is scaled to the portions planned.
    packs: {ingredient_id: (container, size in base unit, base)} so "1 crate" of eggs counts as 30 eggs."""
    packs = packs or {}
    if entry.get("recipe_id"):
        r = recipes.get(entry["recipe_id"])
        if not r:
            return []
        factor = float(entry["qty"]) / max(float(r["portions"]), 1)
        out = []
        for ing, qty, unit in items.get(entry["recipe_id"], []):
            q, base = to_base(float(qty) * factor, unit, packs.get(ing))
            out.append((ing, base, q))
        return out
    q, base = to_base(float(entry["qty"]), entry.get("unit") or "pcs", packs.get(entry.get("ingredient_id")))
    return [(entry["ingredient_id"], base, q)]


def total_needs(entries, recipes, items, names_for_entry=None, packs=None):
    """Add up every ingredient across the given entries: 3 onions + 3 onions = 6 onions; 500 g + 1 kg = 1.5 kg.

    Returns {(ingredient_id, base): {"qty": total, "for": [dish names]}}.
    """
    totals = defaultdict(lambda: {"qty": 0.0, "for": []})
    for e in entries:
        label = names_for_entry(e) if names_for_entry else None
        for ing, base, q in entry_needs(e, recipes, items, packs):
            t = totals[(ing, base)]
            t["qty"] += q
            if label and label not in t["for"]:
                t["for"].append(label)
    return dict(totals)


def buyable(qty, base):
    """An amount you can actually ask for at the market: 5.88 onions -> 6, 38.75 g -> 40 g, 1.625 kg -> 1.65 kg."""
    import math
    if qty <= 0:
        return 0.0
    if base in ("g", "ml"):
        step = 5 if qty < 100 else (50 if qty < 2000 else 100)
        return float(math.ceil(qty / step - 1e-9) * step)
    return float(math.ceil(qty - 1e-9))


def shopping_list(needs, pantry, low_levels=None, prices=None, packs=None):
    """What to buy: needed minus what's already in the pantry, plus staples that are running low.

    Items bought in containers round up to whole ones (12 eggs needed -> 1 crate).
    Returns dicts with ingredient_id, base, need, have, to_buy (base unit), packs (whole containers or None),
    pack (container name or None), reason, est (estimated cost or None).
    """
    prices = prices or {}
    packs = packs or {}
    out = []
    for (ing, base), n in needs.items():
        if "short" in n:  # already worked out by allocate(): stock shared out meal by meal
            have = max(n["qty"] - n["short"], 0.0)
            to_buy = round(max(n["short"], 0.0), 3)
        else:
            have = float(pantry.get((ing, base), 0.0))
            to_buy = round(max(n["qty"] - have, 0.0), 3)
        if to_buy <= 0:
            continue
        out.append({"ingredient_id": ing, "base": base, "need": n["qty"], "have": have, "to_buy": to_buy,
                    "reason": "For " + ", ".join(n["for"]) if n["for"] else "", "low": False})
    listed = {(r["ingredient_id"], r["base"]) for r in out}
    for (ing, base), level in (low_levels or {}).items():
        if level is None or (ing, base) in listed:
            continue
        have = float(pantry.get((ing, base), 0.0))
        if have <= float(level):
            # top it back up to twice the warning level
            out.append({"ingredient_id": ing, "base": base, "need": 0.0, "have": have,
                        "to_buy": round(max(float(level) * 2 - have, float(level)), 3),
                        "reason": "Running low", "low": True})
    for r in out:
        pack = packs.get(r["ingredient_id"])
        if pack and pack[2] == r["base"] and pack[1]:
            r["packs"], r["pack"] = packs_for(r["to_buy"], pack), pack[0]
            r["buy_qty"] = r["packs"] * float(pack[1])   # what you'll actually bring home
        else:
            # nobody buys 0.88 of an onion: counted things round up to whole ones, weights and volumes to a
            # sensible step (half portions in the plan make odd amounts otherwise)
            r["to_buy"] = buyable(r["to_buy"], r["base"])
            r["packs"], r["pack"], r["buy_qty"] = None, None, r["to_buy"]
        per = prices.get((r["ingredient_id"], r["base"]))
        r["est"] = round(per * r["buy_qty"], 2) if per is not None else None
    return out


# ---- sharing out the stock -----------------------------------------------------------------------
def _when(e):
    return (meal_time(e["day"], e["slot"]), e.get("id") or 0)


def _key(e):
    """Plan entries are keyed by their id (or, for unsaved ones in tests, by the object itself)."""
    return e["id"] if e.get("id") is not None else id(e)


def allocate(entries, recipes, items, pantry, fridge, household, today, packs=None):
    """Share the fridge and pantry out across the planned meals, in the order they'll be eaten.

    Earlier meals get first claim, so two meals can't both count the same 2 onions. A meal whose dish
    is already in the fridge (enough for everyone eating) is eaten from there and needs no ingredients.
    Cooking more portions than are eaten puts the rest in the fridge, where a later meal of the same
    dish can use them before they go off.

    entries: plan entries; only open ones from today on are counted.
    Returns {"meals": {entry_id: {"status": "ready" | "leftovers" | "short",
                                  "missing": [(ingredient_id, base, qty)], "needs": [(ing, base, qty)]}},
             "stock_after": pantry left once every meal has taken its share}.
    """
    stock = {k: float(v) for k, v in pantry.items()}
    boxes = [[b["recipe_id"], float(b["portions"]), b["eat_by"]] for b in fridge
             if b.get("recipe_id") and float(b["portions"]) > 0]
    meals = {}
    for e in sorted((e for e in entries if e["status"] == OPEN and e["day"] >= today), key=_when):
        rid = e.get("recipe_id")
        recipe = recipes.get(rid) if rid else None
        if recipe:
            eat = min(float(household), float(e["qty"]))
            ready = sorted((b for b in boxes if b[0] == rid and b[1] > 1e-9 and b[2] >= e["day"]), key=lambda b: b[2])
            if eat > 0 and sum(b[1] for b in ready) >= eat - 1e-9:
                left = eat
                for b in ready:
                    t = min(b[1], left)
                    b[1] -= t
                    left -= t
                meals[_key(e)] = {"status": "leftovers", "missing": [], "needs": []}
                continue
        needs = entry_needs(e, recipes, items, packs)
        missing = []
        for ing, base, q in needs:
            have = stock.get((ing, base), 0.0)
            used = min(have, q)
            stock[(ing, base)] = have - used
            if q - used > 1e-6:
                missing.append((ing, base, q - used))
        if recipe:
            extra = float(e["qty"]) - min(float(household), float(e["qty"]))
            if extra > 1e-9:
                boxes.append([rid, extra, e["day"] + timedelta(days=int(recipe.get("keeps_days") or 3))])
        meals[_key(e)] = {"status": "short" if missing else "ready", "missing": missing, "needs": needs}
    return {"meals": meals, "stock_after": stock}


def repeat_plan(plan, today, horizon=14):
    """Fill empty meals in the next `horizon` days with whatever was planned 7 days earlier.

    Works day by day, so a week copied into the first 7 days carries on into the next 7 in the same go.
    A breakfast, lunch or supper that already has something planned is left alone.
    Returns the new entries as dicts: day, slot, recipe_id, ingredient_id, qty, unit."""
    by_slot = defaultdict(list)
    for e in plan:
        if today - timedelta(days=7) <= e["day"] <= today + timedelta(days=horizon - 1):
            by_slot[(e["day"], e["slot"])].append(e)
    new = []
    for i in range(horizon):
        d = today + timedelta(days=i)
        for slot in SLOTS:
            if by_slot.get((d, slot)):
                continue
            src = by_slot.get((d - timedelta(days=7), slot))
            if src:
                copies = [{"day": d, "slot": slot, "recipe_id": e.get("recipe_id"), "ingredient_id": e.get("ingredient_id"),
                           "qty": e["qty"], "unit": e.get("unit")} for e in src]
                by_slot[(d, slot)] = copies
                new += copies
    return new


def shortfall(alloc, entries, names_for_entry=None):
    """What the given meals still need after the stock is shared out, in the shape shopping_list() takes:
    {(ingredient_id, base): {"qty": needed, "short": still to buy, "for": [dish names]}}."""
    totals = defaultdict(lambda: {"qty": 0.0, "short": 0.0, "for": []})
    for e in entries:
        m = alloc["meals"].get(_key(e))
        if not m:
            continue
        missing = defaultdict(float)
        for ing, base, q in m["missing"]:
            missing[(ing, base)] += q
        label = names_for_entry(e) if names_for_entry else None
        for ing, base, q in m["needs"]:
            t = totals[(ing, base)]
            t["qty"] += q
            if missing.get((ing, base)):
                t["short"] += missing.pop((ing, base))
                if label and label not in t["for"]:
                    t["for"].append(label)
    return {k: v for k, v in totals.items() if v["short"] > 1e-6}


def food_budget(book, categories, today):
    """This month's limit and spending across the budgets that cover the kitchen's money categories.
    A group budget (like Food) covers all its categories; a category budget counts only when its group has none.
    Returns {"limit", "spent", "names"} or None when no budget covers the kitchen."""
    import pandas as pd
    status = book.budget_status(pd.Period(today, "M"))
    groups = {book.group_of.get(c) for c in categories}
    limit = spent = 0.0
    names, covered = [], set()
    for s in status:
        if s["is_group"] and s["name"] in groups:
            limit += s["limit"]
            spent += s["spent"]
            names.append(s["name"])
            covered.add(s["name"])
    for s in status:
        if not s["is_group"] and s["name"] in categories and book.group_of.get(s["name"]) not in covered:
            limit += s["limit"]
            spent += s["spent"]
            names.append(s["name"])
    return {"limit": limit, "spent": spent, "names": names} if names else None


def budget_guard(limit, spent, planned):
    """Warn before the shopping, not after. planned: estimated cost of what the plan still needs bought
    this month. Returns {"level": "75" | "90" | "will_go_over" | "over", "text": ...} or None."""
    if not limit or limit <= 0:
        return None
    gh = lambda x: f"GH₵{x:,.2f}"  # noqa: E731
    after = spent + (planned or 0)
    if spent > limit:
        return {"level": "over", "text": f"Food spending is {gh(spent - limit)} over this month's {gh(limit)} budget."}
    if after > limit:
        return {"level": "will_go_over",
                "text": f"The planned shopping (about {gh(planned)}) would take food spending to {gh(after)}, "
                        f"{gh(after - limit)} over the {gh(limit)} budget. Consider swapping a dish."}
    pct = after / limit * 100
    if pct >= 75:
        return {"level": "90" if pct >= 90 else "75",
                "text": f"With the planned shopping, food spending reaches {pct:.0f}% of the {gh(limit)} budget "
                        f"({gh(limit - after)} left)."}
    return None


GUARD_JOKE = {"75": "budget_75", "90": "budget_90", "will_go_over": "budget_over", "over": "budget_over"}


# ---- money --------------------------------------------------------------------------------------
def cost_of(needs, prices):
    """Estimated cost of a set of needs from remembered prices: (total, ingredients with no price yet)."""
    total, unknown = 0.0, 0
    for key, n in needs.items():
        per = prices.get(key)
        if per is None:
            unknown += 1
        else:
            total += per * n["qty"]
    return round(total, 2), unknown


def recipe_cost(recipe_id, recipes, items, prices, packs=None):
    """(cost of one batch, cost per portion, ingredients with no price yet)."""
    r = recipes.get(recipe_id)
    if not r:
        return 0.0, 0.0, 0
    entry = {"recipe_id": recipe_id, "qty": r["portions"]}
    needs = {}
    for ing, base, q in entry_needs(entry, recipes, items, packs):
        needs.setdefault((ing, base), {"qty": 0.0, "for": []})["qty"] += q
    total, unknown = cost_of(needs, prices)
    return total, round(total / max(r["portions"], 1), 2), unknown


def price_changes(lines, old_prices, threshold=0.2):
    """Big price moves since last time: [(name, old per unit, new per unit, change as a fraction)].
    lines: [{"ingredient_id", "name", "qty" (base), "base", "price"}]."""
    out = []
    for ln in lines:
        if not ln.get("ingredient_id") or not ln["qty"] or not ln["price"]:
            continue
        old = old_prices.get((ln["ingredient_id"], ln["base"]))
        if not old:
            continue
        new = ln["price"] / ln["qty"]
        change = (new - old) / old
        if abs(change) >= threshold:
            out.append((ln["name"], old, new, change))
    return sorted(out, key=lambda x: -abs(x[3]))


# ---- what to cook --------------------------------------------------------------------------------
def suggest(recipes, items, pantry, fridge, recent, today, packs=None, limit=3):
    """Dishes worth planning next, best first: eat up leftovers, use what's in the pantry, and don't repeat
    what was had recently.

    recent: plan entries from the last couple of weeks. Returns [{"recipe_id", "score", "reasons": [...]}].
    """
    last_had = {}
    for e in recent:
        if e.get("recipe_id") and e["day"] <= today:
            last_had[e["recipe_id"]] = max(last_had.get(e["recipe_id"], e["day"]), e["day"])
    planned_ahead = {e["recipe_id"] for e in recent if e.get("recipe_id") and e["day"] > today}
    leftover = {}
    for b in fridge:
        if b.get("recipe_id") and b["eat_by"] >= today and float(b["portions"]) > 0:
            leftover[b["recipe_id"]] = leftover.get(b["recipe_id"], 0) + float(b["portions"])

    out = []
    for rid, r in recipes.items():
        if rid in planned_ahead:
            continue
        score, reasons = 0.0, []
        if leftover.get(rid):
            score += 5
            reasons.append(f"{leftover[rid]:g} portions already in the fridge")
        lines = entry_needs({"recipe_id": rid, "qty": r["portions"]}, recipes, items, packs)
        if lines:
            covered = sum(1 for ing, base, q in lines if float(pantry.get((ing, base), 0)) >= q - 1e-9)
            score += 3 * covered / len(lines)
            if covered == len(lines):
                reasons.append("everything is in the pantry")
            elif covered:
                reasons.append(f"{covered} of {len(lines)} ingredients in the pantry")
        days = (today - last_had[rid]).days if rid in last_had else None
        if days is None:
            score += 1.5
            reasons.append("not had in the last few weeks")
        elif days < 4:
            score -= 3
        else:
            score += min(days, 14) / 7
            reasons.append(f"last had {days} days ago")
        out.append({"recipe_id": rid, "score": round(score, 2), "reasons": reasons})
    out.sort(key=lambda x: (-x["score"], recipes[x["recipe_id"]]["name"]))
    return [x for x in out if x["score"] > 0][:limit]


def after_use(pantry, uses):
    """Pantry after using ingredients. Never goes below zero; returns (new pantry, shortfalls)."""
    new = dict(pantry)
    short = []
    for ing, base, q in uses:
        have = float(new.get((ing, base), 0.0))
        if q > have + 1e-9:
            short.append((ing, base, q - have))
        new[(ing, base)] = max(have - q, 0.0)
    return new, short


def leftovers(portions_cooked, eaten_now):
    """Portions that go into the fridge after a meal."""
    return max(float(portions_cooked) - float(eaten_now), 0.0)


def take_portions(batches, wanted):
    """Take portions from fridge batches, oldest eat-by first.

    batches: [{"id", "portions", "eat_by"}]. Returns ([(batch_id, portions_taken)], portions still missing).
    """
    taken, left = [], float(wanted)
    for b in sorted(batches, key=lambda b: (b["eat_by"], b["id"])):
        if left <= 0:
            break
        t = min(float(b["portions"]), left)
        if t > 0:
            taken.append((b["id"], t))
            left -= t
    return taken, max(left, 0.0)


def fridge_flags(batch, today, low_portions=1):
    """'past' (eat-by gone), 'soon' (today or tomorrow), 'low' (few portions left) or None."""
    if batch["eat_by"] < today:
        return "past"
    if batch["eat_by"] <= today + timedelta(days=1):
        return "soon"
    if float(batch["portions"]) <= low_portions:
        return "low"
    return None


def meal_time(day, slot):
    return datetime(day.year, day.month, day.day, MEAL_HOUR.get(slot, 12))


def reminders(now, entries, recipes, items, pantry, fridge, names, household, low_portions=1, packs=None,
              alloc=None, fun=False, low_levels=None):
    """Things that affect cooking in the next day or so, most urgent first.

    entries: plan entries for today and tomorrow. fridge: batches with recipe_id, label, portions, eat_by.
    names: {ingredient_id: name}. alloc: allocate()'s result, if already worked out.
    fun: put a joke in front of each reminder (see quips.py). low_levels: {(ing, base): warn level}.
    Returns [(tone, text)] where tone is 'warn', 'info' or 'ok'.
    """
    from meals.quips import with_joke

    today = now.date()
    out = []
    open_entries = [e for e in entries if e["status"] == OPEN and e["day"] >= today]
    if alloc is None:
        alloc = allocate(open_entries, recipes, items, pantry, fridge, household, today, packs)
    status = alloc["meals"]

    # prep that needs doing ahead (soak beans, defrost fish)
    for e in sorted(open_entries, key=_when):
        r = recipes.get(e.get("recipe_id"))
        if not r or not r.get("prep_note") or not r.get("prep_hours") or status.get(_key(e), {}).get("status") == "leftovers":
            continue
        at = meal_time(e["day"], e["slot"])
        start = at - timedelta(hours=int(r["prep_hours"]))
        if start <= now + timedelta(hours=12) and now < at:
            when = "now" if start <= now else f"by {start:%a %H:%M}"
            day_word = "today's" if e["day"] == today else "tomorrow's"
            text = f"{r['prep_note']} {when}, for {day_word} {e['slot'].lower()} ({r['name']})."
            out.append(("warn" if start <= now else "info", with_joke("prep", text, today, e.get("id"), fun)))

    # leftovers in the fridge that cover a planned meal
    in_fridge = defaultdict(float)
    for b in fridge:
        if b.get("recipe_id") and b["eat_by"] >= today:
            in_fridge[b["recipe_id"]] += float(b["portions"])
    for e in sorted(open_entries, key=_when):
        if status.get(_key(e), {}).get("status") == "leftovers" and in_fridge.get(e["recipe_id"]):
            r = recipes[e["recipe_id"]]
            day_word = "Today's" if e["day"] == today else "Tomorrow's"
            text = (f"{day_word} {e['slot'].lower()}: {in_fridge[e['recipe_id']]:g} portions of {r['name']} "
                    "are already in the fridge, no need to cook.")
            out.append(("ok", with_joke("leftovers", text, today, e.get("id"), fun)))

    # ingredients missing for today's and tomorrow's cooking, after the stock is shared out
    missing = defaultdict(float)
    for e in open_entries:
        for ing, base, q in status.get(_key(e), {}).get("missing", []):
            missing[(ing, base)] += q
    if missing:
        rows = list(missing.items())
        listed = ", ".join(f"{fmt(q, base)} {names.get(ing, '?')}".replace(" pcs", "") for (ing, base), q in rows[:6])
        more = f" and {len(rows) - 6} more" if len(rows) > 6 else ""
        out.append(("warn", with_joke("missing", f"Buy before cooking: {listed}{more}.", today, "", fun)))

    # fridge food going off or running low
    for b in sorted(fridge, key=lambda b: b["eat_by"]):
        flag = fridge_flags(b, today, low_portions)
        unit = b.get("unit") or "portion"
        if flag == "past":
            text = f"{b['label']} in the fridge was due by {b['eat_by']:%a %d %b}. Check it before eating."
            out.append(("warn", with_joke("past", text, today, b.get("id"), fun)))
        elif flag == "soon":
            when = "today" if b["eat_by"] == today else "tomorrow"
            text = f"Eat the {frac(b['portions'])} {plural(unit, float(b['portions']))} of {b['label']} by {when}."
            out.append(("warn", with_joke("eat_soon", text, today, b.get("id"), fun)))
        elif flag == "low":
            text = (f"Only {frac(b['portions'])} {plural(unit, float(b['portions']))} of {b['label']} "
                    "left in the fridge.")
            out.append(("info", with_joke("low_portions", text, today, b.get("id"), fun)))

    # staples running low (only when the caller asks)
    if low_levels:
        low = sorted(names.get(ing, "?") for (ing, base), level in low_levels.items()
                     if level is not None and float(pantry.get((ing, base), 0)) <= float(level))
        if low:
            text = "Running low: " + ", ".join(low[:6]) + (f" and {len(low) - 6} more" if len(low) > 6 else "") + "."
            out.append(("info", with_joke("low_stock", text, today, "", fun)))
    order = {"warn": 0, "info": 1, "ok": 2}
    return sorted(out, key=lambda x: order[x[0]])

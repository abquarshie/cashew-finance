"""The meal planner's arithmetic, kept apart from the screens so it can be tested on its own.

Everything works on plain data:
- plan entries: dicts with day, slot, recipe_id or ingredient_id, qty, unit, status
- recipes: {id: {"name", "portions", "keeps_days", "prep_note", "prep_hours"}}
- recipe items: {recipe_id: [(ingredient_id, qty, unit), ...]}
- pantry: {(ingredient_id, base_unit): qty}
"""
from collections import defaultdict
from datetime import datetime, timedelta

from meals.units import fmt, packs_for, plural, to_base

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
            r["packs"], r["pack"], r["buy_qty"] = None, None, r["to_buy"]
        per = prices.get((r["ingredient_id"], r["base"]))
        r["est"] = round(per * r["buy_qty"], 2) if per is not None else None
    return out


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


def reminders(now, entries, recipes, items, pantry, fridge, names, household, low_portions=1, packs=None):
    """Things that affect cooking in the next day or so, most urgent first.

    entries: plan entries for today and tomorrow. fridge: batches with recipe_id, label, portions, eat_by.
    names: {ingredient_id: name}. Returns [(tone, text)] where tone is 'warn', 'info' or 'ok'.
    """
    today = now.date()
    out = []
    open_entries = [e for e in entries if e["status"] == OPEN]

    # prep that needs doing ahead (soak beans, defrost fish)
    for e in sorted(open_entries, key=lambda e: meal_time(e["day"], e["slot"])):
        r = recipes.get(e.get("recipe_id"))
        if not r or not r.get("prep_note") or not r.get("prep_hours"):
            continue
        at = meal_time(e["day"], e["slot"])
        start = at - timedelta(hours=int(r["prep_hours"]))
        if start <= now + timedelta(hours=12) and now < at:
            when = "now" if start <= now else f"by {start:%a %H:%M}"
            day_word = "today's" if e["day"] == today else "tomorrow's"
            out.append(("warn" if start <= now else "info",
                        f"{r['prep_note']} {when}, for {day_word} {e['slot'].lower()} ({r['name']})."))

    # leftovers in the fridge that cover a planned meal
    by_recipe = defaultdict(float)
    for b in fridge:
        if b.get("recipe_id") and b["eat_by"] >= today:
            by_recipe[b["recipe_id"]] += float(b["portions"])
    for e in open_entries:
        if e.get("recipe_id") and by_recipe.get(e["recipe_id"], 0) >= min(float(household), float(e["qty"])):
            r = recipes[e["recipe_id"]]
            day_word = "Today's" if e["day"] == today else "Tomorrow's"
            out.append(("ok", f"{day_word} {e['slot'].lower()}: {by_recipe[e['recipe_id']]:g} portions of {r['name']} "
                              "are already in the fridge, no need to cook."))

    # ingredients missing for today's and tomorrow's cooking
    cook = [e for e in open_entries if not (e.get("recipe_id") and by_recipe.get(e["recipe_id"], 0) >= float(household))]
    needs = total_needs(cook, recipes, items, packs=packs)
    missing = [(ing, base, n["qty"] - float(pantry.get((ing, base), 0.0))) for (ing, base), n in needs.items()
               if n["qty"] - float(pantry.get((ing, base), 0.0)) > 1e-6]
    if missing:
        listed = ", ".join(f"{fmt(q, base)} {names.get(ing, '?')}".replace(" pcs", "") for ing, base, q in missing[:6])
        more = f" and {len(missing) - 6} more" if len(missing) > 6 else ""
        out.append(("warn", f"Buy before cooking: {listed}{more}."))

    # fridge food going off or running low
    for b in sorted(fridge, key=lambda b: b["eat_by"]):
        flag = fridge_flags(b, today, low_portions)
        if flag == "past":
            out.append(("warn", f"{b['label']} in the fridge was due by {b['eat_by']:%a %d %b}. Check it before eating."))
        elif flag == "soon":
            when = "today" if b["eat_by"] == today else "tomorrow"
            unit = b.get("unit") or "portion"
            out.append(("warn", f"Eat the {b['portions']:g} {plural(unit, float(b['portions']))} of "
                                f"{b['label']} by {when}."))
        elif flag == "low":
            unit = b.get("unit") or "portion"
            out.append(("info", f"Only {b['portions']:g} {plural(unit, float(b['portions']))} of {b['label']} "
                                "left in the fridge."))
    order = {"warn": 0, "info": 1, "ok": 2}
    return sorted(out, key=lambda x: order[x[0]])

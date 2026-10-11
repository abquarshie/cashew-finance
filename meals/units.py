"""Units of measure for ingredients.

Weights and volumes convert automatically (500 g + 1 kg = 1.5 kg). Counted things
("3 onions", "2 tins") stay as they are: they're only added to other quantities
in the same unit, because an onion has no fixed weight.

Every quantity is stored in a "base" unit: grams, millilitres, or the count word
itself (pcs, tin, bunch...).
"""
WEIGHT = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "l": 1000.0, "cup": 250.0, "tbsp": 15.0, "tsp": 5.0}
COUNTS = ["pcs", "tin", "sachet", "bunch", "bag", "bottle", "loaf", "tray", "ball"]
UNITS = list(WEIGHT) + list(VOLUME) + COUNTS


def base_of(unit):
    """The unit a quantity is stored and added up in."""
    if unit in WEIGHT:
        return "g"
    if unit in VOLUME:
        return "ml"
    return unit or "pcs"


def to_base(qty, unit):
    """(quantity in base unit, base unit)."""
    if unit in WEIGHT:
        return qty * WEIGHT[unit], "g"
    if unit in VOLUME:
        return qty * VOLUME[unit], "ml"
    return qty, unit or "pcs"


def same_kind(unit_a, unit_b):
    return base_of(unit_a) == base_of(unit_b)


def _num(x):
    """1.0 -> '1', 1.5 -> '1.5', 0.333 -> '0.33'."""
    s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def fmt(qty, base):
    """A stored quantity in the most natural unit: 1500 g -> '1.5 kg', 3 pcs -> '3 pcs'."""
    if qty is None:
        return ""
    if base == "g":
        return f"{_num(qty / 1000)} kg" if abs(qty) >= 1000 else f"{_num(qty)} g"
    if base == "ml":
        return f"{_num(qty / 1000)} l" if abs(qty) >= 1000 else f"{_num(qty)} ml"
    if base == "pcs":
        return _num(qty)
    word = base if abs(qty) == 1 or base.endswith("s") else base + ("es" if base.endswith(("ch", "sh")) else "s")
    return f"{_num(qty)} {word}"


def from_base(qty, base, unit):
    """A stored quantity in the unit someone typed it in (for showing it back to them)."""
    if unit in WEIGHT and base == "g":
        return qty / WEIGHT[unit]
    if unit in VOLUME and base == "ml":
        return qty / VOLUME[unit]
    return qty

"""Units of measure for ingredients.

Weights and volumes convert automatically (500 g + 1 kg = 1.5 kg). Counted things
("3 onions", "2 tins") stay as they are: an onion has no fixed weight.

Items can also have a container they're bought and stored in: a crate of 30 eggs,
a 5 kg bag of rice, a 1.5 l bottle of oil, a pack of 10 stock cubes. Recipes can use
either the container ("1 crate") or the usual unit ("4 eggs"), and both add up.

Every quantity is stored in a "base" unit: grams, millilitres, or the count word
itself (pcs, tin, bunch...).
"""
import math

WEIGHT = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "l": 1000.0, "cup": 250.0, "tbsp": 15.0, "tsp": 5.0}
COUNTS = ["pcs", "tin", "sachet", "bunch", "bag", "bottle", "loaf", "tray", "ball"]
# what things are bought and stored in
CONTAINERS = ["crate", "bag", "bottle", "can", "tin", "pack", "packet", "sachet", "box", "jar", "tray", "bunch",
              "loaf", "ball", "carton", "gallon", "bucket", "olonka"]
UNITS = list(WEIGHT) + list(VOLUME) + list(dict.fromkeys(COUNTS + CONTAINERS))
LEFTOVER_UNITS = ["portion", "serving", "bowl", "plate", "container"]

_IRREGULAR = {"loaf": "loaves", "pcs": "pcs", "olonka": "olonkas"}


def plural(word, n=2):
    if abs(n - 1) < 1e-9 or word in WEIGHT or word in VOLUME:
        return word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word.endswith(("ch", "sh", "x", "s")):
        return word + "es"
    return word + "s"


def base_of(unit):
    """The unit a quantity is stored and added up in."""
    if unit in WEIGHT:
        return "g"
    if unit in VOLUME:
        return "ml"
    return unit or "pcs"


def units_for(unit, pack=None):
    """The few units that make sense for one item, so nobody scrolls past 30 to find "bag".
    Rice counted in kg offers kg, g and its bag; eggs offer pcs and the crate."""
    base = base_of(unit)
    if base == "g":
        out = ["kg", "g"] if unit == "kg" else ["g", "kg"]
    elif base == "ml":
        out = [unit] + [u for u in VOLUME if u != unit]
    else:
        out = [unit or "pcs"]
    if pack and pack[0] and pack[0] not in out:
        out.insert(0, pack[0])
    return out


def to_base(qty, unit, pack=None):
    """(quantity in base unit, base unit).

    pack is the ingredient's container as (name, size in base unit, base), e.g. ("crate", 30, "pcs").
    A quantity given in that container converts to the base: 2 crates -> 60 pcs.
    """
    if pack and unit == pack[0] and pack[1]:
        return qty * float(pack[1]), pack[2]
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
    return f"{_num(qty)} {plural(base, qty)}"


def fmt_stock(qty, base, pack=None):
    """A quantity the way it sits on the shelf: '1 crate + 6', '1.5 bags (7.5 kg)', '2 bottles'."""
    if not pack or not pack[1] or pack[2] != base or qty < float(pack[1]) - 1e-9:
        return fmt(qty, base)
    name, size = pack[0], float(pack[1])
    if base in ("g", "ml"):
        n = qty / size
        return f"{_num(n)} {plural(name, n)} ({fmt(qty, base)})"
    whole = math.floor(qty / size + 1e-9)
    rest = qty - whole * size
    out = f"{whole} {plural(name, whole)}"
    return out + (f" + {fmt(rest, base)}" if rest > 1e-9 else "")


def packs_for(qty, pack):
    """Whole containers needed to cover qty (base unit): 12 eggs with crates of 30 -> 1."""
    if not pack or not pack[1]:
        return None
    return max(math.ceil(qty / float(pack[1]) - 1e-9), 1)


def from_base(qty, base, unit, pack=None):
    """A stored quantity in the unit someone typed it in (for showing it back to them)."""
    if pack and unit == pack[0] and pack[1] and pack[2] == base:
        return qty / float(pack[1])
    if unit in WEIGHT and base == "g":
        return qty / WEIGHT[unit]
    if unit in VOLUME and base == "ml":
        return qty / VOLUME[unit]
    return qty

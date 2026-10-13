"""Units of measure for ingredients.

Weights and volumes convert automatically (500 g + 1 kg = 1.5 kg). Counted things
("3 onions", "2 tins") stay as they are: an onion has no fixed weight.

Items can also have a container they're bought and stored in: a crate of 30 eggs,
a 5 kg bag of rice, a 1.5 l bottle of oil, a pack of 10 stock cubes. Recipes can use
either the container ("1 crate") or the usual unit ("4 eggs"), and both add up.

Every quantity is stored in a "base" unit: grams, millilitres, or the count word
itself (pcs, tin, bunch...). Cups, tablespoons and teaspoons are volumes (stored in ml) but are
shown back in the cook's own measure: "3 cups of rice", not "750 ml of rice".

An item can also be "sold loose" (onions, tomatoes, plantain): its container is known (a bag of
40 onions) but the shopping list asks for 5 onions, not a whole bag. And it can have other units
besides its container, e.g. Sankofa spice in a 5 tsp sachet or an 80 tsp container, or margarine
by the tablespoon (15 g). A pack is (container, size in base unit, base unit[, loose[, {unit: size}]]).
"""
import math

WEIGHT = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "l": 1000.0, "cup": 250.0, "tbsp": 15.0, "tsp": 5.0}
COUNTS = ["pcs", "tin", "sachet", "bunch", "bag", "bottle", "loaf", "tray", "ball", "teabag", "slice", "finger",
          "clove"]
KITCHEN = ("cup", "tbsp", "tsp")  # volumes the cook measures with; shown as they are, not as ml
# what things are bought and stored in
CONTAINERS = ["crate", "bag", "bottle", "can", "tin", "pack", "packet", "sachet", "box", "jar", "tray", "bunch",
              "loaf", "ball", "carton", "gallon", "bucket", "olonka", "tub", "pouch", "basket", "thumb", "bulb", "set",
              "tuber", "bundle", "kilo", "container"]
UNITS = list(WEIGHT) + list(VOLUME) + list(dict.fromkeys(COUNTS + CONTAINERS))
LEFTOVER_UNITS = ["portion", "serving", "bowl", "plate", "container"]

_IRREGULAR = {"loaf": "loaves", "pcs": "pcs", "olonka": "olonkas"}
_NO_PLURAL = {"g", "kg", "ml", "l", "tbsp", "tsp", "pcs"}


def plural(word, n=2):
    if 0 < float(n) <= 1 + 1e-9 or word in _NO_PLURAL:  # 1 crate, ½ crate, 2 crates, 3 cups, 2 tbsp
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


def loose(pack):
    """True when the item is bought by the piece even though it also comes in a container."""
    return bool(pack and len(pack) > 3 and pack[3])


def alts(pack):
    """Other units this item can be measured in: {unit: size in base unit}."""
    return (pack[4] or {}) if pack and len(pack) > 4 else {}


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
    for extra in alts(pack):
        if extra not in out:
            out.append(extra)
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
    if unit in alts(pack):
        return qty * float(alts(pack)[unit]), pack[2]
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


FRACTIONS = {0.25: "¼", 1 / 3: "⅓", 0.5: "½", 2 / 3: "⅔", 0.75: "¾"}


def frac(x):
    """Counts and portions the way people say them: 1.5 -> '1½', 0.25 -> '¼', 3 -> '3', 1.2 -> '1.2'."""
    if x is None:
        return ""
    x = float(x)
    whole = math.floor(x + 1e-9)
    rest = x - whole
    if rest < 0.01:
        return f"{whole:,}"
    for value, sign in FRACTIONS.items():
        if abs(rest - value) < 0.01:
            return (f"{whole:,}" if whole else "") + sign
    return _num(x)


QUICK = [0.25, 0.5, 1, 1.5, 2, 3]  # one-tap amounts on a phone, where typing "1/2" isn't possible


def fmt(qty, base, usual=None):
    """A stored quantity in the most natural unit: 1500 g -> '1.5 kg', 3 pcs -> '3'.
    usual: the item's own unit; cups, tbsp and tsp are shown as such (750 ml of rice counted in cups -> '3 cups')."""
    if qty is None:
        return ""
    if usual in KITCHEN and base == "ml":
        n = qty / VOLUME[usual]
        return f"{frac(n)} {plural(usual, n)}"
    if base == "g":
        return f"{_num(qty / 1000)} kg" if abs(qty) >= 1000 else f"{_num(qty)} g"
    if base == "ml":
        return f"{_num(qty / 1000)} l" if abs(qty) >= 1000 else f"{_num(qty)} ml"
    if base == "pcs":
        return frac(qty)
    return f"{frac(qty)} {plural(base, qty)}"


def fmt_stock(qty, base, pack=None, usual=None):
    """A quantity the way it sits on the shelf: '1 crate + 6', '1.5 bags (7.5 kg)', '2 bottles'."""
    if not pack or not pack[1] or pack[2] != base or qty < float(pack[1]) - 1e-9:
        return fmt(qty, base, usual)
    name, size = pack[0], float(pack[1])
    if base in ("g", "ml"):
        n = qty / size
        return f"{_num(n)} {plural(name, n)} ({fmt(qty, base, usual)})"
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
    if unit in alts(pack) and pack[2] == base:
        return qty / float(alts(pack)[unit])
    if unit in WEIGHT and base == "g":
        return qty / WEIGHT[unit]
    if unit in VOLUME and base == "ml":
        return qty / VOLUME[unit]
    return qty

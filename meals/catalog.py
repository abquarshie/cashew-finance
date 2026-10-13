"""The Ghanaian kitchen catalog: everyday ingredients with how they're bought and measured, classic soup and
stew templates, the starches they're eaten with, and ready-made pairings for the planner.

It is added to the database once (see seed()), alongside anything already there:
- an item that already exists under the same name (any capitals) is kept as it is; only a missing
  container or shelf is filled in, and only when it's measured the same way;
- a recipe or pairing that already exists by name is left alone;
- after that, everything can be changed or deleted in the app, and nothing comes back.

No Streamlit here: it runs inside ensure_schema(), so the daily job can set a new database up too.
"""
import json

from meals.units import base_of, to_base

FLAG = "seeded_kitchen_gh1"

DAIRY, GRAINS, PROTEIN, AROMATICS, SANKOFA, BASICS = (
    "Dairy, beverages & pantry", "Grains & starches", "Proteins & seafood", "Oils, sauces & aromatics",
    "Sankofa spices", "Soup & stew basics")
SECTIONS = [DAIRY, GRAINS, PROTEIN, AROMATICS, SANKOFA, BASICS]

# (shelf, name, base unit, money category, purchase unit, how many base units in one, sold loose, {other unit: base units})
# "Base unit" is what recipes and the pantry count in; the purchase unit is what you bring home from the market.
CATALOG = [
    # ---- dairy, beverages and pantry: specific household products ----
    (DAIRY, "Lele Gold evaporated milk (400g)", "tbsp", "Dairy/Cereal", "tin", 16, False, None),
    (DAIRY, "Lipton Yellow Label tea", "teabag", "Dairy/Cereal", "pack", 25, False, None),
    (DAIRY, "Josd brown cocoa powder (400g)", "tbsp", "Dairy/Cereal", "jar", 80, False, None),
    (DAIRY, "Cook Brand margarine (900g)", "g", "Dairy/Cereal", "tub", 900, False, {"tbsp": 15}),   # ~60 tbsp a tub
    (DAIRY, "Pride of the West flour (2kg)", "cup", "Staples", "bag", 16, False, {"kg": 8}),          # 16 cups = 2 kg
    # ---- grains and starches ----
    (GRAINS, "A55 Gold jasmine rice (5kg)", "cup", "Staples", "bag", 25, False, {"kg": 5}),          # 25 cups = 5 kg
    (GRAINS, "Black-eyed peas (beans)", "cup", "Staples", "olonka", 6, False, None),
    (GRAINS, "Yam", "slice", "Staples", "tuber", 8, False, None),
    (GRAINS, "Plantain", "finger", "Fruits/Veges", "bundle", 5, True, None),
    (GRAINS, "Gari", "cup", "Staples", "olonka", 8, False, None),
    (GRAINS, "Kokonte powder", "cup", "Staples", "bag", 10, False, None),
    (GRAINS, "Fermented corn dough", "cup", "Staples", "kilo", 4, False, None),
    (GRAINS, "Fermented cassava dough", "cup", "Staples", "kilo", 4, False, None),
    (GRAINS, "Cassava", "kg", "Staples", None, None, False, None),
    # ---- proteins and seafood: meat is bought by the kilo (1 kg = 1000 g) ----
    (PROTEIN, "Fresh tilapia", "kg", "Meat/Fish", None, None, False, None),
    (PROTEIN, "Hard chicken", "kg", "Meat/Fish", None, None, False, None),
    (PROTEIN, "Beef", "kg", "Meat/Fish", None, None, False, None),
    (PROTEIN, "Goat meat", "kg", "Meat/Fish", None, None, False, None),
    (PROTEIN, "Crabs", "pcs", "Meat/Fish", "set", 6, False, None),
    (PROTEIN, "Snails", "pcs", "Meat/Fish", "set", 6, False, None),
    (PROTEIN, "Adɔde (Volta clams)", "cup", "Meat/Fish", None, None, False, None),
    (PROTEIN, "Eggs", "pcs", "Dairy/Cereal", "crate", 30, False, None),
    (PROTEIN, "Smoked mackerel", "pcs", "Meat/Fish", None, None, False, None),
    # ---- oils, sauces and aromatics ----
    (AROMATICS, "Tasty Tom tomato mix", "tbsp", "Canned or Sachet items", "pouch", 4, False, None),
    (AROMATICS, "Vegetable oil", "l", "Oils", "bottle", 1, False, None),
    (AROMATICS, "Palm oil", "l", "Oils", "bottle", 1, False, None),
    (AROMATICS, "Tomato paste", "tbsp", "Canned or Sachet items", "tin", 4, False, None),
    (AROMATICS, "Tomatoes", "pcs", "Fruits/Veges", "basket", 35, True, None),       # medium tomatoes, 5 kg basket
    (AROMATICS, "Onions", "pcs", "Fruits/Veges", "bag", 40, True, None),            # medium onions
    (AROMATICS, "Ginger", "tbsp", "Spices", "thumb", 1.5, False, None),             # 1 thumb = 1.5 tbsp blended
    (AROMATICS, "Garlic", "clove", "Spices", "bulb", 6, False, None),
    (AROMATICS, "Pepper", "pcs", "Fruits/Veges", None, None, False, None),
    # ---- what the soup and stew templates need besides the above ----
    (BASICS, "Garden eggs", "pcs", "Fruits/Veges", None, None, False, None),
    (BASICS, "Kontomire", "bunch", "Fruits/Veges", None, None, False, None),
    (BASICS, "Okro", "pcs", "Fruits/Veges", None, None, False, None),
    (BASICS, "Groundnut paste", "g", "Canned or Sachet items", "jar", 500, False, None),
    (BASICS, "Palm nut cream", "g", "Canned or Sachet items", "tin", 800, False, None),
]
# Sankofa natural spices: every flavour comes as a 25 g sachet (5 tsp) or a 400 g container (80 tsp)
SANKOFA_FLAVOURS = ["Stew & Gravy", "Soup Seasoning", "Jollof Rice", "Chicken", "Beef", "Fish", "Noodles & Pasta",
                    "Ginger & Garlic", "Hot Pepper Blend", "Curry Powder"]
CATALOG += [(SANKOFA, f"Sankofa {f}", "tsp", "Spices", "sachet", 5, False, {"container": 80}) for f in SANKOFA_FLAVOURS]

# When a database already has one of these items measured another way (the old starter recipes counted
# ginger in grams and garlic in pieces), template amounts are converted with these rough equivalents:
# {item: {that base unit: how much of it one catalog unit is}}. Without an equivalent the line is skipped.
EQUIV = {
    "ginger": {"g": 10},              # 1 tbsp blended ginger ≈ 10 g
    "garlic": {"pcs": 1},             # 1 clove = 1 piece
    "tomato paste": {"sachet": 0.25},  # a 70 g sachet ≈ 4 tbsp
    "gari": {"g": 150},               # 1 cup ≈ 150 g
    "plantain": {"pcs": 1},
}

POT = 14  # soups and stews serve 2 people for a week: 2 x 7 portions

# name, role, portions, keeps (days), prep note, prep hours ahead, method, [(item, qty, unit)]
TEMPLATES = [
    # ---- the soups and stews: one big pot for the week ----
    ("Light soup", "soup", POT, 7, "Season the goat meat", 3,
     "Season and steam the goat meat with onion, ginger and garlic. Boil tomatoes, pepper, onion and garden eggs, "
     "blend, sieve into the meat and simmer 30 minutes.",
     [("Goat meat", 1.5, "kg"), ("Tomatoes", 10, "pcs"), ("Onions", 3, "pcs"), ("Pepper", 6, "pcs"),
      ("Garden eggs", 6, "pcs"), ("Ginger", 2, "tbsp"), ("Garlic", 6, "clove"), ("Sankofa Soup Seasoning", 3, "tsp")]),
    ("Groundnut soup", "soup", POT, 7, "Season the chicken", 3,
     "Steam the seasoned chicken. Loosen the groundnut paste with water and cook until the oil rises. Add blended "
     "tomatoes, onion and pepper, then the chicken, and simmer until thick.",
     [("Hard chicken", 1.5, "kg"), ("Groundnut paste", 500, "g"), ("Tomatoes", 6, "pcs"), ("Tomato paste", 4, "tbsp"),
      ("Onions", 3, "pcs"), ("Pepper", 5, "pcs"), ("Ginger", 2, "tbsp"), ("Garlic", 4, "clove"),
      ("Sankofa Chicken", 3, "tsp")]),
    ("Palm nut soup", "soup", POT, 7, None, None,
     "Steam the beef with onion. Stir the palm nut cream into water and boil. Add blended tomatoes, pepper and "
     "garden eggs, then the beef, crabs and fish, and simmer until the oil rises.",
     [("Palm nut cream", 800, "g"), ("Beef", 1, "kg"), ("Smoked mackerel", 2, "pcs"), ("Crabs", 6, "pcs"),
      ("Tomatoes", 5, "pcs"), ("Onions", 3, "pcs"), ("Pepper", 5, "pcs"), ("Garden eggs", 6, "pcs"),
      ("Sankofa Soup Seasoning", 3, "tsp")]),
    ("Okra soup", "soup", POT, 7, None, None,
     "Steam the beef. Fry onion, tomatoes and pepper in palm oil, add the meat stock, crabs and fish, then the "
     "chopped okro, and cook 10 minutes.",
     [("Okro", 30, "pcs"), ("Beef", 1, "kg"), ("Smoked mackerel", 2, "pcs"), ("Crabs", 6, "pcs"),
      ("Palm oil", 150, "ml"), ("Tomatoes", 5, "pcs"), ("Onions", 2, "pcs"), ("Pepper", 5, "pcs"),
      ("Sankofa Fish", 2, "tsp")]),
    ("Tomato stew", "stew", POT, 7, "Season the beef", 3,
     "Season and brown the beef. Fry sliced onions in the oil, add the paste, then blended tomatoes, pepper, ginger "
     "and garlic. Cook down until the oil rises, then add the beef.",
     [("Beef", 1, "kg"), ("Tomatoes", 15, "pcs"), ("Tomato paste", 8, "tbsp"), ("Onions", 4, "pcs"),
      ("Vegetable oil", 400, "ml"), ("Pepper", 4, "pcs"), ("Ginger", 2, "tbsp"), ("Garlic", 6, "clove"),
      ("Sankofa Stew & Gravy", 4, "tsp")]),
    ("Kontomire stew", "stew", POT, 7, None, None,
     "Boil and chop the kontomire. Fry onions and tomatoes in palm oil, add pepper, the flaked fish and kontomire, "
     "then stir in beaten eggs.",
     [("Kontomire", 4, "bunch"), ("Palm oil", 250, "ml"), ("Onions", 3, "pcs"), ("Tomatoes", 6, "pcs"),
      ("Pepper", 4, "pcs"), ("Smoked mackerel", 3, "pcs"), ("Eggs", 6, "pcs"), ("Sankofa Fish", 2, "tsp")]),
    # ---- the starches: cooked fresh for each meal, for 2 people ----
    ("Kokonte", "starch", 2, 1, None, None,
     "Stir the powder into boiling water a little at a time, then turn firmly until smooth.",
     [("Kokonte powder", 1.5, "cup")]),
    ("Fufu", "starch", 2, 1, None, None,
     "Boil peeled cassava and green plantain until soft, then pound together until smooth and stretchy.",
     [("Cassava", 1, "kg"), ("Plantain", 2, "finger")]),
    ("Banku", "starch", 2, 1, None, None,
     "Mix both doughs with water and a pinch of salt, then cook, turning all the time, until firm and smooth.",
     [("Fermented corn dough", 1.5, "cup"), ("Fermented cassava dough", 0.5, "cup")]),
    ("Plain rice", "starch", 2, 2, None, None, "Wash the rice and steam it with salted water until done.",
     [("A55 Gold jasmine rice (5kg)", 1.5, "cup")]),
    ("Waakye", "starch", 2, 2, "Soak the beans", 10,
     "Boil the soaked beans with waakye leaves until half soft, add the washed rice and cook until done.",
     [("A55 Gold jasmine rice (5kg)", 1, "cup"), ("Black-eyed peas (beans)", 0.5, "cup")]),
    ("Boiled yam", "starch", 2, 1, None, None, "Peel the slices and boil in salted water until soft.",
     [("Yam", 4, "slice")]),
    ("Boiled plantain", "starch", 2, 1, None, None, "Peel and boil the plantain until soft.",
     [("Plantain", 3, "finger")]),
]

# name, [dishes], side item eaten with it (item, amount per person, unit) or None
PAIRINGS = [
    ("Kokonte + Palm nut soup", ["Kokonte", "Palm nut soup"], None),
    ("Kokonte + Groundnut soup", ["Kokonte", "Groundnut soup"], None),
    ("Fufu + Light soup", ["Fufu", "Light soup"], None),
    ("Fufu + Palm nut soup", ["Fufu", "Palm nut soup"], None),
    ("Fufu + Groundnut soup", ["Fufu", "Groundnut soup"], None),
    ("Banku + Okra soup", ["Banku", "Okra soup"], None),
    ("Banku + Light soup", ["Banku", "Light soup"], None),
    ("Waakye + Stew + Gari", ["Waakye", "Tomato stew"], ("Gari", 0.5, "cup")),
    ("Plain rice + Tomato stew", ["Plain rice", "Tomato stew"], None),
    ("Boiled yam + Kontomire stew", ["Boiled yam", "Kontomire stew"], None),
    ("Boiled plantain + Kontomire stew", ["Boiled plantain", "Kontomire stew"], None),
]


def _pack_info(unit, pack, size, alt_units):
    """(pack size in base units, {other unit: base units}) from sizes given in the item's own unit."""
    one = to_base(1, unit)[0]
    pack_base = float(size) * one if pack and size else None
    alts = {u: round(float(v) * one, 6) for u, v in (alt_units or {}).items()} or None
    return pack_base, alts


def _items(cur):
    """{lower-case name: (id, unit, pack_name, pack_size, alt_units)} for every ingredient."""
    cur.execute("SELECT id, name, unit, pack_name, pack_size, alt_units FROM meals.ingredients")
    return {n.lower(): (i, u, pn, ps, au) for i, n, u, pn, ps, au in cur.fetchall()}


def line_amount(item, qty, unit):
    """A recipe line in the unit the item is actually kept in: (qty, unit), or None if it can't be converted.
    item: (id, unit, pack_name, pack_size, alt_units) as _items() returns it, plus the item's name."""
    _, have_unit, pack_name, pack_size, alt_units = item[:5]
    name = item[5] if len(item) > 5 else ""
    if base_of(unit) == base_of(have_unit) or unit == pack_name or unit in (alt_units or {}):
        return qty, unit
    per = EQUIV.get(name.lower(), {}).get(base_of(have_unit))
    if per is None:
        return None
    base = base_of(have_unit)
    return round(float(qty) * per, 3), (have_unit if base_of(have_unit) == have_unit else base)


def add_items(cur, rows, expense_categories):
    """Add catalog rows, reusing items that already exist by name. Returns {name: item tuple}."""
    fallback = "Staples" if "Staples" in expense_categories else (expense_categories[0] if expense_categories else None)
    have = _items(cur)
    out = {}
    for section, name, unit, cat, pack, size, loose, alt_units in rows:
        pack_base, alts = _pack_info(unit, pack, size, alt_units)
        found = have.get(name.lower())
        if found:
            iid, have_unit, have_pack, _, _ = found
            same = base_of(have_unit) == base_of(unit)
            if same and not have_pack and pack:
                cur.execute("UPDATE meals.ingredients SET pack_name = %s, pack_size = %s, loose = %s, alt_units = %s "
                            "WHERE id = %s", (pack, pack_base, loose, json.dumps(alts) if alts else None, iid))
            elif same and alts and have_pack == pack:
                cur.execute("UPDATE meals.ingredients SET alt_units = COALESCE(alt_units, %s), loose = loose OR %s "
                            "WHERE id = %s", (json.dumps(alts), loose, iid))
            cur.execute("UPDATE meals.ingredients SET section = COALESCE(section, %s) WHERE id = %s", (section, iid))
        else:
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, pack_name, pack_size, loose, alt_units, "
                        "section) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (name, unit, cat if cat in expense_categories else fallback, pack, pack_base, loose,
                         json.dumps(alts) if alts else None, section))
            iid = cur.fetchone()[0]
    have = _items(cur)
    for row in rows:
        out[row[1]] = have[row[1].lower()] + (row[1],)
    return out


def add_recipes(cur, recipes, with_role=True):
    """Add recipes by name (skipping names already used). Lines whose item is missing or can't be converted are
    left out. Returns how many recipes were added."""
    items = {k: v + (k,) for k, v in _items(cur).items()}
    cur.execute("SELECT lower(name) FROM meals.recipes")
    taken = {r[0] for r in cur.fetchall()}
    added = 0
    for rec in recipes:
        if with_role:
            name, role, portions, keeps, note, hours, method, lines = rec
        else:
            (name, portions, keeps, note, hours, method, lines), role = rec, "main"
        if name.lower() in taken:
            continue
        cur.execute("INSERT INTO meals.recipes (name, portions, keeps_days, prep_note, prep_hours, method, role) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (name, portions, keeps, note, hours, method, role))
        rid = cur.fetchone()[0]
        for item, qty, unit in lines:
            found = items.get(item.lower())
            amount = line_amount(found, qty, unit) if found else None
            if amount:
                cur.execute("INSERT INTO meals.recipe_items (recipe_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (rid, found[0], amount[0], amount[1]))
        taken.add(name.lower())
        added += 1
    return added


def add_pairings(cur, pairings=PAIRINGS):
    items = {k: v + (k,) for k, v in _items(cur).items()}
    cur.execute("SELECT lower(name), id FROM meals.recipes")
    recipes = dict(cur.fetchall())
    cur.execute("SELECT lower(name) FROM meals.pairings")
    taken = {r[0] for r in cur.fetchall()}
    added = 0
    for name, dishes, side in pairings:
        ids = [recipes.get(d.lower()) for d in dishes]
        if name.lower() in taken or None in ids:
            continue
        cur.execute("INSERT INTO meals.pairings (name) VALUES (%s) RETURNING id", (name,))
        pid = cur.fetchone()[0]
        for rid in ids:
            cur.execute("INSERT INTO meals.pairing_items (pairing_id, recipe_id) VALUES (%s, %s)", (pid, rid))
        if side:
            found = items.get(side[0].lower())
            amount = line_amount(found, side[1], side[2]) if found else None
            if amount:
                cur.execute("INSERT INTO meals.pairing_items (pairing_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (pid, found[0], amount[0], amount[1]))
        added += 1
    return added


def seed(cur):
    """Add the catalog, templates and pairings to this database, once."""
    cur.execute("SELECT 1 FROM app_meta WHERE key = %s", (FLAG,))
    if cur.fetchone():
        return False
    cur.execute("SELECT name FROM categories WHERE kind = 'Expense' ORDER BY id")
    expense = [r[0] for r in cur.fetchall()]
    add_items(cur, CATALOG, expense)
    add_recipes(cur, TEMPLATES)
    add_pairings(cur)
    cur.execute("INSERT INTO app_meta (key, value) VALUES (%s, 'yes') ON CONFLICT (key) DO NOTHING", (FLAG,))
    return True

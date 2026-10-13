"""A few everyday Ghanaian dishes to start the recipe book with. Quantities are typical for
4 portions; edit them to match how your family cooks."""

# name, usual unit, money category, running-low level (usual unit), container it's bought in, container size (usual unit)
# Units match the Ghanaian kitchen catalog (meals/catalog.py): ginger in tablespoons, garlic in cloves, gari in cups.
INGREDIENTS = [
    ("Rice", "kg", "Staples", 1, "bag", 5), ("Black-eyed beans", "kg", "Staples", 0.5, "bag", 1),
    ("Gari", "cup", "Staples", 2, "olonka", 8), ("Fermented corn dough", "cup", "Staples", None, "kilo", 4),
    ("Onions", "pcs", "Fruits/Veges", 3, "bag", 40, True), ("Tomatoes", "pcs", "Fruits/Veges", None, "basket", 35, True),
    ("Pepper", "pcs", "Fruits/Veges", None, None, None), ("Ripe plantain", "finger", "Fruits/Veges", None, "bundle", 5, True),
    ("Green plantain", "finger", "Fruits/Veges", None, "bundle", 5, True),
    ("Kontomire", "bunch", "Fruits/Veges", None, None, None),
    ("Okro", "pcs", "Fruits/Veges", None, None, None), ("Ginger", "tbsp", "Spices", 3, "thumb", 1.5),
    ("Garlic", "clove", "Spices", 3, "bulb", 6), ("Stock cubes", "pcs", "Spices", 4, "pack", 10),
    ("Tomato paste", "tbsp", "Canned or Sachet items", 4, "tin", 4),
    ("Vegetable oil", "l", "Oils", 0.5, "bottle", 1.5), ("Palm oil", "l", "Oils", 0.25, "bottle", 1),
    ("Chicken", "kg", "Meat/Fish", None, None, None), ("Smoked mackerel", "pcs", "Meat/Fish", None, None, None),
    ("Eggs", "pcs", "Dairy/Cereal", 4, "crate", 30), ("Milk", "tin", "Dairy/Cereal", 1, None, None),
    ("Bread", "loaf", "Bakery", None, None, None),
]

# name, portions, keeps (days), prep note, prep hours ahead, method, [(ingredient, qty, unit)]
RECIPES = [
    ("Jollof rice with chicken", 4, 3, "Season the chicken", 3,
     "Season and brown the chicken. Fry onions, blended tomatoes, pepper and paste; add stock, then rice. "
     "Cover and steam until done.",
     [("Rice", 750, "g"), ("Chicken", 1, "kg"), ("Tomatoes", 5, "pcs"), ("Tomato paste", 4, "tbsp"),
      ("Onions", 3, "pcs"), ("Vegetable oil", 150, "ml"), ("Pepper", 3, "pcs"), ("Ginger", 3, "tbsp"),
      ("Garlic", 3, "clove"), ("Stock cubes", 2, "pcs")]),
    ("Red red", 4, 2, "Soak the beans", 10,
     "Boil the soaked beans until soft. Fry onions, tomatoes and pepper in palm oil, add fish and beans. "
     "Serve with fried ripe plantain and gari.",
     [("Black-eyed beans", 500, "g"), ("Palm oil", 150, "ml"), ("Onions", 2, "pcs"), ("Tomatoes", 3, "pcs"),
      ("Pepper", 2, "pcs"), ("Smoked mackerel", 1, "pcs"), ("Ripe plantain", 4, "finger"), ("Gari", 1.5, "cup")]),
    ("Kontomire stew with plantain", 4, 2, None, None,
     "Boil the green plantain. Fry onions and tomatoes in palm oil, add chopped kontomire, fish and beaten eggs.",
     [("Kontomire", 2, "bunch"), ("Palm oil", 100, "ml"), ("Onions", 2, "pcs"), ("Tomatoes", 4, "pcs"),
      ("Pepper", 2, "pcs"), ("Smoked mackerel", 2, "pcs"), ("Eggs", 4, "pcs"), ("Green plantain", 4, "finger")]),
    ("Okro stew with banku", 4, 2, None, None,
     "Cook the banku from corn dough. Fry onions, tomatoes and pepper in palm oil, add fish and chopped okro.",
     [("Okro", 20, "pcs"), ("Fermented corn dough", 4, "cup"), ("Palm oil", 100, "ml"), ("Smoked mackerel", 2, "pcs"),
      ("Onions", 1, "pcs"), ("Tomatoes", 3, "pcs"), ("Pepper", 3, "pcs")]),
    ("Light soup with chicken", 4, 3, None, None,
     "Steam the seasoned chicken. Boil tomatoes, onions and pepper, blend, and simmer with the chicken.",
     [("Chicken", 1, "kg"), ("Tomatoes", 6, "pcs"), ("Onions", 2, "pcs"), ("Pepper", 3, "pcs"), ("Ginger", 2, "tbsp"),
      ("Garlic", 2, "clove"), ("Stock cubes", 1, "pcs")]),
    ("Bread, eggs and tea", 4, 1, None, None, "Fry or boil the eggs; serve with bread and tea with milk.",
     [("Bread", 1, "loaf"), ("Eggs", 4, "pcs"), ("Milk", 1, "tin")]),
]


# Household supplies: (name, counted in, warn when down to, bought in, each holds)
SUPPLIES = [
    ("Washing powder", "kg", 0.5, "pack", 1),
    ("Dishwashing liquid", "ml", 200, "bottle", 500),
    ("Bleach", "ml", 250, "bottle", 1000),
    ("Disinfectant", "ml", 100, "bottle", 500),
    ("Toilet roll", "pcs", 4, "pack", 10),
    ("Bathing soap", "pcs", 2, "pack", 3),
    ("Bar soap for washing", "pcs", 1, None, None),
    ("Sponges", "pcs", 1, "pack", 3),
    ("Bin bags", "pcs", 5, "pack", 20),
]


def load_starter(conn, expense_categories):
    """Add the starter ingredients and recipes. Items already there (any capitals, e.g. from the catalog)
    are reused, and recipe names already used are skipped. Returns how many recipes were added."""
    from meals.catalog import add_items, add_recipes
    rows = []
    for name, unit, cat, low, pack, size, *rest in INGREDIENTS:
        rows.append((None, name, unit, cat, pack, size, bool(rest and rest[0]), None))
    with conn.cursor() as cur:
        items = add_items(cur, rows, expense_categories)
        from meals.units import to_base
        for name, unit, _, low, *_ in INGREDIENTS:  # warning levels, only where none is set yet
            if low is not None and items[name][1] == unit:
                cur.execute("UPDATE meals.ingredients SET low_level = COALESCE(low_level, %s) WHERE id = %s",
                            (to_base(low, unit)[0], items[name][0]))
        return add_recipes(cur, RECIPES, with_role=False)

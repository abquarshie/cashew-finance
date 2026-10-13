"""A few everyday Ghanaian dishes to start the recipe book with. Quantities are typical for
4 portions; edit them to match how your family cooks."""

# name, usual unit, money category, running-low level (usual unit), container it's bought in, container size (usual unit)
INGREDIENTS = [
    ("Rice", "kg", "Staples", 1, "bag", 5), ("Black-eyed beans", "kg", "Staples", 0.5, "bag", 1),
    ("Gari", "kg", "Staples", 0.5, "bag", 1), ("Corn dough", "kg", "Staples", None, None, None),
    ("Onions", "pcs", "Fruits/Veges", 3, None, None), ("Tomatoes", "pcs", "Fruits/Veges", None, None, None),
    ("Pepper", "pcs", "Fruits/Veges", None, None, None), ("Ripe plantain", "pcs", "Fruits/Veges", None, None, None),
    ("Green plantain", "pcs", "Fruits/Veges", None, None, None), ("Kontomire", "bunch", "Fruits/Veges", None, None, None),
    ("Okro", "pcs", "Fruits/Veges", None, None, None), ("Ginger", "g", "Spices", 50, None, None),
    ("Garlic", "pcs", "Spices", 2, None, None), ("Stock cubes", "pcs", "Spices", 4, "pack", 10),
    ("Tomato paste", "sachet", "Canned or Sachet items", 2, None, None),
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
     [("Rice", 750, "g"), ("Chicken", 1, "kg"), ("Tomatoes", 5, "pcs"), ("Tomato paste", 2, "sachet"),
      ("Onions", 3, "pcs"), ("Vegetable oil", 150, "ml"), ("Pepper", 3, "pcs"), ("Ginger", 30, "g"),
      ("Garlic", 3, "pcs"), ("Stock cubes", 2, "pcs")]),
    ("Red red", 4, 2, "Soak the beans", 10,
     "Boil the soaked beans until soft. Fry onions, tomatoes and pepper in palm oil, add fish and beans. "
     "Serve with fried ripe plantain and gari.",
     [("Black-eyed beans", 500, "g"), ("Palm oil", 150, "ml"), ("Onions", 2, "pcs"), ("Tomatoes", 3, "pcs"),
      ("Pepper", 2, "pcs"), ("Smoked mackerel", 1, "pcs"), ("Ripe plantain", 4, "pcs"), ("Gari", 200, "g")]),
    ("Kontomire stew with plantain", 4, 2, None, None,
     "Boil the green plantain. Fry onions and tomatoes in palm oil, add chopped kontomire, fish and beaten eggs.",
     [("Kontomire", 2, "bunch"), ("Palm oil", 100, "ml"), ("Onions", 2, "pcs"), ("Tomatoes", 4, "pcs"),
      ("Pepper", 2, "pcs"), ("Smoked mackerel", 2, "pcs"), ("Eggs", 4, "pcs"), ("Green plantain", 4, "pcs")]),
    ("Okro stew with banku", 4, 2, None, None,
     "Cook the banku from corn dough. Fry onions, tomatoes and pepper in palm oil, add fish and chopped okro.",
     [("Okro", 20, "pcs"), ("Corn dough", 1, "kg"), ("Palm oil", 100, "ml"), ("Smoked mackerel", 2, "pcs"),
      ("Onions", 1, "pcs"), ("Tomatoes", 3, "pcs"), ("Pepper", 3, "pcs")]),
    ("Light soup with chicken", 4, 3, None, None,
     "Steam the seasoned chicken. Boil tomatoes, onions and pepper, blend, and simmer with the chicken.",
     [("Chicken", 1, "kg"), ("Tomatoes", 6, "pcs"), ("Onions", 2, "pcs"), ("Pepper", 3, "pcs"), ("Ginger", 20, "g"),
      ("Garlic", 2, "pcs"), ("Stock cubes", 1, "pcs")]),
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
    """Add the starter ingredients and recipes (skipping any names that already exist)."""
    from meals.units import to_base
    fallback = "Staples" if "Staples" in expense_categories else (expense_categories[0] if expense_categories else None)
    with conn.cursor() as cur:
        ids = {}
        for name, unit, cat, low, pack, size in INGREDIENTS:
            low_base = to_base(low, unit)[0] if low is not None else None
            pack_base = to_base(size, unit)[0] if size else None
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level, pack_name, pack_size) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                        (name, unit, cat if cat in expense_categories else fallback, low_base, pack, pack_base))
            ids[name] = cur.fetchone()[0]
        added = 0
        for name, portions, keeps, note, hours, method, lines in RECIPES:
            cur.execute("SELECT 1 FROM meals.recipes WHERE name = %s", (name,))
            if cur.fetchone():
                continue
            cur.execute("INSERT INTO meals.recipes (name, portions, keeps_days, prep_note, prep_hours, method) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (name, portions, keeps, note, hours, method))
            rid = cur.fetchone()[0]
            for ing, qty, unit in lines:
                cur.execute("INSERT INTO meals.recipe_items (recipe_id, ingredient_id, qty, unit) VALUES (%s, %s, %s, %s)",
                            (rid, ids[ing], qty, unit))
            added += 1
    return added

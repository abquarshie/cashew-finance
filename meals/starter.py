"""A few everyday Ghanaian dishes to start the recipe book with. Quantities are typical for
4 portions; edit them to match how your family cooks."""

# name, usual unit, money category, running-low level (in the usual unit, or None)
INGREDIENTS = [
    ("Rice", "kg", "Staples", 1), ("Black-eyed beans", "kg", "Staples", 0.5), ("Gari", "kg", "Staples", 0.5),
    ("Corn dough", "kg", "Staples", None), ("Onions", "pcs", "Fruits/Veges", 3), ("Tomatoes", "pcs", "Fruits/Veges", None),
    ("Pepper", "pcs", "Fruits/Veges", None), ("Ripe plantain", "pcs", "Fruits/Veges", None),
    ("Green plantain", "pcs", "Fruits/Veges", None), ("Kontomire", "bunch", "Fruits/Veges", None),
    ("Okro", "pcs", "Fruits/Veges", None), ("Ginger", "g", "Spices", 50), ("Garlic", "pcs", "Spices", 2),
    ("Stock cubes", "pcs", "Spices", 4), ("Tomato paste", "sachet", "Canned or Sachet items", 2),
    ("Vegetable oil", "l", "Oils", 0.5), ("Palm oil", "l", "Oils", 0.25), ("Chicken", "kg", "Meat/Fish", None),
    ("Smoked mackerel", "pcs", "Meat/Fish", None), ("Eggs", "pcs", "Dairy/Cereal", 4), ("Milk", "tin", "Dairy/Cereal", 1),
    ("Bread", "loaf", "Bakery", None),
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


def load_starter(conn, expense_categories):
    """Add the starter ingredients and recipes (skipping any names that already exist)."""
    from meals.units import to_base
    fallback = "Staples" if "Staples" in expense_categories else (expense_categories[0] if expense_categories else None)
    with conn.cursor() as cur:
        ids = {}
        for name, unit, cat, low in INGREDIENTS:
            low_base = to_base(low, unit)[0] if low is not None else None
            cur.execute("INSERT INTO meals.ingredients (name, unit, category, low_level) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                        (name, unit, cat if cat in expense_categories else fallback, low_base))
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

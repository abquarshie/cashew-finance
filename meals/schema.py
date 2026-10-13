"""Tables for the meal planner, kept in their own Postgres schema ("meals") so the money
tables are never touched by it. Quantities are stored in base units (see meals/units.py)."""

TABLES = [
    "CREATE SCHEMA IF NOT EXISTS meals",
    """
    CREATE TABLE IF NOT EXISTS meals.ingredients (
        id SERIAL PRIMARY KEY,
        name VARCHAR(60) UNIQUE NOT NULL,
        unit VARCHAR(12) NOT NULL DEFAULT 'pcs',      -- the unit you usually buy and count it in
        category VARCHAR(50),                          -- money category its cost is logged under (e.g. Meat/Fish)
        low_level NUMERIC(12, 3)                       -- warn when pantry stock falls to this (base unit)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.recipes (
        id SERIAL PRIMARY KEY,
        name VARCHAR(80) UNIQUE NOT NULL,
        portions INTEGER NOT NULL DEFAULT 4,           -- how many portions one batch makes
        keeps_days INTEGER NOT NULL DEFAULT 3,         -- how long leftovers keep in the fridge
        prep_note TEXT,                                -- e.g. 'Soak the beans'
        prep_hours INTEGER,                            -- how long before the meal the prep note matters
        method TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.recipe_items (
        id SERIAL PRIMARY KEY,
        recipe_id INTEGER NOT NULL REFERENCES meals.recipes(id) ON DELETE CASCADE,
        ingredient_id INTEGER NOT NULL REFERENCES meals.ingredients(id) ON DELETE RESTRICT,
        qty NUMERIC(12, 3) NOT NULL,
        unit VARCHAR(12) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.plan (
        id SERIAL PRIMARY KEY,
        day DATE NOT NULL,
        slot VARCHAR(10) NOT NULL,                     -- Breakfast, Lunch or Supper
        recipe_id INTEGER REFERENCES meals.recipes(id) ON DELETE CASCADE,
        ingredient_id INTEGER REFERENCES meals.ingredients(id) ON DELETE CASCADE,  -- a plain item like bananas
        qty NUMERIC(12, 3) NOT NULL,                   -- portions to cook, or how much of the plain item
        unit VARCHAR(12),
        status VARCHAR(12) NOT NULL DEFAULT 'planned', -- planned, cooked, from_fridge, done
        done_at TIMESTAMPTZ,
        done_by VARCHAR(30),
        CHECK (recipe_id IS NOT NULL OR ingredient_id IS NOT NULL)
    )
    """,
    "CREATE INDEX IF NOT EXISTS plan_day_idx ON meals.plan (day)",
    # what ticking an entry changed (pantry and fridge), so unticking can put it back exactly
    "ALTER TABLE meals.plan ADD COLUMN IF NOT EXISTS undo JSONB",
    """
    CREATE TABLE IF NOT EXISTS meals.fridge (
        id SERIAL PRIMARY KEY,
        recipe_id INTEGER REFERENCES meals.recipes(id) ON DELETE SET NULL,
        label VARCHAR(80) NOT NULL,
        portions NUMERIC(8, 2) NOT NULL,               -- portions still left
        cooked_on DATE NOT NULL,
        eat_by DATE NOT NULL,
        plan_id INTEGER REFERENCES meals.plan(id) ON DELETE SET NULL,  -- the cooking that made it
        created_by VARCHAR(30)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.pantry (
        ingredient_id INTEGER NOT NULL REFERENCES meals.ingredients(id) ON DELETE CASCADE,
        unit VARCHAR(12) NOT NULL,                     -- base unit: g, ml or a count word
        qty NUMERIC(12, 3) NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (ingredient_id, unit)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.prices (
        ingredient_id INTEGER NOT NULL REFERENCES meals.ingredients(id) ON DELETE CASCADE,
        unit VARCHAR(12) NOT NULL,                     -- base unit
        per_unit NUMERIC(12, 5) NOT NULL,              -- last price paid per base unit
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (ingredient_id, unit)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.trips (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        account VARCHAR(50) NOT NULL,
        total NUMERIC(12, 2) NOT NULL,
        created_by VARCHAR(30),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.trip_items (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES meals.trips(id) ON DELETE CASCADE,
        ingredient_id INTEGER REFERENCES meals.ingredients(id) ON DELETE SET NULL,
        name VARCHAR(60) NOT NULL,
        qty NUMERIC(12, 3) NOT NULL,                   -- base unit
        unit VARCHAR(12) NOT NULL,
        price NUMERIC(12, 2) NOT NULL,
        category VARCHAR(50) NOT NULL
    )
    """,
]

TABLES += [
    # the container an item is bought and stored in, e.g. a crate of 30 eggs or a 5 kg bag of rice
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS pack_name VARCHAR(12)",
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS pack_size NUMERIC(12, 3)",  # in the base unit
    # leftovers can be counted in portions, servings, bowls...
    "ALTER TABLE meals.fridge ADD COLUMN IF NOT EXISTS unit VARCHAR(12) NOT NULL DEFAULT 'portion'",
    # where a shopping trip happened (Makola, Shoprite...)
    "ALTER TABLE meals.trips ADD COLUMN IF NOT EXISTS shop VARCHAR(60)",
    """
    CREATE TABLE IF NOT EXISTS meals.waste (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        label VARCHAR(80) NOT NULL,
        amount NUMERIC(8, 2) NOT NULL,                 -- portions (or other leftover units) thrown away
        unit VARCHAR(12) NOT NULL DEFAULT 'portion',
        value NUMERIC(12, 2),                          -- estimated cost of what was thrown away
        recipe_id INTEGER REFERENCES meals.recipes(id) ON DELETE SET NULL,
        created_by VARCHAR(30)
    )
    """,
]

TABLES += [
    # half portions and the like: a recipe can make 2.5 portions (whole numbers before)
    """
    DO $$ BEGIN
      IF (SELECT data_type FROM information_schema.columns
          WHERE table_schema = 'meals' AND table_name = 'recipes' AND column_name = 'portions') = 'integer' THEN
        ALTER TABLE meals.recipes ALTER COLUMN portions TYPE NUMERIC(8, 2);
      END IF;
    END $$
    """,
]

TABLES += [
    # household supplies (washing powder, bleach, toilet roll…) live alongside food, marked as 'household'
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS kind VARCHAR(10) NOT NULL DEFAULT 'food'",
]

TABLES += [
    # food bought ready-made (kenkey, waakye…): a recipe marked bought, with its usual price, unit and seller
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS bought BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2)",          # usual price for one unit
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS count_unit VARCHAR(12)",        # ball, pack, portion…
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS shop VARCHAR(60)",
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS category VARCHAR(50)",          # money category when paid
    # a one-off bought item typed straight into the plan ("Fried yam from the roadside")
    "ALTER TABLE meals.plan ADD COLUMN IF NOT EXISTS label VARCHAR(80)",
    "ALTER TABLE meals.plan ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2)",
    """
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'plan_check') THEN
        ALTER TABLE meals.plan DROP CONSTRAINT plan_check;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'plan_has_something') THEN
        ALTER TABLE meals.plan ADD CONSTRAINT plan_has_something
          CHECK (recipe_id IS NOT NULL OR ingredient_id IS NOT NULL OR label IS NOT NULL);
      END IF;
    END $$
    """,
    # what was paid for bought food, for price trends
    """
    CREATE TABLE IF NOT EXISTS meals.bought (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        plan_id INTEGER REFERENCES meals.plan(id) ON DELETE SET NULL,
        recipe_id INTEGER REFERENCES meals.recipes(id) ON DELETE SET NULL,
        label VARCHAR(80) NOT NULL,
        qty NUMERIC(12, 3) NOT NULL,
        unit VARCHAR(12) NOT NULL,
        paid NUMERIC(12, 2) NOT NULL,
        shop VARCHAR(60)
    )
    """,
]

TABLES += [
    # the Ghanaian kitchen catalog: which shelf an item sits on, whether it's sold loose even though it also
    # comes in a container (onions by the piece, not the 40-onion bag), and other units it's measured in
    # ({"container": 400} for an 80 tsp spice container; {"tbsp": 15} for margarine by the spoon), in base units
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS section VARCHAR(40)",
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS loose BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE meals.ingredients ADD COLUMN IF NOT EXISTS alt_units JSONB",
    # what part a dish plays in a meal: a starch (kokonte, fufu, banku…) eaten with a soup or stew
    "ALTER TABLE meals.recipes ADD COLUMN IF NOT EXISTS role VARCHAR(10) NOT NULL DEFAULT 'main'",
    # ready-made pairings for the planner, e.g. "Kokonte + Palm nut soup"
    """
    CREATE TABLE IF NOT EXISTS meals.pairings (
        id SERIAL PRIMARY KEY,
        name VARCHAR(120) UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meals.pairing_items (
        id SERIAL PRIMARY KEY,
        pairing_id INTEGER NOT NULL REFERENCES meals.pairings(id) ON DELETE CASCADE,
        recipe_id INTEGER REFERENCES meals.recipes(id) ON DELETE CASCADE,
        ingredient_id INTEGER REFERENCES meals.ingredients(id) ON DELETE CASCADE,  -- a side like gari
        qty NUMERIC(12, 3),                            -- for a side item: how much per person
        unit VARCHAR(12),
        CHECK (recipe_id IS NOT NULL OR ingredient_id IS NOT NULL)
    )
    """,
    "CREATE INDEX IF NOT EXISTS plan_day_slot_idx ON meals.plan (day, slot)",
]

# Backup and restore order (parents before children).
BACKUP_TABLES = ["meals.ingredients", "meals.recipes", "meals.recipe_items", "meals.pairings", "meals.pairing_items",
                 "meals.plan", "meals.fridge", "meals.pantry", "meals.prices", "meals.trips", "meals.trip_items",
                 "meals.waste", "meals.bought"]


def ensure_meals_schema(cur):
    for sql in TABLES:
        cur.execute(sql)

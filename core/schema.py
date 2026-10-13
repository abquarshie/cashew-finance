"""Database tables and starting data.

No Streamlit imports here, so the daily job (run_auto.py) can set the database
up on its own, without anyone opening the app first.
"""

# Starting categories (group, type, [categories]). Everything can be edited in the app afterwards.
SEED_CATEGORIES = [
    ("Income", "Income", ["Salary", "Additional income"]),
    ("Food", "Expense", ["Fruits/Veges", "Dairy/Cereal", "Canned or Sachet items", "Spices", "Oils", "Meat/Fish", "Bakery", "Staples", "Dining Out"]),
    ("Water", "Expense", ["Cooking water", "Drinking water"]),
    ("Utility", "Expense", ["Electricity", "Water for washing and bathing", "Internet Data", "Telephone calls credit", "Gas", "Firewood", "Trash"]),
    ("Health", "Expense", ["Medications", "Hospital bills"]),
    ("Toiletries", "Expense", ["Supplies"]),
    ("Transportation", "Expense", ["Work", "Meetings", "Other"]),
    ("Family", "Expense", ["Mother", "Others"]),
    ("Purpose", "Expense", ["Sewing", "Assembly and conventions", "Store", "Maintenance", "Shirt/Dress", "Utensils"]),
    ("Other", "Expense", ["Debt - work", "Charges", "Salon/Barber", "Coins savings"]),
    ("Transfer", "Transfer", ["Between accounts", "Susu"]),
]
SEED_ACCOUNTS = ["Cash", "GCB", "Susu", "Fidelity - Emergency", "Flip"]
# Accounts whose names sound like savings don't count as everyday money for "Safe to spend" (editable in the app).
SAVINGS_WORDS = "(susu|emergency|saving|invest|fixed|pension|t-bill)"

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        type VARCHAR(10) NOT NULL, -- 'Income', 'Expense' or 'Transfer'
        category VARCHAR(50) NOT NULL,
        amount NUMERIC(10, 2) NOT NULL,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS budgets (
        category VARCHAR(50) PRIMARY KEY,
        monthly_limit NUMERIC(10, 2) NOT NULL
    )
    """,
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS member VARCHAR(50)",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account VARCHAR(50)",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS to_account VARCHAR(50)",
    """
    CREATE TABLE IF NOT EXISTS goals (
        id SERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL,
        target NUMERIC(12, 2) NOT NULL,
        deadline DATE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS goal_contributions (
        id SERIAL PRIMARY KEY,
        goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        amount NUMERIC(12, 2) NOT NULL,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name VARCHAR(50) UNIQUE NOT NULL,
        group_name VARCHAR(60) NOT NULL,
        kind VARCHAR(10) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        name VARCHAR(50) UNIQUE NOT NULL,
        opening_balance NUMERIC(12, 2) NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recurring_rules (
        id SERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL,
        type VARCHAR(10) NOT NULL,
        amount NUMERIC(10, 2) NOT NULL,
        category VARCHAR(50) NOT NULL,
        account VARCHAR(50) NOT NULL,
        to_account VARCHAR(50),
        member VARCHAR(50),
        note TEXT,
        frequency VARCHAR(20) NOT NULL,
        start_date DATE NOT NULL,
        next_date DATE NOT NULL,
        run_count INTEGER NOT NULL DEFAULT 0,
        end_date DATE,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        last_run DATE
    )
    """,
    # The daily job reads this column; older databases were created without it.
    "ALTER TABLE recurring_rules ADD COLUMN IF NOT EXISTS fee NUMERIC(10, 2)",
    "CREATE TABLE IF NOT EXISTS app_meta (key VARCHAR(50) PRIMARY KEY, value TEXT)",
    # ---- sign-in ----
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(30) UNIQUE NOT NULL,      -- always stored in lower case
        display_name VARCHAR(50) NOT NULL,
        password_hash TEXT NOT NULL,               -- pbkdf2_sha256$iterations$salt$hash, never the password
        is_owner BOOLEAN NOT NULL DEFAULT FALSE,
        failed_logins INTEGER NOT NULL DEFAULT 0,
        locked_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_login TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash CHAR(64) PRIMARY KEY,           -- sha256 of the browser's token, so a database leak can't be replayed
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL
    )
    """,
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_by VARCHAR(30)",
    "ALTER TABLE goal_contributions ADD COLUMN IF NOT EXISTS created_by VARCHAR(30)",
    # when each entry was added (used to spot double entries); older rows stay empty
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "ALTER TABLE transactions ALTER COLUMN created_at SET DEFAULT now()",
    # "everyday money": accounts that count towards Safe to spend. Savings-type accounts start switched off.
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS spendable BOOLEAN",
    f"UPDATE accounts SET spendable = NOT (name ~* '{SAVINGS_WORDS}') WHERE spendable IS NULL",
    "ALTER TABLE accounts ALTER COLUMN spendable SET DEFAULT TRUE",
    # speeds up the newest-first listing as the history grows
    "CREATE INDEX IF NOT EXISTS transactions_date_idx ON transactions (date DESC, id DESC)",
    # the double-entry check looks for the same category and amount
    "CREATE INDEX IF NOT EXISTS transactions_cat_amount_idx ON transactions (category, amount)",
    # lookups by a linked row (each delete of a goal or a person checks these)
    "CREATE INDEX IF NOT EXISTS goal_contributions_goal_idx ON goal_contributions (goal_id)",
    "CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id)",
]


def _version():
    """A fingerprint of every table definition and the starting data. When the database already carries it,
    there's nothing to create or upgrade, so starting up costs one quick query instead of dozens."""
    import hashlib

    from meals.catalog import FLAG
    from meals.schema import TABLES as MEAL_TABLES
    text = "\n".join(TABLES + MEAL_TABLES + [FLAG, repr(SEED_CATEGORIES), repr(SEED_ACCOUNTS)])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


SCHEMA_KEY = "schema_version"


def ensure_schema(conn):
    """Create or upgrade every table, and add the starting categories and kitchen catalog once.
    Safe to run every time; when the database is already up to date it only reads one value."""
    from meals.catalog import seed as seed_kitchen
    from meals.schema import ensure_meals_schema

    version = _version()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM app_meta WHERE key = %s", (SCHEMA_KEY,))
        row = cur.fetchone()
    except Exception:  # a brand-new database has no app_meta table yet
        conn.rollback()
        cur = conn.cursor()
        row = None
    if row and row[0] == version:
        conn.commit()
        cur.close()
        return
    for sql in TABLES:
        cur.execute(sql)
    ensure_meals_schema(cur)
    cur.execute("SELECT 1 FROM app_meta WHERE key = 'seeded_v2'")
    if cur.fetchone() is None:
        for group, kind, names in SEED_CATEGORIES:
            for name in names:
                cur.execute(
                    "INSERT INTO categories (name, group_name, kind) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, group, kind),
                )
        for acct in SEED_ACCOUNTS:
            cur.execute("INSERT INTO accounts (name, spendable) VALUES (%s, NOT (%s ~* %s)) ON CONFLICT (name) DO NOTHING",
                        (acct, acct, SAVINGS_WORDS))
        cur.execute("INSERT INTO app_meta (key, value) VALUES ('seeded_v2', 'yes')")
    seed_kitchen(cur)
    cur.execute("INSERT INTO app_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (SCHEMA_KEY, version))
    conn.commit()
    cur.close()

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
]


def ensure_schema(conn):
    """Create or upgrade every table, and add the starting categories once. Safe to run every time."""
    cur = conn.cursor()
    for sql in TABLES:
        cur.execute(sql)
    cur.execute("SELECT 1 FROM app_meta WHERE key = 'seeded_v2'")
    if cur.fetchone() is None:
        for group, kind, names in SEED_CATEGORIES:
            for name in names:
                cur.execute(
                    "INSERT INTO categories (name, group_name, kind) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, group, kind),
                )
        for acct in SEED_ACCOUNTS:
            cur.execute("INSERT INTO accounts (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (acct,))
        cur.execute("INSERT INTO app_meta (key, value) VALUES ('seeded_v2', 'yes')")
    conn.commit()
    cur.close()

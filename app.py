import html
from contextlib import contextmanager
from datetime import date, timedelta

import altair as alt
import pandas as pd
import psycopg2
import streamlit as st
from dateutil.relativedelta import relativedelta

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
CURRENCY = "GH₵"

GREEN = "#1FA971"
CORAL = "#E4574F"
TEAL = "#14A38F"
CAT_COLORS = ["#14A38F", "#E4572E", "#F2A541", "#5B8DEF", "#8DBF8B", "#D17A93", "#9FB0C3", "#A58BC9", "#C9A227", "#4FB0C6"]

SHARED = "Household"  # used when a transaction isn't tied to one family member
KINDS = ["Expense", "Income", "Transfer"]
FREQUENCIES = ["Weekly", "Every 2 weeks", "Monthly", "Yearly"]

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

st.set_page_config(page_title="Cashew Finance", page_icon="💰", layout="wide", initial_sidebar_state="expanded")

# ----------------------------------------------------------------------------
# Styling (light / dark / follows system)
# ----------------------------------------------------------------------------
LIGHT_VARS = "--muted:#5F7079;--line:#DDE5E2;--card:#FFFFFF;--bar:#E4EBE8;--hover:#EAF1EE;--checked:#DCEEE8;"
DARK_VARS = "--muted:#9AA9B1;--line:#2C373C;--card:#161D21;--bar:#2A3438;--hover:#1D272B;--checked:#16332F;"

try:  # Streamlit 1.46+ reports the active theme; older versions fall back to the OS setting
    theme_type = st.context.theme.type
except Exception:
    theme_type = None

if theme_type == "dark":
    ROOT_CSS = f":root{{{DARK_VARS}}}"
elif theme_type == "light":
    ROOT_CSS = f":root{{{LIGHT_VARS}}}"
else:
    ROOT_CSS = f":root{{{LIGHT_VARS}}} @media (prefers-color-scheme: dark){{:root{{{DARK_VARS}}}}}"

APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
/*ROOT*/

.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp input, .stApp textarea, .stApp button, .stApp li { font-family: 'Manrope', sans-serif; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2rem; max-width: 1200px; }

/* keep the hide / show sidebar arrows easy to find */
[data-testid="stSidebarCollapseButton"] { opacity: 1 !important; visibility: visible !important; }

section[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] div[role="radiogroup"] { gap: 2px; }
section[data-testid="stSidebar"] div[role="radiogroup"] label { padding: 0.55rem 0.8rem; border-radius: 10px; width: 100%; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: var(--hover); }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background: var(--checked); font-weight: 700; }
.brand { font-size: 1.35rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0.1rem; }
.brand-sub { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.2rem; }

.page-title { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.03em; margin: 0; line-height: 1.2; }
.page-sub { color: var(--muted); font-size: 0.95rem; margin: 0.15rem 0 1.2rem 0; }
.section-title { font-size: 1.05rem; font-weight: 700; margin: 0.2rem 0 0.6rem 0; }

.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 1.1rem 1.25rem; height: 100%; }
.kpi-label { color: var(--muted); font-size: 0.85rem; font-weight: 600; }
.kpi-value { font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; margin: 0.15rem 0; color: inherit; }
.kpi-sub { font-size: 0.8rem; font-weight: 600; color: var(--muted); }
.kpi-sub.good { color: #1FA971; }
.kpi-sub.bad { color: #E4574F; }
.kpi.featured { background: #0F3D3A; border-color: #0F3D3A; }
.kpi.featured .kpi-label, .kpi.featured .kpi-sub { color: #A8CFC8; }
.kpi.featured .kpi-value { color: #FFFFFF; }
.kpi.featured .kpi-sub.good { color: #7EE0B5; }
.kpi.featured .kpi-sub.bad { color: #FFB4A8; }

.acct-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.8rem; }
.acct { border: 1px solid var(--line); border-radius: 12px; padding: 0.8rem 1rem; }
.acct-name { color: var(--muted); font-size: 0.82rem; font-weight: 600; }
.acct-bal { font-size: 1.2rem; font-weight: 800; letter-spacing: -0.01em; }
.acct-bal.neg { color: #E4574F; }

.budget-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0.9rem 1.6rem; }
.budget-head { display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.92rem; margin-bottom: 0.35rem; }
.budget-name { font-weight: 700; }
.budget-amt { color: var(--muted); }
.bar { background: var(--bar); height: 9px; border-radius: 999px; overflow: hidden; }
.fill { height: 100%; border-radius: 999px; }
.fill.ok { background: #1FA971; }
.fill.warn { background: #E0A030; }
.fill.over { background: #E4574F; }
.budget-foot { font-size: 0.78rem; margin-top: 0.3rem; color: var(--muted); }
.budget-foot.over { color: #E4574F; font-weight: 700; }

.recent-row { display: flex; justify-content: space-between; align-items: center; padding: 0.65rem 0; border-bottom: 1px solid var(--line); }
.recent-row:last-child { border-bottom: none; }
.recent-cat { font-weight: 700; font-size: 0.92rem; }
.recent-meta { color: var(--muted); font-size: 0.8rem; }
.amt { font-weight: 700; }
.amt.income { color: #1FA971; }
.amt.expense { color: #E4574F; }
.amt.transfer { color: var(--muted); }

div.stButton > button, div.stDownloadButton > button,
button[kind="secondaryFormSubmit"], button[kind="primaryFormSubmit"] { border-radius: 10px; font-weight: 600; }
</style>
"""
st.markdown(APP_CSS.replace("/*ROOT*/", ROOT_CSS), unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
def get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


@contextmanager
def db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def execute(sql, params=None):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cur.close()


def run_many(statements):
    """Run several statements in one transaction (all succeed or none do)."""
    with db() as conn:
        cur = conn.cursor()
        for sql, params in statements:
            cur.execute(sql, params)
        cur.close()


@st.cache_resource
def init_db():
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                type VARCHAR(10) NOT NULL, -- 'Income', 'Expense' or 'Transfer'
                category VARCHAR(50) NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                note TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                category VARCHAR(50) PRIMARY KEY,
                monthly_limit NUMERIC(10, 2) NOT NULL
            );
            """
        )
        cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS member VARCHAR(50);")
        cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account VARCHAR(50);")
        cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS to_account VARCHAR(50);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id SERIAL PRIMARY KEY,
                name VARCHAR(80) NOT NULL,
                target NUMERIC(12, 2) NOT NULL,
                deadline DATE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS goal_contributions (
                id SERIAL PRIMARY KEY,
                goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                date DATE NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                note TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                group_name VARCHAR(60) NOT NULL,
                kind VARCHAR(10) NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                opening_balance NUMERIC(12, 2) NOT NULL DEFAULT 0
            );
            """
        )
        cur.execute(
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
            );
            """
        )
        cur.execute("CREATE TABLE IF NOT EXISTS app_meta (key VARCHAR(50) PRIMARY KEY, value TEXT);")

        # Seed the starting categories and accounts once; after that they belong to you.
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
        cur.close()
    return True


init_db()


# ----------------------------------------------------------------------------
# Auto transactions
# ----------------------------------------------------------------------------
def occurrence(start, frequency, n):
    """The date of the n-th run (0-based) of a rule that starts on `start`."""
    if frequency == "Weekly":
        return start + timedelta(weeks=n)
    if frequency == "Every 2 weeks":
        return start + timedelta(weeks=2 * n)
    if frequency == "Yearly":
        return start + relativedelta(years=n)
    return start + relativedelta(months=n)


def apply_recurring():
    """Create every auto transaction that is due. Runs whenever the app opens,
    so anything missed while the app was closed is added with its original date."""
    today = date.today()
    created = 0
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, type, amount, category, account, to_account, member, note,
                   frequency, start_date, run_count, end_date
            FROM recurring_rules
            WHERE active AND next_date <= %s
            FOR UPDATE SKIP LOCKED
            """,
            (today,),
        )
        for (rid, name, typ, amount, cat, acct, to_acct, member, note, freq, start, n, end) in cur.fetchall():
            nxt = occurrence(start, freq, n)
            guard = 0
            while nxt <= today and (end is None or nxt <= end) and guard < 400:
                label = f"Auto · {name}" + (f" · {note}" if note else "")
                cur.execute(
                    "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (nxt, typ, cat, amount, label, member or SHARED, acct, to_acct),
                )
                n += 1
                created += 1
                guard += 1
                nxt = occurrence(start, freq, n)
            still_active = end is None or nxt <= end
            cur.execute(
                "UPDATE recurring_rules SET run_count=%s, next_date=%s, active=%s, last_run=%s WHERE id=%s",
                (n, nxt, still_active, today, rid),
            )
        cur.close()
    return created


try:
    auto_created = apply_recurring()
except Exception as exc:  # never block the whole app because of an auto rule
    auto_created = 0
    st.warning(f"Auto transactions could not run: {exc}")


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_data():
    with db() as conn:
        df_t = pd.read_sql(
            "SELECT id, date, type, category, amount, note, member, account, to_account "
            "FROM transactions ORDER BY date DESC, id DESC",
            conn,
        )
        df_b = pd.read_sql("SELECT category, monthly_limit FROM budgets ORDER BY category", conn)
        df_c = pd.read_sql("SELECT name, group_name, kind FROM categories ORDER BY id", conn)
        df_a = pd.read_sql("SELECT name, opening_balance FROM accounts ORDER BY id", conn)
    df_t["amount"] = df_t["amount"].astype(float)
    df_t["note"] = df_t["note"].fillna("")
    df_t["member"] = df_t["member"].fillna(SHARED)
    df_t["account"] = df_t["account"].fillna("")
    df_t["to_account"] = df_t["to_account"].fillna("")
    df_t["group"] = df_t["category"].map(dict(zip(df_c["name"], df_c["group_name"]))).fillna(df_t["category"])
    df_b["monthly_limit"] = df_b["monthly_limit"].astype(float)
    df_a["opening_balance"] = df_a["opening_balance"].astype(float)
    if not df_t.empty:
        df_t["date"] = pd.to_datetime(df_t["date"]).dt.date
    return df_t, df_b, df_c, df_a


def load_goals():
    with db() as conn:
        goals = pd.read_sql(
            """
            SELECT g.id, g.name, g.target, g.deadline, COALESCE(SUM(c.amount), 0) AS saved
            FROM goals g LEFT JOIN goal_contributions c ON c.goal_id = g.id
            GROUP BY g.id, g.name, g.target, g.deadline
            ORDER BY g.id
            """,
            conn,
        )
        contribs = pd.read_sql(
            """
            SELECT c.id, c.date, g.name AS goal, c.amount, c.note
            FROM goal_contributions c JOIN goals g ON g.id = c.goal_id
            ORDER BY c.date DESC, c.id DESC LIMIT 50
            """,
            conn,
        )
    goals["target"] = goals["target"].astype(float)
    goals["saved"] = goals["saved"].astype(float)
    contribs["amount"] = contribs["amount"].astype(float)
    contribs["note"] = contribs["note"].fillna("")
    return goals, contribs


def load_rules():
    with db() as conn:
        rules = pd.read_sql("SELECT * FROM recurring_rules ORDER BY id", conn)
    rules["amount"] = rules["amount"].astype(float)
    return rules


df_transactions, df_budgets, df_cats, df_accts = load_data()
multi_member = (not df_transactions.empty) and df_transactions["member"].nunique() > 1
CAT_GROUP = dict(zip(df_cats["name"], df_cats["group_name"]))
account_names = df_accts["name"].tolist()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def money(x):
    return f"{CURRENCY}{x:,.2f}"


def flash(message, icon="✅"):
    """Show a toast on the next run (survives st.rerun)."""
    st.session_state["_flash"] = (message, icon)


def show_flash():
    if "_flash" in st.session_state:
        message, icon = st.session_state.pop("_flash")
        st.toast(message, icon=icon)
    if auto_created:
        st.toast(f"Added {auto_created} auto transaction{'s' if auto_created != 1 else ''}", icon="🔁")


def page_header(title, subtitle):
    st.markdown(
        f'<div class="page-title">{html.escape(title)}</div><div class="page-sub">{html.escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def section(title):
    st.markdown(f'<div class="section-title">{html.escape(title)}</div>', unsafe_allow_html=True)


def show_table(df, **kwargs):
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def show_chart(chart):
    try:
        st.altair_chart(chart, width="stretch")
    except TypeError:
        st.altair_chart(chart, use_container_width=True)


def kpi(label, value, sub="", tone="", featured=False):
    cls = "kpi featured" if featured else "kpi"
    sub_html = f'<div class="kpi-sub {tone}">{sub}</div>' if sub else ""
    return (
        f'<div class="{cls}"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>'
    )


def progress_item(name, right_text, pct, tone, foot, foot_over=False):
    foot_cls = "budget-foot over" if foot_over else "budget-foot"
    return (
        f'<div><div class="budget-head"><span class="budget-name">{html.escape(name)}</span>'
        f'<span class="budget-amt">{right_text}</span></div>'
        f'<div class="bar"><div class="fill {tone}" style="width:{min(pct, 100):.1f}%"></div></div>'
        f'<div class="{foot_cls}">{foot}</div></div>'
    )


def delta_vs_last(cur, prev, good_when_up=True):
    if prev == 0:
        return "No data last month", ""
    pct = (cur - prev) / abs(prev) * 100
    if abs(pct) < 0.5:
        return "Same as last month", ""
    arrow = "▲" if pct > 0 else "▼"
    went_good = (pct > 0) == good_when_up
    return f"{arrow} {abs(pct):.0f}% vs last month", ("good" if went_good else "bad")


def category_names(kind=None):
    """Category names in the order you set them up, grouped together."""
    d = df_cats if kind is None else df_cats[df_cats["kind"] == kind]
    names = []
    for _, grp in d.groupby("group_name", sort=False):
        names.extend(grp["name"].tolist())
    return names


def cat_label(name):
    group = CAT_GROUP.get(name)
    return f"{group} › {name}" if group else name


def all_members():
    others = set(df_transactions["member"].tolist()) - {SHARED} if not df_transactions.empty else set()
    return [SHARED] + sorted(others)


def account_view(row):
    if row["type"] == "Transfer":
        return f"{row['account'] or '—'} → {row['to_account'] or '—'}"
    return row["account"] or "—"


def account_balances():
    bal = df_accts.set_index("name")["opening_balance"].astype(float)
    if df_transactions.empty:
        return bal
    t = df_transactions

    def total(mask, col):
        return t[mask].groupby(col)["amount"].sum().reindex(bal.index, fill_value=0.0)

    return (
        bal
        + total(t["type"] == "Income", "account")
        - total(t["type"] == "Expense", "account")
        - total(t["type"] == "Transfer", "account")
        + total(t["type"] == "Transfer", "to_account")
    )


def tx_label(row):
    note = f" | {row['note']}" if row["note"] else ""
    acct = f" | {account_view(row)}" if (row["account"] or row["type"] == "Transfer") else ""
    return f"#{row['id']} | {row['date']:%d %b %Y} | {row['type']} | {row['category']}{acct} | {money(row['amount'])}{note}"


def recent_list_html(df, n=5):
    rows = []
    for _, r in df.head(n).iterrows():
        if r["type"] == "Income":
            sign, cls = "+", "income"
        elif r["type"] == "Expense":
            sign, cls = "−", "expense"
        else:
            sign, cls = "⇄ ", "transfer"
        parts = [f"{r['date']:%d %b}"]
        acct = account_view(r)
        if acct != "—":
            parts.append(html.escape(acct))
        if r["member"] != SHARED:
            parts.append(html.escape(r["member"]))
        if r["note"]:
            parts.append(html.escape(r["note"]))
        rows.append(
            f'<div class="recent-row"><div><div class="recent-cat">{html.escape(r["category"])}</div>'
            f'<div class="recent-meta">{" · ".join(parts)}</div></div>'
            f'<div class="amt {cls}">{sign}{money(r["amount"])}</div></div>'
        )
    return "".join(rows)


def need_setup_warning():
    st.warning("Add at least one account in **Categories & Accounts** first.")


# ----------------------------------------------------------------------------
# Navigation
# ----------------------------------------------------------------------------
NAV = {
    "Dashboard": "📊  Dashboard",
    "Add Transaction": "➕  Add Transaction",
    "Auto": "🔁  Auto Transactions",
    "Manage Budgets": "🎯  Budgets",
    "Goals": "🏆  Savings Goals",
    "Manage / Delete": "🧾  Manage Transactions",
    "Setup": "⚙️  Categories & Accounts",
}

with st.sidebar:
    st.markdown('<div class="brand">💰 Cashew</div><div class="brand-sub">Family finance tracker</div>', unsafe_allow_html=True)
    menu = st.radio("Navigation", list(NAV.keys()), format_func=lambda k: NAV[k], label_visibility="collapsed")

show_flash()

# ----------------------------------------------------------------------------
# DASHBOARD
# ----------------------------------------------------------------------------
if menu == "Dashboard":
    if df_transactions.empty:
        page_header("Dashboard", "Your money at a glance")
        st.info("No transactions yet. Open **Add Transaction** in the sidebar to record your first one.")
    else:
        df_transactions["year_month"] = pd.to_datetime(df_transactions["date"]).dt.to_period("M")
        available_periods = sorted(df_transactions["year_month"].unique(), reverse=True)

        head_l, head_r = st.columns([3, 1])
        with head_r:
            selected_period = st.selectbox(
                "Month", available_periods, format_func=lambda x: x.strftime("%B %Y"), label_visibility="collapsed"
            )
        with head_l:
            page_header("Dashboard", f"Summary for {selected_period.strftime('%B %Y')}")

        filtered_df = df_transactions[df_transactions["year_month"] == selected_period]
        prev_df = df_transactions[df_transactions["year_month"] == selected_period - 1]

        def totals(d):
            inc = d.loc[d["type"] == "Income", "amount"].sum()
            exp = d.loc[d["type"] == "Expense", "amount"].sum()
            return inc, exp

        total_income, total_expense = totals(filtered_df)
        prev_income, prev_expense = totals(prev_df)
        net_balance = total_income - total_expense
        prev_net = prev_income - prev_expense

        inc_sub, inc_tone = delta_vs_last(total_income, prev_income, good_when_up=True)
        exp_sub, exp_tone = delta_vs_last(total_expense, prev_expense, good_when_up=False)
        net_sub, net_tone = delta_vs_last(net_balance, prev_net, good_when_up=True)

        if total_income > 0:
            rate = net_balance / total_income * 100
            rate_val = f"{rate:.0f}%"
            rate_sub = "of income saved" if rate >= 0 else "Spending exceeds income"
            rate_tone = "good" if rate >= 20 else ("bad" if rate < 0 else "")
        else:
            rate_val, rate_sub, rate_tone = "—", "No income this month", ""

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi("Income", money(total_income), inc_sub, inc_tone), unsafe_allow_html=True)
        c2.markdown(kpi("Expenses", money(total_expense), exp_sub, exp_tone), unsafe_allow_html=True)
        c3.markdown(kpi("Net balance", money(net_balance), net_sub, net_tone, featured=True), unsafe_allow_html=True)
        c4.markdown(kpi("Savings rate", rate_val, rate_sub, rate_tone), unsafe_allow_html=True)

        # --- Accounts -----------------------------------------------------
        if not df_accts.empty:
            st.write("")
            balances = account_balances()
            with st.container(border=True):
                section("Accounts · current balances")
                cards = "".join(
                    f'<div class="acct"><div class="acct-name">{html.escape(name)}</div>'
                    f'<div class="acct-bal{" neg" if value < 0 else ""}">{money(value)}</div></div>'
                    for name, value in balances.items()
                )
                st.markdown(f'<div class="acct-grid">{cards}</div>', unsafe_allow_html=True)
                unassigned = int(((df_transactions["account"] == "") & (df_transactions["type"] != "Transfer")).sum())
                caption = f"Total across accounts: {money(balances.sum())}"
                if unassigned:
                    caption += f" · {unassigned} older transaction{'s have' if unassigned != 1 else ' has'} no account yet (assign them in Categories & Accounts)"
                st.caption(caption)

        st.write("")

        # --- Charts -------------------------------------------------------
        left, right = st.columns([3, 2])

        with left:
            with st.container(border=True):
                section("Income vs expenses, last 6 months")
                periods = pd.period_range(end=selected_period, periods=6, freq="M")
                monthly = df_transactions.groupby(["year_month", "type"])["amount"].sum().unstack(fill_value=0)
                for col in ("Income", "Expense"):
                    if col not in monthly.columns:
                        monthly[col] = 0.0
                monthly = monthly.reindex(periods, fill_value=0.0)
                labels = [p.strftime("%b '%y") for p in periods]
                trend = pd.DataFrame(
                    {
                        "Month": labels * 2,
                        "Type": ["Income"] * 6 + ["Expenses"] * 6,
                        "Amount": list(monthly["Income"]) + list(monthly["Expense"]),
                    }
                )
                trend_chart = (
                    alt.Chart(trend)
                    .mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2.5, interpolate="monotone")
                    .encode(
                        x=alt.X("Month:N", sort=labels, axis=alt.Axis(title=None, labelAngle=0)),
                        y=alt.Y("Amount:Q", axis=alt.Axis(title=None, format="~s")),
                        color=alt.Color(
                            "Type:N",
                            scale=alt.Scale(domain=["Income", "Expenses"], range=[GREEN, CORAL]),
                            legend=alt.Legend(title=None, orient="top"),
                        ),
                        tooltip=[
                            alt.Tooltip("Month:N"),
                            alt.Tooltip("Type:N"),
                            alt.Tooltip("Amount:Q", format=",.2f"),
                        ],
                    )
                    .properties(height=250)
                    .configure_view(strokeWidth=0)
                )
                show_chart(trend_chart)

        with right:
            with st.container(border=True):
                section("Where the money went")
                view_mode = st.radio(
                    "View", ["By group", "By category"], horizontal=True, label_visibility="collapsed", key="spend_mode"
                )
                expenses_only = filtered_df[filtered_df["type"] == "Expense"]
                if expenses_only.empty:
                    st.caption("No expenses this month.")
                elif view_mode == "By group":
                    spend = (
                        expenses_only.groupby("group", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
                    )
                    donut = (
                        alt.Chart(spend)
                        .mark_arc(innerRadius=62, outerRadius=105, padAngle=0.02)
                        .encode(
                            theta=alt.Theta("amount:Q", stack=True),
                            color=alt.Color(
                                "group:N",
                                sort=list(spend["group"]),
                                scale=alt.Scale(range=CAT_COLORS),
                                legend=alt.Legend(title=None, orient="right"),
                            ),
                            order=alt.Order("amount:Q", sort="descending"),
                            tooltip=[
                                alt.Tooltip("group:N", title="Group"),
                                alt.Tooltip("amount:Q", title="Spent", format=",.2f"),
                            ],
                        )
                        .properties(height=230)
                        .configure_view(strokeWidth=0)
                    )
                    show_chart(donut)
                    top = spend.iloc[0]
                    share = top["amount"] / spend["amount"].sum() * 100
                    st.caption(f"{top['group']} is your biggest expense group at {share:.0f}% of spending.")
                else:
                    spend = (
                        expenses_only.groupby("category", as_index=False)["amount"]
                        .sum()
                        .sort_values("amount", ascending=False)
                        .head(10)
                    )
                    cat_chart = (
                        alt.Chart(spend)
                        .mark_bar(cornerRadiusEnd=6, color=TEAL, size=16)
                        .encode(
                            y=alt.Y("category:N", sort="-x", axis=alt.Axis(title=None)),
                            x=alt.X("amount:Q", axis=alt.Axis(title=None, format="~s")),
                            tooltip=[
                                alt.Tooltip("category:N", title="Category"),
                                alt.Tooltip("amount:Q", title="Spent", format=",.2f"),
                            ],
                        )
                        .properties(height=max(80, 30 * len(spend)))
                        .configure_view(strokeWidth=0)
                    )
                    show_chart(cat_chart)
                    st.caption("Your top 10 categories this month.")

        # --- Spending by family member (only once more than one person is recorded) ---
        if multi_member:
            by_member = (
                filtered_df[filtered_df["type"] == "Expense"]
                .groupby("member", as_index=False)["amount"]
                .sum()
                .sort_values("amount", ascending=False)
            )
            if not by_member.empty:
                st.write("")
                with st.container(border=True):
                    section("Spending by family member")
                    member_chart = (
                        alt.Chart(by_member)
                        .mark_bar(cornerRadiusEnd=6, color=TEAL, size=18)
                        .encode(
                            y=alt.Y("member:N", sort="-x", axis=alt.Axis(title=None)),
                            x=alt.X("amount:Q", axis=alt.Axis(title=None, format="~s")),
                            tooltip=[
                                alt.Tooltip("member:N", title="Who"),
                                alt.Tooltip("amount:Q", title="Spent", format=",.2f"),
                            ],
                        )
                        .properties(height=max(60, 38 * len(by_member)))
                        .configure_view(strokeWidth=0)
                    )
                    show_chart(member_chart)

        # --- Budgets ------------------------------------------------------
        st.write("")
        with st.container(border=True):
            section("Budget progress")
            if df_budgets.empty:
                st.caption("No monthly budgets yet. Add limits in **Budgets** to track them here.")
            else:
                expenses_this_month = filtered_df[filtered_df["type"] == "Expense"]
                spent_by_group = expenses_this_month.groupby("group")["amount"].sum()
                spent_by_cat = expenses_this_month.groupby("category")["amount"].sum()
                group_set = set(df_cats["group_name"])
                items = []
                for _, row in df_budgets.iterrows():
                    key = row["category"]
                    limit = float(row["monthly_limit"])
                    spent = float((spent_by_group if key in group_set else spent_by_cat).get(key, 0.0))
                    pct = spent / limit * 100 if limit > 0 else 0.0
                    tone = "ok" if pct < 75 else ("warn" if pct < 100 else "over")
                    if spent > limit:
                        foot, over = f"⚠️ Over budget by {money(spent - limit)}", True
                    else:
                        foot, over = f"{money(limit - spent)} left · {pct:.0f}% used", False
                    items.append(progress_item(key, f"{money(spent)} of {money(limit)}", pct, tone, foot, over))
                st.markdown(f'<div class="budget-grid">{"".join(items)}</div>', unsafe_allow_html=True)

        # --- Transactions -------------------------------------------------
        st.write("")
        with st.container(border=True):
            section(f"Transactions in {selected_period.strftime('%B %Y')}")
            if multi_member:
                f1, f2, f3, f4 = st.columns([1, 2, 1.3, 2])
                member_filter = f3.selectbox("Family member", ["All"] + all_members())
            else:
                f1, f2, f4 = st.columns([1, 2, 2])
                member_filter = "All"
            type_filter = f1.selectbox("Type", ["All"] + KINDS)
            cat_filter = f2.multiselect("Category", sorted(filtered_df["category"].unique()))
            query = f4.text_input("Search", placeholder="Search notes or categories")

            view = filtered_df
            if type_filter != "All":
                view = view[view["type"] == type_filter]
            if cat_filter:
                view = view[view["category"].isin(cat_filter)]
            if member_filter != "All":
                view = view[view["member"] == member_filter]
            if query:
                view = view[
                    view["note"].str.contains(query, case=False, na=False)
                    | view["category"].str.contains(query, case=False, na=False)
                    | view["group"].str.contains(query, case=False, na=False)
                ]

            st.caption(f"{len(view)} transaction{'s' if len(view) != 1 else ''}")
            view = view.assign(account_view=[account_view(r) for _, r in view.iterrows()])
            cols = ["date", "type", "group", "category", "account_view"] + (["member"] if multi_member else []) + ["note", "amount"]
            show_table(
                view[cols],
                column_config={
                    "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "type": st.column_config.TextColumn("Type"),
                    "group": st.column_config.TextColumn("Group"),
                    "category": st.column_config.TextColumn("Category"),
                    "account_view": st.column_config.TextColumn("Account"),
                    "member": st.column_config.TextColumn("Who"),
                    "note": st.column_config.TextColumn("Note"),
                    "amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY}%.2f"),
                },
            )

# ----------------------------------------------------------------------------
# ADD TRANSACTION
# ----------------------------------------------------------------------------
elif menu == "Add Transaction":
    page_header("Add transaction", "Record income, an expense, or a move between accounts")

    form_col, recent_col = st.columns([3, 2])

    with form_col:
        with st.container(border=True):
            t_type = st.radio("Type", KINDS, horizontal=True)
            kind_names = category_names(t_type)
            default_acct = account_names.index("Cash") if "Cash" in account_names else 0

            if not account_names:
                need_setup_warning()
            elif not kind_names:
                st.warning(f"No {t_type.lower()} categories yet. Add some in **Categories & Accounts**.")
            else:
                with st.form(f"transaction_form_{t_type}", clear_on_submit=True):
                    r1, r2 = st.columns(2)
                    t_date = r1.date_input("Date", value=date.today())
                    t_amount = r2.number_input(f"Amount ({CURRENCY})", min_value=0.01, format="%.2f")

                    t_to_account = None
                    if t_type == "Transfer":
                        a1, a2 = st.columns(2)
                        t_account = a1.selectbox("From account", account_names, index=default_acct)
                        t_to_account = a2.selectbox("To account", account_names, index=min(1, len(account_names) - 1))
                        t_category = st.selectbox("Purpose", kind_names)
                        t_member, t_new_member = SHARED, ""
                    else:
                        r3, r4 = st.columns(2)
                        t_category = r3.selectbox("Category", kind_names, format_func=cat_label)
                        t_account = r4.selectbox("Account", account_names, index=default_acct)
                        r5, r6 = st.columns(2)
                        t_member = r5.selectbox("Family member", all_members(), help=f"{SHARED} means shared by everyone.")
                        t_new_member = r6.text_input("Or add a family member", placeholder="e.g. Ama")
                    t_note = st.text_input("Note / Description")

                    submitted = st.form_submit_button("Save transaction", type="primary")

                    if submitted:
                        if t_type == "Transfer" and t_account == t_to_account:
                            st.warning("Choose two different accounts.")
                        else:
                            final_member = t_new_member.strip() or t_member
                            execute(
                                "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                (t_date, t_type, t_category, t_amount, t_note, final_member, t_account, t_to_account),
                            )
                            if t_type == "Transfer":
                                flash(f"Moved {money(t_amount)} from {t_account} to {t_to_account}", "⇄")
                            else:
                                flash(f"Saved {money(t_amount)} to {t_category}")
                            st.rerun()
            st.caption("Need a new category or account? Add it in **Categories & Accounts**.")

    with recent_col:
        with st.container(border=True):
            section("Latest entries")
            if df_transactions.empty:
                st.caption("Nothing here yet. Your latest entries will show up here.")
            else:
                st.markdown(recent_list_html(df_transactions), unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# AUTO TRANSACTIONS
# ----------------------------------------------------------------------------
elif menu == "Auto":
    page_header("Auto transactions", "Moves and regular entries that add themselves")
    st.caption(
        "They are added whenever the app is opened. If you skip a few days, anything missed is added "
        "with its original date."
    )
    df_rules = load_rules()
    today = date.today()

    with st.container(border=True):
        section("Your auto transactions")
        if df_rules.empty:
            st.caption("None yet. Create your first one below, for example a monthly move from Cash to Susu.")
        else:
            rows = []
            for _, r in df_rules.iterrows():
                if r["type"] == "Transfer":
                    detail = f"{r['account']} → {r['to_account']} ({r['category']})"
                else:
                    detail = f"{r['type']} · {cat_label(r['category'])} · {r['account']}"
                finished = (not r["active"]) and pd.notna(r["end_date"]) and r["next_date"] > r["end_date"]
                status = "Active" if r["active"] else ("Finished" if finished else "Paused")
                rows.append(
                    {
                        "Name": r["name"],
                        "What": detail,
                        "Amount": r["amount"],
                        "Repeats": r["frequency"],
                        "Next": r["next_date"] if r["active"] else None,
                        "Ends": r["end_date"] if pd.notna(r["end_date"]) else None,
                        "Status": status,
                    }
                )
            show_table(
                pd.DataFrame(rows),
                column_config={
                    "Amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY}%.2f"),
                    "Next": st.column_config.DateColumn("Next", format="DD MMM YYYY"),
                    "Ends": st.column_config.DateColumn("Ends", format="DD MMM YYYY"),
                },
            )
            with st.expander("Pause, change or delete"):
                rule_names = {int(r["id"]): r["name"] for _, r in df_rules.iterrows()}
                pick = st.selectbox("Auto transaction", list(rule_names.keys()), format_func=lambda i: rule_names[i], key="rule_pick")
                rule = df_rules[df_rules["id"] == pick].iloc[0]
                finished = (not rule["active"]) and pd.notna(rule["end_date"]) and rule["next_date"] > rule["end_date"]

                b1, b2, b3 = st.columns(3)
                with b1:
                    new_amount = st.number_input(
                        f"Amount ({CURRENCY})", min_value=0.01, value=float(rule["amount"]), format="%.2f", key=f"rule_amt_{pick}"
                    )
                    if st.button("Update amount", key=f"rule_upd_{pick}"):
                        execute("UPDATE recurring_rules SET amount=%s WHERE id=%s", (new_amount, int(pick)))
                        flash("Amount updated. It applies to future runs.")
                        st.rerun()
                with b2:
                    st.write("")
                    if finished:
                        st.caption("This one has finished.")
                    elif rule["active"]:
                        if st.button("Pause", key=f"rule_pause_{pick}"):
                            execute("UPDATE recurring_rules SET active=FALSE WHERE id=%s", (int(pick),))
                            flash("Paused", "⏸️")
                            st.rerun()
                    else:
                        if st.button("Resume", key=f"rule_resume_{pick}"):
                            # skip the days it was paused instead of backfilling them
                            n = int(rule["run_count"])
                            start = rule["start_date"]
                            while occurrence(start, rule["frequency"], n) < today and n < 5000:
                                n += 1
                            execute(
                                "UPDATE recurring_rules SET active=TRUE, run_count=%s, next_date=%s WHERE id=%s",
                                (n, occurrence(start, rule["frequency"], n), int(pick)),
                            )
                            flash("Resumed", "▶️")
                            st.rerun()
                with b3:
                    confirm_rule = st.checkbox("Yes, delete it", key=f"rule_conf_{pick}")
                    if st.button("Delete", type="primary", disabled=not confirm_rule, key=f"rule_del_{pick}"):
                        execute("DELETE FROM recurring_rules WHERE id=%s", (int(pick),))
                        flash("Auto transaction deleted. Entries it already added are kept.", "🗑️")
                        st.rerun()

    st.write("")
    with st.container(border=True):
        section("New auto transaction")
        if not account_names:
            need_setup_warning()
        else:
            n_type = st.radio("Type", KINDS, horizontal=True, key="rule_type")
            n_names = category_names(n_type)
            default_acct = account_names.index("Cash") if "Cash" in account_names else 0
            if not n_names:
                st.warning(f"No {n_type.lower()} categories yet. Add some in **Categories & Accounts**.")
            else:
                with st.form(f"rule_form_{n_type}", clear_on_submit=True):
                    q1, q2 = st.columns(2)
                    n_name = q1.text_input("Name", placeholder="e.g. Monthly Susu")
                    n_amount = q2.number_input(f"Amount ({CURRENCY})", min_value=0.01, format="%.2f")

                    n_to = None
                    if n_type == "Transfer":
                        a1, a2, a3 = st.columns(3)
                        n_account = a1.selectbox("From account", account_names, index=default_acct)
                        n_to = a2.selectbox("To account", account_names, index=min(1, len(account_names) - 1))
                        n_category = a3.selectbox("Purpose", n_names)
                        n_member = SHARED
                    else:
                        a1, a2, a3 = st.columns(3)
                        n_category = a1.selectbox("Category", n_names, format_func=cat_label)
                        n_account = a2.selectbox("Account", account_names, index=default_acct)
                        n_member = a3.selectbox("Family member", all_members())

                    s1, s2, s3 = st.columns(3)
                    n_freq = s1.selectbox("Repeats", FREQUENCIES, index=2)
                    n_start = s2.date_input("First run", value=date.today(), help="A date in the past is filled in right away.")
                    n_end = s3.date_input("Stop after (optional)", value=None)
                    n_note = st.text_input("Note (optional)")

                    if st.form_submit_button("Create auto transaction", type="primary"):
                        if not n_name.strip():
                            st.warning("Give it a name.")
                        elif n_type == "Transfer" and n_account == n_to:
                            st.warning("Choose two different accounts.")
                        elif n_end is not None and n_end < n_start:
                            st.warning("The stop date is before the first run.")
                        else:
                            execute(
                                "INSERT INTO recurring_rules (name, type, amount, category, account, to_account, member, note, "
                                "frequency, start_date, next_date, run_count, end_date, active) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, TRUE)",
                                (n_name.strip(), n_type, n_amount, n_category, n_account, n_to, n_member, n_note,
                                 n_freq, n_start, n_start, n_end),
                            )
                            flash(f"'{n_name.strip()}' created", "🔁")
                            st.rerun()

# ----------------------------------------------------------------------------
# MANAGE BUDGETS
# ----------------------------------------------------------------------------
elif menu == "Manage Budgets":
    page_header("Budgets", "Set a monthly limit for a whole group or a single category")

    form_col, list_col = st.columns([2, 3])

    targets = {}
    for g, grp in df_cats[df_cats["kind"] == "Expense"].groupby("group_name", sort=False):
        targets[g] = f"{g} (whole group)"
        for n in grp["name"]:
            targets[n] = f"{g} › {n}"

    with form_col:
        with st.container(border=True):
            section("Set a budget")
            if not targets:
                st.caption("Add expense categories first in **Categories & Accounts**.")
            else:
                with st.form("budget_form", clear_on_submit=True):
                    b_key = st.selectbox("Budget for", list(targets.keys()), format_func=lambda k: targets[k],
                                         help="Pick a group like Food, or one category. Saving again updates the limit.")
                    b_limit = st.number_input(f"Monthly limit ({CURRENCY})", min_value=0.0, format="%.2f")
                    if st.form_submit_button("Save budget", type="primary"):
                        execute(
                            "INSERT INTO budgets (category, monthly_limit) VALUES (%s, %s) "
                            "ON CONFLICT (category) DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit",
                            (b_key, b_limit),
                        )
                        flash(f"Budget for '{b_key}' saved")
                        st.rerun()

    with list_col:
        with st.container(border=True):
            section("Current budgets")
            if df_budgets.empty:
                st.caption("No budgets yet. Add your first one on the left.")
            else:
                show_table(
                    df_budgets,
                    column_config={
                        "category": st.column_config.TextColumn("Budget"),
                        "monthly_limit": st.column_config.NumberColumn("Monthly limit", format=f"{CURRENCY}%.2f"),
                    },
                )
                with st.expander("Remove a budget"):
                    to_remove = st.selectbox("Budget", df_budgets["category"].tolist(), key="budget_to_remove")
                    if st.button("Remove budget"):
                        execute("DELETE FROM budgets WHERE category = %s", (to_remove,))
                        flash(f"Budget for '{to_remove}' removed", "🗑️")
                        st.rerun()

# ----------------------------------------------------------------------------
# SAVINGS GOALS
# ----------------------------------------------------------------------------
elif menu == "Goals":
    page_header("Savings goals", "Save together for school fees, rent, a car or anything else")
    df_goals, df_contribs = load_goals()

    with st.container(border=True):
        section("Progress")
        if df_goals.empty:
            st.caption("No goals yet. Create your first one in the **New goal** tab below.")
        else:
            today = date.today()
            items = []
            for _, g in df_goals.iterrows():
                target, saved = g["target"], g["saved"]
                pct = saved / target * 100 if target > 0 else 0.0
                remaining = max(target - saved, 0.0)
                deadline = g["deadline"]
                has_deadline = pd.notna(deadline)
                if has_deadline:
                    deadline = pd.to_datetime(deadline).date()

                if saved >= target:
                    foot = "🎉 Goal reached"
                elif has_deadline:
                    months_left = (deadline.year - today.year) * 12 + (deadline.month - today.month)
                    if deadline < today:
                        foot = f"Past its {deadline:%d %b %Y} date · {money(remaining)} still to go"
                    else:
                        per_month = remaining / max(months_left, 1)
                        foot = f"{money(remaining)} to go · due {deadline:%d %b %Y} · about {money(per_month)} a month"
                else:
                    foot = f"{money(remaining)} to go · {pct:.0f}% saved"
                items.append(progress_item(g["name"], f"{money(saved)} of {money(target)}", pct, "ok", foot))
            st.markdown(f'<div class="budget-grid">{"".join(items)}</div>', unsafe_allow_html=True)

    st.write("")
    tab_add, tab_new, tab_manage = st.tabs(["Add money", "New goal", "History & manage"])

    with tab_add:
        if df_goals.empty:
            st.caption("Create a goal first, then add money to it here.")
        else:
            with st.form("contribution_form", clear_on_submit=True):
                goal_names = {int(r["id"]): r["name"] for _, r in df_goals.iterrows()}
                k_goal = st.selectbox("Goal", list(goal_names.keys()), format_func=lambda i: goal_names[i])
                k1, k2 = st.columns(2)
                k_amount = k1.number_input(f"Amount ({CURRENCY})", min_value=0.01, format="%.2f")
                k_date = k2.date_input("Date", value=date.today())
                k_note = st.text_input("Note", placeholder="e.g. Ama's contribution")
                if st.form_submit_button("Add to goal", type="primary"):
                    execute(
                        "INSERT INTO goal_contributions (goal_id, date, amount, note) VALUES (%s, %s, %s, %s)",
                        (int(k_goal), k_date, k_amount, k_note),
                    )
                    flash(f"Added {money(k_amount)} to {goal_names[k_goal]}")
                    st.rerun()
            st.caption("Goal savings are tracked separately and don't change your income or expenses.")

    with tab_new:
        with st.form("goal_form", clear_on_submit=True):
            n_name = st.text_input("Goal name", placeholder="e.g. School fees")
            n1, n2 = st.columns(2)
            n_target = n1.number_input(f"Target ({CURRENCY})", min_value=1.0, format="%.2f")
            n_deadline = n2.date_input("Deadline (optional)", value=None)
            if st.form_submit_button("Create goal", type="primary"):
                if not n_name.strip():
                    st.warning("Give the goal a name.")
                else:
                    execute(
                        "INSERT INTO goals (name, target, deadline) VALUES (%s, %s, %s)",
                        (n_name.strip(), n_target, n_deadline),
                    )
                    flash(f"Goal '{n_name.strip()}' created", "🏆")
                    st.rerun()

    with tab_manage:
        if df_contribs.empty:
            st.caption("No contributions yet.")
        else:
            show_table(
                df_contribs[["date", "goal", "amount", "note"]],
                column_config={
                    "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "goal": st.column_config.TextColumn("Goal"),
                    "amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY}%.2f"),
                    "note": st.column_config.TextColumn("Note"),
                },
            )
            with st.expander("Remove a contribution"):
                c_labels = {
                    int(r["id"]): f"{r['date']:%d %b %Y} | {r['goal']} | {money(r['amount'])}"
                    for _, r in df_contribs.iterrows()
                }
                c_pick = st.selectbox("Contribution", list(c_labels.keys()), format_func=lambda i: c_labels[i])
                if st.button("Remove contribution"):
                    execute("DELETE FROM goal_contributions WHERE id = %s", (int(c_pick),))
                    flash("Contribution removed", "🗑️")
                    st.rerun()
        if not df_goals.empty:
            with st.expander("Delete a goal"):
                g_names = {int(r["id"]): r["name"] for _, r in df_goals.iterrows()}
                g_pick = st.selectbox("Goal to delete", list(g_names.keys()), format_func=lambda i: g_names[i], key="goal_delete")
                g_confirm = st.checkbox("Yes, delete this goal and its history")
                if st.button("Delete goal", type="primary", disabled=not g_confirm):
                    execute("DELETE FROM goals WHERE id = %s", (int(g_pick),))
                    flash(f"Goal '{g_names[g_pick]}' deleted", "🗑️")
                    st.rerun()

# ----------------------------------------------------------------------------
# MANAGE / DELETE TRANSACTIONS
# ----------------------------------------------------------------------------
elif menu == "Manage / Delete":
    page_header("Manage transactions", "Edit, delete or export your records")

    if df_transactions.empty:
        st.info("No transactions available yet.")
    else:
        labels = {int(r["id"]): tx_label(r) for _, r in df_transactions.iterrows()}
        ids = list(labels.keys())

        tab_edit, tab_delete, tab_export = st.tabs(["Edit", "Delete", "Export"])

        with tab_edit:
            edit_id = st.selectbox("Select a transaction", ids, format_func=lambda i: labels[i], key="edit_select")
            row = df_transactions[df_transactions["id"] == edit_id].iloc[0]
            cats = category_names()
            if row["category"] not in cats:
                cats = cats + [row["category"]]
            members = all_members()
            acct_options = ["(none)"] + account_names
            if row["account"] and row["account"] not in acct_options:
                acct_options.append(row["account"])
            to_options = ["(none)"] + account_names
            if row["to_account"] and row["to_account"] not in to_options:
                to_options.append(row["to_account"])
            with st.form(f"edit_form_{edit_id}"):
                e1, e2 = st.columns(2)
                e_date = e1.date_input("Date", value=row["date"])
                e_amount = e2.number_input(f"Amount ({CURRENCY})", min_value=0.01, value=float(row["amount"]), format="%.2f")
                e3, e4, e5 = st.columns(3)
                e_type = e3.selectbox("Type", KINDS, index=KINDS.index(row["type"]) if row["type"] in KINDS else 0)
                e_category = e4.selectbox("Category", cats, index=cats.index(row["category"]), format_func=cat_label)
                e_member = e5.selectbox("Family member", members, index=members.index(row["member"]))
                e6, e7 = st.columns(2)
                e_account = e6.selectbox(
                    "Account (from account for transfers)", acct_options,
                    index=acct_options.index(row["account"]) if row["account"] else 0,
                )
                e_to = e7.selectbox(
                    "To account (transfers only)", to_options,
                    index=to_options.index(row["to_account"]) if row["to_account"] else 0,
                )
                e_note = st.text_input("Note / Description", value=row["note"])
                if st.form_submit_button("Save changes", type="primary"):
                    if e_type == "Transfer" and (e_account == "(none)" or e_to == "(none)" or e_account == e_to):
                        st.warning("A transfer needs two different accounts.")
                    else:
                        execute(
                            "UPDATE transactions SET date=%s, type=%s, category=%s, amount=%s, note=%s, member=%s, "
                            "account=%s, to_account=%s WHERE id=%s",
                            (
                                e_date, e_type, e_category, e_amount, e_note, e_member,
                                None if e_account == "(none)" else e_account,
                                e_to if (e_type == "Transfer" and e_to != "(none)") else None,
                                int(edit_id),
                            ),
                        )
                        flash(f"Updated transaction #{edit_id}")
                        st.rerun()

        with tab_delete:
            selected_id = st.selectbox(
                "Select a transaction to remove", ids, format_func=lambda i: labels[i], key="delete_select"
            )
            confirm = st.checkbox("Yes, delete this transaction permanently")
            if st.button("Delete transaction", type="primary", disabled=not confirm):
                execute("DELETE FROM transactions WHERE id = %s", (int(selected_id),))
                flash(f"Deleted transaction #{selected_id}", "🗑️")
                st.rerun()

        with tab_export:
            st.write(f"Download all {len(df_transactions)} transactions as a spreadsheet-friendly CSV.")
            export_df = df_transactions[["id", "date", "type", "group", "category", "account", "to_account", "member", "amount", "note"]]
            st.download_button(
                "Download CSV",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"cashew_transactions_{date.today():%Y-%m-%d}.csv",
                mime="text/csv",
            )

# ----------------------------------------------------------------------------
# CATEGORIES & ACCOUNTS
# ----------------------------------------------------------------------------
elif menu == "Setup":
    page_header("Categories & accounts", "Shape the app around how your family handles money")
    tab_cats, tab_accts = st.tabs(["Categories", "Accounts"])

    groups = list(dict.fromkeys(df_cats["group_name"].tolist()))
    group_kind = dict(zip(df_cats["group_name"], df_cats["kind"]))

    # ---------------------------- Categories ----------------------------
    with tab_cats:
        with st.container(border=True):
            section("Your categories")
            show_table(
                df_cats.rename(columns={"group_name": "Group", "name": "Category", "kind": "Type"})[["Group", "Category", "Type"]],
                height=320,
            )

        cat_action = st.radio(
            "What would you like to do?",
            ["Add a category", "Edit a category", "Rename a group", "Delete a category", "Move past transactions"],
            horizontal=True,
            key="cat_action",
        )

        with st.container(border=True):
            if cat_action == "Add a category":
                with st.form("cat_add", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    g_sel = c1.selectbox("Group", groups)
                    g_new = c2.text_input("Or a new group", placeholder="e.g. School")
                    n1, n2 = st.columns(2)
                    c_name = n1.text_input("Category name", max_chars=50)
                    c_kind = n2.selectbox("Type (only for a new group)", KINDS)
                    if st.form_submit_button("Add category", type="primary"):
                        g = g_new.strip() or g_sel
                        name = c_name.strip()
                        if not name or not g:
                            st.warning("Enter a category name and pick a group.")
                        elif name.lower() in [x.lower() for x in df_cats["name"]]:
                            st.warning(f"'{name}' already exists.")
                        else:
                            execute(
                                "INSERT INTO categories (name, group_name, kind) VALUES (%s, %s, %s)",
                                (name, g, group_kind.get(g, c_kind)),
                            )
                            flash(f"Added '{name}' to {g}")
                            st.rerun()

            elif cat_action == "Edit a category":
                if df_cats.empty:
                    st.caption("No categories yet.")
                else:
                    sel = st.selectbox("Category", df_cats["name"].tolist(), format_func=cat_label, key="cat_edit_sel")
                    cur_group = CAT_GROUP[sel]
                    e1, e2 = st.columns(2)
                    new_name = e1.text_input("Name", value=sel, key=f"cat_name_{sel}", max_chars=50)
                    new_group_sel = e2.selectbox("Group", groups, index=groups.index(cur_group), key=f"cat_grp_{sel}")
                    new_group_txt = st.text_input("Or move it to a new group", key=f"cat_ngrp_{sel}")
                    if st.button("Save changes", type="primary", key="cat_edit_save"):
                        new_name = new_name.strip()
                        new_group = new_group_txt.strip() or new_group_sel
                        others = [x.lower() for x in df_cats["name"] if x != sel]
                        if not new_name:
                            st.warning("The name can't be empty.")
                        elif new_name.lower() in others:
                            st.warning(f"'{new_name}' already exists.")
                        else:
                            kind = group_kind.get(new_group, df_cats.loc[df_cats["name"] == sel, "kind"].iloc[0])
                            stmts = [("UPDATE categories SET name=%s, group_name=%s, kind=%s WHERE name=%s",
                                      (new_name, new_group, kind, sel))]
                            if new_name != sel:
                                stmts += [
                                    ("UPDATE transactions SET category=%s WHERE category=%s", (new_name, sel)),
                                    ("UPDATE recurring_rules SET category=%s WHERE category=%s", (new_name, sel)),
                                    ("UPDATE budgets SET category=%s WHERE category=%s "
                                     "AND NOT EXISTS (SELECT 1 FROM budgets WHERE category=%s)", (new_name, sel, new_name)),
                                ]
                            run_many(stmts)
                            flash(f"'{new_name}' updated")
                            st.rerun()

            elif cat_action == "Rename a group":
                if not groups:
                    st.caption("No groups yet.")
                else:
                    g_pick = st.selectbox("Group", groups, key="grp_pick")
                    g_name = st.text_input("New name", value=g_pick, key=f"grp_name_{g_pick}", max_chars=60)
                    if st.button("Rename group", type="primary", key="grp_save"):
                        g_name = g_name.strip()
                        if not g_name:
                            st.warning("The name can't be empty.")
                        elif g_name != g_pick and g_name.lower() in [x.lower() for x in groups]:
                            st.warning(f"A group called '{g_name}' already exists.")
                        elif g_name != g_pick:
                            run_many([
                                ("UPDATE categories SET group_name=%s WHERE group_name=%s", (g_name, g_pick)),
                                ("UPDATE budgets SET category=%s WHERE category=%s "
                                 "AND NOT EXISTS (SELECT 1 FROM budgets WHERE category=%s)", (g_name, g_pick, g_name)),
                            ])
                            flash(f"Group renamed to '{g_name}'")
                            st.rerun()

            elif cat_action == "Delete a category":
                if df_cats.empty:
                    st.caption("No categories yet.")
                else:
                    d_sel = st.selectbox("Category", df_cats["name"].tolist(), format_func=cat_label, key="cat_del_sel")
                    used = int((df_transactions["category"] == d_sel).sum()) if not df_transactions.empty else 0
                    if used:
                        st.caption(f"{used} past transaction{'s use' if used != 1 else ' uses'} it. They keep the name, "
                                   "or you can move them first with **Move past transactions**.")
                    d_conf = st.checkbox("Yes, delete this category", key="cat_del_conf")
                    if st.button("Delete category", type="primary", disabled=not d_conf, key="cat_del_btn"):
                        execute("DELETE FROM categories WHERE name=%s", (d_sel,))
                        flash(f"'{d_sel}' deleted", "🗑️")
                        st.rerun()

            else:  # Move past transactions
                used_cats = sorted(df_transactions["category"].unique()) if not df_transactions.empty else []
                if not used_cats or df_cats.empty:
                    st.caption("There are no past transactions to move yet.")
                else:
                    st.caption("Useful for entries made before these categories existed, like an old 'Food & Dining'.")
                    m1, m2 = st.columns(2)
                    from_cat = m1.selectbox("From", used_cats, key="move_from")
                    to_cat = m2.selectbox("To", category_names(), format_func=cat_label, key="move_to")
                    count = int((df_transactions["category"] == from_cat).sum())
                    if st.button(f"Move {count} transaction{'s' if count != 1 else ''}", type="primary", key="move_btn"):
                        if from_cat == to_cat:
                            st.warning("Pick two different categories.")
                        else:
                            execute("UPDATE transactions SET category=%s WHERE category=%s", (to_cat, from_cat))
                            flash(f"Moved {count} transaction{'s' if count != 1 else ''} to '{to_cat}'")
                            st.rerun()

    # ----------------------------- Accounts -----------------------------
    with tab_accts:
        with st.container(border=True):
            section("Your accounts")
            if df_accts.empty:
                st.caption("No accounts yet. Add your first one below.")
            else:
                bal_now = account_balances()
                show_table(
                    pd.DataFrame(
                        {
                            "Account": df_accts["name"],
                            "Opening balance": df_accts["opening_balance"],
                            "Balance now": [bal_now[n] for n in df_accts["name"]],
                        }
                    ),
                    column_config={
                        "Opening balance": st.column_config.NumberColumn(format=f"{CURRENCY}%.2f"),
                        "Balance now": st.column_config.NumberColumn(format=f"{CURRENCY}%.2f"),
                    },
                )

        acct_action = st.radio(
            "What would you like to do?",
            ["Add an account", "Edit an account", "Delete an account", "Assign older transactions"],
            horizontal=True,
            key="acct_action",
        )

        with st.container(border=True):
            if acct_action == "Add an account":
                with st.form("acct_add", clear_on_submit=True):
                    a1, a2 = st.columns(2)
                    a_name = a1.text_input("Account name", max_chars=50, placeholder="e.g. MoMo")
                    a_open = a2.number_input(f"Opening balance ({CURRENCY})", value=0.0, step=10.0, format="%.2f",
                                             help="What the account held before your first entry here.")
                    if st.form_submit_button("Add account", type="primary"):
                        name = a_name.strip()
                        if not name:
                            st.warning("Enter an account name.")
                        elif name.lower() in [x.lower() for x in account_names]:
                            st.warning(f"'{name}' already exists.")
                        else:
                            execute("INSERT INTO accounts (name, opening_balance) VALUES (%s, %s)", (name, a_open))
                            flash(f"Account '{name}' added")
                            st.rerun()

            elif acct_action == "Edit an account":
                if df_accts.empty:
                    st.caption("No accounts yet.")
                else:
                    a_sel = st.selectbox("Account", account_names, key="acct_edit_sel")
                    cur_open = float(df_accts.loc[df_accts["name"] == a_sel, "opening_balance"].iloc[0])
                    e1, e2 = st.columns(2)
                    new_a_name = e1.text_input("Name", value=a_sel, key=f"acct_name_{a_sel}", max_chars=50)
                    new_a_open = e2.number_input(f"Opening balance ({CURRENCY})", value=cur_open, step=10.0, format="%.2f",
                                                 key=f"acct_open_{a_sel}")
                    if st.button("Save changes", type="primary", key="acct_edit_save"):
                        new_a_name = new_a_name.strip()
                        others = [x.lower() for x in account_names if x != a_sel]
                        if not new_a_name:
                            st.warning("The name can't be empty.")
                        elif new_a_name.lower() in others:
                            st.warning(f"'{new_a_name}' already exists.")
                        else:
                            stmts = [("UPDATE accounts SET name=%s, opening_balance=%s WHERE name=%s", (new_a_name, new_a_open, a_sel))]
                            if new_a_name != a_sel:
                                stmts += [
                                    ("UPDATE transactions SET account=%s WHERE account=%s", (new_a_name, a_sel)),
                                    ("UPDATE transactions SET to_account=%s WHERE to_account=%s", (new_a_name, a_sel)),
                                    ("UPDATE recurring_rules SET account=%s WHERE account=%s", (new_a_name, a_sel)),
                                    ("UPDATE recurring_rules SET to_account=%s WHERE to_account=%s", (new_a_name, a_sel)),
                                ]
                            run_many(stmts)
                            flash(f"Account '{new_a_name}' updated")
                            st.rerun()

            elif acct_action == "Delete an account":
                if df_accts.empty:
                    st.caption("No accounts yet.")
                else:
                    d_acct = st.selectbox("Account", account_names, key="acct_del_sel")
                    tx_used = 0
                    if not df_transactions.empty:
                        tx_used = int(((df_transactions["account"] == d_acct) | (df_transactions["to_account"] == d_acct)).sum())
                    rules_df = load_rules()
                    rules_used = int(((rules_df["account"] == d_acct) | (rules_df["to_account"] == d_acct)).sum()) if not rules_df.empty else 0
                    if tx_used or rules_used:
                        st.warning(
                            f"'{d_acct}' is used by {tx_used} transaction{'s' if tx_used != 1 else ''} and "
                            f"{rules_used} auto transaction{'s' if rules_used != 1 else ''}, so it can't be deleted. "
                            "You can rename it instead."
                        )
                    else:
                        d_conf = st.checkbox("Yes, delete this account", key="acct_del_conf")
                        if st.button("Delete account", type="primary", disabled=not d_conf, key="acct_del_btn"):
                            execute("DELETE FROM accounts WHERE name=%s", (d_acct,))
                            flash(f"Account '{d_acct}' deleted", "🗑️")
                            st.rerun()

            else:  # Assign older transactions
                n_unassigned = 0
                if not df_transactions.empty:
                    n_unassigned = int(((df_transactions["account"] == "") & (df_transactions["type"] != "Transfer")).sum())
                if not n_unassigned:
                    st.caption("Every income and expense entry already has an account.")
                elif not account_names:
                    need_setup_warning()
                else:
                    st.caption(f"{n_unassigned} older entr{'ies have' if n_unassigned != 1 else 'y has'} no account. "
                               "Put them all in one account so balances add up. You can still edit single ones later.")
                    as_acct = st.selectbox("Account", account_names, index=account_names.index("Cash") if "Cash" in account_names else 0, key="assign_acct")
                    if st.button(f"Assign {n_unassigned} to {as_acct}", type="primary", key="assign_btn"):
                        execute("UPDATE transactions SET account=%s WHERE account IS NULL AND type <> 'Transfer'", (as_acct,))
                        flash(f"Assigned {n_unassigned} to {as_acct}")
                        st.rerun()

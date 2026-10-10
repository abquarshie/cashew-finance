import html
from contextlib import contextmanager
from datetime import date

import altair as alt
import pandas as pd
import psycopg2
import streamlit as st

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
CURRENCY = "GH₵"

GREEN = "#1FA971"
CORAL = "#E4574F"
TEAL = "#14A38F"
CAT_COLORS = ["#14A38F", "#E4572E", "#F2A541", "#5B8DEF", "#8DBF8B", "#D17A93", "#9FB0C3", "#A58BC9"]

DEFAULT_CATEGORIES = ["Food & Dining", "Rent & Housing", "Utilities", "Transport", "Entertainment", "Salary", "Other"]
SHARED = "Household"  # used when a transaction isn't tied to one family member

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


@st.cache_resource
def init_db():
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                type VARCHAR(10) NOT NULL, -- 'Income' or 'Expense'
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
        # Family member on each transaction (existing rows stay untouched and show as Household)
        cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS member VARCHAR(50);")
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
        cur.close()
    return True


init_db()


def load_data():
    with db() as conn:
        df_t = pd.read_sql(
            "SELECT id, date, type, category, amount, note, member FROM transactions ORDER BY date DESC, id DESC", conn
        )
        df_b = pd.read_sql("SELECT category, monthly_limit FROM budgets ORDER BY category", conn)
    df_t["amount"] = df_t["amount"].astype(float)
    df_t["note"] = df_t["note"].fillna("")
    df_t["member"] = df_t["member"].fillna(SHARED)
    df_b["monthly_limit"] = df_b["monthly_limit"].astype(float)
    if not df_t.empty:
        df_t["date"] = pd.to_datetime(df_t["date"]).dt.date
    return df_t, df_b


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


df_transactions, df_budgets = load_data()
multi_member = (not df_transactions.empty) and df_transactions["member"].nunique() > 1


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


def all_categories():
    cats = set(DEFAULT_CATEGORIES) | set(df_budgets["category"].tolist())
    if not df_transactions.empty:
        cats |= set(df_transactions["category"].tolist())
    return sorted(cats)


def all_members():
    others = set(df_transactions["member"].tolist()) - {SHARED} if not df_transactions.empty else set()
    return [SHARED] + sorted(others)


def tx_label(row):
    note = f" | {row['note']}" if row["note"] else ""
    return f"#{row['id']} | {row['date']:%d %b %Y} | {row['type']} | {row['category']} | {money(row['amount'])}{note}"


def recent_list_html(df, n=5):
    rows = []
    for _, r in df.head(n).iterrows():
        sign = "+" if r["type"] == "Income" else "−"
        cls = "income" if r["type"] == "Income" else "expense"
        parts = [f"{r['date']:%d %b}"]
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


# ----------------------------------------------------------------------------
# Navigation
# ----------------------------------------------------------------------------
NAV = {
    "Dashboard": "📊  Dashboard",
    "Add Transaction": "➕  Add Transaction",
    "Manage Budgets": "🎯  Budgets",
    "Goals": "🏆  Savings Goals",
    "Manage / Delete": "🧾  Manage Transactions",
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
                spend = (
                    filtered_df[filtered_df["type"] == "Expense"]
                    .groupby("category", as_index=False)["amount"]
                    .sum()
                    .sort_values("amount", ascending=False)
                )
                if spend.empty:
                    st.caption("No expenses this month.")
                else:
                    donut = (
                        alt.Chart(spend)
                        .mark_arc(innerRadius=62, outerRadius=105, padAngle=0.02)
                        .encode(
                            theta=alt.Theta("amount:Q", stack=True),
                            color=alt.Color(
                                "category:N",
                                sort=list(spend["category"]),
                                scale=alt.Scale(range=CAT_COLORS),
                                legend=alt.Legend(title=None, orient="right"),
                            ),
                            order=alt.Order("amount:Q", sort="descending"),
                            tooltip=[
                                alt.Tooltip("category:N", title="Category"),
                                alt.Tooltip("amount:Q", title="Spent", format=",.2f"),
                            ],
                        )
                        .properties(height=250)
                        .configure_view(strokeWidth=0)
                    )
                    show_chart(donut)
                    top = spend.iloc[0]
                    share = top["amount"] / spend["amount"].sum() * 100
                    st.caption(f"{top['category']} is your biggest expense at {share:.0f}% of spending.")

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
                spent_by_cat = (
                    expenses_this_month.groupby("category")["amount"].sum()
                    if not expenses_this_month.empty
                    else pd.Series(dtype=float)
                )
                items = []
                for _, row in df_budgets.iterrows():
                    cat = row["category"]
                    limit = float(row["monthly_limit"])
                    spent = float(spent_by_cat.get(cat, 0.0))
                    pct = spent / limit * 100 if limit > 0 else 0.0
                    tone = "ok" if pct < 75 else ("warn" if pct < 100 else "over")
                    if spent > limit:
                        foot, over = f"⚠️ Over budget by {money(spent - limit)}", True
                    else:
                        foot, over = f"{money(limit - spent)} left · {pct:.0f}% used", False
                    items.append(progress_item(cat, f"{money(spent)} of {money(limit)}", pct, tone, foot, over))
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
            type_filter = f1.selectbox("Type", ["All", "Income", "Expense"])
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
                ]

            st.caption(f"{len(view)} transaction{'s' if len(view) != 1 else ''}")
            cols = ["date", "type", "category"] + (["member"] if multi_member else []) + ["note", "amount"]
            show_table(
                view[cols],
                column_config={
                    "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "type": st.column_config.TextColumn("Type"),
                    "category": st.column_config.TextColumn("Category"),
                    "member": st.column_config.TextColumn("Who"),
                    "note": st.column_config.TextColumn("Note"),
                    "amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY}%.2f"),
                },
            )

# ----------------------------------------------------------------------------
# ADD TRANSACTION
# ----------------------------------------------------------------------------
elif menu == "Add Transaction":
    page_header("Add transaction", "Record income or an expense")

    form_col, recent_col = st.columns([3, 2])

    with form_col:
        with st.container(border=True):
            with st.form("transaction_form", clear_on_submit=True):
                t_type = st.radio("Type", ["Expense", "Income"], horizontal=True)
                r1, r2 = st.columns(2)
                t_date = r1.date_input("Date", value=date.today())
                t_amount = r2.number_input(f"Amount ({CURRENCY})", min_value=0.01, format="%.2f")
                r3, r4 = st.columns(2)
                t_category = r3.selectbox("Category", all_categories())
                t_new_category = r4.text_input("Or new category", placeholder="Leave empty to use the one on the left")
                r5, r6 = st.columns(2)
                t_member = r5.selectbox("Family member", all_members(), help=f"{SHARED} means shared by everyone.")
                t_new_member = r6.text_input("Or add a family member", placeholder="e.g. Ama")
                t_note = st.text_input("Note / Description")

                submitted = st.form_submit_button("Save transaction", type="primary")

                if submitted:
                    final_category = t_new_category.strip() or t_category
                    final_member = t_new_member.strip() or t_member
                    execute(
                        "INSERT INTO transactions (date, type, category, amount, note, member) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (t_date, t_type, final_category, t_amount, t_note, final_member),
                    )
                    flash(f"Saved {money(t_amount)} to {final_category}")
                    st.rerun()

    with recent_col:
        with st.container(border=True):
            section("Latest entries")
            if df_transactions.empty:
                st.caption("Nothing here yet. Your latest entries will show up here.")
            else:
                st.markdown(recent_list_html(df_transactions), unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# MANAGE BUDGETS
# ----------------------------------------------------------------------------
elif menu == "Manage Budgets":
    page_header("Budgets", "Set a monthly limit for each category")

    form_col, list_col = st.columns([2, 3])

    with form_col:
        with st.container(border=True):
            section("Set a budget")
            with st.form("budget_form", clear_on_submit=True):
                b_category = st.text_input(
                    "Category name", placeholder="e.g. Groceries", help="Use an existing name to update its limit."
                )
                b_limit = st.number_input(f"Monthly limit ({CURRENCY})", min_value=0.0, format="%.2f")
                b_submitted = st.form_submit_button("Save budget", type="primary")

                if b_submitted:
                    if not b_category.strip():
                        st.warning("Enter a category name.")
                    else:
                        execute(
                            "INSERT INTO budgets (category, monthly_limit) VALUES (%s, %s) "
                            "ON CONFLICT (category) DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit",
                            (b_category.strip(), b_limit),
                        )
                        flash(f"Budget for '{b_category.strip()}' saved")
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
                        "category": st.column_config.TextColumn("Category"),
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
            cats = all_categories()
            members = all_members()
            with st.form(f"edit_form_{edit_id}"):
                e1, e2 = st.columns(2)
                e_date = e1.date_input("Date", value=row["date"])
                e_amount = e2.number_input(f"Amount ({CURRENCY})", min_value=0.01, value=float(row["amount"]), format="%.2f")
                e3, e4, e5 = st.columns(3)
                e_type = e3.selectbox("Type", ["Expense", "Income"], index=0 if row["type"] == "Expense" else 1)
                e_category = e4.selectbox("Category", cats, index=cats.index(row["category"]))
                e_member = e5.selectbox("Family member", members, index=members.index(row["member"]))
                e_note = st.text_input("Note / Description", value=row["note"])
                if st.form_submit_button("Save changes", type="primary"):
                    execute(
                        "UPDATE transactions SET date=%s, type=%s, category=%s, amount=%s, note=%s, member=%s WHERE id=%s",
                        (e_date, e_type, e_category, e_amount, e_note, e_member, int(edit_id)),
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
            export_df = df_transactions[["id", "date", "type", "category", "member", "amount", "note"]]
            st.download_button(
                "Download CSV",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"cashew_transactions_{date.today():%Y-%m-%d}.csv",
                mime="text/csv",
            )

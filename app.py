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
CURRENCY = "$"  # change to "GH₵", "€", etc.

INK = "#14212B"
MUTED = "#6B7C85"
LINE = "#E3E9E7"
GREEN = "#16875A"
CORAL = "#D6453D"
AMBER = "#E0A030"
CAT_COLORS = ["#0F766E", "#E4572E", "#F2A541", "#3D5A80", "#7A9E7E", "#B56576", "#8D99AE", "#6D597A"]

DEFAULT_CATEGORIES = ["Food & Dining", "Rent & Housing", "Utilities", "Transport", "Entertainment", "Salary", "Other"]

st.set_page_config(page_title="Cashew Finance", page_icon="💰", layout="wide")

# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp input, .stApp textarea, .stApp button, .stApp li {{ font-family: 'Manrope', sans-serif; }}
.stApp {{ background: #F5F7F6; color: {INK}; }}
#MainMenu, footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2rem; max-width: 1200px; }}

section[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid {LINE}; }}
section[data-testid="stSidebar"] div[role="radiogroup"] {{ gap: 2px; }}
section[data-testid="stSidebar"] div[role="radiogroup"] label {{
    padding: 0.55rem 0.8rem; border-radius: 10px; width: 100%;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {{ background: #F0F5F3; }}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
    background: #E3F1ED; font-weight: 700;
}}
.brand {{ font-size: 1.35rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0.1rem; }}
.brand-sub {{ color: {MUTED}; font-size: 0.85rem; margin-bottom: 1.2rem; }}

.page-title {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -0.03em; margin: 0; line-height: 1.2; }}
.page-sub {{ color: {MUTED}; font-size: 0.95rem; margin: 0.15rem 0 1.2rem 0; }}
.section-title {{ font-size: 1.05rem; font-weight: 700; margin: 0.2rem 0 0.6rem 0; }}

.kpi {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 14px; padding: 1.1rem 1.25rem; height: 100%; }}
.kpi-label {{ color: {MUTED}; font-size: 0.85rem; font-weight: 600; }}
.kpi-value {{ font-size: 1.75rem; font-weight: 800; letter-spacing: -0.02em; margin: 0.15rem 0; }}
.kpi-sub {{ font-size: 0.8rem; font-weight: 600; color: {MUTED}; }}
.kpi-sub.good {{ color: {GREEN}; }}
.kpi-sub.bad {{ color: {CORAL}; }}
.kpi.featured {{ background: #0F3D3A; border-color: #0F3D3A; }}
.kpi.featured .kpi-label {{ color: #A8CFC8; }}
.kpi.featured .kpi-value {{ color: #FFFFFF; }}
.kpi.featured .kpi-sub {{ color: #A8CFC8; }}
.kpi.featured .kpi-sub.good {{ color: #7EE0B5; }}
.kpi.featured .kpi-sub.bad {{ color: #FFB4A8; }}

.budget-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0.9rem 1.6rem; }}
.budget-head {{ display: flex; justify-content: space-between; font-size: 0.92rem; margin-bottom: 0.35rem; }}
.budget-name {{ font-weight: 700; }}
.budget-amt {{ color: {MUTED}; }}
.bar {{ background: #E8EEEC; height: 9px; border-radius: 999px; overflow: hidden; }}
.fill {{ height: 100%; border-radius: 999px; }}
.fill.ok {{ background: {GREEN}; }}
.fill.warn {{ background: {AMBER}; }}
.fill.over {{ background: {CORAL}; }}
.budget-foot {{ font-size: 0.78rem; margin-top: 0.3rem; color: {MUTED}; }}
.budget-foot.over {{ color: {CORAL}; font-weight: 700; }}

.recent-row {{ display: flex; justify-content: space-between; align-items: center;
    padding: 0.65rem 0; border-bottom: 1px solid {LINE}; }}
.recent-row:last-child {{ border-bottom: none; }}
.recent-cat {{ font-weight: 700; font-size: 0.92rem; }}
.recent-meta {{ color: {MUTED}; font-size: 0.8rem; }}
.amt {{ font-weight: 700; }}
.amt.income {{ color: {GREEN}; }}
.amt.expense {{ color: {CORAL}; }}

div.stButton > button, div.stDownloadButton > button, button[kind="secondaryFormSubmit"], button[kind="primaryFormSubmit"] {{
    border-radius: 10px; font-weight: 600;
}}
</style>
""",
    unsafe_allow_html=True,
)

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
        cur.close()
    return True


init_db()


def load_data():
    with db() as conn:
        df_t = pd.read_sql(
            "SELECT id, date, type, category, amount, note FROM transactions ORDER BY date DESC, id DESC", conn
        )
        df_b = pd.read_sql("SELECT category, monthly_limit FROM budgets ORDER BY category", conn)
    df_t["amount"] = df_t["amount"].astype(float)
    df_t["note"] = df_t["note"].fillna("")
    df_b["monthly_limit"] = df_b["monthly_limit"].astype(float)
    if not df_t.empty:
        df_t["date"] = pd.to_datetime(df_t["date"]).dt.date
    return df_t, df_b


df_transactions, df_budgets = load_data()

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


def tx_label(row):
    note = f" | {row['note']}" if row["note"] else ""
    return f"#{row['id']} | {row['date']:%d %b %Y} | {row['type']} | {row['category']} | {money(row['amount'])}{note}"


def recent_list_html(df, n=5):
    rows = []
    for _, r in df.head(n).iterrows():
        sign = "+" if r["type"] == "Income" else "−"
        cls = "income" if r["type"] == "Income" else "expense"
        meta = f"{r['date']:%d %b}" + (f" · {html.escape(r['note'])}" if r["note"] else "")
        rows.append(
            f'<div class="recent-row"><div><div class="recent-cat">{html.escape(r["category"])}</div>'
            f'<div class="recent-meta">{meta}</div></div>'
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
    "Manage / Delete": "🧾  Manage Transactions",
}

with st.sidebar:
    st.markdown('<div class="brand">💰 Cashew</div><div class="brand-sub">Personal finance tracker</div>', unsafe_allow_html=True)
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
                monthly = (
                    df_transactions.groupby(["year_month", "type"])["amount"].sum().unstack(fill_value=0)
                )
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
                    .configure_axis(gridColor="#EDF1EF", labelColor=MUTED, domainColor=LINE)
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
                        .mark_arc(innerRadius=62, outerRadius=105, stroke="#FFFFFF", strokeWidth=2)
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
                        foot = f'<div class="budget-foot over">⚠️ Over budget by {money(spent - limit)}</div>'
                    else:
                        foot = f'<div class="budget-foot">{money(limit - spent)} left · {pct:.0f}% used</div>'
                    items.append(
                        f'<div><div class="budget-head"><span class="budget-name">{html.escape(cat)}</span>'
                        f'<span class="budget-amt">{money(spent)} of {money(limit)}</span></div>'
                        f'<div class="bar"><div class="fill {tone}" style="width:{min(pct, 100):.1f}%"></div></div>'
                        f"{foot}</div>"
                    )
                st.markdown(f'<div class="budget-grid">{"".join(items)}</div>', unsafe_allow_html=True)

        # --- Transactions -------------------------------------------------
        st.write("")
        with st.container(border=True):
            section(f"Transactions in {selected_period.strftime('%B %Y')}")
            f1, f2, f3 = st.columns([1, 2, 2])
            type_filter = f1.selectbox("Type", ["All", "Income", "Expense"])
            cat_filter = f2.multiselect("Category", sorted(filtered_df["category"].unique()))
            query = f3.text_input("Search", placeholder="Search notes or categories")

            view = filtered_df
            if type_filter != "All":
                view = view[view["type"] == type_filter]
            if cat_filter:
                view = view[view["category"].isin(cat_filter)]
            if query:
                view = view[
                    view["note"].str.contains(query, case=False, na=False)
                    | view["category"].str.contains(query, case=False, na=False)
                ]

            st.caption(f"{len(view)} transaction{'s' if len(view) != 1 else ''}")
            show_table(
                view[["date", "type", "category", "note", "amount"]],
                column_config={
                    "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "type": st.column_config.TextColumn("Type"),
                    "category": st.column_config.TextColumn("Category"),
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
                t_note = st.text_input("Note / Description")

                submitted = st.form_submit_button("Save transaction", type="primary")

                if submitted:
                    final_category = t_new_category.strip() or t_category
                    execute(
                        "INSERT INTO transactions (date, type, category, amount, note) VALUES (%s, %s, %s, %s, %s)",
                        (t_date, t_type, final_category, t_amount, t_note),
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
            with st.form(f"edit_form_{edit_id}"):
                e1, e2 = st.columns(2)
                e_date = e1.date_input("Date", value=row["date"])
                e_amount = e2.number_input(f"Amount ({CURRENCY})", min_value=0.01, value=float(row["amount"]), format="%.2f")
                e3, e4 = st.columns(2)
                e_type = e3.selectbox("Type", ["Expense", "Income"], index=0 if row["type"] == "Expense" else 1)
                e_category = e4.selectbox("Category", cats, index=cats.index(row["category"]))
                e_note = st.text_input("Note / Description", value=row["note"])
                if st.form_submit_button("Save changes", type="primary"):
                    execute(
                        "UPDATE transactions SET date=%s, type=%s, category=%s, amount=%s, note=%s WHERE id=%s",
                        (e_date, e_type, e_category, e_amount, e_note, int(edit_id)),
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
            export_df = df_transactions[["id", "date", "type", "category", "amount", "note"]]
            st.download_button(
                "Download CSV",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"cashew_transactions_{date.today():%Y-%m-%d}.csv",
                mime="text/csv",
            )

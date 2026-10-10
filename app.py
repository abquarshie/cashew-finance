import streamlit as st
import pandas as pd
import psycopg2
from datetime import date

# Page Configuration
st.set_page_config(
    page_title="Cashew Finance",
    page_icon="💰",
    layout="wide"
)

# Database Connection Setup
def get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

# Initialize Database Tables
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            type VARCHAR(10) NOT NULL, -- 'Income' or 'Expense'
            category VARCHAR(50) NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            note TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            category VARCHAR(50) PRIMARY KEY,
            monthly_limit NUMERIC(10, 2) NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# App Header
st.title("💰 Cashew Finance Tracker")

# Sidebar Navigation
menu = st.sidebar.selectbox("Navigation", ["Dashboard", "Add Transaction", "Manage Budgets", "Manage / Delete"])

# Load Data from Neon
def load_data():
    conn = get_db_connection()
    df_trans = pd.read_sql("SELECT * FROM transactions ORDER BY date DESC", conn)
    df_budgets = pd.read_sql("SELECT * FROM budgets", conn)
    conn.close()
    if not df_trans.empty:
        df_trans['date'] = pd.to_datetime(df_trans['date']).dt.date
    return df_trans, df_trans, df_budgets # returning cleaned trans

df_transactions, _, df_budgets = load_data()

# --- TAB 1: DASHBOARD ---
if menu == "Dashboard":
    st.subheader("Financial Dashboard")
    
    if df_transactions.empty:
        st.info("No transactions recorded yet. Use the sidebar to add some!")
    else:
        # Create a year-month column for filtering
        df_transactions['year_month'] = pd.to_datetime(df_transactions['date']).dt.to_period('M')
        available_periods = sorted(df_transactions['year_month'].unique(), reverse=True)
        
        # Month Selector
        selected_period = st.selectbox(
            "Select Month", 
            available_periods, 
            format_func=lambda x: x.strftime('%B %Y')
        )
        
        # Filter transactions for the selected month
        filtered_df = df_transactions[df_transactions['year_month'] == selected_period]
        
        # Metrics
        total_income = filtered_df[filtered_df["type"] == "Income"]["amount"].sum()
        total_expense = filtered_df[filtered_df["type"] == "Expense"]["amount"].sum()
        net_balance = total_income - total_expense
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Monthly Income", f"${total_income:,.2f}")
        col2.metric("Monthly Expenses", f"${total_expense:,.2f}")
        col3.metric("Net Balance", f"${net_balance:,.2f}")
        
        st.divider()
        
        # Budget Progress Section
        st.subheader(f"📊 Budget Progress for {selected_period.strftime('%B %Y')}")
        if df_budgets.empty:
            st.write("No monthly budgets set yet. Go to 'Manage Budgets' to add limits.")
        else:
            expenses_this_month = filtered_df[filtered_df["type"] == "Expense"]
            spent_by_cat = expenses_this_month.groupby("category")["amount"].sum() if not expenses_this_month.empty else pd.Series(dtype=float)
            
            for index, row in df_budgets.iterrows():
                cat = row['category']
                limit = float(row['monthly_limit'])
                spent = float(spent_by_cat.get(cat, 0.0))
                progress = min(spent / limit, 1.0) if limit > 0 else 0.0
                
                col_a, col_b = st.columns([2, 3])
                with col_a:
                    st.write(f"**{cat}**")
                    st.text(f"Spent: ${spent:,.2f} / Limit: ${limit:,.2f}")
                with col_b:
                    st.progress(progress)
                    if spent > limit:
                        st.markdown(f":red[⚠️ Over budget by ${spent - limit:,.2f}!]")
        
        st.divider()
        st.subheader(f"Transactions in {selected_period.strftime('%B %Y')}")
        st.dataframe(filtered_df.drop(columns=['year_month']), use_container_width=True)

# --- TAB 2: ADD TRANSACTION ---
elif menu == "Add Transaction":
    st.subheader("Add New Transaction")
    
    default_categories = ["Food & Dining", "Rent & Housing", "Utilities", "Transport", "Entertainment", "Salary", "Other"]
    if not df_budgets.empty:
        db_categories = df_budgets["category"].tolist()
        categories = list(set(default_categories + db_categories))
    else:
        categories = default_categories

    with st.form("transaction_form", clear_on_submit=True):
        t_date = st.date_input("Date", value=date.today())
        t_type = st.selectbox("Type", ["Expense", "Income"])
        t_category = st.selectbox("Category", categories)
        t_amount = st.number_input("Amount ($)", min_value=0.01, format="%.2f")
        t_note = st.text_input("Note / Description")
        
        submitted = st.form_submit_button("Save Transaction")
        
        if submitted:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO transactions (date, type, category, amount, note) VALUES (%s, %s, %s, %s, %s)",
                (t_date, t_type, t_category, t_amount, t_note)
            )
            conn.commit()
            cur.close()
            conn.close()
            st.success("Transaction saved successfully!")
            st.rerun()

# --- TAB 3: MANAGE BUDGETS ---
elif menu == "Manage Budgets":
    st.subheader("Monthly Category Budgets")
    
    with st.form("budget_form", clear_on_submit=True):
        b_category = st.text_input("Category Name (e.g., Groceries)")
        b_limit = st.number_input("Monthly Limit ($)", min_value=0.0, format="%.2f")
        
        b_submitted = st.form_submit_button("Set Budget")
        
        if b_submitted and b_category:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO budgets (category, monthly_limit) VALUES (%s, %s) ON CONFLICT (category) DO UPDATE SET monthly_limit = EXCLUDED.monthly_limit",
                (b_category, b_limit)
            )
            conn.commit()
            cur.close()
            conn.close()
            st.success(f"Budget for '{b_category}' saved!")
            st.rerun()
            
    st.write("### Current Budgets")
    if not df_budgets.empty:
        st.dataframe(df_budgets, use_container_width=True)
    else:
        st.write("No budgets set yet.")

# --- TAB 4: MANAGE / DELETE TRANSACTIONS ---
elif menu == "Manage / Delete":
    st.subheader("Delete Transactions")
    if df_transactions.empty:
        st.write("No transactions available to delete.")
    else:
        df_transactions['display_label'] = df_transactions.apply(
            lambda x: f"ID {x['id']} | {x['date']} | {x['type']} | {x['category']} | ${x['amount']} | {x['note']}", axis=1
        )
        selected_to_delete = st.selectbox("Select transaction to remove", df_transactions['display_label'])
        
        if st.button("Delete Transaction", type="primary"):
            selected_id = int(selected_to_delete.split("|")[0].replace("ID", "").strip())
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM transactions WHERE id = %s", (selected_id,))
            conn.commit()
            cur.close()
            conn.close()
            st.success(f"Successfully deleted transaction ID {selected_id}!")
            st.rerun()

import streamlit as st
import pandas as pd
import psycopg2
from datetime import date

# 1. Page Configuration (Fixes the logo/title on mobile & PC)
st.set_page_config(
    page_title="Cashew Finance",
    page_icon="💰",
    layout="wide"
)

# 2. Database Connection Setup
def get_db_connection():
    # Connects using the Neon database URL stored in Streamlit secrets
    return psycopg2.connect(st.secrets["DATABASE_URL"])

# Initialize Database Tables if they don't exist
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Transactions table
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
    
    # Budgets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            category VARCHAR(50) PRIMARY KEY,
            monthly_limit NUMERIC(10, 2) NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# Run table initialization on load
init_db()

# App Header
st.title("💰 Cashew Finance Tracker")
st.write("Track your income, expenses, and monthly budget categories.")

# Sidebar Navigation
menu = st.sidebar.selectbox("Navigation", ["Dashboard & Charts", "Add Transaction", "Manage Budgets"])

# Fetch existing data from Neon
def load_data():
    conn = get_db_connection()
    df_trans = pd.read_sql("SELECT * FROM transactions ORDER BY date DESC", conn)
    df_budgets = pd.read_sql("SELECT * FROM budgets", conn)
    conn.close()
    return df_trans, df_budgets

df_transactions, df_budgets = load_data()

# --- TAB 1: DASHBOARD & CHARTS ---
if menu == "Dashboard & Charts":
    st.subheader("Financial Overview")
    
    if df_transactions.empty:
        info_box = st.info("No transactions recorded yet. Use the sidebar to add some!")
    else:
        # Calculate summary metrics
        total_income = df_transactions[df_transactions["type"] == "Income"]["amount"].sum()
        total_expense = df_transactions[df_transactions["type"] == "Expense"]["amount"].sum()
        net_balance = total_income - total_expense
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Income", f"${total_income:,.2f}")
        col2.metric("Total Expenses", f"${total_expense:,.2f}")
        col3.metric("Net Balance", f"${net_balance:,.2f}")
        
        st.divider()
        
        # Spending Breakdown by Category (Expenses only)
        st.subheader("Expenses by Category")
        expenses_df = df_transactions[df_transactions["type"] == "Expense"]
        
        if not expenses_df.empty:
            category_totals = expenses_df.groupby("category")["amount"].sum()
            st.bar_chart(category_totals)
        else:
            st.write("No expense transactions recorded yet.")
            
        # Recent Transactions Table
        st.subheader("Recent Transactions")
        st.dataframe(df_transactions, use_container_width=True)

# --- TAB 2: ADD TRANSACTION ---
elif menu == "Add Transaction":
    st.subheader("Add New Transaction")
    
    # Get available categories for dropdown
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
            
    st.write("### Current Budget Limits")
    if not df_budgets.empty:
        st.dataframe(df_budgets, use_container_width=True)
    else:
        st.write("No budget limits set yet.")

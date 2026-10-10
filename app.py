"""Cashew: family finance tracker. This file only sets things up and picks the page;
each page lives in views/."""
import streamlit as st

from auto_rules import apply_recurring_rules
from core.db import db, init_db, invalidate
from ui.components import flash, show_flash
from ui.nav import PAGES
from ui.theme import apply_theme
from views import auto, budgets, dashboard, goals, setup, transactions

st.set_page_config(page_title="Cashew", page_icon="💰", layout="wide", initial_sidebar_state="auto")
apply_theme()

# Keep anything half-typed in a form when you switch pages (Streamlit forgets widget values otherwise).
for key in [k for k in st.session_state.keys() if str(k).startswith("draft_")]:
    st.session_state[key] = st.session_state[key]

try:
    init_db()
except Exception as exc:
    st.error(f"Couldn't reach the database. Check DATABASE_URL in your secrets. ({exc})")
    st.stop()

# Add any auto transactions that are due, once per visit. The daily job does the same.
if "auto_checked" not in st.session_state:
    st.session_state["auto_checked"] = True
    try:
        with db() as conn:
            created = apply_recurring_rules(conn)
        if created:
            invalidate()
            flash(f"Added {created} auto transaction{'s' if created != 1 else ''}", ":material/autorenew:")
    except Exception as exc:  # never block the whole app because of an auto rule
        st.warning(f"Auto transactions couldn't run: {exc}")

pages = {
    "": [
        st.Page(dashboard.render, title="Dashboard", icon=":material/space_dashboard:", url_path="dashboard", default=True),
    ],
    "Money": [
        st.Page(transactions.render_add, title="Add transaction", icon=":material/add_circle:", url_path="add"),
        st.Page(transactions.render, title="Transactions", icon=":material/receipt_long:", url_path="transactions"),
        st.Page(auto.render, title="Auto transactions", icon=":material/autorenew:", url_path="auto"),
    ],
    "Planning": [
        st.Page(budgets.render, title="Budgets", icon=":material/donut_small:", url_path="budgets"),
        st.Page(goals.render, title="Savings goals", icon=":material/savings:", url_path="goals"),
    ],
    "Settings": [
        st.Page(setup.render, title="Categories & accounts", icon=":material/tune:", url_path="setup"),
    ],
}
for group in pages.values():
    for pg in group:
        PAGES[pg.url_path] = pg
page = st.navigation(pages, position="sidebar")

st.logo("assets/logo.svg", icon_image="assets/icon.svg", size="large")

show_flash()

# On a phone the menu covers the page; close it after a page is picked from it.
if st.session_state.get("_last_page") not in (None, page.url_path):
    st.html(
        """<script>
        (() => {
          if (window.innerWidth > 768) return;
          const side = document.querySelector('[data-testid="stSidebar"]');
          if (!side || side.getAttribute('aria-expanded') !== 'true') return;
          const btn = document.querySelector('[data-testid="stSidebarCollapseButton"] button');
          if (btn) btn.click();
        })();
        </script>""",
        unsafe_allow_javascript=True,
        width="content",
    )
st.session_state["_last_page"] = page.url_path

page.run()

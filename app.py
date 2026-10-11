"""Cashew: family finance tracker. This file only sets things up, checks who is
signed in and picks the page; each page lives in views/."""
from html import escape
from pathlib import Path

import streamlit as st

from auto_rules import apply_recurring_rules
from core.data import book
from core.db import init_db, invalidate, transact
from ui import nav
from ui.components import flash, show_flash
from ui.login import current_user, login_screen, sign_out, write_cookie
from ui.theme import apply_theme
from views import auto, budgets, dashboard, goals, people, setup, transactions

HERE = Path(__file__).parent
st.set_page_config(page_title="Cashew", page_icon=str(HERE / "assets" / "icon.svg"), layout="wide",
                   initial_sidebar_state="auto")
apply_theme()

try:
    init_db()
except Exception as exc:
    st.error(f"Couldn't reach the database. Check DATABASE_URL in your secrets. ({exc})")
    st.stop()

PAGES = [
    # (group, run, title, icon, url)
    ("", dashboard.render, "Dashboard", ":material/space_dashboard:", "dashboard"),
    ("Money", transactions.render_add, "Add transaction", ":material/add_circle:", "add"),
    ("Money", transactions.render, "Transactions", ":material/receipt_long:", "transactions"),
    ("Money", auto.render, "Auto transactions", ":material/autorenew:", "auto"),
    ("Planning", budgets.render, "Budgets", ":material/donut_small:", "budgets"),
    ("Planning", goals.render, "Savings goals", ":material/savings:", "goals"),
    ("Settings", setup.render, "Categories & accounts", ":material/tune:", "setup"),
    ("Settings", people.render, "People & sign-in", ":material/group:", "people"),
]

user = current_user()

# ---- signed out: every address shows the sign-in screen, then opens the page that was asked for ----
if user is None:
    show_flash()
    signin_pages = [st.Page(login_screen, title="Sign in", url_path=url, default=(i == 0))
                    for i, (_, _, _, _, url) in enumerate(PAGES)]
    st.navigation(signin_pages, position="hidden").run()
    st.stop()

# ---- signed in ----
# Pick up name or role changes, and sign out anyone whose account was removed.
_row = book().users[book().users["id"] == user["id"]]
if not len(_row):
    sign_out()
    st.rerun()
user = st.session_state["user"] = {**user, "name": _row["display_name"].iloc[0], "is_owner": bool(_row["is_owner"].iloc[0])}
write_cookie()

# Keep anything half-typed in a form when you switch pages (Streamlit forgets widget values otherwise).
for key in [k for k in st.session_state.keys() if str(k).startswith("draft_")]:
    st.session_state[key] = st.session_state[key]

# Add any auto transactions that are due. Only asks the database when one is actually due;
# the daily job does the same.
if book().auto_due():
    try:
        created = transact(apply_recurring_rules)
        invalidate()
        if created:
            flash(f"Added {created} auto transaction{'s' if created != 1 else ''}", ":material/autorenew:")
    except Exception as exc:  # never block the whole app because of an auto rule
        st.warning(f"Auto transactions couldn't run: {exc}")

groups = {}
for group, run, title, icon, url in PAGES:
    pg = st.Page(run, title=title, icon=icon, url_path=url, default=(url == "dashboard"))
    groups.setdefault(group, []).append(pg)
    nav.PAGES[url] = pg
page = st.navigation(groups, position="sidebar")

st.logo(str(HERE / "assets" / "logo.svg"), icon_image=str(HERE / "assets" / "icon.svg"), size="large")

with st.sidebar:
    nav.DRAWER = st.container()  # pages can add extra panels here (the dashboard's "More stats")
    st.divider()
    me = st.container(horizontal=True, vertical_alignment="center", key="me")
    me.html(
        f'<div class="me"><div class="me-avatar">{escape(user["name"][:1].upper())}</div>'
        f'<div><div class="me-name">{escape(user["name"])}</div>'
        f'<div class="me-role">{"Owner" if user["is_owner"] else "Member"} · @{escape(user["username"])}</div></div></div>',
        width="stretch",
    )
    if me.button("Sign out", icon=":material/logout:", type="tertiary", key="signout"):
        sign_out()
        st.rerun()

show_flash()

# On a phone the menu covers the page; close it after a page is picked from it.
if st.session_state.get("_last_page") not in (None, page.url_path):
    st.session_state["_nav_count"] = st.session_state.get("_nav_count", 0) + 1
    st.html(
        f"<script>/* visit {st.session_state['_nav_count']}: changes each time, so the browser runs it again */"
        """
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

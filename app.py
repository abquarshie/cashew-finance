"""Cashew: family finance tracker. This file only sets things up, checks who is
signed in and picks the page; each page lives in views/."""
from html import escape
from pathlib import Path

import streamlit as st

from auto_rules import apply_recurring_rules
from core import auth
from core.data import book
from core.db import init_db, invalidate, transact
from ui import nav
from ui.components import flash, show_flash
from ui.login import current_user, login_screen, sign_out, write_cookie
from ui.theme import apply_theme, home_icon, theme_missing
from meals.pages import shopping as meal_shopping
from views import dashboard, sections

HERE = Path(__file__).parent
st.set_page_config(page_title="Cashew", page_icon=str(HERE / "assets" / "icon.svg"), layout="wide",
                   initial_sidebar_state="auto")
apply_theme()
home_icon()

try:
    init_db()
except Exception as exc:
    st.error(f"Couldn't reach the database. Check DATABASE_URL in your secrets. ({exc})")
    st.stop()

PAGES = [
    # (group, run, title, icon, url)
    ("", dashboard.render, "Home", ":material/home:", "dashboard"),
    ("Money", sections.money, "Transactions", ":material/receipt_long:", "transactions"),
    ("Money", sections.plan, "Budgets & goals", ":material/donut_small:", "budgets"),
    ("Kitchen", sections.kitchen, "Meals", ":material/restaurant:", "meals"),
    ("Kitchen", meal_shopping.render, "Shopping list", ":material/shopping_cart:", "shopping"),
    ("Kitchen", sections.pantry, "Pantry / Inventory", ":material/inventory_2:", "pantry"),
    ("Settings", sections.settings, "Settings", ":material/settings:", "settings"),
]
# Old addresses (bookmarks, links in messages) still open the right place.
OLD = {"add": ("dashboard", None), "auto": ("transactions", "Repeats"), "goals": ("budgets", "Goals"),
       "fridge": ("meals", "Fridge"), "recipes": ("meals", "Recipes"), "setup": ("settings", "Accounts"),
       "people": ("settings", "People")}

user = current_user()

# ---- signed out: every address shows the sign-in screen, then opens the page that was asked for ----
if user is None:
    show_flash()
    signin_pages = [st.Page(login_screen, title="Sign in", url_path=url, default=(i == 0))
                    for i, url in enumerate([p[4] for p in PAGES] + list(OLD))]
    st.navigation(signin_pages, position="hidden").run()
    st.stop()

# ---- signed in ----
# Pick up name or role changes, and sign out anyone whose account was removed, whose password the owner
# reset, or whose sign-in has expired (checked against data that's already loaded: no extra database trip).
_row = book().users[book().users["id"] == user["id"]]
if not len(_row) or auth.token_hash(st.session_state.get("_token")) not in book().live_tokens:
    sign_out("You've been signed out. Please sign in again.")
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
    if group == "Kitchen" and not book().feature("kitchen"):
        continue
    pg = st.Page(run, title=title, icon=icon, url_path=url, default=(url == "dashboard"))
    groups.setdefault(group, []).append(pg)
    nav.PAGES[url] = pg
for old, (new, tab) in OLD.items():
    if new not in nav.PAGES:
        continue
    def _redirect(new=new, tab=tab):
        if tab:
            st.session_state[f"tab_{new}"] = tab
        st.switch_page(nav.PAGES[new])
    groups.setdefault("", []).append(st.Page(_redirect, title=old, url_path=old, visibility="hidden"))
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
if theme_missing() and user["is_owner"]:
    st.warning("Cashew's colours and settings file didn't reach the server, so you're seeing Streamlit's red. "
               "Make sure the **.streamlit** folder (with config.toml inside) is in your GitHub repository, in the "
               "same folder as app.py, then reboot the app. On a Mac, Finder hides folders starting with a dot: "
               "press Cmd+Shift+. to see it before uploading.", icon=":material/palette:")
# Backups that quietly stop are the worst kind: tell the owner on every page until they run again.
_age = book().backup_age_days()
if user["is_owner"] and _age is not None and _age >= 3:
    st.warning(f"The daily backup hasn't run for {_age} days. On GitHub, open Actions → Daily to see why. "
               "Settings → People has the details.", icon=":material/cloud_off:")

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

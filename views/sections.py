"""The app's pages. Each one is a single place in the menu, with tabs for the parts inside it."""
import streamlit as st

from core.data import FEATURES, book, set_feature
from ui.components import card, flash, section
from ui.entry import add_button
from ui.nav import tabbed


def money():
    from views import auto, transactions

    def entries():
        add_button("money")
        transactions.render()
    tabbed("transactions", "Money", "", [
        ("Transactions", entries),
        ("Repeats", auto.render),
    ])


def plan():
    from views import budgets, goals
    tabs = [("Budgets", budgets.render)]
    if book().feature("goals"):
        tabs.append(("Goals", goals.render))
    tabbed("budgets", "Plan", "", tabs)


def kitchen():
    from meals.pages import fridge, household, plan as meal_plan, recipes
    tabbed("meals", "Meals", "", [
        ("Plan", meal_plan.render),
        ("Recipes", recipes.render),
        ("Fridge", fridge.render),
        ("Household", household.render),
    ])


def pantry():
    """The pantry stock table on its own page, one tap from the menu."""
    from meals.data import kitchen
    from meals.pages.fridge import pantry_table
    from ui.components import page_header
    page_header("Pantry / Inventory", "What's in stock. Type a new number to correct it.")
    pantry_table(kitchen())


def settings():
    from views import people, setup
    user = st.session_state["user"]
    b = book()
    tabs = [
        ("Accounts", setup.render),
        ("People", people.render),
    ]
    if user["is_owner"]:
        if b.feature("reminders"):
            tabs.append(("Reminders", people.reminders_tab))
        tabs.append(("Parts", _features))
    tabbed("settings", "Settings", "", tabs)


def _features():
    b = book()
    with card("features"):
        section("Parts of Cashew")
        st.caption("Switch off what your family doesn't use, so nobody sees it. Nothing is deleted: switch it back "
                   "on and everything is where you left it.")
        for name, (label, help_text) in FEATURES.items():
            on = b.feature(name)
            new = st.toggle(label, value=on, key=f"feature_{name}", help=help_text)
            st.caption(help_text)
            if new != on:
                set_feature(name, new)
                flash(f"{label} switched {'on' if new else 'off'}", ":material/toggle_on:")
                st.rerun()

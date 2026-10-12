"""Today's meals on Home: one line that opens the meal plan."""
from datetime import date, datetime, timedelta

import streamlit as st

from meals.data import kitchen
from meals.logic import SLOTS, reminders
from ui.nav import link


def today_line():
    """The next meal still to cook today, and how many reminders are waiting. Tapping it opens Meals.
    If anything goes wrong here, the rest of Home still works."""
    try:
        k = kitchen()
        today, now = date.today(), datetime.now()
        todays = k.entries(today)
        soon = k.entries(today, today + timedelta(days=1))
        notes = reminders(now, soon, k.recipes, k.items, k.pantry, k.fridge, k.names, k.household, packs=k.packs)
        to_do = [e for e in todays if e["status"] == "planned"]
        if to_do:
            slot = next(s for s in SLOTS if any(e["slot"] == s for e in to_do))
            dishes = ", ".join(k.entry_name(e) for e in to_do if e["slot"] == slot)
            label = f"{slot}: {dishes}"
        elif todays:
            label = "Today's meals are all done"
        else:
            label = "Nothing planned for today"
        if notes:
            label += f" · {len(notes)} reminder{'s' if len(notes) != 1 else ''}"
        with st.container(key="card-meal-line"):
            st.page_link(link("meals"), label=label, icon=":material/restaurant:", width="stretch")
    except Exception as exc:  # never let the kitchen break the money side
        st.caption(f"Today's meals couldn't load ({exc}).")

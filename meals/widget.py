"""The "Today's meals" panel on the dashboard."""
from datetime import date, datetime, timedelta

import streamlit as st

from meals.data import kitchen
from meals.logic import SLOTS, reminders
from ui.components import empty, esc, field_msg
from ui.nav import link

TONE = {"warn": "warn", "info": "hint", "ok": "ok"}


def today_panel():
    """Today's menu from the plan and the fridge, plus reminders that affect cooking.
    If anything goes wrong here, the rest of the dashboard still works."""
    ss = st.session_state
    try:
        from meals.pages.plan import _entry_row
        k = kitchen()
        today = date.today()
        now = datetime.now()
        todays = k.entries(today)
        soon = k.entries(today, today + timedelta(days=1))
        notes = reminders(now, soon, k.recipes, k.items, k.pantry, k.fridge, k.names, k.household, packs=k.packs)
        to_do = sum(1 for e in todays if e["status"] == "planned")
        label = "Today's meals"
        if todays:
            label += f" · {to_do} to go" if to_do else " · all done"
        if notes:
            label += f" · {len(notes)} reminder{'s' if len(notes) != 1 else ''}"
        ss.setdefault("draft_open_meals", True)  # open when the app starts; you can fold it away
        with st.expander(label, key="draft_open_meals", icon=":material/restaurant:", on_change="rerun"):
            if not todays:
                empty("Nothing planned for today.")
            for slot in SLOTS:
                slot_entries = [e for e in todays if e["slot"] == slot]
                if slot_entries:
                    st.html(f'<div class="meal-slot">{esc(slot)}</div>')
                    for e in slot_entries:
                        _entry_row(k, e, today)
            for tone, text in notes:
                field_msg(text, TONE[tone])
            st.page_link(link("meals"), label="Open the meal plan", icon=":material/calendar_view_week:")
    except Exception as exc:  # never let the kitchen break the money dashboard
        st.caption(f"Today's meals couldn't load ({exc}).")

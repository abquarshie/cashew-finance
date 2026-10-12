"""The Today card: what to cook, whether it's all in, and the one reminder that matters most.
Shown on Home and at the top of the meal plan; the morning Telegram message is built from the same summary."""
from datetime import datetime

import streamlit as st

from meals.briefing import STATUS_ICON, today_summary
from meals.data import kitchen
from ui.components import esc
from ui.nav import link

TONE = {"warn": "warn", "info": "hint", "ok": "ok", "hint": "hint"}


def today_card(link_to_plan=True):
    """On Home: the most urgent reminder and a link to the plan. On the plan itself (link_to_plan=False):
    every reminder for today and tomorrow. If anything goes wrong here, the rest of the page still works."""
    try:
        k = kitchen()
        s = today_summary(k, datetime.now())
        rows = "".join(
            f'<div class="today-row {status}"><span class="today-slot">{esc(slot)}</span>'
            f'<span class="today-dish">{esc(name)}</span>'
            f'<span class="today-tag">{STATUS_ICON[status]} {esc(label)}</span></div>'
            for slot, name, status, label in s["meals"])
        shown = [s["note"]] if link_to_plan and s["note"] else ([] if link_to_plan else s["notes"])
        note = "".join(f'<div class="today-note {TONE[tone]}">{esc(text)}</div>' for tone, text in shown)
        more = len(s["notes"]) - len(shown)
        with st.container(key="card-today"):
            st.html(f'<div class="today-head">🍲 Today · {s["day"]:%a %d %b}</div>{rows}{note}')
            if link_to_plan:
                label = "Open the meal plan" + (f" · {more} more reminder{'s' if more != 1 else ''}" if more > 0 else "")
                st.page_link(link("meals"), label=label, icon=":material/calendar_view_week:")
    except Exception as exc:  # never let the kitchen break the money side
        st.caption(f"Today's meals couldn't load ({exc}).")

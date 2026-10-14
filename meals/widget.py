"""The Today card: what to cook and whether it's all in.
Shown on Home and at the top of the meal plan; the morning Telegram message is built from the same summary."""
from datetime import datetime

import streamlit as st

from meals.briefing import STATUS_ICON, today_summary
from meals.data import kitchen
from ui.components import esc
from ui.nav import link

TONE = {"warn": "warn", "info": "hint", "ok": "ok", "hint": "hint"}


def _tag(status, label):
    """The line under a meal: 'Missing: 2 cups Kokonte powder', 'All in', 'From the fridge'."""
    if status == "short" and label.startswith("missing "):
        return f"Missing: {label[len('missing '):]}"
    return label[:1].upper() + label[1:] if label else ""


def _row(slot, name, status, label):
    tag = _tag(status, label)
    tag_html = f'<div class="today-tag">{STATUS_ICON[status]} {esc(tag)}</div>' if tag else ""
    return (f'<div class="today-row {status}"><div class="today-dish"><span class="today-slot">{esc(slot)}:</span> '
            f'{esc(name)}</div>{tag_html}</div>')


def today_card(link_to_plan=True):
    """On Home (link_to_plan=True): each of today's meals with what's missing under it, and a link to the plan,
    which also says how many reminders are waiting there. On the plan itself: every reminder for today and
    tomorrow too. If anything goes wrong here, the rest of the page still works."""
    try:
        k = kitchen()
        s = today_summary(k, datetime.now())
        if s["meals"]:
            rows = "".join(_row(*m) for m in s["meals"])
        else:
            rows = '<div class="today-row"><div class="today-dish muted">Nothing planned for today.</div></div>'
        notes = "" if link_to_plan else "".join(
            f'<div class="today-note {TONE[tone]}">{esc(text)}</div>' for tone, text in s["notes"])
        with st.container(key="card-today"):
            st.html(f'<div class="today-head">🍲 Today · {s["day"]:%a %d %b}</div>{rows}{notes}')
            if link_to_plan:
                n = len(s["reminders"])
                label = "Open the meal plan" + (f" · {n} reminder{'s' if n != 1 else ''}" if n else "")
                st.page_link(link("meals"), label=label, icon=":material/calendar_view_week:")
    except Exception as exc:  # never let the kitchen break the money side
        st.caption(f"Today's meals couldn't load ({exc}).")

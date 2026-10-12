"""Small building blocks shared by every page."""
from datetime import date, timedelta
from html import escape

import streamlit as st

from core.data import SHARED, clean_note, money


def esc(x):
    return escape(str(x))


def page_header(title, subtitle=""):
    if st.session_state.get("_in_tab"):  # inside a tab the page already has its title; keep only the one-line explanation
        if subtitle:
            st.caption(subtitle)
        return
    sub = f'<div class="page-sub">{esc(subtitle)}</div>' if subtitle else ""
    st.html(f'<div class="page-head"><div class="page-title">{esc(title)}</div>{sub}</div>')


def section(title, aside=""):
    aside_html = f'<span class="section-aside">{esc(aside)}</span>' if aside else ""
    st.html(f'<div class="section"><span class="section-title">{esc(title)}</span>{aside_html}</div>')


def card(key):
    """A white card with a soft shadow. Use as `with card("name"):`."""
    return st.container(key=f"card-{key}")


def pill(text, tone="neutral"):
    return f'<span class="pill {tone}">{esc(text)}</span>'


def field_msg(text, tone="error"):
    st.html(f'<div class="field-msg {tone}">{esc(text)}</div>')


def empty(text):
    st.html(f'<div class="empty">{esc(text)}</div>')


def flash(message, icon=":material/check_circle:"):
    """Show a toast on the next run (survives st.rerun). Several can queue up."""
    st.session_state.setdefault("_flash", []).append((message, icon))


def show_flash():
    for message, icon in st.session_state.pop("_flash", []):
        long = icon in (":material/warning:", ":material/trending_up:", ":material/trending_down:")
        st.toast(message, icon=icon, duration="long" if long else "short")


# ---- KPI cards ---------------------------------------------------------------
def kpi_html(label, value, sub="", featured=False):
    cls = "kpi featured" if featured else "kpi"
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return f'<div class="{cls}"><div class="kpi-label">{esc(label)}</div><div class="kpi-value">{esc(value)}</div>{sub_html}</div>'


def kpi_grid(cards, cls=""):
    st.html(f'<div class="kpi-grid {cls}">{"".join(cards)}</div>')


def change_pill(cur, prev, good_when_up=True):
    """A small pill comparing with last month."""
    if prev == 0:
        return pill("New this month" if cur else "No data yet", "neutral")
    pct = (cur - prev) / abs(prev) * 100
    if abs(pct) < 0.5:
        return pill("Same as last month", "neutral")
    up = pct > 0
    tone = "in" if up == good_when_up else "out"
    return pill(f"{'▲' if up else '▼'} {abs(pct):.0f}% vs last month", tone)


# ---- progress bars ------------------------------------------------------------
def progress_html(name, pct, tone, right_pill, foot_left, foot_right="", foot_over=False):
    over_cls = ' class="over"' if foot_over else ""
    return (
        f'<div><div class="prog-head"><span class="prog-name">{esc(name)}</span>{right_pill}</div>'
        f'<div class="bar"><div class="fill {tone}" style="width:{max(min(pct, 100), 0):.1f}%"></div></div>'
        f'<div class="prog-foot"><span{over_cls}>{foot_left}</span><span>{foot_right}</span></div></div>'
    )


def budget_html(b):
    pct = b["pct"]
    if b["spent"] > b["limit"]:
        tone, state = "over", pill("Over", "out")
        left, over = f"{money(b['spent'] - b['limit'])} over", True
    elif pct >= 75:
        tone, state = "warn", pill("Near limit", "warn")
        left, over = f"{money(b['limit'] - b['spent'])} left", False
    else:
        tone, state = "ok", pill("On track", "in")
        left, over = f"{money(b['limit'] - b['spent'])} left", False
    right = f'<span class="num">{money(b["spent"])} of {money(b["limit"])}</span>'
    return progress_html(b["name"], pct, tone, state, left, right, over)


# ---- activity feed -------------------------------------------------------------
def day_label(d):
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    if d > today:
        return f"Upcoming, {d:%a %d %b}"
    return f"{d:%a %d %b}" if d.year == today.year else f"{d:%d %b %Y}"


def activity_items(book, limit=8):
    """Recent transactions and goal savings, newest first, as plain dicts."""
    items = []
    for _, r in book.tx.head(limit * 2).iterrows():
        items.append({"date": r["date"], "id": r["id"], "kind": r["type"], "title": r["category"],
                      "amount": r["amount"], "account": r["account"], "to": r["to_account"],
                      "who": r["member"], "note": clean_note(r["note"]), "auto": bool(r["is_auto"]),
                      "fee": bool(r["is_fee"]), "by": r["created_by"]})
    for _, c in book.contribs.head(limit).iterrows():
        items.append({"date": c["date"], "id": -c["id"], "kind": "Goal", "title": c["goal"], "amount": c["amount"],
                      "account": "", "to": "", "who": SHARED, "note": c["note"], "auto": False, "fee": False,
                      "by": c["created_by"]})
    items.sort(key=lambda i: (i["date"], i["id"]), reverse=True)
    return items[:limit]


def feed_html(items, show_who=False, names=None):
    """names: username -> display name; when given, each entry says who added it."""
    out, last_day = [], None
    for i in items:
        if i["date"] != last_day:
            out.append(f'<div class="feed-day">{esc(day_label(i["date"]))}</div>')
            last_day = i["date"]
        kind = i["kind"]
        if kind == "Income":
            icon, cls, amount = "+", "in", money(i["amount"], signed=True)
            where = i["account"]
        elif kind == "Expense":
            icon, cls, amount = "−", "out", money(-i["amount"], signed=True)
            where = i["account"]
        elif kind == "Transfer":
            icon, cls, amount = "⇄", "move", money(i["amount"])
            where = f"{i['account'] or '?'} to {i['to'] or '?'}"
        else:
            icon, cls, amount = "★", "goal", money(i["amount"])
            where = "Saved towards goal"
        tags = ""
        if i["auto"]:
            tags += pill("Auto", "accent")
        if i["fee"]:
            tags += pill("Fee", "neutral")
        meta = [f"<b>{esc(where)}</b>"] if where else []
        if show_who and i["who"] != SHARED:
            meta.append(esc(i["who"]))
        if i["note"] and not i["auto"]:
            meta.append(esc(i["note"]))
        if names and i.get("by"):
            meta.append(f"added by {esc(names.get(i['by'], i['by']))}")
        out.append(
            f'<div class="feed-row"><div class="feed-icon {cls}">{icon}</div>'
            f'<div class="feed-main"><div class="feed-title"><span class="t">{esc(i["title"])}</span>{tags}</div>'
            f'<div class="feed-meta">{", ".join(meta)}</div></div>'
            f'<div class="amt {cls}">{amount}</div></div>'
        )
    return f'<div class="feed">{"".join(out)}</div>'


def accounts_html(balances):
    cards = "".join(
        f'<div class="acct"><div class="acct-name">{esc(name)}</div>'
        f'<div class="acct-bal{" neg" if value < 0 else ""}">{money(value)}</div></div>'
        for name, value in balances.items()
    )
    return f'<div class="acct-grid">{cards}</div>'


# ---- confirmation ---------------------------------------------------------------
@st.dialog("Please confirm", width="small")
def confirm(message, statements, done_message, button="Delete", icon=":material/delete:", undo=None, after=None):
    """Ask before anything that can't easily be taken back, then run all statements together."""
    from core.db import run_many

    st.markdown(message)
    row = st.container(horizontal=True, horizontal_alignment="right")
    if row.button("Cancel", key="confirm_cancel"):
        st.rerun()
    if row.button(button, type="primary", key="confirm_go"):
        try:
            run_many(statements)
        except Exception as exc:
            st.error(f"That didn't save: {exc}")
            return
        if undo:
            st.session_state["_undo"] = undo
        if after:
            after()
        flash(done_message, icon)
        st.rerun()

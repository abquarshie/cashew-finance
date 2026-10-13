from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from core.data import CURRENCY, book, money
from ui.components import (activity_items, budget_html, card, change_pill, empty, esc, feed_html, field_msg, kpi_grid,
                           kpi_html, page_header, pill, progress_html, section)
from ui.entry import add_button
from meals.widget import today_card
from ui.nav import drawer, link

IN_COLOR = "#1FA971"
OUT_COLOR = "#E4574F"
# axis labels like 1.5k instead of 1500
SHORT = "datum.value >= 1000 ? format(datum.value / 1000, '~') + 'k' : format(datum.value, ',')"
CAT_COLORS = ["#14A38F", "#E4572E", "#F2A541", "#5B8DEF", "#8DBF8B", "#D17A93", "#9FB0C3", "#A58BC9", "#C9A227", "#4FB0C6"]


def _trend_chart(b, period, height=230):
    periods = pd.period_range(end=period, periods=6, freq="M")
    rows = []
    for p in periods:
        inc, exp = b.month_totals(p)
        rows += [{"Month": p.strftime("%b"), "Type": "Income", "Amount": inc},
                 {"Month": p.strftime("%b"), "Type": "Expenses", "Amount": exp}]
    labels = [p.strftime("%b") for p in periods]
    return (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(point=alt.OverlayMarkDef(size=55, filled=True), strokeWidth=2.5, interpolate="monotone")
        .encode(
            x=alt.X("Month:N", sort=labels, axis=alt.Axis(title=None, labelAngle=0, domain=False, ticks=False)),
            y=alt.Y("Amount:Q", axis=alt.Axis(title=None, tickCount=4, domain=False, ticks=False, labelExpr=SHORT)),
            color=alt.Color("Type:N", scale=alt.Scale(domain=["Income", "Expenses"], range=[IN_COLOR, OUT_COLOR]),
                            legend=alt.Legend(title=None, orient="top", direction="horizontal")),
            tooltip=["Month:N", "Type:N", alt.Tooltip("Amount:Q", format=",.2f", title=f"Amount ({CURRENCY})")],
        )
        .properties(height=height)
        .configure_view(strokeWidth=0).configure(background="transparent")
    )


def _spend_chart(spend, field):
    return (
        alt.Chart(spend)
        .mark_arc(innerRadius=58, outerRadius=98, padAngle=0.02, cornerRadius=3)
        .encode(
            theta=alt.Theta("amount:Q", stack=True),
            color=alt.Color(f"{field}:N", sort=list(spend[field]), scale=alt.Scale(range=CAT_COLORS),
                            legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=150)),
            order=alt.Order("amount:Q", sort="descending"),
            tooltip=[alt.Tooltip(f"{field}:N", title="Spent on"), alt.Tooltip("amount:Q", title=f"Amount ({CURRENCY})", format=",.2f")],
        )
        .properties(height=300)
        .configure_view(strokeWidth=0).configure(background="transparent")
    )



@st.fragment
def _spending(period):
    """Its Groups/Categories switch only redraws this panel."""
    b = book()
    month_tx = b.month_expenses(period)
    if not len(month_tx):
        empty("No expenses this month.")
        return
    mode = st.segmented_control("Show", ["Groups", "Categories"], default="Groups", key="spend_mode",
                                label_visibility="collapsed") or "Groups"
    field = "group" if mode == "Groups" else "category"
    spend = month_tx.groupby(field, as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    if field == "category" and len(spend) > 8:
        top, rest = spend.head(7), spend.iloc[7:]
        spend = pd.concat([top, pd.DataFrame([{field: "Everything else", "amount": rest["amount"].sum()}])])
    st.altair_chart(_spend_chart(spend, field), width="stretch")
    lead = spend.iloc[0]
    st.caption(f"{lead[field]} took {lead['amount'] / month_tx['amount'].sum() * 100:.0f}% of spending.")


def _mini(label, value, sub="", wide=False):
    sub_html = f'<div class="mini-sub">{sub}</div>' if sub else ""
    return f'<div class="mini{" wide" if wide else ""}"><div class="mini-label">{esc(label)}</div><div class="mini-value">{esc(value)}</div>{sub_html}</div>'


def _more_stats(b, period):
    """Secondary tiles, tucked into the sidebar behind a toggle."""
    slot = drawer()
    on = slot.toggle("More stats", key="draft_more_stats", help="Total in all accounts, net balance, savings rate, budgets at risk, "
                     "the next auto entry, spending by person, and income and expenses over 6 months.")
    if not on:
        return
    inc, exp = b.month_totals(period)
    p_inc, p_exp = b.month_totals(period - 1)
    balances = b.balances()
    total = float(balances.sum()) if len(balances) else 0.0
    total_tile = _mini("In all accounts", money(total),
                       f"{len(balances)} account{'s' if len(balances) != 1 else ''}, savings included", wide=True)
    net_tile = _mini("Net balance", money(inc - exp), change_pill(inc - exp, p_inc - p_exp), wide=True)
    if inc > 0:
        rate = (inc - exp) / inc * 100
        rate_tile = _mini("Savings rate", f"{rate:.0f}%", "of income kept" if rate >= 0 else "Spending is above income")
    else:
        rate_tile = _mini("Savings rate", "—", "No income recorded yet")
    status = b.budget_status(period)
    at_risk = sum(1 for s in status if s["pct"] >= 75)
    if status:
        risk_tile = _mini("Budgets at risk", str(at_risk),
                          "All on track" if not at_risk else f"of {len(status)} near or over the limit")
    else:
        risk_tile = _mini("Budgets at risk", "—", "No budgets set")
    nxt = b.next_auto()
    if nxt is None:
        next_tile = _mini("Next auto entry", "—", "None set up", wide=True)
    else:
        days = (nxt["next_date"] - date.today()).days
        when = "Today" if days <= 0 else ("Tomorrow" if days == 1 else f"{nxt['next_date']:%a %d %b}")
        next_tile = _mini("Next auto entry", when, esc(f"{nxt['name']}, {money(nxt['amount'])}"), wide=True)

    tiles = [total_tile, net_tile, rate_tile, risk_tile, next_tile]

    if b.multi_member:
        by_member = b.month_expenses(period).groupby("member")["amount"].sum().sort_values(ascending=False)
        if len(by_member):
            total = float(by_member.sum())
            people = "".join(
                progress_html(who, amt / total * 100, "ok", pill(f"{amt / total * 100:.0f}%", "neutral"),
                              f'<span class="num">{money(amt)}</span>')
                for who, amt in by_member.items())
            tiles.append(f'<div class="mini wide"><div class="mini-label">Spending by person, {period.strftime("%B")}</div>'
                         f'<div class="mini-people">{people}</div></div>')
    slot.html(f'<div class="mini-stack">{"".join(tiles)}</div>')
    with slot.container(key="mini-trend"):
        st.html('<div class="mini-label">Income and expenses, 6 months</div>')
        st.altair_chart(_trend_chart(b, period, height=170), width="stretch")


def _safe_tile(b):
    """The one big number: what can be spent until payday."""
    s2s = b.safe_to_spend()
    if s2s["safe"] > 0:
        sub = f"About {money(max(s2s['per_day'], 0))} a day for {s2s['days']} day{'s' if s2s['days'] != 1 else ''}"
    else:
        sub = "Spending is ahead of what's coming in"
    neg = " neg" if s2s["safe"] < 0 else ""
    return (f'<div class="hero"><div class="hero-label">Safe to spend until payday, {s2s["payday"]:%a %d %b}</div>'
            f'<div class="hero-value{neg}">{money(s2s["safe"])}</div><div class="hero-sub">{sub}</div></div>'), s2s


def _balances(b, s2s):
    """Every account, one tap below the big number."""
    balances = b.balances()
    total = float(balances.sum()) if len(balances) else 0.0
    everyday = set(b.everyday_accounts)
    with st.expander(f"Account balances · {money(total)} in all", icon=":material/account_balance_wallet:"):
        rows = "".join(
            f'<div class="bal-row"><span>{esc(n)}{"" if n in everyday else " <i>savings</i>"}</span>'
            f'<b class="{"neg" if v < 0 else ""}">{money(v)}</b></div>'
            for n, v in balances.items())
        st.html(f'<div class="bal-rows">{rows}</div>')
        st.caption(f"Safe to spend is your everyday money ({money(s2s['money'])}) minus {money(s2s['bills'])} in "
                   f"repeat bills before payday and {money(s2s['budget_left'])} still to spend in budgets. "
                   "Savings accounts aren't counted.")
        unassigned = b.unassigned_count()
        if unassigned:
            field_msg(f"{unassigned} older entr{'ies have' if unassigned != 1 else 'y has'} no account, so balances "
                      "may be off. Fix this in Settings → Accounts.", "warn")


def render():
    b = book()
    ss = st.session_state
    name = (ss.get("user") or {}).get("name")
    page_header(f"Hello, {name}" if name else "Home")

    hero, s2s = _safe_tile(b)
    st.html(hero)
    _balances(b, s2s)
    add_button("home")
    if b.feature("kitchen"):
        today_card()

    period = st.selectbox("Month", b.months(), format_func=lambda p: p.strftime("%B %Y"), key="dash_month",
                          label_visibility="collapsed")
    inc, exp = b.month_totals(period)
    if period == pd.Period(date.today(), "M"):  # part-way through the month: compare the same days of last month
        p_inc, p_exp = b.month_totals(period - 1, upto_day=date.today().day)
        prev = period - 1
        last = min(date.today().day, prev.days_in_month)
        versus = f"1–{last} {prev.strftime('%b')}"  # e.g. "1–13 Sep": the same days of last month
    else:
        p_inc, p_exp = b.month_totals(period - 1)
        versus = "last month"
    kpi_grid([
        kpi_html("Income", money(inc), change_pill(inc, p_inc, versus=versus)),
        kpi_html("Expenses", money(exp), change_pill(exp, p_exp, good_when_up=False, versus=versus)),
    ], cls="two")
    _more_stats(b, period)

    with card("activity"):
        section("Recent activity")
        items = activity_items(b, limit=5)
        if items:
            st.html(feed_html(items, show_who=b.multi_member, names=b.name_of_user if len(b.users) > 1 else None))
            st.page_link(link("transactions"), label="See all transactions", icon=":material/receipt_long:")
        else:
            empty("Nothing recorded yet. Tap Add an entry to record your first one.")

    month = period.strftime("%B")
    with st.expander(f"Budgets and spending · {month}", icon=":material/donut_small:"):
        status = b.budget_status(period)
        if status:
            st.html(f'<div class="prog-list">{"".join(budget_html(s) for s in status)}</div>')
        else:
            empty("No monthly budgets yet.")
            st.page_link(link("budgets"), label="Set a budget", icon=":material/donut_small:")
        st.html('<div class="section"><span class="section-title">Where the money went</span></div>')
        _spending(period)

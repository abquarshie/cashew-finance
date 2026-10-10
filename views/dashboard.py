from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from core.data import CURRENCY, book, money
from ui.components import (accounts_html, activity_items, budget_html, card, change_pill, empty, feed_html,
                           kpi_grid, kpi_html, page_header, pill, progress_html, section)
from ui.entry import goal_dialog, quick_add_dialog, set_kind
from ui.nav import link

IN_COLOR = "#1FA971"
OUT_COLOR = "#E4574F"
# axis labels like 1.5k instead of 1500
SHORT = "datum.value >= 1000 ? format(datum.value / 1000, '~') + 'k' : format(datum.value, ',')"
CAT_COLORS = ["#14A38F", "#E4572E", "#F2A541", "#5B8DEF", "#8DBF8B", "#D17A93", "#9FB0C3", "#A58BC9", "#C9A227", "#4FB0C6"]


def _quick_actions(b):
    row = st.container(horizontal=True, key="quick-actions", gap="small")
    for kind, icon in (("Expense", ":material/remove:"), ("Income", ":material/add:"), ("Transfer", ":material/swap_horiz:")):
        if row.button(kind, icon=icon, key=f"qa_{kind}", type="primary" if kind == "Expense" else "secondary"):
            set_kind("q", kind)
            quick_add_dialog(b)
    if row.button("Add to goal", icon=":material/savings:", key="qa_goal"):
        goal_dialog(b)


def _trend_chart(b, period):
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
        .properties(height=230)
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


def render():
    b = book()
    months = b.months()
    head, pick = st.columns([3, 1], vertical_alignment="bottom")
    with pick:
        period = st.selectbox("Month", months, format_func=lambda p: p.strftime("%B %Y"), key="dash_month",
                              label_visibility="collapsed")
    with head:
        this_month = period == pd.Period(date.today(), "M")
        page_header("Dashboard", "This month so far" if this_month else f"Summary for {period.strftime('%B %Y')}")

    inc, exp = b.month_totals(period)
    p_inc, p_exp = b.month_totals(period - 1)
    net, p_net = inc - exp, p_inc - p_exp
    if inc > 0:
        rate = net / inc * 100
        rate_val = f"{rate:.0f}%"
        rate_sub = "of income kept" if rate >= 0 else "Spending is above income"
    else:
        rate_val, rate_sub = "—", "No income recorded yet"

    balances = b.balances()
    status = b.budget_status(period)
    at_risk = sum(1 for s in status if s["pct"] >= 75)
    if not status:
        risk_val, risk_sub = "—", "No budgets set"
    else:
        risk_val = str(at_risk)
        risk_sub = "All on track" if not at_risk else f"of {len(status)} near or over the limit"
    nxt = b.next_auto()
    if nxt is None:
        next_val, next_sub = "—", "None set up"
    else:
        days = (nxt["next_date"] - date.today()).days
        next_val = "Today" if days <= 0 else ("Tomorrow" if days == 1 else f"{nxt['next_date']:%a %d %b}")
        next_sub = f"{nxt['name']}, {money(nxt['amount'])}"

    kpi_grid([
        kpi_html("Net balance", money(net), change_pill(net, p_net), featured=True),
        kpi_html("Income", money(inc), change_pill(inc, p_inc)),
        kpi_html("Expenses", money(exp), change_pill(exp, p_exp, good_when_up=False)),
        kpi_html("Savings rate", rate_val, rate_sub),
        kpi_html("In all accounts", money(float(balances.sum()) if len(balances) else 0), f"Across {len(balances)} accounts"),
        kpi_html("Budgets at risk", risk_val, risk_sub),
        kpi_html("Next auto entry", next_val, next_sub),
    ])

    _quick_actions(b)

    left, right = st.columns([2, 3], gap="medium")
    with left:
        with card("activity"):
            section("Recent activity")
            items = activity_items(b, limit=8)
            if items:
                st.html(feed_html(items, show_who=b.multi_member))
                st.page_link(link("transactions"), label="See all transactions", icon=":material/receipt_long:")
            else:
                empty("Nothing recorded yet. Tap Expense or Income above to add your first entry.")
    with right:
        with card("trend"):
            section("Income and expenses", "Last 6 months")
            st.altair_chart(_trend_chart(b, period), width="stretch")
        with card("spending"):
            section("Where the money went")
            month_tx = b.tx[(b.tx["month"] == period) & (b.tx["type"] == "Expense")] if len(b.tx) else b.tx
            if not len(month_tx):
                empty("No expenses this month.")
            else:
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

    with card("budgets"):
        section("Budgets", period.strftime("%B"))
        if status:
            st.html(f'<div class="prog-list">{"".join(budget_html(s) for s in status)}</div>')
        else:
            empty("No monthly budgets yet.")
            st.page_link(link("budgets"), label="Set a budget", icon=":material/donut_small:")

    if b.multi_member:
        month_exp = b.tx[(b.tx["month"] == period) & (b.tx["type"] == "Expense")]
        by_member = month_exp.groupby("member")["amount"].sum().sort_values(ascending=False)
        if len(by_member):
            total = float(by_member.sum())
            with card("members"):
                section("Spending by person", period.strftime("%B"))
                rows = "".join(
                    progress_html(who, amt / total * 100, "ok", pill(f"{amt / total * 100:.0f}%", "neutral"),
                                  f'<span class="num">{money(amt)}</span>')
                    for who, amt in by_member.items()
                )
                st.html(f'<div class="prog-list">{rows}</div>')

    if len(balances):
        with card("accounts"):
            section("Accounts", "Balance now")
            st.html(accounts_html(balances))
            n = b.unassigned_count()
            if n:
                st.caption(f"{n} older entr{'ies have' if n != 1 else 'y has'} no account, so these balances may be off. "
                           "Assign them in Categories & accounts.")


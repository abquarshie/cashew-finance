"""Colours, spacing and card styling. Streamlit's own widgets take their colours from
.streamlit/config.toml; this file styles the custom pieces to match."""
import streamlit as st

LIGHT = {
    "bg": "#F5F7F8", "card": "#FFFFFF", "line": "#E3E9EC", "text": "#0F1B22", "muted": "#5F7079",
    "accent": "#14A38F", "accent-ink": "#0E7F6F", "accent-soft": "#E2F4F0",
    "in": "#15824F", "in-soft": "#E1F3E9", "out": "#C93C33", "out-soft": "#FCE9E7",
    "warn": "#9A6400", "warn-soft": "#FCF1DC", "neutral-soft": "#EDF1F3", "bar": "#E8EEF0",
    "feature": "#0F3D3A", "feature-text": "#FFFFFF", "feature-muted": "#A8CFC8",
    "feature-in": "#7EE0B5", "feature-out": "#FFB4A8",
    "shadow": "0 1px 2px rgba(15,27,34,.05), 0 6px 20px -6px rgba(15,27,34,.10)",
}
DARK = {
    "bg": "#0E1417", "card": "#161E22", "line": "#253035", "text": "#E6ECEF", "muted": "#93A3AB",
    "accent": "#2BC4AD", "accent-ink": "#5ED6C3", "accent-soft": "#123430",
    "in": "#4CD39A", "in-soft": "#12301F", "out": "#FF8A80", "out-soft": "#3A1B19",
    "warn": "#F2C266", "warn-soft": "#3A2E14", "neutral-soft": "#202A2E", "bar": "#253035",
    "feature": "#0F3D3A", "feature-text": "#FFFFFF", "feature-muted": "#9CC8C0",
    "feature-in": "#7EE0B5", "feature-out": "#FFB4A8",
    "shadow": "0 0 0 1px rgba(255,255,255,.02)",
}


def _vars(tokens):
    return "".join(f"--{k}:{v};" for k, v in tokens.items())


CSS = """
<style>
/*ROOT*/

/* ---- page frame ---- */
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"], .block-container {
  padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1200px;
}
[data-testid="stSidebarCollapseButton"] { opacity: 1 !important; visibility: visible !important; }
section[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
[data-testid="stSidebarNavSeparator"] { display: none; }

.brand { display: flex; align-items: center; gap: .6rem; margin: .1rem 0 .2rem; }
.brand-mark { width: 30px; height: 30px; border-radius: 9px; background: var(--accent);
  display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 1rem; }
.brand-name { font-size: 1.15rem; font-weight: 800; letter-spacing: -.02em; }
.brand-sub { color: var(--muted); font-size: .8rem; }

/* ---- type ---- */
.page-head { margin: 0 0 1.4rem; }
.page-title { font-size: 1.85rem; font-weight: 800; letter-spacing: -.03em; line-height: 1.15; margin: 0; }
.page-sub { color: var(--muted); font-size: .93rem; margin-top: .25rem; }
.section { display: flex; justify-content: space-between; align-items: baseline; gap: .75rem; margin: 0 0 .1rem; }
.section-title { font-size: 1rem; font-weight: 750; letter-spacing: -.01em; }
.section-aside { color: var(--muted); font-size: .8rem; font-weight: 600; }
.muted { color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }

/* ---- cards: any container keyed "card-..." ---- */
div[class*="st-key-card-"] {
  background: var(--card); border: 1px solid var(--line); border-radius: 18px;
  padding: 1.15rem 1.2rem 1.2rem; box-shadow: var(--shadow);
}
div[class*="st-key-card-"] div[class*="st-key-card-"] { box-shadow: none; }

/* unsaved-changes bar stays in view while you scroll */
div.st-key-card-savebar { position: sticky; bottom: 14px; z-index: 20; border-color: var(--accent);
  box-shadow: 0 10px 30px -8px rgba(15,27,34,.28); }

/* ---- KPI grid ---- */
.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: .2rem; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.1rem;
  box-shadow: var(--shadow); min-width: 0; }
.kpi-label { color: var(--muted); font-size: .8rem; font-weight: 650; }
.kpi-value { font-size: 1.5rem; font-weight: 800; letter-spacing: -.02em; margin: .2rem 0 .35rem;
  font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-sub { font-size: .76rem; color: var(--muted); font-weight: 600; line-height: 1.35; }
.kpi.featured { grid-column: span 2; background: var(--feature); border-color: var(--feature); position: relative; overflow: hidden; }
.kpi.featured::after { content: ""; position: absolute; right: -40px; top: -60px; width: 190px; height: 190px;
  border-radius: 50%; border: 26px solid rgba(255,255,255,.05); }
.kpi.featured .kpi-label, .kpi.featured .kpi-sub { color: var(--feature-muted); }
.kpi.featured .kpi-value { color: var(--feature-text); font-size: 2rem; }
.kpi.featured .pill.in { background: rgba(126,224,181,.16); color: var(--feature-in); }
.kpi.featured .pill.out { background: rgba(255,180,168,.16); color: var(--feature-out); }
.kpi.featured .pill.neutral { background: rgba(255,255,255,.1); color: var(--feature-muted); }

.kpi-grid.three { grid-template-columns: 1.35fr 1fr 1fr; }
.kpi-grid.three .kpi.featured { grid-column: span 1; }
/* net balance with "in all accounts" under it; income and expenses beside them */
.kpi-grid.four { grid-template-columns: 1.3fr 1fr; grid-template-rows: auto auto; grid-auto-flow: column; }
.kpi-grid.four .kpi.featured { grid-column: auto; }
.kpi-grid.four .kpi-sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* account balances (tall, left) with income and expenses stacked beside it */
.kpi-grid.bal-grid { grid-template-columns: 1.5fr 1fr; grid-template-rows: auto 1fr; }
.kpi-grid.bal-grid .kpi.bal { grid-row: span 2; grid-column: auto; }
.bal-rows { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); column-gap: 1.4rem; margin: .1rem 0 .2rem; }
.bal-row { display: flex; justify-content: space-between; gap: .6rem; font-size: .84rem; padding: .32rem 0;
  border-top: 1px solid rgba(255,255,255,.09); }
.bal-row span { color: var(--feature-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bal-row span i { font-style: normal; font-size: .68rem; font-weight: 700; padding: 0 6px; border-radius: 999px;
  background: rgba(255,255,255,.1); margin-left: 4px; }
.bal-row b { color: var(--feature-text); font-weight: 700; font-variant-numeric: tabular-nums; }
.bal-row b.neg, .safe b.neg { color: var(--feature-out); }
.safe { margin-top: .7rem; padding: .7rem .8rem; border-radius: 12px; background: rgba(255,255,255,.07); position: relative; z-index: 1; }
.safe-head { display: flex; justify-content: space-between; align-items: baseline; gap: .6rem; }
.safe-head span { color: var(--feature-muted); font-size: .8rem; font-weight: 650; }
.safe-head b { color: var(--feature-in); font-size: 1.2rem; font-weight: 800; font-variant-numeric: tabular-nums; white-space: nowrap; }
.safe-sub { color: var(--feature-muted); font-size: .74rem; line-height: 1.45; margin-top: .25rem; }
.bal-note { color: var(--feature-muted); font-size: .72rem; margin-top: .5rem; }
.kpi.featured .kpi-label, .kpi.featured .kpi-value, .bal-rows { position: relative; z-index: 1; }

/* ---- kitchen ---- */
.meal-slot { color: var(--muted); font-size: .74rem; font-weight: 700; margin: .55rem 0 -.2rem; }
div[class*="st-key-meal-entry-"] { gap: .25rem !important; border-bottom: 1px solid var(--line); padding: .15rem 0; }
div[class*="st-key-meal-entry-"]:last-child { border-bottom: none; }
div[class*="st-key-meal-fr-"] { border-bottom: 1px solid var(--line); padding: .45rem 0; gap: .5rem !important; }

/* ---- collapsible dashboard panels ---- */
div[class*="st-key-draft_open_"] details { background: var(--card); border: 1px solid var(--line) !important;
  border-radius: 18px !important; box-shadow: var(--shadow); overflow: hidden; }
div[class*="st-key-draft_open_"] summary { padding: 1rem 1.2rem; background: transparent !important; }
div[class*="st-key-draft_open_"] summary:hover p { color: var(--accent-ink); }
div[class*="st-key-draft_open_"] summary p { font-size: 1rem; font-weight: 750; letter-spacing: -.01em; }
div[class*="st-key-draft_open_"] [data-testid="stExpanderDetails"] { padding: 0 1.2rem 1.2rem; }
div[class*="st-key-draft_open_"] div.st-key-card-quick-add { background: none; border: 0; box-shadow: none; padding: 0;
  border-radius: 0; }
div.st-key-mini-trend { border: 1px solid var(--line); border-radius: 14px; padding: .7rem .8rem .3rem; background: var(--card);
  margin-top: 0; }

/* ---- sidebar drawer tiles ---- */
.mini-stack { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mini.wide { grid-column: span 2; }
.mini { border: 1px solid var(--line); border-radius: 14px; padding: .7rem .8rem; background: var(--card); }
.mini-label { color: var(--muted); font-size: .76rem; font-weight: 650; }
.mini-value { font-size: 1.15rem; font-weight: 800; letter-spacing: -.01em; font-variant-numeric: tabular-nums; margin-top: 1px; }
.mini-sub { color: var(--muted); font-size: .74rem; font-weight: 600; margin-top: 1px; }
.mini-row { display: flex; justify-content: space-between; gap: .5rem; font-size: .8rem; padding: .28rem 0;
  border-top: 1px solid var(--line); margin-top: .3rem; }
.mini-row:first-of-type { margin-top: .45rem; }
.mini-row span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini-row b { font-variant-numeric: tabular-nums; font-weight: 700; }
.mini-row b.neg { color: var(--out); }
.mini-people { display: grid; gap: .7rem; margin-top: .5rem; }
.mini-people .prog-foot { display: none; }

/* ---- entry form ---- */
div.st-key-card-quick-add [data-testid="stNumberInputContainer"] input,
div.st-key-card-add-form [data-testid="stNumberInputContainer"] input { font-size: 1.35rem; font-weight: 800;
  font-variant-numeric: tabular-nums; }
div.st-key-card-quick-add [data-testid="stNumberInputContainer"],
div.st-key-card-add-form [data-testid="stNumberInputContainer"] { min-height: 3.1rem; }
[data-testid="stPills"] button, [data-testid="stButtonGroup"] button { min-height: 2.25rem; }

/* ---- pills ---- */
.pill { display: inline-flex; align-items: center; gap: 4px; padding: 1px 9px; border-radius: 999px;
  font-size: .7rem; font-weight: 700; line-height: 1.6; white-space: nowrap; vertical-align: middle; }
.pill.in { background: var(--in-soft); color: var(--in); }
.pill.out { background: var(--out-soft); color: var(--out); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.accent { background: var(--accent-soft); color: var(--accent-ink); }
.pill.neutral { background: var(--neutral-soft); color: var(--muted); }

/* ---- activity feed ---- */
.feed-day { font-size: .76rem; font-weight: 700; color: var(--muted); margin: .9rem 0 .15rem; }
.feed-day:first-child { margin-top: .2rem; }
.feed-row { display: flex; align-items: center; gap: .75rem; padding: .62rem 0; border-bottom: 1px solid var(--line); }
.feed-row:last-child { border-bottom: none; }
.feed-icon { flex: none; width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center;
  font-size: .95rem; font-weight: 800; }
.feed-icon.in { background: var(--in-soft); color: var(--in); }
.feed-icon.out { background: var(--out-soft); color: var(--out); }
.feed-icon.move, .feed-icon.goal { background: var(--accent-soft); color: var(--accent-ink); }
.feed-main { flex: 1; min-width: 0; }
.feed-title { font-weight: 700; font-size: .92rem; display: flex; align-items: center; gap: 6px; }
.feed-title span.t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-meta { color: var(--muted); font-size: .78rem; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-meta b { font-weight: 650; }
.amt { font-weight: 750; font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .92rem; }
.amt.in { color: var(--in); }
.amt.out { color: var(--text); }
.amt.move, .amt.goal { color: var(--muted); }

/* ---- progress (budgets, goals) ---- */
.prog-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.05rem 1.8rem; }
.prog-head { display: flex; justify-content: space-between; align-items: center; gap: .5rem; margin-bottom: .4rem; }
.prog-name { font-weight: 700; font-size: .92rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { background: var(--bar); height: 8px; border-radius: 999px; overflow: hidden; }
.fill { height: 100%; border-radius: 999px; background: var(--accent); }
.fill.ok { background: var(--accent); }
.fill.warn { background: #E0A030; }
.fill.over { background: var(--out); }
.prog-foot { display: flex; justify-content: space-between; gap: .5rem; font-size: .77rem; margin-top: .35rem; color: var(--muted); }
.prog-foot .over { color: var(--out); font-weight: 700; }

/* ---- accounts ---- */
.acct-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.acct { border: 1px solid var(--line); border-radius: 14px; padding: .75rem .9rem; min-width: 0; }
.acct-name { color: var(--muted); font-size: .78rem; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acct-bal { font-size: 1.1rem; font-weight: 800; letter-spacing: -.01em; font-variant-numeric: tabular-nums; margin-top: 2px; }
.acct-bal.neg { color: var(--out); }

/* ---- rule cards ---- */
.rule { display: flex; justify-content: space-between; align-items: center; gap: .8rem; padding: .8rem 0; border-bottom: 1px solid var(--line); }
.rule:last-child { border-bottom: none; }
.rule-name { font-weight: 700; font-size: .95rem; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.rule-meta { color: var(--muted); font-size: .8rem; margin-top: 3px; }
.rule-right { text-align: right; flex: none; }
.rule-next { color: var(--muted); font-size: .76rem; margin-top: 3px; }

/* ---- inline validation ---- */
.field-msg { font-size: .8rem; font-weight: 600; margin: -.45rem 0 .1rem; line-height: 1.4; }
.field-msg.error { color: var(--out); }
.field-msg.warn { color: var(--warn); }
.field-msg.hint { color: var(--muted); font-weight: 500; }
.field-msg.ok { color: var(--in); }

/* ---- sign-in ---- */
div.st-key-card-auth { max-width: 440px; margin: 4vh auto 0; }
.auth-head { text-align: center; margin: .2rem 0 .6rem; }
.auth-logo { width: 52px; height: 52px; margin: 0 auto .55rem; display: block; }
.auth-note { background: var(--accent-soft); color: var(--text); border-radius: 12px; padding: .75rem .9rem;
  font-size: .88rem; line-height: 1.45; }
.auth-title { font-size: 1.6rem; font-weight: 800; letter-spacing: -.03em; }
.auth-sub { color: var(--muted); font-size: .92rem; margin-top: .15rem; }

/* ---- signed-in person in the sidebar ---- */
.me { display: flex; align-items: center; gap: .6rem; }
.me-avatar { width: 34px; height: 34px; border-radius: 50%; background: var(--accent-soft); color: var(--accent-ink);
  display: grid; place-items: center; font-weight: 800; font-size: .9rem; flex: none; }
.me-name { font-weight: 700; font-size: .9rem; line-height: 1.2; }
.me-role { color: var(--muted); font-size: .76rem; }

.empty { color: var(--muted); font-size: .9rem; padding: .3rem 0; }

/* ---- buttons ---- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button { font-weight: 700; }
div.st-key-quick-actions .stButton > button { border-radius: 999px; padding: .35rem 1rem; min-height: 2.4rem; }

/* ---- phone ---- */
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 3.2rem .85rem 5rem; }
  .page-head { margin-bottom: 1rem; }
  .page-title { font-size: 1.5rem; }
  .kpi-grid, .kpi-grid.three, .kpi-grid.four, .kpi-grid.bal-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .kpi-grid.bal-grid { grid-template-rows: none; }
  .kpi-grid.bal-grid .kpi.bal { grid-column: span 2; grid-row: auto; }
  .bal-rows { grid-template-columns: 1fr; }
  .kpi-grid.four { grid-template-rows: none; grid-auto-flow: row; }
  .kpi-grid.three .kpi.featured, .kpi-grid.four .kpi.featured, .kpi-grid.four .kpi:nth-child(2) { grid-column: span 2; }
  .kpi-grid.four .kpi:nth-child(2) .kpi-value { font-size: 1.35rem; }
  div[class*="st-key-draft_open_"] summary { padding: .85rem .95rem; }
  div[class*="st-key-draft_open_"] [data-testid="stExpanderDetails"] { padding: 0 .95rem 1rem; }
  .kpi { padding: .8rem .85rem; border-radius: 14px; }
  .kpi-value { font-size: 1.12rem; }
  .kpi.featured .kpi-value { font-size: 1.7rem; }
  div[class*="st-key-card-"] { padding: .95rem .95rem 1rem; border-radius: 16px; }
  .prog-list { grid-template-columns: 1fr; }
  div.st-key-quick-actions { display: grid !important; grid-template-columns: 1fr 1fr; gap: 8px !important; }
  div.st-key-quick-actions > div { width: 100% !important; }
  div.st-key-quick-actions .stButton > button { width: 100%; }
  .acct-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""


def apply_theme():
    try:  # Streamlit reports the active theme; fall back to the phone/computer setting
        kind = st.context.theme.type
    except Exception:
        kind = None
    if kind == "dark":
        root = f":root{{{_vars(DARK)}}}"
    elif kind == "light":
        root = f":root{{{_vars(LIGHT)}}}"
    else:
        root = f":root{{{_vars(LIGHT)}}} @media (prefers-color-scheme: dark){{:root{{{_vars(DARK)}}}}}"
    st.html(CSS.replace("/*ROOT*/", root))

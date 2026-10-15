"""Colours, spacing and card styling. Streamlit's own widgets take their colours from
.streamlit/config.toml; this file styles the custom pieces to match."""
import streamlit as st

LIGHT = {
    "bg": "#F5F7F8", "card": "#FFFFFF", "line": "#E3E9EC", "text": "#0F1B22", "muted": "#5F7079",
    "accent": "#14A38F", "accent-ink": "#0E7F6F", "accent-soft": "#E2F4F0",
    "in": "#15824F", "in-soft": "#E1F3E9", "out": "#C93C33", "out-soft": "#FCE9E7",
    "warn": "#9A6400", "warn-soft": "#FCF1DC", "neutral-soft": "#EDF1F3", "bar": "#E8EEF0",
    "feature": "#0F3D3A", "feature-text": "#FFFFFF", "feature-muted": "#A8CFC8",
    "feature-in": "#7EE0B5", "feature-out": "#FFB4A8", "feature-over": "#5C1A26", "feature-over-muted": "#E8B4BC",
    "shadow": "0 1px 2px rgba(15,27,34,.05), 0 6px 20px -6px rgba(15,27,34,.10)",
}
DARK = {
    "bg": "#0E1417", "card": "#161E22", "line": "#253035", "text": "#E6ECEF", "muted": "#93A3AB",
    "accent": "#2BC4AD", "accent-ink": "#5ED6C3", "accent-soft": "#123430",
    "in": "#4CD39A", "in-soft": "#12301F", "out": "#FF8A80", "out-soft": "#3A1B19",
    "warn": "#F2C266", "warn-soft": "#3A2E14", "neutral-soft": "#202A2E", "bar": "#253035",
    "feature": "#0F3D3A", "feature-text": "#FFFFFF", "feature-muted": "#9CC8C0",
    "feature-in": "#7EE0B5", "feature-out": "#FFB4A8", "feature-over": "#4A1520", "feature-over-muted": "#E0A9B2",
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
/* Streamlit Cloud's own buttons in the app's top bar (Share, star, edit, GitHub; Fork for visitors) */
[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], .stAppDeployButton { display: none !important; }


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


/* ---- Home: what's left of this month's budgets is the one big number ---- */
.hero { background: var(--feature); border-radius: 20px; padding: 1.15rem 1.3rem 1.2rem; position: relative; overflow: hidden;
  margin-bottom: .2rem; }
.hero::after { content: ""; position: absolute; right: -50px; top: -70px; width: 210px; height: 210px; border-radius: 50%;
  background: rgba(255,255,255,.06); }
.hero-label { color: var(--feature-muted); font-size: .84rem; font-weight: 650; position: relative; z-index: 1; }
.hero-value { color: var(--feature-text); font-size: 2.6rem; font-weight: 850; letter-spacing: -.035em; line-height: 1.1;
  margin: .25rem 0 .3rem; font-variant-numeric: tabular-nums; position: relative; z-index: 1; }
.hero.over { background: var(--feature-over); }
.hero.over .hero-label { color: var(--feature-over-muted); }
.kpi-grid.two { grid-template-columns: 1fr 1fr; }
.bal-rows { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); column-gap: 1.4rem; margin: 0 0 .3rem; }
.bal-row { display: flex; justify-content: space-between; gap: .6rem; font-size: .9rem; padding: .4rem 0;
  border-bottom: 1px solid var(--line); }
.bal-row span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bal-row b { font-weight: 750; font-variant-numeric: tabular-nums; }
.bal-row b.neg { color: var(--out); }
.bal-row span i { font-style: normal; font-size: .68rem; font-weight: 700; padding: 0 6px; border-radius: 999px;
  background: var(--neutral-soft); margin-left: 4px; }
.bal-savings { margin-top: .7rem; padding-top: .3rem; border-top: 2px solid var(--line); }
/* ---- Today card: what to cook and whether it's all in ---- */
.today-head { font-size: 1rem; font-weight: 750; letter-spacing: -.01em; margin-bottom: .35rem; }
.today-row { padding: .45rem 0; border-top: 1px solid var(--line); font-size: .9rem; line-height: 1.35; }
.today-slot { color: var(--muted); font-weight: 700; }
.today-dish { font-weight: 650; min-width: 0; }
.today-tag { color: var(--muted); font-size: .78rem; font-weight: 600; margin-top: .1rem; }
.today-row.short .today-tag { color: var(--warn); }
.today-row.ready .today-tag, .today-row.leftovers .today-tag { color: var(--in); }
.today-row.done .today-dish { color: var(--muted); text-decoration: line-through; }
.today-note { margin-top: .5rem; padding: .55rem .7rem; border-radius: 12px; font-size: .84rem; line-height: 1.45;
  background: var(--accent-soft); }
.today-note.warn { background: var(--warn-soft); }
.bought-row { font-size: .95rem; line-height: 1.4; padding: .35rem 0; min-width: 0; }
.week-head { color: var(--muted); font-size: .8rem; font-weight: 700; margin: .2rem 0 .1rem; }
div[class*="st-key-add_open_"] button { min-height: 3rem; font-size: 1.02rem; border-radius: 14px; }

/* ---- Telegram preview ---- */
.tg-preview { background: var(--neutral-soft); border-radius: 14px 14px 14px 4px; padding: .8rem .95rem; font-size: .88rem;
  line-height: 1.5; max-width: 520px; }

/* ---- kitchen ---- */
.week-cost { border-radius: 14px; padding: .75rem .95rem; font-size: .88rem; line-height: 1.5; margin: .1rem 0 .4rem;
  background: var(--accent-soft); color: var(--text); }
.week-cost.warn { background: var(--warn-soft); }
div[class*="st-key-meal-mk-"] { border-bottom: 1px solid var(--line); padding: .35rem 0 .45rem; }
div[class*="st-key-meal-mk-"] [data-testid="stCheckbox"] label p { font-size: 1rem; font-weight: 650; }
.mk-why { color: var(--muted); font-size: .76rem; margin: -.55rem 0 0 1.85rem; }
.week-cost b { font-weight: 750; }
.meal-slot { color: var(--muted); font-size: .74rem; font-weight: 700; margin: .55rem 0 -.2rem; }
.meal-parts { color: var(--muted); font-size: .76rem; line-height: 1.4; margin: -.35rem 0 .2rem 1.85rem; }
div[class*="st-key-meal-combo-"] { gap: .25rem !important; padding: .15rem 0; }
div[class*="st-key-meal-entry-"] { gap: .25rem !important; border-bottom: 1px solid var(--line); padding: .15rem 0; }
div[class*="st-key-meal-entry-"]:last-child { border-bottom: none; }
div[class*="st-key-meal-fr-"] { border-bottom: 1px solid var(--line); padding: .45rem 0; gap: .5rem !important; }

div.st-key-mini-trend { border: 1px solid var(--line); border-radius: 14px; padding: .7rem .8rem .3rem; background: var(--card);
  margin-top: 0; }

/* ---- sidebar drawer tiles ---- */
.mini-stack { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mini.wide { grid-column: span 2; }
.mini { border: 1px solid var(--line); border-radius: 14px; padding: .7rem .8rem; background: var(--card); }
.mini-label { color: var(--muted); font-size: .76rem; font-weight: 650; }
.mini-value { font-size: 1.15rem; font-weight: 800; letter-spacing: -.01em; font-variant-numeric: tabular-nums; margin-top: 1px; }
.mini-sub { color: var(--muted); font-size: .74rem; font-weight: 600; margin-top: 1px; }
.mini-people { display: grid; gap: .7rem; margin-top: .5rem; }
.mini-people .prog-foot { display: none; }

/* ---- entry form ---- */
div.st-key-draft_q_amount [data-testid="stNumberInputContainer"] input { font-size: 1.35rem; font-weight: 800;
  font-variant-numeric: tabular-nums; }
div.st-key-draft_q_amount [data-testid="stNumberInputContainer"] { min-height: 3.1rem; }
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

/* ---- phone ---- */
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 3.2rem .85rem 5rem; }
  .page-head { margin-bottom: 1rem; }
  .page-title { font-size: 1.5rem; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .hero-value { font-size: 2.2rem; }
  .bal-rows { grid-template-columns: 1fr; }
  .kpi { padding: .8rem .85rem; border-radius: 14px; }
  .kpi-value { font-size: 1.12rem; }
  div[class*="st-key-card-"] { padding: .95rem .95rem 1rem; border-radius: 16px; }
  .prog-list { grid-template-columns: 1fr; }
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


# Phones take a home-screen icon from the page around the app. Without this, every Streamlit app gets
# Streamlit's red crown. The script points that page at Cashew's own icon and manifest in static/
# (served at app/static/ because .streamlit/config.toml switches on enableStaticServing).
HOME_ICON = """<script>/* home-screen icon */
(() => {
  const dir = location.pathname.replace(/[^/]*$/, "");
  const base = location.origin + dir + "app/static/";
  let doc = document;
  try { if (window.top.document) doc = window.top.document; } catch (e) { /* another site: use our own page */ }
  if (doc.querySelector('link[data-cashew]')) return;
  const head = doc.head;
  const put = (tag, attrs, drop) => {
    if (drop) head.querySelectorAll(drop).forEach(el => el.remove());
    const el = doc.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    el.setAttribute("data-cashew", "");
    head.appendChild(el);
  };
  put("link", {rel: "manifest", href: base + "manifest.json"}, 'link[rel="manifest"]');
  put("link", {rel: "apple-touch-icon", href: base + "apple-touch-icon.png"}, 'link[rel="apple-touch-icon"]');
  put("link", {rel: "icon", type: "image/png", sizes: "192x192", href: base + "icon-192.png"}, 'link[rel~="icon"]');
  put("meta", {name: "theme-color", content: "#14A38F"}, 'meta[name="theme-color"]');
  put("meta", {name: "apple-mobile-web-app-title", content: "Cashew"}, 'meta[name="apple-mobile-web-app-title"]');
  put("meta", {name: "application-name", content: "Cashew"}, 'meta[name="application-name"]');
})();
</script>"""


# Streamlit Cloud puts a "Manage app" button, its crown badge and the author's picture on the page around the
# app, outside it. Hide them there (same site, so the app may reach it), including when they appear late.
HOST_CHROME = """<script>/* hide host buttons */
(() => {
  let doc;
  try { doc = window.top.document; } catch (e) { return; }
  if (!doc || doc === document || doc.getElementById("cashew-host-chrome")) return;
  const style = doc.createElement("style");
  style.id = "cashew-host-chrome";
  style.textContent = `
    [class*="viewerBadge"], [class*="profileContainer"], [class*="ProfileContainer"],
    [data-testid="manage-app-button"], [data-testid*="appCreator"], [data-testid*="viewerBadge"],
    a[href*="streamlit.io/cloud"], a[href*="share.streamlit.io/user"] { display: none !important; }`;
  doc.head.appendChild(style);
  const sweep = () => {
    doc.querySelectorAll("button, a, div[role=button]").forEach(el => {
      if ((el.textContent || "").trim() !== "Manage app") return;
      // hide the floating panel that holds it (a few levels up at most), never anything holding the app itself
      let box = el, up = 0;
      while (up < 4 && box.parentElement && box.parentElement !== doc.body &&
             getComputedStyle(box).position !== "fixed" && !box.parentElement.querySelector("iframe")) {
        box = box.parentElement; up += 1;
      }
      if (!box.querySelector("iframe")) box.style.setProperty("display", "none", "important");
    });
  };
  sweep();
  new MutationObserver(sweep).observe(doc.body, {childList: true, subtree: true});
})();
</script>"""


def hide_host_chrome():
    st.html(HOST_CHROME, unsafe_allow_javascript=True, width="content")


def home_icon():
    if st.get_option("server.enableStaticServing"):
        st.html(HOME_ICON, unsafe_allow_javascript=True, width="content")


def theme_missing():
    """True when .streamlit/config.toml didn't reach the server (colours fall back to Streamlit's red)."""
    return st.get_option("theme.light.primaryColor") is None

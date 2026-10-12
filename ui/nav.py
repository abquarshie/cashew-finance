"""Shared navigation bits, filled in by app.py."""
PAGES = {}     # url path -> st.Page, so any page can link to another
DRAWER = None  # a sidebar container pages can add panels to


def link(name):
    return PAGES[name]


def go(name, tab=None, label=None, icon=None):
    """A link to a page, opened on one of its tabs."""
    import streamlit as st
    params = {f"tab_{name}": tab} if tab else None
    st.page_link(PAGES[name], label=label, icon=icon, query_params=params)


def drawer():
    import streamlit as st
    return DRAWER if DRAWER is not None else st.sidebar


def tabbed(name, title, subtitle, tabs):
    """One page with a row of tabs. Only the open tab is drawn, so the others cost nothing.

    tabs: list of (label, draw). The open tab shows in the address (?tab_<page>=Label),
    so a link or bookmark can open a page on a given tab.
    """
    import streamlit as st
    from ui.components import page_header

    page_header(title, subtitle)
    if not tabs:
        return
    draws = dict(tabs)
    key = f"tab_{name}"
    if len(tabs) > 1:
        if st.session_state.get(key) not in draws:
            st.session_state.pop(key, None)
        st.segmented_control(title, list(draws), default=tabs[0][0], key=key, required=True,
                             label_visibility="collapsed", bind="query-params", width="stretch")
    draw = draws.get(st.session_state.get(key), tabs[0][1])
    st.session_state["_in_tab"] = True  # the tab's own big title is left out
    try:
        draw()
    finally:
        st.session_state["_in_tab"] = False

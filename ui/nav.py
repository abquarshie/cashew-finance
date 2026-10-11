"""Shared navigation bits, filled in by app.py."""
PAGES = {}     # url path -> st.Page, so any page can link to another
DRAWER = None  # a sidebar container pages can add panels to


def link(name):
    return PAGES[name]


def drawer():
    import streamlit as st
    return DRAWER if DRAWER is not None else st.sidebar

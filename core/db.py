"""Talking to Postgres. Reads go through cached loaders in core/data.py; every write clears that cache."""
from contextlib import contextmanager

import pandas as pd
import psycopg2
import streamlit as st

from core.schema import ensure_schema


def connect():
    return psycopg2.connect(st.secrets["DATABASE_URL"], connect_timeout=15)


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql, params=None):
    """Run a SELECT and return a DataFrame."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        cur.close()
    return pd.DataFrame(rows, columns=cols)


def run_many(statements):
    """Run several statements in one transaction (all succeed or none do), then refresh the data."""
    with db() as conn:
        cur = conn.cursor()
        for sql, params in statements:
            cur.execute(sql, params)
        cur.close()
    invalidate()


def execute(sql, params=None):
    run_many([(sql, params)])


def invalidate():
    st.cache_data.clear()


@st.cache_resource(show_spinner=False)
def init_db():
    with db() as conn:
        ensure_schema(conn)
    return True

"""Talking to Postgres.

Connections are kept open in a small pool and reused, instead of opening a new
one for every query (each new connection costs several round trips to the
database server, which is most of the wait on a slow link). Reads go through the
cached loaders in core/data.py; every write clears that cache.
"""
import pandas as pd
import psycopg2
import streamlit as st
from psycopg2.pool import ThreadedConnectionPool

from core.schema import ensure_schema

_STALE = (psycopg2.OperationalError, psycopg2.InterfaceError)


@st.cache_resource(show_spinner=False)
def _pool(dsn):
    return ThreadedConnectionPool(
        1, 8, dsn, connect_timeout=15,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def transact(fn):
    """Run fn(conn) as one transaction on a pooled connection and return its result.

    Hosted databases close connections that sit idle; if the pooled one has gone
    stale, it is thrown away and the work is tried once more on a fresh one.
    """
    pool = _pool(st.secrets["DATABASE_URL"])
    for attempt in (1, 2):
        conn = pool.getconn()
        broken = False
        try:
            result = fn(conn)
            conn.commit()
            return result
        except _STALE:
            broken = True
            if attempt == 2:
                raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                broken = True
            raise
        finally:
            pool.putconn(conn, close=broken or conn.closed != 0)


def query(sql, params=None):
    """Run one SELECT and return a DataFrame."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
    return transact(work)


def fetch_one(sql, params=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    return transact(work)


def run_many(statements, refresh=True):
    """Run several statements in one transaction (all succeed or none do), then refresh the data."""
    def work(conn):
        with conn.cursor() as cur:
            for sql, params in statements:
                cur.execute(sql, params)
    transact(work)
    if refresh:
        invalidate()


def execute(sql, params=None, refresh=True):
    run_many([(sql, params)], refresh=refresh)


def invalidate():
    """Throw away cached data so every open session sees the change on its next tap."""
    st.cache_data.clear()
    from core.data import load_book
    load_book.clear()


@st.cache_resource(show_spinner=False)
def init_db():
    transact(ensure_schema)
    return True

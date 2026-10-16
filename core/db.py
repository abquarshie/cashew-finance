"""Talking to Postgres.

Connections are kept open in a small pool and reused, instead of opening a new
one for every query (each new connection costs several round trips to the
database server, which is most of the wait on a slow link). Reads go through the
cached loaders in core/data.py; every write clears that cache.

Reads run in autocommit mode: a transaction costs a BEGIN and a COMMIT, each its
own round trip, so a single read inside one took three trips instead of one.
"""
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


def _borrow(pool, wait=10.0):
    """A connection from the pool. When all are busy (several people using the app at once), wait a moment
    for one to come free instead of failing straight away, as the pool itself would."""
    import time
    from psycopg2.pool import PoolError
    deadline = time.monotonic() + wait
    while True:
        try:
            return pool.getconn()
        except PoolError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def transact(fn, read_only=False):
    """Run fn(conn) as one transaction on a pooled connection and return its result.
    read_only=True skips the transaction (and its two extra round trips) for plain reads.

    Hosted databases close connections that sit idle; if the pooled one has gone
    stale, it is thrown away and the work is tried once more on a fresh one.

    A write is only retried when the connection failed before COMMIT was sent. If it fails during the
    commit, the database may already have saved the work, and running it again would save it twice
    (a duplicate expense), so the error is raised instead.
    """
    pool = _pool(st.secrets["DATABASE_URL"])
    for attempt in (1, 2):
        conn = _borrow(pool)
        broken = False
        committing = False
        try:
            if read_only:
                conn.autocommit = True
                try:
                    return fn(conn)
                finally:
                    if not conn.closed:
                        conn.autocommit = False
            result = fn(conn)
            committing = True
            conn.commit()
            return result
        except _STALE:
            broken = True
            if attempt == 2 or committing:
                raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                broken = True
            raise
        finally:
            pool.putconn(conn, close=broken or conn.closed != 0)


def fetch_one(sql, params=None):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    return transact(work, read_only=True)


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
    """Throw away cached data (money and kitchen) so every open session sees the change on its next tap.
    Each reload is a single round trip, so refreshing both is cheaper than ever showing stale data."""
    st.cache_data.clear()
    from core.data import load_book
    from meals.data import load_kitchen
    load_book.clear()
    load_kitchen.clear()


@st.cache_resource(show_spinner=False)
def init_db():
    transact(ensure_schema)
    return True

"""Adds any auto transactions that are due. Run daily by the GitHub Action,
or by hand with:  DATABASE_URL=... python run_auto.py"""
import os
import sys

import psycopg2

from auto_rules import apply_recurring_rules
from core.schema import ensure_schema


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        ensure_schema(conn)  # brings older databases up to date, so this never needs the app opened first
        created = apply_recurring_rules(conn)
    finally:
        conn.close()
    print(f"Added {created} auto transaction(s).")


if __name__ == "__main__":
    main()

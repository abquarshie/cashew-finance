"""Adds any auto transactions that are due. Run daily by the GitHub Action,
or by hand with:  DATABASE_URL=... python run_auto.py"""
import os
import sys

import psycopg2

from auto_rules import apply_recurring_rules


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    conn = psycopg2.connect(url)
    try:
        created = apply_recurring_rules(conn)
    except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn):
        conn.rollback()
        sys.exit("The database isn't ready yet. Open the app once so it can set itself up, then run this again.")
    finally:
        conn.close()
    print(f"Added {created} auto transaction(s).")


if __name__ == "__main__":
    main()

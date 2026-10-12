"""Send the morning or evening reminder to the family's Telegram. Run by the GitHub Action:

    DATABASE_URL=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python notify.py morning
    DATABASE_URL=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python notify.py evening

TELEGRAM_CHAT_ID can list several chats separated by commas (each person, or one family group).
Add --dry-run to print the message instead of sending it.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime

import psycopg2

from core.data import Book
from core.data import _load_frames as load_money
from core.schema import ensure_schema
from meals.briefing import evening, morning
from meals.data import Kitchen
from meals.data import _load as load_kitchen


def food_budget_left(book, kitchen, today):
    import pandas as pd
    cats = {c for c in kitchen.category_of.values() if c}
    groups = {book.group_of.get(c) for c in cats}
    left, found, covered = 0.0, False, set()
    status = book.budget_status(pd.Period(today, "M"))
    for s in status:
        if s["is_group"] and s["name"] in groups:
            left += max(s["limit"] - s["spent"], 0)
            covered.add(s["name"])
            found = True
    for s in status:
        if not s["is_group"] and s["name"] in cats and book.group_of.get(s["name"]) not in covered:
            left += max(s["limit"] - s["spent"], 0)
            found = True
    return left if found else None


def build(mode, conn, now=None):
    now = now or datetime.now()
    ensure_schema(conn)
    k = Kitchen(load_kitchen(conn))
    if mode == "evening":
        return evening(k, now)
    book = Book(load_money(conn))
    return morning(k, book, now, food_budget_left(book, k, now.date()))


def send(text, token, chat_ids, api=None):
    api = (api or os.environ.get("TELEGRAM_API") or "https://api.telegram.org").rstrip("/")
    sent = 0
    for chat in [c.strip() for c in chat_ids.split(",") if c.strip()]:
        body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"{api}/bot{token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            reply = json.loads(resp.read())
            if not reply.get("ok"):
                raise RuntimeError(f"Telegram refused the message for chat {chat}: {reply}")
        sent += 1
    return sent


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = args[0] if args else "morning"
    if mode not in ("morning", "evening"):
        sys.exit("Use: python notify.py morning|evening [--dry-run]")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    conn = psycopg2.connect(url, connect_timeout=20)
    try:
        text = build(mode, conn)
    finally:
        conn.close()
    if not text:
        print("Nothing needs doing tonight, so no message.")
        return
    if "--dry-run" in sys.argv:
        print(text)
        return
    token, chats = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chats:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID need to be set as repository secrets.")
    n = send(text, token, chats)
    print(f"Sent the {mode} message to {n} chat{'s' if n != 1 else ''}.")


if __name__ == "__main__":
    main()

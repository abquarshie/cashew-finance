"""Load a Cashew backup into a database.

    DATABASE_URL=... python restore.py cashew-backup-2026-10-11.zip[.enc] [--replace] [--yes]

- Encrypted backups need BACKUP_PASSPHRASE set (or --passphrase "...").
- Without --replace it only loads into a database that has no transactions yet
  (for example a brand-new one), so it can't overwrite your records by accident.
- With --replace, everything currently in the database is replaced by the backup.
  It happens in one step: if anything goes wrong, nothing changes.
- Everyone needs to sign in again afterwards.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

from core.backup import decrypt, read_zip, restore_zip


def main():
    ap = argparse.ArgumentParser(description="Load a Cashew backup into the database in DATABASE_URL.")
    ap.add_argument("backup")
    ap.add_argument("--replace", action="store_true", help="overwrite what's in the database now")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    ap.add_argument("--passphrase", default=os.environ.get("BACKUP_PASSPHRASE"))
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    try:
        data = decrypt(Path(args.backup).read_bytes(), args.passphrase)
        manifest, _ = read_zip(data)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))

    rows = manifest.get("rows", {})
    print(f"Backup made {manifest.get('made_at', '?')}: {rows.get('transactions', '?')} transactions, "
          f"{rows.get('users', '?')} people.")
    if args.replace and not args.yes:
        answer = input("This REPLACES everything in the database with the backup. Type 'replace' to go ahead: ")
        if answer.strip().lower() != "replace":
            sys.exit("Nothing changed.")

    conn = psycopg2.connect(url, connect_timeout=20)
    try:
        restored = restore_zip(conn, data, replace=args.replace)
    except ValueError as exc:
        conn.rollback()
        sys.exit(str(exc))
    finally:
        conn.close()
    print("Restored: " + ", ".join(f"{n} {t}" for t, n in restored.items() if n))
    print("Done. Everyone will need to sign in again.")


if __name__ == "__main__":
    main()

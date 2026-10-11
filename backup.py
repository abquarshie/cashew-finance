"""Save a full backup of Cashew's data. Run daily by the GitHub Action, or by hand:

    DATABASE_URL=... python backup.py [folder]

If BACKUP_PASSPHRASE is set the backup is encrypted (the GitHub Action always sets it).
Use restore.py to load a backup back in.
"""
import os
import sys
from pathlib import Path

import psycopg2

from core.backup import backup_filename, encrypt, export_zip


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "backups")
    folder.mkdir(parents=True, exist_ok=True)
    passphrase = os.environ.get("BACKUP_PASSPHRASE")
    if os.environ.get("REQUIRE_ENCRYPTION") and not passphrase:
        sys.exit("BACKUP_PASSPHRASE is not set, so the backup would be saved unencrypted. Add it as a repository secret.")

    conn = psycopg2.connect(url, connect_timeout=20)
    try:
        data, counts = export_zip(conn)
    finally:
        conn.close()
    if passphrase:
        data = encrypt(data, passphrase)
    path = folder / backup_filename(encrypted=bool(passphrase))
    path.write_bytes(data)
    total = sum(counts.values())
    print(f"Saved {path} ({len(data) / 1024:.0f} KB, {total} rows: "
          + ", ".join(f"{n} {t}" for t, n in counts.items() if n) + ")")


if __name__ == "__main__":
    main()

"""Full backups of the family's data, and restoring from one.

A backup is a zip with one CSV per table plus a small manifest. It can be
encrypted with a passphrase (the daily GitHub backup always is), so a copy
sitting on GitHub can't be read by anyone who doesn't know the passphrase.

No Streamlit imports here, so backup.py and restore.py can run on their own.
"""
import base64
import csv
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from core.schema import ensure_schema

# Restored in this order so linked rows find what they point to. Sign-in sessions are left out on purpose:
# after a restore everyone simply signs in again.
TABLES = ["categories", "accounts", "budgets", "users", "transactions", "recurring_rules", "goals",
          "goal_contributions", "app_meta"]
MAGIC = b"CASHEW-ENC1"


# ---- making a backup ------------------------------------------------------------
def export_zip(conn):
    """All tables as CSVs in a zip (bytes), plus a manifest with row counts."""
    ensure_schema(conn)
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z, conn.cursor() as cur:
        for table in TABLES:
            out = io.StringIO()
            cur.copy_expert(f"COPY (SELECT * FROM {table}) TO STDOUT WITH CSV HEADER", out)
            data = out.getvalue()
            z.writestr(f"{table}.csv", data)
            counts[table] = max(len(list(csv.reader(io.StringIO(data)))) - 1, 0)
        z.writestr("manifest.json", json.dumps({
            "app": "Cashew", "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": counts,
        }, indent=2))
    conn.rollback()  # read-only; nothing to keep
    return buf.getvalue(), counts


def _key(passphrase, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode()))


def encrypt(data, passphrase):
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_key(passphrase, salt)).encrypt(data)


def decrypt(data, passphrase):
    from cryptography.fernet import Fernet, InvalidToken
    if not data.startswith(MAGIC):
        return data  # not encrypted
    if not passphrase:
        raise ValueError("This backup is encrypted. Set BACKUP_PASSPHRASE (or pass --passphrase) to open it.")
    salt, body = data[len(MAGIC):len(MAGIC) + 16], data[len(MAGIC) + 16:]
    try:
        return Fernet(_key(passphrase, salt)).decrypt(body)
    except InvalidToken:
        raise ValueError("Wrong passphrase for this backup.") from None


# ---- restoring ---------------------------------------------------------------------
def read_zip(data):
    """Check a backup and return (manifest, {table: csv text})."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a Cashew backup (not a zip file).") from None
    names = set(z.namelist())
    if "manifest.json" not in names or "transactions.csv" not in names:
        raise ValueError("That zip isn't a Cashew backup (manifest or transactions missing).")
    manifest = json.loads(z.read("manifest.json"))
    return manifest, {t: z.read(f"{t}.csv").decode() for t in TABLES if f"{t}.csv" in names}


def restore_zip(conn, data, replace=False):
    """Load a backup into the database in one transaction: it all goes in, or nothing changes.

    Without replace=True this refuses to touch a database that already has transactions.
    Returns the number of rows restored per table.
    """
    _, tables = read_zip(data)
    ensure_schema(conn)
    restored = {}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions")
        if cur.fetchone()[0] and not replace:
            raise ValueError("This database already has transactions. Use replace to overwrite them with the backup.")
        cur.execute("TRUNCATE " + ", ".join(TABLES + ["sessions"]) + " RESTART IDENTITY CASCADE")
        for table in TABLES:
            text = tables.get(table)
            if not text:
                restored[table] = 0
                continue
            header = next(csv.reader(io.StringIO(text)))
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
            known = {r[0] for r in cur.fetchall()}
            unknown = [c for c in header if c not in known]
            if unknown:
                raise ValueError(f"The backup's {table} has columns this version doesn't know: {', '.join(unknown)}")
            cols = ", ".join(f'"{c}"' for c in header)
            cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH CSV HEADER", io.StringIO(text))
            cur.execute(f"SELECT count(*) FROM {table}")
            restored[table] = cur.fetchone()[0]
            if "id" in header:  # carry on numbering new rows after the restored ones
                cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                seq = cur.fetchone()[0]
                if seq:
                    cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)", (seq,))
    conn.commit()
    return restored


def backup_filename(encrypted=False, when=None):
    when = when or datetime.now(timezone.utc)
    return f"cashew-backup-{when:%Y-%m-%d}.zip" + (".enc" if encrypted else "")

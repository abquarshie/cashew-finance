"""Auto transaction logic shared by the Streamlit app and the daily scheduled job.

No Streamlit imports here, so run_auto.py can use it on its own.
"""
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

SHARED = "Household"
FEE_CATEGORY = "Charges"


def occurrence(start, frequency, n):
    """The date of the n-th run (0-based) of a rule that starts on `start`."""
    if frequency == "Weekly":
        return start + timedelta(weeks=n)
    if frequency == "Every 2 weeks":
        return start + timedelta(weeks=2 * n)
    if frequency == "Yearly":
        return start + relativedelta(years=n)
    return start + relativedelta(months=n)


def catch_up(start, frequency, n, today=None):
    """The run number of the first date from today on, skipping the dates a rule wasn't running
    (paused, or finished and then extended), so they aren't all added at once."""
    today = today or date.today()
    guard = 0
    while occurrence(start, frequency, n) < today and guard < 5000:
        n += 1
        guard += 1
    return n


def apply_recurring_rules(conn, today=None):
    """Create every auto transaction that is due and return how many were added.

    Safe to run often and from several places at once: due rules are locked while
    they are processed, so the same entry is never added twice.
    """
    today = today or date.today()
    created = 0
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, type, amount, fee, category, account, to_account, member, note,
               frequency, start_date, run_count, end_date
        FROM recurring_rules
        WHERE active AND next_date <= %s
        FOR UPDATE SKIP LOCKED
        """,
        (today,),
    )
    for (rid, name, typ, amount, fee, cat, acct, to_acct, member, note, freq, start, n, end) in cur.fetchall():
        nxt = occurrence(start, freq, n)
        guard = 0
        while nxt <= today and (end is None or nxt <= end) and guard < 400:
            label = f"Auto · {name}" + (f" · {note}" if note else "")
            cur.execute(
                "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (nxt, typ, cat, amount, label, member or SHARED, acct, to_acct),
            )
            created += 1
            if typ == "Transfer" and fee is not None and fee > 0:
                cur.execute(
                    "INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                    "VALUES (%s, 'Expense', %s, %s, %s, %s, %s, NULL)",
                    (nxt, FEE_CATEGORY, fee, f"Fee · {name}", SHARED, acct),
                )
            n += 1
            guard += 1
            nxt = occurrence(start, freq, n)
        still_active = end is None or nxt <= end
        cur.execute(
            "UPDATE recurring_rules SET run_count=%s, next_date=%s, active=%s, last_run=%s WHERE id=%s",
            (n, nxt, still_active, today, rid),
        )
    conn.commit()
    cur.close()
    return created

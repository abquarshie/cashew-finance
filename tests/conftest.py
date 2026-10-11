"""Shared setup for Cashew's tests.

Everything runs against a throwaway database named in TEST_DATABASE_URL (its name
must contain "test", so the real database can never be touched). It is wiped and
filled with a few months of sample entries at the start of each run.

Browser tests start the app on its own port with a temporary secrets file.
"""
import os
import random
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.schema import ensure_schema  # noqa: E402

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://cashew@localhost:5433/cashew_test")
SHOTS = ROOT / "tests" / "screenshots"
OWNER = ("xan", "Xan", "Kenkey and fish 2026")
MEMBER = ("ama", "Ama", "Waakye on Saturday")


def _admin_url(url):
    p = urlparse(url)
    return urlunparse(p._replace(path="/postgres"))


def months_ago(n, day):
    """A date n months before this month, on the given day (clamped to the month's length)."""
    y, m = date.today().year, date.today().month - n
    while m <= 0:
        m += 12
        y -= 1
    for d in (day, 28):
        try:
            return date(y, m, d)
        except ValueError:
            continue


def seed(conn):
    """A realistic few months: salary, everyday spending, transfers, budgets, goals and auto entries."""
    random.seed(7)
    today = date.today()
    cur = conn.cursor()
    cur.execute("INSERT INTO accounts (name, opening_balance, spendable) VALUES ('MoMo', 150, TRUE) ON CONFLICT DO NOTHING")
    cur.execute("UPDATE accounts SET opening_balance = 650 WHERE name = 'Cash'")
    cur.execute("UPDATE accounts SET opening_balance = 4200 WHERE name = 'GCB'")
    spend = [("Fruits/Veges", 20, 90), ("Meat/Fish", 40, 160), ("Staples", 60, 220), ("Dining Out", 25, 120),
             ("Electricity", 150, 300), ("Internet Data", 50, 120), ("Work", 15, 60), ("Medications", 30, 150)]
    rows = []
    for back in (3, 2, 1, 0):
        rows.append((months_ago(back, 1), "Income", "Salary", 5200, "", "Household", "GCB", None))
        rows.append((months_ago(back, 2), "Transfer", "Between accounts", 800, "", "Household", "GCB", "Cash"))
        for _ in range(14 if back else 5):
            cat, lo, hi = random.choice(spend)
            d = months_ago(back, random.randint(1, 27))
            if d >= today:
                d = today - timedelta(days=1)
            rows.append((d, "Expense", cat, round(random.uniform(lo, hi), 2), random.choice(["", "Makola", "Shoprite"]),
                         random.choice(["Household", "Ama"]), random.choice(["Cash", "GCB"]), None))
    cur.executemany("INSERT INTO transactions (date, type, category, amount, note, member, account, to_account) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", rows)
    for k, v in [("Food", 1500), ("Utility", 450), ("Dining Out", 200), ("Health", 150)]:
        cur.execute("INSERT INTO budgets VALUES (%s, %s)", (k, v))
    cur.execute("INSERT INTO goals (name, target, deadline) VALUES ('School fees', 6000, %s) RETURNING id",
                (today + timedelta(days=90),))
    goal = cur.fetchone()[0]
    cur.execute("INSERT INTO goal_contributions (goal_id, date, amount, note) VALUES (%s, %s, 1500, '')",
                (goal, today - timedelta(days=20)))
    soon = today + timedelta(days=3)
    cur.execute(
        "INSERT INTO recurring_rules (name, type, amount, fee, category, account, to_account, member, note, frequency, "
        "start_date, next_date, run_count) VALUES "
        "('Monthly Susu', 'Transfer', 500, NULL, 'Susu', 'GCB', 'Susu', 'Household', '', 'Monthly', %s, %s, 0), "
        "('Data bundle', 'Expense', 60, NULL, 'Internet Data', 'Cash', NULL, 'Household', '', 'Weekly', %s, %s, 0)",
        (soon, soon, soon, soon))
    conn.commit()


@pytest.fixture(scope="session")
def db_url():
    name = urlparse(TEST_DB).path.lstrip("/")
    if "test" not in name:
        pytest.exit(f"Refusing to run: the test database name must contain 'test' (got '{name}').")
    admin = psycopg2.connect(_admin_url(TEST_DB))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,))
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        cur.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    conn = psycopg2.connect(TEST_DB)
    ensure_schema(conn)
    seed(conn)
    conn.close()
    return TEST_DB


@pytest.fixture(scope="session")
def conn(db_url):
    c = psycopg2.connect(db_url)
    c.autocommit = True
    yield c
    c.close()


def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else None


# ---- the running app ----------------------------------------------------------------
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url(db_url, tmp_path_factory):
    secrets = tmp_path_factory.mktemp("secrets") / "secrets.toml"
    secrets.write_text(f'DATABASE_URL = "{db_url}"\n')
    port = _free_port()
    log = open(tmp_path_factory.mktemp("log") / "streamlit.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false", "--secrets.files", str(secrets)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        # tests also change the database directly, so don't let the app hold on to old data
        env={**os.environ, "CASHEW_CACHE_SECONDS": "1"})
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.exit("The app didn't start within 60 seconds.")
    time.sleep(1.5)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


PHONE = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
DESKTOP = dict(viewport={"width": 1366, "height": 950})


@pytest.fixture
def phone(browser, request):
    ctx = browser.new_context(**PHONE)
    page = ctx.new_page()
    yield page
    _shot_on_failure(request, page)
    ctx.close()


@pytest.fixture
def desktop(browser, request):
    ctx = browser.new_context(**DESKTOP)
    page = ctx.new_page()
    yield page
    _shot_on_failure(request, page)
    ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


def _shot_on_failure(request, page):
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        SHOTS.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(SHOTS / f"{request.node.name}.png"), full_page=True)
        except Exception:
            pass

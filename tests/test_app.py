"""The app in a real browser, mostly at phone size. The tests run in order and share one database:
the owner signs up first, then everything else builds on that."""
import io
import zipfile
from datetime import date, timedelta

import pytest

from conftest import MEMBER, OWNER, PHONE, q
from helpers import (amount_box, box, chip, details, go, no_errors, open_add, open_app, open_menu, settle, sign_in,
                     tab, toasts, type_in)

pytestmark = pytest.mark.browser

MTN_TEXT = ("Payment made for GHS 50.00 to KOFI MENSAH. Current Balance: GHS 120.50. Available Balance: GHS 120.50. "
            "Reference: lunch. Transaction ID: 51234567890. Fee charged: GHS 0.50 TAX charged: GHS 0.00.")


def last_tx(conn, n=1):
    return q(conn, "SELECT type, category, amount, date, created_by, account, to_account, note FROM transactions "
                   "ORDER BY id DESC LIMIT %s", (n,))


def count_tx(conn):
    return q(conn, "SELECT count(*) FROM transactions")[0][0]


def pick_category(page, name):
    c = chip(page, name)
    if c.count() and c.is_visible():
        c.click()
    else:
        search = page.get_by_role("combobox", name="Search all categories")
        search.click()
        page.keyboard.type(name)
        page.keyboard.press("Enter")
    settle(page)


def save(page, label="Save expense"):
    page.get_by_role("button", name=label).click()
    settle(page, 2500)
    no_errors(page)


# ---- sign-in ------------------------------------------------------------------------------
def test_owner_signs_up_and_stays_signed_in(phone, app_url, conn):
    open_app(phone, app_url, "transactions")
    body = phone.inner_text("body")
    assert "Create owner account" in body, "a deep link shows sign-up first"

    type_in(box(phone, "Your name"), OWNER[1])
    type_in(box(phone, "Username"), "Xan Hann")
    settle(phone)
    assert "Use 3 to 30 letters" in phone.inner_text("body")
    type_in(box(phone, "Username"), OWNER[0])
    type_in(box(phone, "Password"), "short")
    settle(phone)
    assert "at least 8 characters" in phone.inner_text("body")
    type_in(box(phone, "Password"), OWNER[2])
    type_in(box(phone, "Type the password again"), OWNER[2] + "x")
    settle(phone)
    assert "don't match" in phone.inner_text("body")
    type_in(box(phone, "Type the password again"), OWNER[2])
    settle(phone)
    phone.get_by_role("button", name="Create owner account").click()
    settle(phone, 3500)
    no_errors(phone)

    (username, owner, hashed), = q(conn, "SELECT username, is_owner, password_hash FROM users")
    assert username == "xan" and owner
    assert hashed.startswith("pbkdf2_sha256$") and OWNER[2] not in hashed
    assert "/transactions" in phone.url, "lands on the page that was asked for"

    cookie = {c["name"]: c for c in phone.context.cookies()}["cashew_session"]
    assert cookie["expires"] > 0, "remembered for 30 days"
    assert q(conn, "SELECT count(*) FROM sessions WHERE token_hash = encode(sha256(%s::bytea), 'hex')",
             (cookie["value"],))[0][0] == 1, "only a hash of the token is stored"

    again = phone.context.new_page()  # a fresh visit on the same phone
    open_app(again, app_url)
    assert f"Hello, {OWNER[1]}" in again.inner_text("body")
    again.close()


# ---- dashboard -------------------------------------------------------------------------------
def test_dashboard_layout(phone, app_url):
    sign_in(phone, app_url)
    hero = phone.locator(".hero")
    assert "Total budget left" in hero.inner_text(), "one big number at the top: what's left of this month's budgets"
    tiles = phone.locator(".kpi-grid .kpi")
    assert [tiles.nth(i).locator(".kpi-label").inner_text() for i in range(tiles.count())] == ["Income", "Expenses"]

    balances = phone.locator('[data-testid="stExpander"]').filter(has_text="Account balances")
    assert "in all" in balances.locator("summary").inner_text(), "the total sits on the fold"
    assert not phone.locator(".bal-rows").is_visible(), "balances are one tap below"
    balances.locator("summary").click()
    settle(phone)
    rows = phone.locator(".bal-rows").inner_text()
    assert "MoMo" in rows and "savings" in rows, "every account listed, savings marked"

    assert phone.get_by_role("button", name="Add an entry").is_visible()
    assert not amount_box(phone).count(), "the form only appears when Add is tapped"
    activity = phone.locator('[data-testid="stExpander"]').filter(has_text="Recent activity")
    assert not phone.get_by_text("See all transactions").is_visible(), "recent activity starts folded"
    activity.locator("summary").click()
    settle(phone)
    assert phone.get_by_text("See all transactions").is_visible(), "one tap opens it"
    budgets = phone.locator('[data-testid="stExpander"]').filter(has_text="Budgets and spending")
    assert not phone.locator(".prog-list").first.is_visible()
    budgets.locator("summary").click()
    settle(phone)
    assert phone.locator(".prog-list").first.is_visible()

    open_menu(phone)
    sidebar = phone.locator('[data-testid="stSidebar"]')
    links = [t.strip().split("\n")[-1] for t in sidebar.locator('[data-testid="stSidebarNav"] a').all_inner_texts()]
    assert links == ["Home", "Transactions", "Budgets & goals", "Meals", "Shopping list", "Pantry / Inventory",
                     "Settings"], links
    sidebar.get_by_text("More stats").click()
    settle(phone, 2000)
    side = sidebar.inner_text()
    for tile in ("Safe to spend until payday", "In all accounts", "Net balance", "Savings rate", "Budgets at risk", "Next auto entry", "Income and expenses, 6 months"):
        assert tile in side
    assert sidebar.locator('[data-testid="stVegaLiteChart"], .vega-embed').count() >= 1


def test_quick_entry_in_four_taps(phone, app_url, conn):
    sign_in(phone, app_url)
    open_add(phone)
    dialog = phone.locator('[role="dialog"]')
    amt = amount_box(phone)
    assert amt.is_visible()
    body = dialog.inner_text()
    assert "More details · Today" in body, "date, note and who are folded away"
    assert not box(phone, "Note").is_visible()

    type_in(amt, "38.5")
    pick_category(phone, "Staples")
    save(phone)
    kind, cat, amount, when, by, *_ = last_tx(conn)[0]
    assert (kind, cat, float(amount), when, by) == ("Expense", "Staples", 38.5, date.today(), "xan")
    assert not dialog.count() or not dialog.is_visible(), "the pop-up closes after saving"
    assert "Saved GH₵38.50 expense to Staples" in toasts(phone)


def test_duplicates_are_caught(phone, app_url, conn):
    sign_in(phone, app_url)
    open_add(phone)
    pick_category(phone, "Staples")
    phone.get_by_role("button", name="Same as last time: GH₵38.50").click()
    settle(phone)
    assert amount_box(phone).input_value() in ("38.50", "38.5")
    details(phone)
    chip(phone, "Yesterday").click()
    settle(phone)
    before = count_tx(conn)
    save(phone)
    assert "You already added GH₵38.50 for Staples today" in phone.inner_text("body")
    assert count_tx(conn) == before, "nothing saved until confirmed"
    phone.get_by_role("button", name="Save anyway").click()
    settle(phone, 2500)
    assert count_tx(conn) == before + 1
    assert last_tx(conn)[0][3] == date.today() - timedelta(days=1)

    open_add(phone)
    assert "More details · Today" in phone.locator('[role="dialog"]').inner_text(), "the date goes back to today"
    pick_category(phone, "Staples")
    phone.get_by_role("button", name="Same as last time: GH₵38.50").click()
    settle(phone)
    save(phone)
    phone.get_by_role("button", name="Don't save").click()
    settle(phone)
    assert count_tx(conn) == before + 1


def test_budget_warning_when_saving(phone, app_url):
    sign_in(phone, app_url)
    open_add(phone)
    type_in(amount_box(phone), "500")
    pick_category(phone, "Medications")
    save(phone)
    msgs = toasts(phone)
    assert "Health is" in msgs and "over its GH₵150.00 budget" in msgs, msgs


def test_momo_text_fills_the_form(phone, app_url, conn):
    sign_in(phone, app_url)
    open_add(phone)
    phone.get_by_text("Paste a MoMo text").click()
    settle(phone, 600)
    phone.get_by_role("textbox", name="MoMo text").fill(MTN_TEXT)
    phone.get_by_role("button", name="Fill in the form").click()
    settle(phone, 1500)
    body = phone.inner_text("body")
    assert "Paid GH₵50.00 to Kofi Mensah, fee GH₵0.50. Check the details" in body
    assert "Your MoMo balance is GH₵120.50" in body, "balance check against Cashew"
    assert amount_box(phone).input_value() in ("50.00", "50")
    assert box(phone, "Note").input_value() == "Kofi Mensah – lunch"
    save(phone)
    fee, main = last_tx(conn, 2)
    assert (main[0], float(main[2]), main[5]) == ("Expense", 50.0, "MoMo")
    assert "MoMo ID 51234567890" in main[7]
    assert (fee[1], float(fee[2]), fee[5]) == ("Charges", 0.5, "MoMo")

    before = count_tx(conn)
    open_add(phone)
    phone.get_by_text("Paste a MoMo text").click()
    settle(phone, 600)
    phone.get_by_role("textbox", name="MoMo text").fill(MTN_TEXT)
    phone.get_by_role("button", name="Fill in the form").click()
    settle(phone, 1500)
    save(phone)
    assert "This MoMo payment is already saved" in phone.inner_text("body")
    phone.get_by_role("button", name="Don't save").click()
    settle(phone)
    assert count_tx(conn) == before


def test_transfer_with_fee(phone, app_url, conn):
    sign_in(phone, app_url)
    open_add(phone)
    phone.locator(".st-key-draft_q_kind").get_by_text("Transfer").click()
    settle(phone)
    type_in(amount_box(phone), "200")
    chip(phone, "GCB").click()
    settle(phone)
    details(phone)
    type_in(phone.locator(".st-key-draft_q_fee input"), "2")
    save(phone, "Save transfer")
    fee, move = last_tx(conn, 2)
    assert (move[0], float(move[2]), move[5]) == ("Transfer", 200.0, "GCB") and move[6] != "GCB"
    assert (fee[1], float(fee[2])) == ("Charges", 2.0)


# ---- people -------------------------------------------------------------------------------
def test_member_joins_with_invite_code(browser, app_url, conn):
    code = q(conn, "SELECT value FROM app_meta WHERE key = 'invite_code'")[0][0]
    ctx = browser.new_context(**PHONE)
    page = ctx.new_page()
    open_app(page, app_url)
    page.get_by_role("tab", name="I have an invite code").click()
    settle(page, 600)
    type_in(box(page, "Your name"), MEMBER[1])
    type_in(box(page, "Username"), OWNER[0])
    settle(page)
    assert "That username is taken" in page.inner_text("body")
    type_in(box(page, "Username"), MEMBER[0])
    type_in(box(page, "Password"), MEMBER[2])
    type_in(box(page, "Type the password again"), MEMBER[2])
    type_in(box(page, "Invite code"), "AAAA-BBBB-CCCC")
    settle(page)
    page.get_by_role("button", name="Create account").click()
    settle(page, 3000)
    assert "invite code isn't right" in page.inner_text("body")
    type_in(box(page, "Invite code"), code.lower())
    settle(page)
    page.get_by_role("button", name="Create account").click()
    settle(page, 3500)
    no_errors(page)
    assert q(conn, "SELECT is_owner FROM users WHERE username = 'ama'") == [(False,)]
    go(page, "Settings")
    assert "Parts" not in page.inner_text("body"), "members can't switch parts off"
    tab(page, "People")
    body = page.inner_text("body")
    assert "Invite your family" not in body and "Change your password" in body, "members don't get owner tools"
    ctx.close()


def test_owner_tools_and_backup_download(desktop, app_url, conn):
    sign_in(desktop, app_url)
    go(desktop, "Settings")
    tab(desktop, "People")
    code = q(conn, "SELECT value FROM app_meta WHERE key = 'invite_code'")[0][0]
    body = desktop.inner_text("body")
    assert code in body and "Ama" in body
    with desktop.expect_download() as dl:
        desktop.get_by_role("button", name="Download a backup").click()
    data = open(dl.value.path(), "rb").read()
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"manifest.json", "transactions.csv", "users.csv"} <= set(z.namelist())
    assert dl.value.suggested_filename.startswith("cashew-backup-")


def test_sign_out_and_lockout(phone, app_url, conn):
    sign_in(phone, app_url)
    open_menu(phone)
    phone.get_by_role("button", name="Sign out").click()
    settle(phone, 2500)
    phone.reload(wait_until="networkidle")
    settle(phone, 2000)
    assert "Keep me signed in" in phone.inner_text("body"), "stays signed out after reload"

    for i in range(5):
        box(phone, "Username").fill(OWNER[0])
        box(phone, "Password").fill(f"wrong-{i}")
        phone.get_by_role("button", name="Sign in").click()
        settle(phone, 2000)
    assert "Too many wrong tries" in phone.inner_text("body")
    box(phone, "Password").fill(OWNER[2])
    phone.get_by_role("button", name="Sign in").click()
    settle(phone, 2000)
    assert "Too many wrong tries" in phone.inner_text("body"), "even the right password waits out the lock"
    q(conn, "UPDATE users SET locked_until = NULL, failed_logins = 0")  # as if 15 minutes passed
    phone.get_by_role("button", name="Sign in").click()
    settle(phone, 3000)
    assert f"Hello, {OWNER[1]}" in phone.inner_text("body")


# ---- other pages --------------------------------------------------------------------------
def test_edit_delete_and_undo_in_the_table(desktop, app_url, conn):
    sign_in(desktop, app_url, path="transactions")
    grid = desktop.locator('[data-testid="stDataFrame"]').first
    grid.scroll_into_view_if_needed()
    settle(desktop, 1500)  # let the page finish moving before measuring where the cells are
    gb = grid.bounding_box()
    first, second = q(conn, "SELECT id, category FROM transactions WHERE date_trunc('month', date) = "
                            "date_trunc('month', CURRENT_DATE) ORDER BY date DESC, id DESC LIMIT 2")
    row_y = lambda n: gb["y"] + 36 + 35 * n + 17  # noqa: E731
    # click the first row's Date cell (just right of the Delete column), walk right to Amount, type a new value
    desktop.mouse.click(gb["x"] + 84 + 30, row_y(0))
    for _ in range(2):
        desktop.keyboard.press("ArrowRight")
    desktop.keyboard.press("Enter")  # open the cell editor
    desktop.wait_for_timeout(400)
    desktop.keyboard.press("ControlOrMeta+A")
    desktop.keyboard.type("230", delay=40)
    desktop.keyboard.press("Enter")
    settle(desktop, 1500)
    assert "1 change not saved yet" in desktop.inner_text("body")
    desktop.get_by_role("button", name="Save changes").click()
    settle(desktop, 2500)
    assert float(q(conn, "SELECT amount FROM transactions WHERE id = %s", (first[0],))[0][0]) == 230

    gb = grid.bounding_box()
    desktop.mouse.click(gb["x"] + 42, gb["y"] + 36 + 35 + 17)
    settle(desktop, 1500)
    assert "1 to delete not saved yet" in desktop.inner_text("body")
    desktop.get_by_role("button", name="Save changes").click()
    settle(desktop, 1200)
    desktop.locator('[role="dialog"]').get_by_role("button", name="Delete").click()
    settle(desktop, 2500)
    assert q(conn, "SELECT count(*) FROM transactions WHERE id = %s", (second[0],))[0][0] == 0
    desktop.get_by_role("button", name="Undo").click()
    settle(desktop, 2500)
    assert q(conn, "SELECT category FROM transactions WHERE id = %s", (second[0],)) == [(second[1],)]


def test_auto_transaction_fills_in_missed_dates(desktop, app_url, conn):
    sign_in(desktop, app_url, path="transactions?tab_transactions=Repeats")
    desktop.get_by_text("New auto transaction").wait_for()
    settle(desktop, 1500)
    box(desktop, "Name").fill("Weekly MoMo top-up")
    box(desktop, "Name").press("Enter")
    amount = desktop.get_by_role("spinbutton", name="Amount (GH₵)").last
    type_in(amount, "50")
    settle(desktop)
    if not amount.input_value():  # the form redrew while typing; type it again
        type_in(amount, "50")
    type_in(desktop.get_by_role("spinbutton", name="Fee (GH₵), optional"), "0.5")
    desktop.get_by_label("Repeats").click()
    desktop.get_by_role("option", name="Weekly").click()
    settle(desktop)
    start = date.today() - timedelta(days=21)
    seg = desktop.locator('[data-testid="stDateInput"]').filter(has_text="First run").locator('[role="spinbutton"]').first
    seg.click()
    desktop.keyboard.type(start.strftime("%d%m%Y"), delay=60)
    desktop.keyboard.press("Tab")
    desktop.keyboard.press("Escape")
    settle(desktop, 1500)
    assert "will be added straight away" in desktop.inner_text("body")
    desktop.get_by_role("button", name="Create auto transaction").click()
    settle(desktop, 3000)
    no_errors(desktop)
    made = q(conn, "SELECT count(*) FROM transactions WHERE note LIKE 'Auto · Weekly MoMo top-up%%'")[0][0]
    fees = q(conn, "SELECT count(*) FROM transactions WHERE note = 'Fee · Weekly MoMo top-up'")[0][0]
    assert made == fees == 4, (made, fees)


PAGES = ["", "transactions", "transactions?tab_transactions=Repeats", "budgets", "budgets?tab_budgets=Goals",
         "settings", "settings?tab_settings=People", "settings?tab_settings=Parts",
         # old addresses still work
         "add", "auto", "goals", "setup", "people"]


@pytest.mark.parametrize("size,scheme", [("phone", "light"), ("phone", "dark"), ("desktop", "light")])
def test_every_page_opens(browser, app_url, size, scheme):
    opts = PHONE if size == "phone" else {"viewport": {"width": 1366, "height": 900}}
    ctx = browser.new_context(color_scheme=scheme, **opts)
    page = ctx.new_page()
    sign_in(page, app_url)
    for path in PAGES:
        open_app(page, app_url, path)
        no_errors(page)
        assert "Sign in" not in page.locator('[data-testid="stMain"]').inner_text()[:200]
    ctx.close()


def test_old_addresses_open_the_right_tab(desktop, app_url):
    sign_in(desktop, app_url, path="auto")
    assert "Create auto transaction" in desktop.inner_text("body"), "/auto opens Money on the Repeats tab"
    open_app(desktop, app_url, "people")
    assert "Change your password" in desktop.inner_text("body")


def test_switching_parts_off(desktop, app_url, conn):
    sign_in(desktop, app_url, path="settings?tab_settings=Parts")
    for label in ("Kitchen", "Savings goals"):
        desktop.locator('[data-testid="stCheckbox"], [data-testid="stToggle"]').filter(has_text=label).first \
            .locator("label").first.click()
        settle(desktop, 2500)
    assert q(conn, "SELECT key, value FROM app_meta WHERE key IN ('feature_kitchen', 'feature_goals') ORDER BY key") == \
        [("feature_goals", "off"), ("feature_kitchen", "off")]
    open_app(desktop, app_url)
    nav = desktop.locator('[data-testid="stSidebarNav"]').inner_text()
    assert "Meals" not in nav and "Shopping list" not in nav and "Pantry" not in nav
    assert not desktop.locator(".st-key-card-meal-line").count()
    open_app(desktop, app_url, "budgets")
    assert "Goals" not in desktop.locator('[data-testid="stMain"]').inner_text()[:300]
    q(conn, "DELETE FROM app_meta WHERE key LIKE 'feature_%%'")  # back on for the kitchen tests


def test_an_ended_session_signs_the_browser_out(phone, app_url, conn):
    """When the owner resets someone's password (or their sign-in expires), an open browser must not stay in."""
    sign_in(phone, app_url)
    assert f"Hello, {OWNER[1]}" in phone.inner_text("body")
    q(conn, "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = %s)", (OWNER[0],))
    phone.wait_for_timeout(1500)  # the app's data refreshes every second in tests (every minute normally)
    open_menu(phone)
    phone.locator('[data-testid="stSidebar"]').get_by_role("link", name="Transactions").click()
    settle(phone, 2500)
    assert "Keep me signed in" in phone.inner_text("body"), "back to the sign-in screen"
    assert "You've been signed out" in toasts(phone)


def test_the_banner_turns_red_when_budgets_are_overspent(phone, app_url, conn):
    limits = q(conn, "SELECT category, monthly_limit FROM budgets")
    q(conn, "UPDATE budgets SET monthly_limit = 1")
    try:
        phone.wait_for_timeout(1500)  # the app's data refreshes every second in tests
        sign_in(phone, app_url)
        hero = phone.locator(".hero")
        assert "over" in hero.get_attribute("class"), "dark red once the month's budgets are used up"
        text = hero.inner_text()
        assert "Total budget left" in text and "−GH₵" in text, text
        green = "rgb(15, 61, 58)"
        assert phone.evaluate("getComputedStyle(document.querySelector('.hero')).backgroundColor") != green
    finally:
        for cat, limit in limits:
            q(conn, "UPDATE budgets SET monthly_limit = %s WHERE category = %s", (limit, cat))


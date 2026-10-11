"""Small helpers for driving the app in a browser."""
from playwright.sync_api import Page

from conftest import OWNER


def settle(page: Page, ms=1200):
    """Wait for Streamlit to finish its current run."""
    page.wait_for_timeout(ms)
    page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=30000)


def no_errors(page: Page):
    e = page.locator('[data-testid="stException"]')
    assert e.count() == 0, e.first.inner_text()[:1500]


def box(page: Page, name):
    return page.get_by_role("textbox", name=name, exact=True)


def type_in(el, text, key="Enter"):
    el.click()
    el.fill(text)
    if key:
        el.press(key)


def chip(page: Page, text, within=None):
    scope = page.locator(within) if within else page
    return scope.locator('[data-testid="stPills"] button, [data-testid="stButtonGroup"] button').filter(
        has_text=text).first


def open_app(page: Page, url, path=""):
    page.goto(f"{url}/{path}", wait_until="networkidle")
    settle(page, 2000)


def sign_in(page: Page, url, who=OWNER, path=""):
    open_app(page, url, path)
    if page.get_by_role("button", name="Sign in").count():
        box(page, "Username").fill(who[0])
        box(page, "Password").fill(who[2])
        page.get_by_role("button", name="Sign in").click()
        settle(page, 3000)
    no_errors(page)


def open_menu(page: Page):
    btn = page.locator('[data-testid="stExpandSidebarButton"]')
    if btn.count() and btn.is_visible():
        btn.click()
        settle(page, 600)


def go(page: Page, link_name):
    """Use the app's own menu (keeps the session, unlike loading a new address)."""
    open_menu(page)
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name=link_name).click()
    settle(page, 2000)
    no_errors(page)


def amount_box(page: Page, prefix="q"):
    return page.locator(f".st-key-draft_{prefix}_amount input")


def open_panel(page: Page, label):
    page.get_by_text(label, exact=True).first.click()
    settle(page)


def toasts(page: Page):
    t = page.locator('[data-testid="stToast"]')
    return " | ".join(t.nth(i).inner_text() for i in range(t.count()))

import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

LOGIN_URL   = "/login/"
DASHBOARD_URL = "/dashboard/"


def _login(page: Page, base_url: str, email: str, password: str, form_screenshot: str = None):
    """Fill and submit the login form, wait for redirect away from /login/.
    If form_screenshot is a path, a screenshot is taken after filling credentials."""
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(email)
    page.locator("#pw1").fill(password)
    if form_screenshot:
        os.makedirs("screenshots", exist_ok=True)
        page.screenshot(path=form_screenshot)
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)


def test_client_login(page: Page, base_url: str, client_credentials):
    """Valid credentials are accepted and the client lands on the dashboard."""
    _login(
        page, base_url,
        client_credentials["email"], client_credentials["password"],
        form_screenshot="screenshots/client_login_form.png",
    )
    expect(page.locator("#client-dashboard-page")).to_be_visible()
    write_detail("test_client_login", {
        "message": "Login form with credentials filled",
        "screenshot": "screenshots/client_login_form.png",
    })


def test_client_dashboard(page: Page, base_url: str, client_credentials):
    """Client dashboard loads with the main sections visible."""
    _login(page, base_url, client_credentials["email"], client_credentials["password"])
    page.goto(f"{base_url}{DASHBOARD_URL}")
    expect(page.locator("#client-dashboard-page")).to_be_visible()
    expect(page.locator("#dashboard-tutors-heading")).to_be_visible()
    expect(page.locator("#dashboard-billing-heading")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/client_dashboard.png")
    write_detail("test_client_dashboard", {
        "message": "Clients can log in and see the dashboard",
        "screenshot": "screenshots/client_dashboard.png",
    })

from playwright.sync_api import Page, expect
from utils.details import write_detail
from utils.recaptcha_bypass import inject_recaptcha_bypass
import pytest

LOGIN_URL   = "/login/"
DASHBOARD_URL = "/dashboard/"


def _login(page: Page, base_url: str, email: str, password: str, api_key: str):
    """Fill and submit the login form, wait for redirect away from /login/."""
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(email)
    page.locator("#pw1").fill(password)
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)


@pytest.mark.auth
@pytest.mark.critical
def test_client_login(page: Page, base_url: str, api_key: str, client_credentials):
    """Valid credentials are accepted and the client lands on the dashboard."""
    _login(page, base_url, client_credentials["email"], client_credentials["password"], api_key)
    expect(page.locator("#client-dashboard-page")).to_be_visible()
    write_detail("test_client_login", {
        "message": "Login accepted, client landed on dashboard",
    })


@pytest.mark.auth
def test_show_password_toggle(page: Page, base_url: str):
    """
    Regression test for the Aug 2026 v10.2.25 fix (docs/login-mgmt.md Known
    Issues): the "Show Password" checkbox (id="register_form_show_password")
    is a delegated handler shared across forms in js/recaptcha_verify.js.
    Checking it must switch the password field (id="pw1" on every affected
    template) from type="password" to type="text"; unchecking it must switch
    it back — previously the login form's checkbox didn't work at all
    (selector mismatch), and the other two forms got stuck permanently
    type="text" after one toggle (the handler re-queried by a type attribute
    its own action had just changed).

    Covers /login and the tutor applicant registration form
    (/tutor-section/application/), both reachable directly logged out.
    Does NOT cover the third affected form (new-client account creation,
    new_client_create_account.php) — that only renders on single-jobs.php
    behind a separate generate_lead=true&c={crc32(client_id)} URL used for a
    distinct lead-invite flow, not the standard post-submission
    ?new_client=true redirect (confirmed by test_new_client_banner: a normal
    new-client contact-form submission auto-logs the client in and never
    shows this form). Reaching it would need its own job-creation path, not
    just a URL visit — left for a follow-up rather than guessed at here.
    """
    for url in ["/login/", "/tutor-section/application/"]:
        page.goto(f"{base_url}{url}")
        checkbox = page.locator("#register_form_show_password")
        password_field = page.locator("#pw1")
        expect(checkbox).to_be_visible()
        expect(password_field).to_have_attribute("type", "password")

        checkbox.check()
        expect(password_field).to_have_attribute("type", "text")

        checkbox.uncheck()
        expect(password_field).to_have_attribute("type", "password")

    write_detail("test_show_password_toggle", {
        "message": "Show Password checkbox correctly toggles the password field on /login and /tutor-section/application/",
    })


@pytest.mark.auth
def test_client_dashboard(page: Page, base_url: str, api_key: str, client_credentials):
    """Client dashboard loads with the main sections visible."""
    _login(page, base_url, client_credentials["email"], client_credentials["password"], api_key)
    page.goto(f"{base_url}{DASHBOARD_URL}")
    expect(page.locator("#client-dashboard-page")).to_be_visible()
    expect(page.locator("#dashboard-tutors-heading")).to_be_visible()
    expect(page.locator("#dashboard-billing-heading")).to_be_visible()
    write_detail("test_client_dashboard", {
        "message": "Clients can log in and see the dashboard",
    })

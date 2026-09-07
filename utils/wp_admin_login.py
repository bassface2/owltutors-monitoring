import re

from playwright.sync_api import Page, expect

from utils.recaptcha_bypass import inject_recaptcha_bypass

LOGIN_URL = "/login/"


def login_wp_admin(page: Page, base_url: str, email: str, password: str, api_key: str):
    """
    Log in via the custom OT '/login/' front-end form (#ot_login) — the same
    one every other fixture in this suite uses for clients/tutors/applicants
    — then land in real wp-admin.

    NOT wp-login.php: Login.php's ot_custom_login_redirect() (hooked to
    login_init) unconditionally redirects any GET request to wp-login.php to
    '/login/' for logged-out visitors, regardless of role -- discovered when
    this helper's original wp-login.php-based approach failed its first-ever
    real run (#user_login never rendered, page had already redirected away).
    That original approach was written on an incorrect assumption and never
    validated end to end before now.

    Once authenticated, wp-admin/* pages themselves are not blocked --
    only wp-login.php is -- and the 'owl' role has manage_options
    (includes/user-mgmt.php ot_system_add_roles()), so
    redirect_logged_in_user() (Login.php) sends a logged-in 'owl'/admin user
    to admin_url() same as core WordPress would. Staff (administrator/owl
    role) need real wp-admin access (metaboxes, admin dashboard pages,
    native user-profile ACF forms) which this front-end form authenticates
    into just as validly as wp-login.php would have.
    """
    page.goto(f"{base_url}{LOGIN_URL}", wait_until="domcontentloaded")
    expect(page.locator("#ot_login")).to_be_visible()
    page.locator("#ot_login_name").fill(email)
    page.locator("#pw1").fill(password)
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=30000)
    page.wait_for_load_state("domcontentloaded")

    # A failed login re-renders /login/ with an error notice — fail loudly
    # here rather than letting every caller's first wp-admin navigation fail
    # with a much more confusing symptom (e.g. a silent redirect to /login/).
    if LOGIN_URL in page.url:
        raise AssertionError(
            f"wp-admin login failed for {email}: still on {LOGIN_URL} after submit "
            f"(current url: {page.url})"
        )

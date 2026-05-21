from playwright.sync_api import Page, expect

CONTACT_URL = "/contact-us/"


def test_contact_form_renders(page: Page, base_url: str):
    """Contact form page loads and the ACF form is visible."""
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()


def test_contact_form_has_submit(page: Page, base_url: str):
    """Submit button is present and enabled."""
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#contact_form_submit")).to_be_visible()
    expect(page.locator("#contact_form_submit")).to_be_enabled()

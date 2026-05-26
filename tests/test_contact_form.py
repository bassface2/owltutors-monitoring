import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

CONTACT_URL = "/contact-us/"


def test_contact_form_renders(page: Page, base_url: str):
    """Contact form page loads and the ACF form is visible."""
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/contact_form_renders.png")
    write_detail("test_contact_form_renders", {
        "message": "Contact form page loaded with ACF form visible",
        "screenshot": "screenshots/contact_form_renders.png",
    })


def test_contact_form_has_submit(page: Page, base_url: str):
    """Submit button is present and enabled."""
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#contact_form_submit")).to_be_visible()
    expect(page.locator("#contact_form_submit")).to_be_enabled()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/contact_form_submit.png")
    write_detail("test_contact_form_has_submit", {
        "message": "Contact form submit button present and enabled",
        "screenshot": "screenshots/contact_form_submit.png",
    })


def test_contact_form_validation(page: Page, base_url: str):
    """
    Clicking submit without filling required fields shows ACF validation errors
    and does not navigate away from the contact form page.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    # Select a form type so tuition fields become visible (and required)
    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    # Wait for subject checkboxes to load via AJAX
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )

    # Click submit without filling any required fields
    page.locator("#contact_form_submit").click()

    # ACF frontend validation should block submission and show error messages
    expect(page.locator(".acf-error-message").first).to_be_visible(timeout=10000)

    # Must still be on the contact form — no redirect to /jobs/
    assert "/contact-us/" in page.url
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/contact_form_validation.png")
    write_detail("test_contact_form_validation", {
        "message": "Contact form validation blocked empty submit and showed errors",
        "screenshot": "screenshots/contact_form_validation.png",
    })

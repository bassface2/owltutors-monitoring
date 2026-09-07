import os
import re
import pytest
from playwright.sync_api import Page, expect

from utils.auth import auth_headers
from utils.details import write_detail
from utils.recaptcha_bypass import inject_recaptcha_bypass

LOGIN_URL = "/login/"


@pytest.fixture(scope="session")
def group_course_id(base_url: str, api_key: str) -> str:
    """Idempotently finds/creates the permanent "Test Group Course —
    Monitoring Fixture" via owl_repair_test_group_course, rather than a
    hardcoded post ID. That fixture (post 201665) was only ever created
    directly on the local dev site (docs/TESTING_SYSTEM.md, "Bookable course
    on dev site") -- staging's post IDs come from an independent production-
    synced database, so the local ID always failed there with "must be a
    group_course" (found 7 Sept 2026). Passes TEST_MEET_NOW_TUTOR_ID through
    as the course's assigned tutor if set -- needed for
    test_course_materials_visible_to_logged_in_tutor, harmless to omit for
    the guest-checkout tests that don't need a tutor at all.
    """
    import requests
    resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={
            "action": "owl_repair_test_group_course",
            "api_key": api_key,
            "tutor_id": os.environ.get("TEST_MEET_NOW_TUTOR_ID", ""),
        },
        headers=auth_headers(base_url),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    assert data.get("success"), f"owl_repair_test_group_course failed: {data}"
    return data["course_id"]

# Stripe test card — always succeeds, no 3DS challenge.
TEST_CARD_NUMBER = "4242424242424242"
TEST_CARD_EXPIRY = "12/34"
TEST_CARD_CVC = "123"
TEST_CARD_POSTAL = "12345"


def _fill_stripe_card(page: Page):
    """Fills Stripe.js's unified Card Element, which renders as a single iframe
    with cardnumber/exp-date/cvc/postal sub-inputs Stripe manages internally."""
    frame = page.frame_locator("iframe[title='Secure card payment input frame']").first
    frame.locator('[name="cardnumber"]').fill(TEST_CARD_NUMBER)
    frame.locator('[name="exp-date"]').fill(TEST_CARD_EXPIRY)
    frame.locator('[name="cvc"]').fill(TEST_CARD_CVC)
    postal = frame.locator('[name="postal"]')
    if postal.count() > 0:
        postal.fill(TEST_CARD_POSTAL)


@pytest.mark.courses
@pytest.mark.critical
def test_course_checkout_page_loads_for_guest(page: Page, base_url: str, group_course_id: str):
    """
    A logged-out guest can load /course-checkout/?course_id={id} for a live,
    bookable course — the checkout form renders with student details, guest
    account fields (name/email/phone — not required for an already-logged-in
    client), and the Stripe Card Element.
    Covers: 'Course checkout page loads for a guest'.
    """
    page.goto(f"{base_url}/course-checkout/?course_id={group_course_id}", wait_until="domcontentloaded")

    expect(page.locator("#ot-course-checkout-form")).to_be_visible(timeout=15000)
    expect(page.locator("#student_name")).to_be_visible()
    expect(page.locator("#client_name")).to_be_visible()
    expect(page.locator("#client_email")).to_be_visible()
    expect(page.locator("#course-card-element")).to_be_visible()
    expect(page.locator("#course-pay-btn")).to_be_visible()

    write_detail("test_course_checkout_page_loads_for_guest", {
        "message": f"Checkout page loaded for guest, course {group_course_id}",
    })


@pytest.mark.courses
@pytest.mark.critical
def test_course_payment_intent_ajax_returns_client_secret(page: Page, base_url: str, group_course_id: str):
    """
    Submitting the checkout form's guest + student details fires
    ot_course_create_payment_intent via AJAX first (before any card details are
    used), which resolves/creates the guest client account and returns a
    Stripe client_secret. Captures that first AJAX response directly rather
    than completing the full card-entry flow (covered separately by
    test_successful_course_payment_redirects_with_enrolment_confirmed).
    Covers: 'ot_course_create_payment_intent AJAX returns client_secret'.
    """
    page.goto(f"{base_url}/course-checkout/?course_id={group_course_id}", wait_until="domcontentloaded")

    unique = re.sub(r"[^0-9]", "", str(id(page)))[-8:]
    page.locator("#client_name").fill("Owl PI TestBot")
    page.locator("#client_email").fill(f"testbot.course.pi.{unique}@owltutors.co.uk")
    page.locator("#client_phone").fill("07700900000")
    page.locator("#student_name").fill("PI Test Student")
    page.locator("#policy_ack").check()

    with page.expect_response(
        lambda r: "action=ot_course_create_payment_intent" in (r.request.post_data or ""),
        timeout=15000,
    ) as resp_info:
        page.locator("#course-pay-btn").click()

    data = resp_info.value.json()
    assert data.get("success"), f"ot_course_create_payment_intent failed: {data}"
    assert data["data"].get("client_secret", "").startswith("pi_"), (
        f"Expected a Stripe PaymentIntent client_secret, got: {data['data'].get('client_secret')!r}"
    )

    write_detail("test_course_payment_intent_ajax_returns_client_secret", {
        "message": "ot_course_create_payment_intent returned a valid client_secret",
    })


@pytest.mark.courses
@pytest.mark.critical
def test_successful_course_payment_redirects_with_enrolment_confirmed(page: Page, base_url: str, group_course_id: str):
    """
    Full guest checkout: fill guest + student details, enter a Stripe test
    card (4242..., always succeeds, no 3DS), submit, and confirm the
    post-payment redirect lands on /dashboard/?enrolment_confirmed=true.
    This is the only test in this file that creates a real course_enrolment —
    test_client_dashboard_shows_course_bookings (same file) depends on it
    having already run.
    Covers: 'Successful payment redirects with ?enrolment_confirmed=true'.
    """
    unique = re.sub(r"[^0-9]", "", str(id(page)))[-8:]
    client_email = f"testbot.course.pay.{unique}@owltutors.co.uk"

    page.goto(f"{base_url}/course-checkout/?course_id={group_course_id}", wait_until="domcontentloaded")

    page.locator("#client_name").fill("Owl Course TestBot")
    page.locator("#client_email").fill(client_email)
    page.locator("#client_phone").fill("07700900000")
    page.locator("#student_name").fill("Payment Test Student")
    page.locator("#student_year_group").select_option(index=1)
    page.locator("#policy_ack").check()

    _fill_stripe_card(page)

    page.locator("#course-pay-btn").click()
    page.wait_for_url(lambda url: "enrolment_confirmed=true" in url, timeout=30000)

    assert "/dashboard/" in page.url and "enrolment_confirmed=true" in page.url, (
        f"Expected redirect to /dashboard/?enrolment_confirmed=true, got: {page.url}"
    )
    expect(page.locator(".alert-success")).to_contain_text("booking is confirmed")

    write_detail("test_successful_course_payment_redirects_with_enrolment_confirmed", {
        "message": f"Guest checkout succeeded for {client_email}, redirected to {page.url}",
    })


@pytest.mark.courses
def test_client_dashboard_shows_course_bookings(page: Page, base_url: str, api_key: str, group_course_id: str):
    """
    A client with an active course_enrolment sees the full-width 'My course
    bookings' section on /dashboard/, with the course title and amount paid.

    Uses the new owl_create_test_course_enrolment monitoring endpoint (28 Aug
    2026) to create a real enrolment directly rather than repeating the full
    Stripe card-entry flow already covered by
    test_successful_course_payment_redirects_with_enrolment_confirmed in this
    file — that test's own guest-checkout auto-login only persists for its
    own Playwright page/context, not across tests, so re-running the full
    paid checkout here just to get a logged-in client would be redundant.
    Covers: 'Client dashboard shows "My course bookings" with active
    enrolments'.
    """
    import requests
    resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_course_enrolment", "api_key": api_key, "course_id": group_course_id},
        headers=auth_headers(base_url),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    assert data.get("success"), f"owl_create_test_course_enrolment failed: {data}"

    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("domcontentloaded")
    page.locator("#ot_login_name").fill(data["client_email"])
    page.locator("#pw1").fill(data["client_password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=90000)

    page.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")

    bookings = page.locator("section[aria-labelledby='course-bookings-heading']")
    expect(bookings).to_be_visible(timeout=15000)
    expect(bookings).to_contain_text("My course bookings")
    expect(bookings).to_contain_text("Test Group Course — Monitoring Fixture")

    write_detail("test_client_dashboard_shows_course_bookings", {
        "message": f"Enrolment {data['enrolment_id']}: 'My course bookings' section rendered for {data['client_email']}",
    })


@pytest.mark.courses
def test_course_materials_visible_to_logged_in_tutor(page: Page, base_url: str, api_key: str, tutor_credentials, group_course_id: str):
    """
    The course's own tutor (tutor_id matches the logged-in user — TEST_TUTOR_EMAIL
    is the same person as TEST_MEET_NOW_TUTOR_ID, which the fixture course is
    assigned to) sees the tutor-only 'Course materials' section on the course
    page, including the add-material form. A logged-out visitor or a
    different logged-in user does not see this section ($is_course_tutor gate,
    single-group_course.php).
    Covers: 'Course materials visible to logged-in tutor on course page'.
    """
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("domcontentloaded")
    page.locator("#ot_login_name").fill(tutor_credentials["email"])
    page.locator("#pw1").fill(tutor_credentials["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=90000)

    page.goto(f"{base_url}/courses/test-group-course-monitoring-fixture/", wait_until="domcontentloaded")

    expect(page.locator("h2:has-text('Course materials')")).to_be_visible(timeout=15000)
    expect(page.locator('[name="material_description"]')).to_be_visible()

    write_detail("test_course_materials_visible_to_logged_in_tutor", {
        "message": f"Course materials section visible for course {group_course_id}'s own tutor",
    })

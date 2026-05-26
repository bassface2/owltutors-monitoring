import os
import re
import pytest
from playwright.sync_api import Page, expect

from utils.cleanup import delete_test_posts
from utils.details import write_detail

CONTACT_URL = "/contact-us/"
TUTORS_URL  = "/tutors/"
FIRST_NAME  = "Owl"
LAST_NAME   = "TestBot"
EMAIL       = "testbot@owltutors.co.uk"
PHONE       = "07700900000"


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    """Delete all test-flagged records from the dev site after each test."""
    yield
    try:
        result = delete_test_posts(base_url)
        print(
            f"[cleanup] deleted {result.get('deleted_jobs', 0)} job(s), "
            f"{result.get('deleted_students', 0)} student(s), "
            f"{result.get('deleted_users', 0)} user(s)"
        )
    except Exception as e:
        print(f"[cleanup] warning: {e}")


def _flag_test_post(page: Page):
    page.evaluate("document.getElementById('ot_test_post').value = '1'")


def _fill_client_info(page: Page):
    page.locator("input[name='acf[field_5edf8887fb5e7]']").fill(FIRST_NAME)
    page.locator("input[name='acf[field_5edf8899fb5e8]']").fill(LAST_NAME)
    page.locator("input[name='acf[field_5edf889ffb5e9]']").fill(EMAIL)
    page.locator("input[name='acf[field_5a573454bb670]']").fill(PHONE)


def _check_hs(page: Page):
    page.locator(
        "div[data-name='i_confirm_there_are_no_health_and_safety_issues'] input[type='checkbox']"
    ).check()


def _select_first_subject(page: Page):
    """Wait for subject checkboxes to load via AJAX then check Maths.
    Maths is above-fold and not a school-entrance subject, so it doesn't
    trigger the school entrance experience field. Scope to subject_list to
    avoid the disabled Maths checkboxes inside level fields (e.g. 11 Plus)."""
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    page.locator("div[data-name='subject_list'] input[type='checkbox'][value='Maths']").check()


def _select_subject(page: Page, subject: str, level: str = None):
    """Select a named subject, expanding the below-fold section first if the
    subject isn't visible. Then select the level radio if provided — ACF
    conditional logic reveals the level field after the checkbox is checked."""
    checkbox = page.locator(f"input[type='checkbox'][value='{subject}']")

    if not checkbox.is_visible():
        page.locator(".below-fold-divider").click()
        expect(checkbox).to_be_visible(timeout=5000)

    checkbox.check()

    if level:
        subject_slug = subject.lower().replace(" ", "_")
        level_input = page.locator(
            f"div[data-name='{subject_slug}_level'] input[type='checkbox'][value='{level}']"
        )
        expect(level_input).to_be_visible(timeout=5000)
        level_input.check()


def _add_tutors_to_shortlist(page: Page, count: int = 3) -> list:
    """Click `count` Add-to-Request buttons on the current tutors listing page.
    Clicking replaces each button with a 'Complete request' link, so always
    clicking .first picks the next unselected tutor. Returns the list of tutor
    ID strings now stored in sessionStorage['ot_requested_tutor_ids'].

    Tutors load via AJAX, so we wait for networkidle before touching any
    buttons — this ensures the full batch has rendered, not just the first card.
    """
    # Wait for the tutor-listing AJAX to finish before looking for buttons
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".add-to-cart", timeout=15000)
    for _ in range(count):
        page.locator(".add-to-cart").first.click()
    # Wait for the shortlist AJAX (debounced 150 ms) to fire and resolve
    page.wait_for_load_state("networkidle")
    return page.evaluate(
        "JSON.parse(sessionStorage.getItem('ot_requested_tutor_ids') || '[]')"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tutor shortlist / cart
# ─────────────────────────────────────────────────────────────────────────────

def test_requested_tutor_cart(page: Page, base_url: str):
    """
    Navigate to /tutors/, add 3 tutors to the shortlist, and verify the
    shortlist widget renders correctly with the count badge and a submit link
    that points to the contact form with job_type=requested_tutors.
    No database records are created; no cleanup required.
    """
    page.goto(f"{base_url}{TUTORS_URL}")
    ids = _add_tutors_to_shortlist(page, count=3)
    print(f"\n[cart] shortlisted tutor IDs: {ids}")

    # Shortlist panel should be visible
    expect(page.locator("#requested_tutor_output")).to_be_visible()

    # Count badge should show 3
    expect(page.locator("#rb-count")).to_have_text("3")

    # Submit link should be present and point to the contact form.
    # href starts as /contact-us/ and is updated asynchronously by the fetch
    # callback in request_builder.js (150 ms debounce → fetch → .then()).
    # wait_for_function retries until the JS update has landed.
    submit_link = page.locator("#selected_tutors_link")
    expect(submit_link).to_be_visible()
    page.wait_for_function(
        "document.getElementById('selected_tutors_link').href.includes('requested_tutors')",
        timeout=10000,
    )

    # Capture evidence screenshot of the populated cart
    os.makedirs("screenshots", exist_ok=True)
    page.locator("#requested_tutor_output").screenshot(path="screenshots/tutor_cart.png")

    href = submit_link.get_attribute("href")
    assert "requested_tutors" in href, (
        f"Submit link href missing 'requested_tutors': {href}"
    )

    # sessionStorage should contain exactly 3 IDs
    assert len(ids) == 3, f"Expected 3 IDs in sessionStorage, got: {ids}"
    write_detail("test_requested_tutor_cart", {
        "message": "Tutor shortlist populated with 3 tutors and submit link updated",
        "tutor_ids": ids,
        "screenshot": "screenshots/tutor_cart.png",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — tutor enquiry (standard, no requested tutors)
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_form_tutor_submission(page: Page, base_url: str, cleanup_after):
    """
    Submit the contact form as 'A tutor to provide tuition services'.
    Verifies the form is accepted and the browser redirects to the new job URL.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )

    # Wait for subject checkboxes to load via AJAX
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    _select_subject(page, "Japanese", "IB Standard Level")

    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "General tuition required — automated test"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    _fill_client_info(page)
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    # ACF adds is-validating during async validation (reCAPTCHA etc.) before
    # POSTing. PHP then echoes a JS redirect to /jobs/. Allow 90s for the full
    # cycle — the 30s timeout was consistently too short on owltutors.test.
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id}")
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(
        path="screenshots/job_tutor_submission.png"
    )
    write_detail("test_contact_form_tutor_submission", {
        "message": f"Tutor enquiry submitted and redirected to job {job_id}",
        "job_id": job_id,
        "screenshot": "screenshots/job_tutor_submission.png",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — something else
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_form_something_else(page: Page, base_url: str, cleanup_after):
    """
    Submit the contact form as 'Something else'.
    Verifies the form is accepted and the browser redirects to the new job URL.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="Something else"
    )

    # 'Something else' shows requirements + client info only — no subject field
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Other enquiry — automated test"
    )

    _fill_client_info(page)
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id}")
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(
        path="screenshots/job_something_else.png"
    )
    write_detail("test_contact_form_something_else", {
        "message": f"'Something else' enquiry submitted and redirected to job {job_id}",
        "job_id": job_id,
        "screenshot": "screenshots/job_something_else.png",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — requested tutors (full end-to-end flow via shortlist cart)
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_form_requested_tutors(page: Page, base_url: str, cleanup_after):
    """
    Full requested-tutors flow. Adds 3 tutors to the shortlist from /tutors/,
    navigates to the contact form via the 'Submit request' link, verifies the
    form is pre-populated from sessionStorage, then submits and verifies the
    redirect to the new job URL.

    The ot_test_post flag suppresses all side-effect emails including the
    tutor job-advert emails (guarded in job-mgmt.php by $is_test).
    Tutor IDs are discovered dynamically — no env var required.
    """
    # Step 1: add 3 tutors to the shortlist from the listing page
    page.goto(f"{base_url}{TUTORS_URL}")
    ids = _add_tutors_to_shortlist(page, count=3)
    assert len(ids) == 3, f"Expected 3 tutor IDs in sessionStorage, got: {ids}"

    # Step 2: navigate to the contact form via the shortlist submit link.
    # The href is updated asynchronously (150ms debounce → fetch → .then()),
    # so wait for it to contain 'requested_tutors' before clicking.
    page.wait_for_function(
        "document.getElementById('selected_tutors_link').href.includes('requested_tutors')",
        timeout=10000,
    )
    page.locator("#selected_tutors_link").click()
    expect(page.locator("#tutor_request_form")).to_be_visible()

    # contact_form.js adds d-none to the select's grandparent (.acf-input div),
    # so the select itself — not the outer wrapper — is hidden.
    expect(page.locator("div[data-name='contact_form_type'] select")).to_be_hidden()

    # Wait for subject AJAX to settle, then select one subject
    page.wait_for_load_state("networkidle")
    _select_first_subject(page)

    # The hidden field should be populated from sessionStorage (JS Cloudflare fix)
    expected_ids = "|".join(str(i) for i in ids)
    expect(page.locator("#requested_tutor_profiles")).to_have_value(expected_ids)

    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Requested tutors enquiry — automated test"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    _fill_client_info(page)
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id} tutor_ids={ids}")
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(
        path="screenshots/job_requested_tutors.png"
    )
    write_detail("test_contact_form_requested_tutors", {
        "message": f"Requested tutors flow submitted and redirected to job {job_id}",
        "job_id": job_id,
        "tutor_ids": ids,
        "screenshot": "screenshots/job_requested_tutors.png",
    })

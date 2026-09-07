import os
import re
import uuid
import urllib.parse
import requests
import pytest
from playwright.sync_api import Page, expect

from utils.auth import auth_headers
from utils.cleanup import delete_test_posts
from utils.details import write_detail
from utils.get_test_job_fields import get_test_job_fields

CONTACT_URL = "/contact-us/"
TUTORS_URL  = "/tutors/"
LOGIN_URL   = "/login/"
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
    api_key = os.environ.get("OWL_TEST_API_KEY", "")
    page.evaluate(
        """(apiKey) => {
            document.getElementById('ot_test_post').value = '1';
            var inp = document.createElement('input');
            inp.type = 'hidden';
            inp.name = 'ot_test_api_key';
            inp.value = apiKey;
            document.getElementById('tutor_request_form').appendChild(inp);
        }""",
        api_key,
    )


def _fill_client_info(page: Page, email: str = EMAIL):
    page.locator("input[name='acf[field_5edf8887fb5e7]']").fill(FIRST_NAME)
    page.locator("input[name='acf[field_5edf8899fb5e8]']").fill(LAST_NAME)
    page.locator("input[name='acf[field_5edf889ffb5e9]']").fill(email)
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

@pytest.mark.jobs
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

    href = submit_link.get_attribute("href")
    assert "requested_tutors" in href, (
        f"Submit link href missing 'requested_tutors': {href}"
    )

    # sessionStorage should contain exactly 3 IDs
    assert len(ids) == 3, f"Expected 3 IDs in sessionStorage, got: {ids}"
    write_detail("test_requested_tutor_cart", {
        "message": "Tutor shortlist populated with 3 tutors and submit link updated",
        "tutor_ids": ids,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — tutor enquiry (standard, no requested tutors)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
@pytest.mark.critical
def test_contact_form_tutor_submission(page: Page, base_url: str, api_key: str, cleanup_after):
    """
    Submit the contact form as 'A tutor to provide tuition services'.
    Verifies the form is accepted and the browser redirects to the new job URL.

    DB assertion (docs/TESTING_REBUILD_SPEC.md Days 2-3): job_create_type must
    actually be 'Regular' with no requested_job_members.
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

    # Unique email per run (docs/TESTING_REBUILD_SPEC.md Days 9-10): the fixed
    # EMAIL constant was shared across several tests in this file, some of
    # which also select Maths — an interrupted earlier run (cleanup never ran)
    # could leave a same-email/same-subject job behind that trips duplicate-job
    # detection for a later test, corrupting its Stage 1 alert text.
    _fill_client_info(page, f"testbot.tutorsub.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    # ACF adds is-validating during async validation (reCAPTCHA etc.) before
    # POSTing. PHP then echoes a JS redirect to /jobs/. Allow 90s for the full
    # cycle — the 30s timeout was consistently too short on owltutors.test.
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id}")

    fields = get_test_job_fields(base_url, api_key, job_id)
    print(f"\n[db-assert] job {job_id} fields: {fields}")
    assert fields["job_create_type"] == "Regular", (
        f"job {job_id}: job_create_type={fields['job_create_type']!r}, expected 'Regular'"
    )
    assert fields["requested_job_members"] == [], (
        f"job {job_id}: requested_job_members={fields['requested_job_members']!r}, expected empty"
    )

    write_detail("test_contact_form_tutor_submission", {
        "message": f"Tutor enquiry submitted and redirected to job {job_id}; job_create_type verified against DB",
        "job_id": job_id,
        "job_create_type": fields["job_create_type"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — something else
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
@pytest.mark.critical
def test_contact_form_something_else(page: Page, base_url: str, api_key: str, cleanup_after):
    """
    Submit the contact form as 'Something else'.
    Verifies the form is accepted and the browser redirects to the new job URL.

    DB assertion (docs/TESTING_REBUILD_SPEC.md Days 2-3): job_create_type must
    actually be 'Regular' with no requested_job_members.
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

    # Unique email per run — see test_contact_form_tutor_submission for why.
    _fill_client_info(page, f"testbot.something.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id}")

    fields = get_test_job_fields(base_url, api_key, job_id)
    print(f"\n[db-assert] job {job_id} fields: {fields}")
    assert fields["job_create_type"] == "Regular", (
        f"job {job_id}: job_create_type={fields['job_create_type']!r}, expected 'Regular'"
    )
    assert fields["requested_job_members"] == [], (
        f"job {job_id}: requested_job_members={fields['requested_job_members']!r}, expected empty"
    )

    write_detail("test_contact_form_something_else", {
        "message": f"'Something else' enquiry submitted and redirected to job {job_id}; job_create_type verified against DB",
        "job_id": job_id,
        "job_create_type": fields["job_create_type"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — requested tutors (full end-to-end flow via shortlist cart)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
@pytest.mark.critical
def test_contact_form_requested_tutors(page: Page, base_url: str, api_key: str, cleanup_after):
    """
    Full requested-tutors flow. Adds 3 tutors to the shortlist from /tutors/,
    navigates to the contact form via the 'Submit request' link, verifies the
    form is pre-populated from sessionStorage, then submits and verifies the
    redirect to the new job URL.

    The ot_test_post flag suppresses all side-effect emails including the
    tutor job-advert emails (guarded in job-mgmt.php by $is_test).
    Tutor IDs are discovered dynamically — no env var required.

    DB assertion (docs/TESTING_REBUILD_SPEC.md Days 2-3): requested_job_members
    must actually contain the shortlisted tutor IDs, and job_create_type must
    be 'Requested tutors'.
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

    # Wait for subject checkboxes to load via AJAX before selecting one.
    # networkidle is unreliable here — tutor profile requests keep the network
    # busy indefinitely on local. Waiting for the checkbox is the real condition.
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=15000,
    )
    _select_first_subject(page)

    # The hidden field should be populated from sessionStorage (JS Cloudflare fix)
    expected_ids = "|".join(str(i) for i in ids)
    expect(page.locator("#requested_tutor_profiles")).to_have_value(expected_ids)

    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Requested tutors enquiry — automated test"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    # Unique email per run — see test_contact_form_tutor_submission for why.
    _fill_client_info(page, f"testbot.reqtutors.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] job_id={job_id} tutor_ids={ids}")

    fields = get_test_job_fields(base_url, api_key, job_id)
    print(f"\n[db-assert] job {job_id} fields: {fields}")
    assert fields["job_create_type"] == "Requested tutors", (
        f"job {job_id}: job_create_type={fields['job_create_type']!r}, expected 'Requested tutors'"
    )
    expected_ids_int = sorted(int(i) for i in ids)
    actual_ids_int = sorted(fields["requested_job_members"])
    assert actual_ids_int == expected_ids_int, (
        f"job {job_id}: requested_job_members={actual_ids_int}, expected {expected_ids_int} "
        f"(shortlisted in the browser)"
    )

    write_detail("test_contact_form_requested_tutors", {
        "message": f"Requested tutors flow submitted and redirected to job {job_id}; requested_job_members verified against DB",
        "job_id": job_id,
        "tutor_ids": ids,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — new client banner
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
def test_new_client_banner(page: Page, base_url: str, cleanup_after):
    """
    After a new-client contact form submission the job page renders
    div#new_client_password_login (single-jobs.php:1581) prompting the client
    to log in or set their password. Covers: post-submission
    ?new_client=true banner renders on job page.
    """
    # Fresh email each run — test requires a genuinely new account to get
    # ?new_client=true; reusing a fixed address breaks after the first run.
    fresh_email = f"testbot.newclient.{uuid.uuid4().hex[:8]}@owltutors.co.uk"

    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    _select_first_subject(page)
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "New client banner test — automated"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")
    _fill_client_info(page, fresh_email)
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    assert "new_client=true" in page.url, (
        f"Expected new_client=true in redirect URL — got: {page.url}"
    )
    # The contact form auto-logs in new clients on submission, so the password-set
    # form (form#new_client_password) never appears — they land directly on their
    # job page. The meaningful assertions are: ?new_client=true in the URL (above)
    # and that the logged-in job view rendered (nav contains Dashboard link).
    expect(page.locator("a.utility-bar__login[href='/dashboard/']")).to_be_visible(timeout=5000)

    write_detail("test_new_client_banner", {
        "message": f"New client banner visible at {page.url}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — returning (logged-in) client
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.jobs
@pytest.mark.critical
def test_contact_form_returning_client(
    page: Page, base_url: str, api_key: str, returning_client_login, cleanup_after
):
    """
    A logged-in (returning) client submitting the contact form sees personal
    info fields hidden (pre-filled from their account). The job is created,
    linked to the existing account, and redirects to /jobs/.

    Setup: returning_client_login submits once to create the account and
    auto-log the client in — no static TEST_CLIENT_EMAIL/PASSWORD needed.
    The same page instance is reused, so the second submission below runs
    as that already-authenticated client.

    Covers: logged-in returning client submitting a job.

    DB assertion (docs/TESTING_REBUILD_SPEC.md Days 2-3): asserts the job's
    client_id actually resolves to the returning client's account, not just
    that the redirect happened. This is the exact shape of bug that shipped
    undetected for a month — client_id silently resolving to 0 while the
    page/redirect behaviour looked correct.
    """
    page.goto(f"{base_url}{CONTACT_URL}", wait_until="domcontentloaded")
    expect(page.locator("#tutor_request_form")).to_be_visible()
    page.wait_for_load_state("networkidle")

    # Personal info fields are hidden for logged-in clients — PHP/JS suppresses
    # them when a WordPress session exists.
    expect(page.locator("input[name='acf[field_5edf8887fb5e7]']")).to_be_hidden()
    expect(page.locator("input[name='acf[field_5edf889ffb5e9]']")).to_be_hidden()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    _select_first_subject(page)
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Returning client test — automated"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] returning client job_id={job_id} (email: {returning_client_login['email']})")

    fields = get_test_job_fields(base_url, api_key, job_id)
    print(f"\n[db-assert] job {job_id} fields: {fields}")
    expected_email = returning_client_login["email"]
    assert fields["client_id"], (
        f"job {job_id}: client_id is empty/0 — expected it to resolve to {expected_email}"
    )
    assert fields["client_email"] == expected_email, (
        f"job {job_id}: client_id resolved to {fields['client_email']!r}, "
        f"expected the returning client {expected_email!r}"
    )

    write_detail("test_contact_form_returning_client", {
        "message": f"Returning client job submitted and redirected to job {job_id}; client_id verified against DB",
        "job_id": job_id,
        "client_id": fields["client_id"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Contact form — logged-out visitor, email matches an existing client account
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.jobs
@pytest.mark.critical
def test_contact_form_existing_email_logged_out(
    page: Page, base_url: str, api_key: str, cleanup_after
):
    """
    A logged-OUT visitor submitting the contact form with an email that
    matches an existing client account should have the job's client_id
    resolve to that existing account — not a new user, and not 0.

    Regression test for the Aug 2026 existing_user_login vs
    existing_user_email WP_Error ambiguity bug (docs/job-creation.md Known
    Issues): a stripped ACF field (ACF Pro 6.9's acf_form() allowlist
    hardening) caused the registration path to run with an empty
    login/email, producing a WP_Error the code couldn't distinguish from
    "email already registered" — the wrong branch was taken and client_id
    silently resolved to 0 for every logged-out job created by an
    already-registered email during the affected window.

    Distinct from test_contact_form_returning_client above, which only
    exercises the *logged-in* returning-client path — this is the
    logged-out path with a known, already-registered email, which was not
    covered by any existing test.

    Uses a fresh, disposable client (owl_create_test_client) as the
    "existing account", not the shared client_credentials fixture
    (testclient@owltutors.co.uk). Discovered on the first real run of this
    test: resolving an *existing* client during a test-flagged submission
    causes the job-creation code to flag that client _ot_test_user=1 too —
    which, for a normally-persistent shared fixture, means the very next
    cleanup_after in any test deletes the real account outright (confirmed:
    it did, taking test_client_login and everything else depending on that
    account down with it until scripts/recreate_local_fixtures.sh was
    re-run). A disposable client sidesteps this entirely — being deleted by
    cleanup is exactly what should happen to it.
    """
    client_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_client", "api_key": api_key},
        headers=auth_headers(base_url),
        timeout=15,
    )
    client_resp.raise_for_status()
    existing_client = client_resp.json()
    assert existing_client.get("success"), f"owl_create_test_client failed: {existing_client}"
    existing_email = existing_client["client_email"]

    page.goto(f"{base_url}{CONTACT_URL}", wait_until="domcontentloaded")
    expect(page.locator("#tutor_request_form")).to_be_visible()
    page.wait_for_load_state("networkidle")

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    _select_first_subject(page)

    # Personal info fields are visible here once the form has progressed
    # (unlike the logged-in returning-client case above, where they're
    # hidden throughout) — this visitor has no WordPress session. Checked
    # only after selecting type/subject: the field is hidden for *everyone*,
    # logged in or not, until the form reaches this point — checking too
    # early would pass or fail for the wrong reason regardless of login
    # state. Discovered on the first real run of this test.
    expect(page.locator("input[name='acf[field_5edf889ffb5e9]']")).to_be_visible()

    _fill_client_info(page, email=existing_email)
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Existing-email logged-out test — automated"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] existing-email logged-out job_id={job_id} (email: {existing_email})")

    fields = get_test_job_fields(base_url, api_key, job_id)
    print(f"\n[db-assert] job {job_id} fields: {fields}")
    assert fields["client_id"], (
        f"job {job_id}: client_id is empty/0 — expected it to resolve to the existing "
        f"client account {existing_email!r}. This is exactly the shape of the Aug 2026 "
        f"client_id=0 regression: page/redirect behaviour looks correct while the DB "
        f"value is silently wrong."
    )
    assert fields["client_email"] == existing_email, (
        f"job {job_id}: client_id resolved to {fields['client_email']!r}, expected the "
        f"existing client {existing_email!r} — a new account may have been created "
        f"instead of matching the existing one"
    )

    write_detail("test_contact_form_existing_email_logged_out", {
        "message": f"Logged-out submission with an existing client's email correctly resolved to job {job_id}",
        "job_id": job_id,
        "client_id": fields["client_id"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — quality check failure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
def test_stage1_quality_check_fail(page: Page, base_url: str, cleanup_after):
    """
    Submitting a job with very short tuition requirements (< 25 chars) passes
    ACF frontend validation (which only checks non-empty) but fails the PHP
    quality check in ot_system_check_submitted_job_quality().  The job is
    created at 'Stage 1 - Approved but not ready' and the job page shows the
    warning alert: 'Your enquiry requires more information to be processed'.
    Covers: 'Stage 1 path — quality check fails'.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    _select_first_subject(page)

    # Requirements deliberately short (< 25 chars) — passes ACF required, fails PHP check
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Too short"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    # Unique email per run — see test_contact_form_tutor_submission for why. This
    # test specifically was the one observed to flake from this: a leftover
    # same-email Maths job from another interrupted test made duplicate_jobs
    # trigger unexpectedly, replacing the expected 'more information' message.
    _fill_client_info(page, f"testbot.stage1.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] stage1 job_id={job_id}")

    # Stage 1 alert: warning box with the 'more information' message
    stage1_alert = page.locator(".alert-warning")
    expect(stage1_alert).to_be_visible(timeout=10000)
    assert "more information" in (stage1_alert.text_content() or "").lower(), (
        f"Expected Stage 1 warning text, got: {stage1_alert.text_content()!r}"
    )

    write_detail("test_stage1_quality_check_fail", {
        "message": f"Short requirements triggered Stage 1 alert on job {job_id}",
        "job_id": job_id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Health and safety unchecked — job still creates
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
def test_health_safety_unchecked_job_creates(page: Page, base_url: str, cleanup_after):
    """
    Submitting the contact form without ticking the health and safety
    confirmation checkbox does not block job creation — the job is created
    and the browser redirects to /jobs/.  The H&S flag appends a note to
    notes_on_status (verified via the admin), but this smoke test just
    confirms the submission itself succeeds.
    Covers: 'Health and safety flag unchecked appends note to notes_on_status'.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    _select_first_subject(page)
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Health and safety test — automated smoke test submission"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    # Unique email per run — see test_contact_form_tutor_submission for why.
    _fill_client_info(page, f"testbot.hsunchecked.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    # Deliberately do NOT call _check_hs(page) — H&S box left unticked
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] h&s unchecked job_id={job_id}")

    write_detail("test_health_safety_unchecked_job_creates", {
        "message": f"H&S unchecked: job still created at {job_id}; notes_on_status note must be verified in WP admin",
        "job_id": job_id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch L — duplicate job detection
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
def test_duplicate_job_detection(
    page: Page, base_url: str, returning_client_login, cleanup_after
):
    """
    A logged-in client submitting a second job with the same subject as an
    existing open job triggers ot_system_check_for_duplicate_jobs(). The new
    job is created at Stage 1 and the job page shows a dedicated duplicate-job
    notice with an 'already have an open enquiry' message and a link back to
    the original job.
    Setup: returning_client_login submits job #1 with Maths and leaves the
    browser logged in. This test submits job #2 (also Maths). Both jobs are
    flagged ot_test_post=1 for cleanup.

    docs/TESTING_REBUILD_SPEC.md Days 9-10: this test was not flaky, it was
    consistently broken. It checked the generic .alert-warning box for
    'already'/'enquiry' text, but when duplicate_jobs is a failed element,
    ot_single_job_info_alert() (job-mgmt.php) overrides that box's own message
    to 'You have exceeded the maximum number of enquiries' — which contains
    neither word ('enquiries' is not a substring match for 'enquiry'). The
    actual 'already have an open enquiry' text renders in a separate sibling
    div, .ot_single_job_duplicate_jobs, not inside .alert-warning at all. The
    underlying PHP duplicate-detection feature works correctly; only the
    test's selector/assertion was wrong.
    Covers: 'Duplicate job detection — existing open job triggers Stage 1 redirect'.
    """
    page.goto(f"{base_url}{CONTACT_URL}", wait_until="domcontentloaded")
    expect(page.locator("#tutor_request_form")).to_be_visible()
    page.wait_for_load_state("networkidle")

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    # Same subject (Maths) as the setup job created by returning_client_login
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox'][value='Maths']",
        timeout=15000,
    )
    page.locator(
        "div[data-name='subject_list'] input[type='checkbox'][value='Maths']"
    ).check()
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Duplicate detection test — automated smoke test submission"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")
    _check_hs(page)
    _flag_test_post(page)

    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)

    job_id = re.search(r"/jobs/(\d+)/", page.url).group(1)
    print(f"\n[result] duplicate job_id={job_id} (client: {returning_client_login['email']})")

    # Job stays at Stage 1 (not advanced) when the duplicate check fires.
    expect(page.locator(".alert-warning")).to_be_visible(timeout=10000)

    # The duplicate-specific notice (a sibling of .alert-warning, not nested inside
    # it) carries the actual 'already have an open enquiry' text and job link.
    duplicate_notice = page.locator(".ot_single_job_duplicate_jobs")
    expect(duplicate_notice).to_be_visible(timeout=10000)
    notice_text = (duplicate_notice.text_content() or "").lower()
    assert "already" in notice_text and "enquiry" in notice_text, (
        f"Expected duplicate-job notice with 'already ... enquiry' text, got: {notice_text!r}"
    )

    write_detail("test_duplicate_job_detection", {
        "message": f"Duplicate Maths job (job {job_id}) stayed at Stage 1 with duplicate warning",
        "job_id": job_id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch L — admin-submitted job path
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.jobs
def test_admin_job_path_redirects(page: Page, base_url: str, cleanup_after):
    """
    When the contact form POST includes admin_submited_job=true (added by PHP
    in page-contactform.php when an admin views the form), job creation calls
    wp_redirect('/wp-admin/post.php?post=ID&action=edit') instead of the
    client-facing /jobs/ URL.
    This test injects the field via JS to simulate an admin form submission.
    The test browser is not an authenticated admin, so WordPress redirects to
    the login page with redirect_to pointing at /wp-admin/ — confirming the
    admin path was taken, not the normal client /jobs/ path.
    Covers: 'Admin-submitted job path redirects to WP admin edit screen'.
    """
    page.goto(f"{base_url}{CONTACT_URL}")
    expect(page.locator("#tutor_request_form")).to_be_visible()

    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']",
        timeout=10000,
    )
    _select_first_subject(page)
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Admin path test — automated smoke test submission"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")

    # Unique email per run — see test_contact_form_tutor_submission for why.
    _fill_client_info(page, f"testbot.adminpath.{uuid.uuid4().hex[:8]}@owltutors.co.uk")
    _check_hs(page)
    _flag_test_post(page)

    # Inject admin_submited_job=true — normally added by PHP when an admin views the form
    page.evaluate(
        """() => {
            const inp = document.createElement('input');
            inp.type  = 'hidden';
            inp.name  = 'admin_submited_job';
            inp.value = 'true';
            document.getElementById('tutor_request_form').appendChild(inp);
        }"""
    )

    page.locator("#contact_form_submit").click()

    # PHP calls wp_redirect('/wp-admin/post.php?post=ID&action=edit'). Since the
    # browser is not an authenticated admin, WP follows up with a redirect to the
    # login page with redirect_to=/wp-admin/... — wait for either URL pattern.
    page.wait_for_url(
        re.compile(r".*/wp-admin/|.*/login/"),
        timeout=90000,
    )
    page.wait_for_load_state("networkidle", timeout=15000)

    final_url = page.url
    decoded   = urllib.parse.unquote(final_url)
    assert "wp-admin" in decoded, (
        f"Expected redirect to /wp-admin/ (or login?redirect_to=wp-admin), got: {final_url!r}"
    )
    assert "/jobs/" not in final_url, (
        f"admin_submited_job=true should redirect to wp-admin, not /jobs/: {final_url!r}"
    )

    print(f"\n[result] admin path confirmed, final URL: {final_url}")
    write_detail("test_admin_job_path_redirects", {
        "message": f"Admin job path redirected to wp-admin (not /jobs/): {final_url}",
    })

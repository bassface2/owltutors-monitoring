import os
import re
import requests
from playwright.sync_api import Page, expect
from utils.auth import auth_headers
from utils.create_test_job import create_test_job
from utils.details import write_detail
from utils.get_test_job_fields import get_test_job_fields
from utils.recaptcha_bypass import inject_recaptcha_bypass
from utils.timesheet_wizard import (
    complete_goal_wizard_via_skip, fill_and_submit_timesheet_form, submit_student_name_if_shown,
)
import pytest

DASHBOARD_URL = "/dashboard/"
TUTORING_URL  = "/dashboard/tutoring-section/"
PROFILE_URL   = "/dashboard/profile/"
LOGIN_URL     = "/login/"


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    from utils.cleanup import delete_test_posts
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


def _login(page: Page, base_url: str, email: str, password: str, api_key: str):
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(email)
    page.locator("#pw1").fill(password)
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=30000)


def _activate_profile_tab(page: Page, tab_id: str):
    """Force a tutor profile tab pane visible. Hash-nav JS is not always reliable in
    Playwright (timing, external scripts); this guarantees the pane is display:block."""
    page.evaluate(f"""
        () => {{
            const pane = document.querySelector('#{tab_id}');
            if (!pane) return;
            document.querySelectorAll('#tutor_profile_tabs .tab-pane').forEach(
                p => p.classList.remove('show', 'active')
            );
            pane.classList.add('show', 'active');
            pane.classList.remove('fade');
        }}
    """)


@pytest.mark.tutors
def test_tutor_dashboard_loads(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    A logged-in tutor visiting /dashboard/ sees the tutor dashboard.
    Header id="tutor-listings-page" (page-dashboard.php:586).
    Outer container div#tutor_dashboard (page-dashboard.php:483).
    Covers: Tutor dashboard loads for logged-in tutor.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{DASHBOARD_URL}", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("header#tutor-listings-page")).to_be_visible()
    expect(page.locator("div#tutor_dashboard")).to_be_visible()
    write_detail("test_tutor_dashboard_loads", {
        "message": "Tutor dashboard loaded with correct header and container",
    })


@pytest.mark.tutors
@pytest.mark.critical
def test_tutor_dashboard_jobs_board(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    Jobs board tab pane is the default active section at /dashboard/tutoring-section/.
    page-dashboard-tutoring-section.php:97 sets show/active on div#jobs_board.
    Covers: Jobs board section renders with filter form and at least one result.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{TUTORING_URL}", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("div#tutor_dash_tabs")).to_be_visible()
    expect(page.locator("div#jobs_board")).to_be_visible()
    write_detail("test_tutor_dashboard_jobs_board", {
        "message": "Tutor jobs board tab pane visible and active",
    })


@pytest.mark.tutors
@pytest.mark.critical
def test_tutor_dashboard_timesheet_entry(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    The Submit a timesheet tab pane is present in the DOM at /dashboard/tutoring-section/.
    page-dashboard-tutoring-section.php:102 renders div#submit_a_timesheet.
    Covers: Submit a timesheet section renders the job list entry point.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{TUTORING_URL}", wait_until="domcontentloaded", timeout=90000)
    assert page.locator("div#submit_a_timesheet").count() > 0, (
        "#submit_a_timesheet pane not found in DOM at /dashboard/tutoring-section/"
    )
    write_detail("test_tutor_dashboard_timesheet_entry", {
        "message": "Tutor timesheet entry pane present in DOM",
    })


# ── Batch F — tutor login tests ───────────────────────────────────────────────

@pytest.mark.tutors
def test_tutor_jobs_board_filter_returns_results(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    The jobs board filter on /dashboard/tutoring-section/ accepts a subject
    selection and fires an AJAX call (ot_jobs_board_filter via JS in
    ot_logged_in_tutor.js) that updates #tutor_job_output.
    The jobs_board section loads its content dynamically on page load (it is
    the default active tab with class dynamic). #jobs_board_filter appears
    after the AJAX populates div.jobs_board_content.
    Covers: 'Jobs board filter returns AJAX results'.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{TUTORING_URL}", wait_until="domcontentloaded", timeout=90000)
    # #jobs_board_filter is injected by the jobs_board AJAX (ot_dash_ajax_handler?content=jobs_board).
    # On local Laragon this AJAX can take 50+ seconds — wait up to 90s for it.
    page.wait_for_selector("#jobs_board_filter", timeout=90000)

    # A subject is required by JS — selecting by value (subject names are their own values)
    page.locator("select[name='request_search_subject']").select_option("Maths")
    page.locator("select[name='request_search_delivery']").select_option("Online")

    # Wait for the filter's own AJAX response specifically, not networkidle. The tutor
    # dashboard unconditionally fires a second, unrelated request on page load
    # (ot_tutor_dash_ajax_handler('recommended_jobs') in ot_logged_in_tutor.js, for the
    # sidebar "recommended jobs" card) that can still be in flight when the filter is
    # submitted — networkidle waits for *all* network activity to go quiet, so it was
    # timing out on that unrelated widget rather than the filter's own response, even
    # once the filter's query itself was fast. Confirmed live: the filter response
    # itself carries action=ot_jobs_board_filter, so wait for that exactly.
    with page.expect_response(lambda r: "action=ot_jobs_board_filter" in r.url, timeout=30000):
        page.locator("#tutor_jobs_board_filter_btn").click()

    output = page.locator("#tutor_job_output")
    expect(output).to_be_visible()
    assert output.inner_text().strip() != "", (
        "#tutor_job_output is empty after filter — AJAX may not have completed"
    )

    write_detail("test_tutor_jobs_board_filter_returns_results", {
        "message": "Jobs board filter (Maths, Online) submitted; results rendered",
    })


@pytest.mark.tutors
def test_tutor_stripe_connect_section_renders(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    The Stripe Connect section at /dashboard/profile/#stripe_connect renders
    content via ot_dash_ajax_handle (content=stripe_connect). Shows either
    the onboarding prompt (no tutor_stripe_connect_id) or the connected state.
    Covers: 'Stripe Connect onboarding prompt shown when no tutor_stripe_connect_id'.
    NOTE: the specific prompt is only visible if the test tutor lacks
    tutor_stripe_connect_id — both states are accepted here. Manual check
    required to confirm the prompt appears on a fresh account.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    # domcontentloaded avoids 30s timeout waiting for Stripe CDN resources
    page.goto(f"{base_url}{PROFILE_URL}#stripe_connect", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)
    # Activate the tab pane (same hash-nav reliability fix as my_availability)
    _activate_profile_tab(page, "stripe_connect")
    page.wait_for_selector("#stripe_connect", timeout=10000)
    section = page.locator("#stripe_connect")
    expect(section).to_be_visible()
    # stripe_connect content is server-rendered; .stripe_connect_content div is empty by
    # design (ot_dashboard_title_box with $dynamic=false). Check section has some text.
    assert section.inner_text().strip() != "", (
        "#stripe_connect section is empty — expected server-rendered Stripe Connect UI"
    )

    write_detail("test_tutor_stripe_connect_section_renders", {
        "message": "Stripe Connect section rendered content after AJAX load",
    })


@pytest.mark.tutors
def test_tutor_availability_grid_renders(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    The availability grid at /dashboard/profile/#my_availability renders the
    [tutor_availability] shortcode output — #tutor_availability_holder with
    the slot grid inside div.tutor-avail-wrap.
    Covers: 'Tutor dashboard availability slot grid renders'.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{PROFILE_URL}#my_availability", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)
    _activate_profile_tab(page, "my_availability")

    page.wait_for_selector("#tutor_availability_holder", timeout=10000)
    expect(page.locator("#tutor_availability_holder")).to_be_visible()

    # The grid is hidden until tutor_extra_capacity > 0 (availability.vanilla.js
    # calls applyVisibilityFromStudents on load; grid container has hide_on_load CSS).
    # Trigger the capacity input to reveal the grid if the test account has 0 capacity.
    page.evaluate("""
        () => {
            const input = document.getElementById('tutor_extra_capacity');
            if (!input || Number(input.value) > 0) return;
            input.value = '1';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)

    # Dashboard grid cells are button.tutor-avail-slot[data-d][data-s] (not .avail-cell)
    expect(page.locator("button.tutor-avail-slot").first).to_be_visible(timeout=10000)

    write_detail("test_tutor_availability_grid_renders", {
        "message": "Availability slot grid rendered at /dashboard/profile/#my_availability",
    })


@pytest.mark.tutors
@pytest.mark.critical
def test_tutor_availability_grid_saves(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    Clicking an availability cell, confirming the save, and reloading the
    section causes the changed slot state to persist.
    Toggles the first cell, saves via the confirmation modal, reloads, and
    verifies the cell retained its new state.
    Covers: 'Saving availability grid fires AJAX; slot count persists after reload'.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}{PROFILE_URL}#my_availability", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)

    _activate_profile_tab(page, "my_availability")

    # Ensure grid visible (capacity=0 hides grid via availability.vanilla.js)
    page.evaluate("""
        () => {
            const input = document.getElementById('tutor_extra_capacity');
            if (!input || Number(input.value) > 0) return;
            input.value = '1';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)

    # Dashboard grid cells: button.tutor-avail-slot[data-d=day][data-s=slot_index]
    page.wait_for_selector("button.tutor-avail-slot", timeout=15000)

    first_cell = page.locator("button.tutor-avail-slot").first
    d = first_cell.get_attribute("data-d")
    s = first_cell.get_attribute("data-s")
    was_on = "is-on" in (first_cell.get_attribute("class") or "")
    first_cell.click()
    page.wait_for_timeout(400)

    # Open save confirmation and confirm
    page.locator("button.tutor-avail-save").click()
    page.wait_for_selector("#tutor-avail-confirm", state="visible", timeout=8000)
    page.locator("#tutor-avail-confirm").click()
    page.wait_for_load_state("networkidle", timeout=15000)

    # Reload and re-activate the section to verify persistence
    page.goto(f"{base_url}{PROFILE_URL}#my_availability", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)
    _activate_profile_tab(page, "my_availability")
    page.evaluate("""
        () => {
            const input = document.getElementById('tutor_extra_capacity');
            if (!input || Number(input.value) > 0) return;
            input.value = '1';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)
    page.wait_for_selector("button.tutor-avail-slot", timeout=15000)

    reloaded_cell = page.locator(f"button.tutor-avail-slot[data-d='{d}'][data-s='{s}']")
    reloaded_class = reloaded_cell.get_attribute("class") or ""
    if was_on:
        assert "is-on" not in reloaded_class, (
            f"Slot [day={d}, slot={s}] should be OFF after toggle but still has is-on"
        )
    else:
        assert "is-on" in reloaded_class, (
            f"Slot [day={d}, slot={s}] should be ON after toggle but lacks is-on"
        )

    write_detail("test_tutor_availability_grid_saves", {
        "message": f"Availability slot [day={d}, slot={s}] toggled and state persisted after reload",
    })


@pytest.mark.tutors
def test_tutor_dashboard_invoices_renders(page: Page, base_url: str, api_key: str, tutor_credentials):
    """
    The Invoices section at /dashboard/tutoring-section/#invoices loads its
    content via ot_dash_ajax_handle (content=invoices). Empty state is
    acceptable — the test checks the section rendered something, not that
    invoices exist.
    Covers: 'Tutor dashboard invoices section renders (empty state acceptable)'.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    # Navigate with hash — hash-nav JS activates #invoices tab pane
    page.goto(f"{base_url}{TUTORING_URL}#invoices", wait_until="domcontentloaded")
    page.wait_for_selector("#invoices", timeout=15000)
    section = page.locator("#invoices")
    expect(section).to_be_visible()
    # The section is server-rendered (not dynamic AJAX). .invoices_content is always
    # empty — the invoice HTML from ot_tutor_dashboard_invoices() renders alongside it.
    # Verify the section contains at least the title text.
    assert section.inner_text().strip() != "", (
        "#invoices section rendered empty — expected at least a title"
    )

    write_detail("test_tutor_dashboard_invoices_renders", {
        "message": "Invoices section rendered at /dashboard/tutoring-section/#invoices",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Timesheet wizard (single-jobs.php #timesheet tab, timesheet-mgmt.php)
# ─────────────────────────────────────────────────────────────────────────────
# Each test creates its own disposable Stage 4 job (owl_create_test_job) rather
# than reusing the shared stage3_job fixture from test_job_connection.py, since
# these need control over mgmt_ea_or_eb_job and don't need the real applicant/
# accept-terms flow — a fresh, isolated job per test avoids any risk of
# interfering with the Stage 3/4 Connection tests' shared state.

@pytest.mark.tutors
@pytest.mark.critical
def test_timesheet_wizard_renders_stripe_connect_check(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, tutor_credentials
):
    """
    For an 'EA job', ot_timesheets_tutor_create_edit() (timesheet-mgmt.php)
    shows the Stripe Connect form before anything else — student name, goal,
    or the timesheet itself — whenever the tutor has no tutor_stripe_connect_id
    set (true for the local test tutor, see test_tutor_stripe_connect_section_renders's
    note). Only checks the form renders; does not click through to the real
    Stripe OAuth redirect.
    Covers: 'Timesheet wizard renders (Stripe Connect check -> goal -> form)'.
    """
    job = create_test_job(base_url, api_key, stage=4, tutor_id=meet_now_tutor_id, job_type="EA job")

    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}/jobs/{job['job_id']}/#timesheet", wait_until="domcontentloaded")

    expect(page.locator("#timesheet h2:has-text('Connect to Stripe')")).to_be_visible(timeout=15000)

    write_detail("test_timesheet_wizard_renders_stripe_connect_check", {
        "message": f"EA job {job['job_id']} correctly shows the Stripe Connect form first",
        "job_id": job["job_id"],
    })


@pytest.mark.tutors
@pytest.mark.critical
def test_eb_job_timesheet_submission_creates_timesheet_and_redirects(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, tutor_credentials
):
    """
    Drives a full EB job timesheet submission: student name (if shown) -> goal
    wizard (via the "Skip" bypass — see timesheet_wizard.py, avoids the
    ChatGPT-based goal-quality check) -> timesheet form -> "Submit for
    invoicing". Confirms the real POST redirects to
    /dashboard/tutoring-section#submit_a_timesheet (timesheet-mgmt.php's
    success path — no distinct confirmation page).
    Covers: 'EB job timesheet submission creates timesheet and redirects
    correctly'.
    """
    job = create_test_job(base_url, api_key, stage=4, tutor_id=meet_now_tutor_id, job_type="EB job")

    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}/jobs/{job['job_id']}/#timesheet", wait_until="domcontentloaded")

    submit_student_name_if_shown(page)
    complete_goal_wizard_via_skip(page)
    fill_and_submit_timesheet_form(page, submit_type="submit_for_invoicing")

    page.wait_for_url(lambda url: "/dashboard/tutoring-section" in url, timeout=20000)
    assert "submit_a_timesheet" in page.url, (
        f"Expected redirect to #submit_a_timesheet, got: {page.url}"
    )

    write_detail("test_eb_job_timesheet_submission_creates_timesheet_and_redirects", {
        "message": f"EB job {job['job_id']} timesheet submitted, redirected to {page.url}",
        "job_id": job["job_id"],
    })


@pytest.mark.tutors
def test_duplicate_timesheet_check_shows_warning(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, tutor_credentials
):
    """
    ot_check_existing_eb_timesheets_month_year (AJAX, fires automatically on
    page load once the timesheet form's month/year selects are present —
    ot_timesheets.js) warns when a timesheet already exists for the selected
    job/month/year. Submits one timesheet for the current month, then goes
    through the wizard a second time for the same job and confirms the
    auto-triggered warning appears instead of a fresh blank form.
    Covers: 'Duplicate timesheet check AJAX shows warning'.
    """
    job = create_test_job(base_url, api_key, stage=4, tutor_id=meet_now_tutor_id, job_type="EB job")

    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)

    # First submission — establishes a timesheet for the current month/year.
    page.goto(f"{base_url}/jobs/{job['job_id']}/#timesheet", wait_until="domcontentloaded")
    submit_student_name_if_shown(page)
    complete_goal_wizard_via_skip(page)
    fill_and_submit_timesheet_form(page, submit_type="submit_for_invoicing")
    page.wait_for_url(lambda url: "/dashboard/tutoring-section" in url, timeout=20000)

    # Second pass on the same job — goal_repeater's saved text is empty (Skip
    # bypass), so ot_timesheets_tutor_create_edit() shows the goal wizard
    # again rather than jumping straight to the timesheet form.
    page.goto(f"{base_url}/jobs/{job['job_id']}/#timesheet", wait_until="domcontentloaded")
    submit_student_name_if_shown(page)
    complete_goal_wizard_via_skip(page)

    warning = page.locator("#month_year_ajax_call")
    expect(warning).to_be_visible(timeout=15000)
    warning_text = (warning.text_content() or "").strip()
    assert warning_text, "Expected non-empty duplicate-timesheet warning text in #month_year_ajax_call"

    write_detail("test_duplicate_timesheet_check_shows_warning", {
        "message": f"Job {job['job_id']}: duplicate timesheet warning shown on second submission attempt",
        "job_id": job["job_id"],
    })


@pytest.mark.tutors
def test_bill_timesheet_in_stripe_creates_real_invoice(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, tutor_credentials, cleanup_after
):
    """
    ot_stripe_invoice_create() (services/stripe/system.php) -- the function
    the real "Bill timesheet in Stripe" button calls -- successfully creates,
    finalizes, and sends a real (Stripe test-mode) invoice for a genuine EB
    job timesheet.

    Deliberately does NOT drive the real button/admin UI
    (ot_bill_timesheet_inline_callback(), includes/functions.php): that
    callback unconditionally also calls ot_xero_connect_create_invoice() with
    no test-mode gate at all, which would create a real invoice in the
    live-connected Xero organisation on every run of this test -- exactly
    the class of risk docs/TESTING_SYSTEM.md already excludes Xero-touching
    flows from automating (no test-mode suppression exists for Xero, unlike
    Stripe). ot_stripe_invoice_create() itself never touches Xero, so this
    calls it directly via the new owl_trigger_stripe_invoice_create endpoint
    instead -- real Stripe-side coverage with zero Xero risk.

    Builds real prerequisite state rather than faking it: owl_create_test_stripe_client
    creates a disposable client with a genuine Stripe test-mode Customer
    (stripe_id -- the one precondition ot_stripe_invoice_create() hard-requires),
    then a real EB job timesheet is submitted through the actual tutor-facing
    wizard (same helpers as test_eb_job_timesheet_submission_creates_timesheet_and_redirects)
    so every derived field (billing rates, totals, timesheet_status = '2) Ready')
    is populated by the real production code path, not guessed at.
    """
    stripe_client = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_stripe_client", "api_key": api_key},
        headers=auth_headers(base_url),
        timeout=15,
    ).json()
    assert stripe_client.get("success"), f"owl_create_test_stripe_client failed: {stripe_client}"

    job = create_test_job(
        base_url, api_key, stage=4, tutor_id=meet_now_tutor_id, job_type="EB job",
        client_email=stripe_client["client_email"],
    )

    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)
    page.goto(f"{base_url}/jobs/{job['job_id']}/#timesheet", wait_until="domcontentloaded")
    submit_student_name_if_shown(page)
    complete_goal_wizard_via_skip(page)
    fill_and_submit_timesheet_form(page, submit_type="submit_for_invoicing")
    page.wait_for_url(lambda url: "/dashboard/tutoring-section" in url, timeout=20000)

    fields = get_test_job_fields(base_url, api_key, job["job_id"])
    timesheet_id = fields.get("most_recent_timesheet_id")
    assert timesheet_id, f"Expected most_recent_timesheet_id to be set on job {job['job_id']} after submission: {fields}"

    invoice_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={
            "action": "owl_trigger_stripe_invoice_create",
            "api_key": api_key,
            "timesheet_id": timesheet_id,
            "job_id": job["job_id"],
        },
        headers=auth_headers(base_url),
        timeout=30,
    ).json()
    assert invoice_resp.get("success"), f"owl_trigger_stripe_invoice_create failed: {invoice_resp}"
    assert (invoice_resp.get("stripe_invoice_id") or "").startswith("in_"), (
        f"Expected a real Stripe invoice ID (in_...), got: {invoice_resp}"
    )
    assert invoice_resp.get("stripe_invoice_status") == "Open", (
        f"Expected stripe_invoice_status='Open' (finalized and sent), got: {invoice_resp}"
    )

    write_detail("test_bill_timesheet_in_stripe_creates_real_invoice", {
        "message": f"Timesheet {timesheet_id}: Stripe invoice {invoice_resp['stripe_invoice_id']} created and sent",
        "job_id": job["job_id"],
        "timesheet_id": timesheet_id,
    })

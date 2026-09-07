import os
import re
import uuid
import pytest
from pathlib import Path
from playwright.sync_api import Page, expect

from utils.apply import (
    _show_section, _wait_for_section, _save_section,
    _add_repeater_row, _upload_acf_file, complete_application_form,
)
from utils.cleanup import delete_test_posts
from utils.details import write_detail
from utils.recaptcha_bypass import inject_recaptcha_bypass
from utils.test_status_records import get_test_status_record, reset_status_field

FIXTURES_DIR = Path(__file__).parent / "fixtures"

APPLICATION_URL = "/tutor-section/application/"
LOGIN_URL       = "/login/"

# Unique-ish email for the registration submission test.
# Uses a fixed suffix so the cleanup endpoint can delete the user by _ot_test_user meta.
TEST_REG_EMAIL    = "testbot.preapp@owltutors.co.uk"
TEST_REG_PASSWORD = "Owl1Tutor!Test2026"


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    """Delete all test-flagged records (including _ot_test_user) after the test."""
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


def _flag_test_user(page: Page):
    """Inject the test-user flag into the registration form.
    Analogous to _flag_test_post() in test_contact_submissions.py."""
    api_key = os.environ.get("OWL_TEST_API_KEY", "")
    page.evaluate(
        """(apiKey) => {
            document.getElementById('ot_test_user').value = '1';
            document.getElementById('ot_test_api_key_reg').value = apiKey;
        }""",
        api_key,
    )


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Registration -- page loads
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

@pytest.mark.recruitment
def test_tutor_registration_page_loads(page: Page, base_url: str):
    """
    The tutor registration page (/tutor-section/application/) loads for a
    logged-out visitor and shows the [ot_applicant_register_form] shortcode
    (rendered as #signupform).
    Covers: 'Tutor registration page loads with [ot_applicant_register_form] visible'.
    """
    page.goto(f"{base_url}{APPLICATION_URL}")
    expect(page.locator("#signupform")).to_be_visible()
    expect(page.locator("#applicant_register")).to_be_visible()

    write_detail("test_tutor_registration_page_loads", {
        "message": "Tutor registration form visible at /tutor-section/application/",
    })


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Registration -- full submission
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

@pytest.mark.recruitment
@pytest.mark.critical
def test_tutor_registration_submits(page: Page, base_url: str, cleanup_after):
    """
    Submitting the registration form with valid credentials creates a
    pre-applicant user and redirects to /tutor-section/application/?newpreapp=true.

    The ot_test_user flag (injected via page.evaluate) marks the new user with
    _ot_test_user=1 so the cleanup endpoint deletes them after the test.
    reCAPTCHA is skipped by submitting the form directly (PHP does not validate
    reCAPTCHA on registration).
    Covers: 'Registration form submits, creates pre-applicant user, redirects
    to application page (with cleanup)'.
    """
    page.goto(f"{base_url}{APPLICATION_URL}")
    expect(page.locator("#signupform")).to_be_visible()

    page.locator("#email").fill(TEST_REG_EMAIL)
    page.locator("#pw1").fill(TEST_REG_PASSWORD)

    # Inject test flag -- PHP checks ot_test_user + ot_test_api_key_reg before
    # setting _ot_test_user=1 on the new user (only on otdev1602/owltutors.test)
    _flag_test_user(page)

    # Submit directly (bypass reCAPTCHA -- PHP doesn't validate it for registration)
    page.evaluate("document.getElementById('signupform').submit()")

    # Should redirect to the application page with ?newpreapp=true
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)
    assert "tutor-section/application" in page.url, (
        f"Registration did not redirect to application page -- got: {page.url}"
    )

    print(f"\n[result] registration redirect: {page.url}")
    write_detail("test_tutor_registration_submits", {
        "message": f"Registration submitted and redirected to {page.url}",
    })


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Pre-applicant -- application page sections
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

@pytest.mark.recruitment
def test_preapplicant_application_page_loads(
    page: Page, base_url: str, api_key: str, preapplicant_credentials
):
    """
    A logged-in pre-applicant visiting /tutor-section/application/ sees the
    application form with its section tab-panes (#personalDetails,
    #supportingDocuments, #references).
    Covers: 'Pre-applicant application page loads with correct sections visible'.
    """
    # Log in as the test pre-applicant account
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(preapplicant_credentials["email"])
    page.locator("#pw1").fill(preapplicant_credentials["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    # Pre-applicants are redirected to /tutor-section/application/
    page.wait_for_url(
        re.compile(r".*/tutor-section/application/"), timeout=30000
    )

    page.goto(f"{base_url}{APPLICATION_URL}")

    # Personal details section should be visible (first tab-pane, active by default)
    expect(page.locator("#personalDetails")).to_be_visible()
    expect(page.locator("#personalDetailsForm")).to_be_visible()

    # Other tab panes exist in the DOM (may be hidden but should be present)
    assert page.locator("#supportingDocuments").count() > 0, (
        "#supportingDocuments tab pane not found in DOM"
    )
    assert page.locator("#references").count() > 0, (
        "#references tab pane not found in DOM"
    )

    write_detail("test_preapplicant_application_page_loads", {
        "message": "Pre-applicant application page loaded with form sections present",
    })


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Full application flow
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€


@pytest.mark.recruitment
@pytest.mark.critical
def test_tutor_full_application_flow(page: Page, base_url: str, cleanup_after):
    """
    End-to-end tutor application flow:
      1. Register as new pre-applicant at /tutor-section/application/
      2. Fill all 9 form sections (personal details â†' interview booking)
      3. Submit application â†' user promoted to 'applicant'
      4. User deleted by cleanup endpoint (_ot_test_user=1)

    Emails suppressed: wp_mail and ot_sg_mail are skipped for _ot_test_user
    accounts (see pre-app-mgmt.php).
    """
    qts_pdf = str(FIXTURES_DIR / "test_qts.pdf")

    # Unique email per run to avoid conflicts if cleanup from a previous run failed
    run_id  = uuid.uuid4().hex[:8]
    email   = f"testbot.fullapp.{run_id}@owltutors.co.uk"
    password = "Owl1Tutor!Test2026"

    # â"€â"€ 1. Register â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    page.goto(f"{base_url}{APPLICATION_URL}")
    expect(page.locator("#signupform")).to_be_visible()
    page.locator("#email").fill(email)
    page.locator("#pw1").fill(password)
    _flag_test_user(page)
    page.evaluate("document.getElementById('signupform').submit()")
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)
    page.wait_for_load_state("networkidle")  # let JS init + smooth-scroll settle

    print(f"\n[recruit] registered: {email}")

    complete_application_form(page, base_url, qts_pdf)

    # After promotion the applicant form (app-form.php) renders — its h1 is unique
    # to the applicant role. The pre-applicant page title also contains "application"
    # so checking header.bg-navy h1 was a false positive; target the form h1 instead.
    expect(page.locator("div.applicationFormContainer h1")).to_contain_text(
        "application has been received", timeout=10000
    )

    print(f"\n[recruit] application submitted -- user promoted to applicant")

    write_detail("test_tutor_full_application_flow", {
        "message": "Full tutor application flow completed -- pre-applicant promoted to applicant",
    })


# ─────────────────────────────────────────────────────────────────────────────
# No-auth paths — P3/P4
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.recruitment
def test_logged_out_application_page_has_fields(page: Page, base_url: str):
    """
    A logged-out visitor on /tutor-section/application/ sees the registration
    form with email and password inputs ready to fill — verifies the complete
    form is functional, not just the wrapper element.
    Covers: 'Logged-out user visiting application page sees registration form'.
    """
    page.goto(f"{base_url}{APPLICATION_URL}")
    expect(page.locator("#signupform")).to_be_visible()
    expect(page.locator("#email")).to_be_visible()
    expect(page.locator("#pw1")).to_be_visible()
    # Submit button — rendered as <button type="button" id="applicant_register">
    # (JS intercepts the click to run reCAPTCHA before submitting)
    expect(page.locator("#applicant_register")).to_be_visible()

    write_detail("test_logged_out_application_page_has_fields", {
        "message": "Logged-out visitor sees registration form with email and password fields",
    })


@pytest.mark.recruitment
def test_email_already_registered_error(page: Page, base_url: str, preapplicant_credentials):
    """
    Submitting the registration form with an email address that already exists
    in WordPress shows the 'An account exists with this email address' error.
    Uses the preapplicant_credentials session fixture — that email is guaranteed
    to exist without needing a static TEST_CLIENT_EMAIL on every environment.
    On error, Login.php redirects back to the application page with
    ?register-errors=email_exists and renders <p class="logregpw error">.
    Covers: 'Email already registered error shown on registration form'.
    """
    existing_email = preapplicant_credentials["email"]

    page.goto(f"{base_url}{APPLICATION_URL}", wait_until="domcontentloaded")
    expect(page.locator("#signupform")).to_be_visible()
    page.locator("#email").fill(existing_email)
    page.locator("#pw1").fill("AnyPassword123!")
    page.evaluate("document.getElementById('signupform').submit()")

    # Login.php appends ?register-errors=email_exists and redirects to the referer
    # (the application page). The shortcode renders errors as <p class="logregpw error">.
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=15000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_selector("p.error, p.logregpw", timeout=10000)
    error_text = page.locator("p.error, p.logregpw").first.text_content() or ""
    assert "account exists" in error_text.lower() or "already" in error_text.lower(), (
        f"Expected duplicate-email error message, got: {error_text!r}"
    )

    write_detail("test_email_already_registered_error", {
        "message": "Duplicate email shows 'account exists' error on registration form",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch B — pre-applicant form navigation + applicant profile sections (P3)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.recruitment
def test_preapplicant_section_nav_forward_back(
    page: Page, base_url: str, api_key: str, preapplicant_credentials
):
    """
    The application form's 'Previous' button navigates back to the prior
    section without losing data already entered and saved.
    Flow: fill personalDetails → Save & continue (moves to supportingDocuments)
    → click Previous → verify first_names field still has the saved value.
    Uses preapplicant_credentials (session fixture, self-creating — no env vars).
    Covers: 'Form section nav (forward/back) without data loss'.
    """
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(preapplicant_credentials["email"])
    page.locator("#pw1").fill(preapplicant_credentials["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)

    page.goto(f"{base_url}{APPLICATION_URL}")
    _wait_for_section(page, "personalDetails")

    # Fill first name with a recognisable value
    test_name = "NavTest"
    name_input = page.locator("form#personalDetailsForm div[data-name='first_names'] input")
    name_input.fill(test_name)

    # Save & continue — moves to supportingDocuments
    _save_section(page, "personalDetails")
    _wait_for_section(page, "supportingDocuments")

    # Click Previous to go back.
    # Use the phase-2 pattern from _save_section: wait for the current section
    # to lose its .show class, which confirms the POST+redirect completed and
    # JS has re-run on the reloaded page. wait_for_load_state("networkidle") is
    # unreliable here (Heartbeat keeps the network busy and the timeout fires
    # before the page has settled, causing page.evaluate to race with a navigation).
    page.locator(
        "div#supportingDocuments form input[name='formDirection'][value='Previous']"
    ).click()
    try:
        page.wait_for_selector(
            "div#supportingDocuments.tab-pane.show",
            state="hidden",
            timeout=30000,
        )
    except Exception:
        pass
    _wait_for_section(page, "personalDetails")

    # The saved first name must still be present
    saved_value = page.locator(
        "form#personalDetailsForm div[data-name='first_names'] input"
    ).input_value()
    assert saved_value == test_name, (
        f"Expected first_names='{test_name}' after back-navigation, got: {saved_value!r}"
    )

    write_detail("test_preapplicant_section_nav_forward_back", {
        "message": "Section nav: save → forward → back preserves personalDetails data",
    })


@pytest.mark.recruitment
def test_client_role_on_application_page(
    page: Page, base_url: str, returning_client_login
):
    """
    A logged-in client visiting /tutor-section/application/ does NOT see the
    tutor registration form — instead the plugin renders the role-correction
    template (includes/recruitment/client-to-preapplicant.php) which shows
    "Oops! … accidentally registered as a client" and a button to convert their
    account role to pre-applicant.
    Uses returning_client_login (conftest) — no static TEST_CLIENT_EMAIL/PASSWORD needed.
    Covers: 'Client user landing on application page sees role-correction message'.
    """
    # returning_client_login submitted the contact form and left the page logged in.
    # Navigate to the application page in the same authenticated browser session.
    page.goto(f"{base_url}{APPLICATION_URL}", wait_until="domcontentloaded")

    # The tutor registration form (#signupform) must NOT be visible — the plugin
    # detects the client role and renders client-to-preapplicant.php instead.
    expect(page.locator("#signupform")).to_be_hidden()

    # The role-correction template (client-to-preapplicant.php) contains:
    #   "accidentally registered as a client"
    # Verify this text is in the page so we know the client-facing correction
    # path is rendering, not the generic registration form.
    html = page.content()
    assert "accidentally registered as a client" in html.lower(), (
        f"Expected client role-correction message in page HTML. "
        f"URL: {page.url!r}. "
        f"entry-content: {(page.locator('.entry-content, article.page, main').first.inner_text() or '')[:400]!r}"
    )

    write_detail("test_client_role_on_application_page", {
        "message": "Logged-in client sees 'already signed in' on application page; registration form hidden",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch M — Pre-applicant availability form (P2)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.recruitment
def test_preapplicant_availability_tab_has_grid(
    page: Page, base_url: str, api_key: str, preapplicant_credentials
):
    """
    The availability section in the pre-applicant application form renders
    the [tutor_availability] shortcode: #tutor_availability_holder is present
    and #tutor-avail-grid contains slot buttons after JS initialisation.
    Forcing capacity=1 via JS evaluate (same technique as the tutor dashboard
    grid tests) ensures the hide_on_zero container is visible.
    Uses preapplicant_credentials (session fixture, self-creating — no env vars).
    Covers: 'Pre-applicant — availability tab has slot grid'.
    """
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(preapplicant_credentials["email"])
    page.locator("#pw1").fill(preapplicant_credentials["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)

    page.goto(f"{base_url}{APPLICATION_URL}")
    page.wait_for_load_state("networkidle")

    # PHP shows personalDetails for a fresh pre-applicant — force availability visible
    _show_section(page, "availability")
    page.wait_for_selector("#tutor_availability_holder", state="attached", timeout=10000)

    # Force capacity=1 so hide_on_zero wrapper is shown (same pattern as
    # test_tutor_availability_grid_renders in test_tutor_dashboard.py)
    page.evaluate("""
        () => {
            const input = document.getElementById('tutor_extra_capacity');
            if (!input || Number(input.value) > 0) return;
            input.value = '1';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)

    # Grid cells are built client-side by availability.vanilla.js from
    # #tutor-avail-initial-slots JSON injected by PHP
    page.wait_for_selector("button.tutor-avail-slot", timeout=10000)
    expect(page.locator("button.tutor-avail-slot").first).to_be_visible(timeout=5000)

    write_detail("test_preapplicant_availability_tab_has_grid", {
        "message": "Pre-applicant availability tab rendered slot grid",
    })


@pytest.mark.recruitment
def test_preapplicant_availability_save_and_persist(
    page: Page, base_url: str, api_key: str, preapplicant_credentials
):
    """
    Saving a slot via the tutor_availability_save AJAX action in the
    pre-applicant application form persists after a page reload.
    Slot [day=0, slot=16] is saved, the page reloaded, and the cell verified
    to have the is-on class (set by availability.vanilla.js from
    #tutor-avail-initial-slots server-side JSON on reload).
    Cleanup: re-saves an empty grid to restore state.
    Uses preapplicant_credentials (session fixture, self-creating — no env vars).
    Covers: 'Pre-applicant — availability save persists after reload'.
    """
    def _open_avail_grid():
        page.goto(f"{base_url}{APPLICATION_URL}")
        page.wait_for_load_state("networkidle")
        _show_section(page, "availability")
        page.wait_for_selector("#tutor_availability_holder", state="attached", timeout=10000)
        page.evaluate("""
            () => {
                const input = document.getElementById('tutor_extra_capacity');
                if (!input || Number(input.value) > 0) return;
                input.value = '1';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """)
        page.wait_for_selector("button.tutor-avail-slot", timeout=10000)

    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(preapplicant_credentials["email"])
    page.locator("#pw1").fill(preapplicant_credentials["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)

    _open_avail_grid()

    # Save slot [day=0, slot=16] via direct AJAX (same approach as full-flow test)
    save_result = page.evaluate(
        '() => new Promise((resolve, reject) => {'
        '    const avail = window.TutorAvail || {};'
        '    const fd = new FormData();'
        "    fd.append('action', 'tutor_availability_save');"
        "    fd.append('nonce', avail.nonce || '');"
        "    fd.append('tutor_id', String(avail.tutorId || ''));"
        "    fd.append('slots', JSON.stringify({'0': [16]}));"
        "    fd.append('extra_capacity', '0');"
        "    fd.append('timezone', avail.timezone || 'Europe/London');"
        "    fd.append('notes', '');"
        "    fd.append('date_free', '');"
        '    fetch(avail.ajaxUrl || "/wp-admin/admin-ajax.php", { method: "POST", body: fd })'
        '        .then(r => r.json())'
        '        .then(data => data.success ? resolve(data) : reject(data))'
        '        .catch(reject);'
        '})'
    )
    print(f"\n[avail-save] {save_result}")

    # Reload — PHP re-renders #tutor-avail-initial-slots with the saved slot
    _open_avail_grid()

    saved_cell = page.locator("button.tutor-avail-slot[data-d='0'][data-s='16']")
    expect(saved_cell).to_be_attached(timeout=5000)
    cell_class = saved_cell.get_attribute("class") or ""
    assert "is-on" in cell_class, (
        f"Slot [day=0, slot=16] expected is-on after save+reload, got class: {cell_class!r}"
    )

    write_detail("test_preapplicant_availability_save_and_persist", {
        "message": "Pre-applicant slot [day=0, slot=16] persisted with is-on after reload",
    })

    # Cleanup: re-save empty grid to leave the fixture account clean
    page.evaluate(
        '() => new Promise((resolve, reject) => {'
        '    const avail = window.TutorAvail || {};'
        '    const fd = new FormData();'
        "    fd.append('action', 'tutor_availability_save');"
        "    fd.append('nonce', avail.nonce || '');"
        "    fd.append('tutor_id', String(avail.tutorId || ''));"
        "    fd.append('slots', JSON.stringify({}));"
        "    fd.append('extra_capacity', '0');"
        "    fd.append('timezone', avail.timezone || 'Europe/London');"
        "    fd.append('notes', '');"
        "    fd.append('date_free', '');"
        '    fetch(avail.ajaxUrl || "/wp-admin/admin-ajax.php", { method: "POST", body: fd })'
        '        .then(r => r.json())'
        '        .then(data => resolve(data))'
        '        .catch(reject);'
        '})'
    )
    page.wait_for_timeout(300)


# ─────────────────────────────────────────────────────────────────────────────
# Batch A — Applicant dashboard (P2)
# ─────────────────────────────────────────────────────────────────────────────

def _login_as_applicant(page: Page, base_url: str, creds: dict, api_key: str):
    """Log in as the given applicant and land on /tutor-section/application/."""
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(creds["email"])
    page.locator("#pw1").fill(creds["password"])
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)
    page.goto(f"{base_url}{APPLICATION_URL}")
    page.wait_for_load_state("networkidle")


def _force_applicant_tab(page: Page, section_id: str):
    """Force an applicant dashboard tab pane visible via JS.

    The applicant form uses Bootstrap 3 (.active) not Bootstrap 4 (.show).
    Adding both classes ensures the tab is visible regardless of BS version.
    """
    page.evaluate(f"""
        () => {{
            document.querySelectorAll('.tab-pane').forEach(p => {{
                p.classList.remove('show', 'active');
            }});
            const target = document.getElementById('{section_id}');
            if (target) target.classList.add('show', 'active');
        }}
    """)
    page.wait_for_selector(f"#{{'{section_id}'}}:is(.show, .active)", timeout=5000)


@pytest.mark.recruitment
def test_applicant_dashboard_loads(page: Page, base_url: str, api_key: str, applicant_credentials):
    """
    A logged-in applicant visiting /tutor-section/application/ sees the
    applicant dashboard: main wrapper (#tutorFormBox), the Stage 1 confirmed
    well, and all expected section wells in the DOM.
    Covers: 'Applicant dashboard loads with section tabs'.
    """
    _login_as_applicant(page, base_url, applicant_credentials, api_key)

    expect(page.locator("#tutorFormBox")).to_be_visible()
    # Two h1s on the page (theme header + form h1) — target the form's h1 specifically
    # to avoid Playwright strict mode violation.
    expect(page.locator("div.applicationFormContainer h1")).to_contain_text(
        "application has been received", timeout=5000
    )

    # Stage 1 confirmed as completed
    stage1_well = page.locator("div.well.completed.full_width")
    expect(stage1_well).to_be_visible()
    expect(stage1_well).to_contain_text("Stage 1 - Application")

    # All expected section wells in the DOM
    for section in ["supporting_documents", "profile", "profile_picture", "references", "availability"]:
        assert page.locator(f"div.well[value='{section}']").count() > 0, (
            f"Section well '{section}' not found in applicant dashboard"
        )

    write_detail("test_applicant_dashboard_loads", {
        "message": "Applicant dashboard loaded: Stage 1 confirmed, all section wells present",
    })


@pytest.mark.recruitment
def test_applicant_completion_scores(page: Page, base_url: str, api_key: str, applicant_credentials):
    """
    Section wells show correct status for a fresh applicant:
    - Stage 1 is under review (app_approved=false for a new submission)
    - Supporting docs, profile text, profile photo: notstarted (not filled yet)
    - Availability: completed (slots were saved during the pre-applicant form)
    Covers: 'Document completion scores show correct icons'.
    """
    _login_as_applicant(page, base_url, applicant_credentials, api_key)

    # Stage 1: under review, not yet approved
    expect(page.locator("span.status_text.review")).to_be_visible()

    # Sections not yet started by a fresh applicant
    for section in ["supporting_documents", "profile", "profile_picture"]:
        assert page.locator(f"div.well.notstarted[value='{section}']").count() > 0, (
            f"Expected well[value='{section}'] to be 'notstarted' for fresh applicant"
        )

    # Availability was filled during the pre-applicant application form
    assert page.locator("div.well.completed[value='availability']").count() > 0, (
        "Expected availability well to be 'completed' — slots were saved during pre-applicant form"
    )

    write_detail("test_applicant_completion_scores", {
        "message": "Completion scores: docs/profile/photo=notstarted, availability=completed, Stage 1=under review",
    })


@pytest.mark.recruitment
def test_applicant_references_not_sent(page: Page, base_url: str, api_key: str, applicant_credentials):
    """
    The references tab in the applicant dashboard shows 'We haven't sent your
    references out yet' when no reference CPT records exist for this user.
    The .ot_reference_table is absent because $references_made=false.
    Covers: '"References not yet sent" message when CPTs do not exist'.
    """
    _login_as_applicant(page, base_url, applicant_credentials, api_key)

    # Navigate to references tab
    page.evaluate("""
        () => {
            document.querySelectorAll('.tab-pane').forEach(p => {
                p.classList.remove('show', 'active');
            });
            const ref = document.getElementById('references');
            if (ref) ref.classList.add('show', 'active');
        }
    """)
    page.wait_for_selector("#references.active, #references.show", timeout=5000)

    ref_heading = page.locator("#references h3")
    expect(ref_heading).to_contain_text("haven't sent your references out yet", timeout=5000)

    assert page.locator(".ot_reference_table").count() == 0, (
        "Expected no .ot_reference_table when reference CPTs do not exist"
    )

    write_detail("test_applicant_references_not_sent", {
        "message": "References tab shows 'not sent yet' message; no reference table present",
    })


@pytest.mark.recruitment
def test_applicant_availability_tab_has_grid(
    page: Page, base_url: str, api_key: str, applicant_credentials
):
    """
    The availability section in the applicant dashboard renders the
    [tutor_availability] shortcode with slot buttons present after JS init.
    Covers: 'Applicant — availability tab has slot grid'.
    """
    _login_as_applicant(page, base_url, applicant_credentials, api_key)

    page.evaluate("""
        () => {
            document.querySelectorAll('.tab-pane').forEach(p => {
                p.classList.remove('show', 'active');
            });
            const avail = document.getElementById('availability');
            if (avail) avail.classList.add('show', 'active');
        }
    """)
    page.wait_for_selector("#tutor_availability_holder", state="attached", timeout=10000)

    # Force capacity=1 so hide_on_zero wrapper is shown
    page.evaluate("""
        () => {
            const input = document.getElementById('tutor_extra_capacity');
            if (!input || Number(input.value) > 0) return;
            input.value = '1';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """)

    page.wait_for_selector("button.tutor-avail-slot", timeout=10000)
    expect(page.locator("button.tutor-avail-slot").first).to_be_visible(timeout=5000)

    write_detail("test_applicant_availability_tab_has_grid", {
        "message": "Applicant availability tab rendered slot grid",
    })


@pytest.mark.recruitment
def test_applicant_availability_save_and_persist(
    page: Page, base_url: str, api_key: str, applicant_credentials
):
    """
    Saving a slot via tutor_availability_save AJAX in the applicant dashboard
    persists after a page reload (is-on class on the saved cell).
    Cleanup: restores the original slot set by the applicant_credentials fixture.
    Covers: 'Applicant — availability save persists after reload'.
    """
    def _open_avail_grid():
        page.goto(f"{base_url}{APPLICATION_URL}")
        page.wait_for_load_state("networkidle")
        page.evaluate("""
            () => {
                document.querySelectorAll('.tab-pane').forEach(p => {
                    p.classList.remove('show', 'active');
                });
                const avail = document.getElementById('availability');
                if (avail) avail.classList.add('show', 'active');
            }
        """)
        page.wait_for_selector("#tutor_availability_holder", state="attached", timeout=10000)
        page.evaluate("""
            () => {
                const input = document.getElementById('tutor_extra_capacity');
                if (!input || Number(input.value) > 0) return;
                input.value = '1';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """)
        page.wait_for_selector("button.tutor-avail-slot", timeout=10000)

    def _save_slots(slots_json: str):
        return page.evaluate(
            '() => new Promise((resolve, reject) => {'
            '    const avail = window.TutorAvail || {};'
            '    const fd = new FormData();'
            "    fd.append('action', 'tutor_availability_save');"
            "    fd.append('nonce', avail.nonce || '');"
            "    fd.append('tutor_id', String(avail.tutorId || ''));"
            f"    fd.append('slots', '{slots_json}');"
            "    fd.append('extra_capacity', '0');"
            "    fd.append('timezone', avail.timezone || 'Europe/London');"
            "    fd.append('notes', '');"
            "    fd.append('date_free', '');"
            '    fetch(avail.ajaxUrl || "/wp-admin/admin-ajax.php", { method: "POST", body: fd })'
            '        .then(r => r.json())'
            '        .then(data => data.success ? resolve(data) : reject(data))'
            '        .catch(reject);'
            '})'
        )

    _login_as_applicant(page, base_url, applicant_credentials, api_key)
    _open_avail_grid()

    # Save a distinct slot so it doesn't overlap the fixture's slot [day=0, slot=16]
    save_result = _save_slots('{"1": [10]}')
    print(f"\n[applicant-avail-save] {save_result}")

    _open_avail_grid()

    saved_cell = page.locator("button.tutor-avail-slot[data-d='1'][data-s='10']")
    expect(saved_cell).to_be_attached(timeout=5000)
    cell_class = saved_cell.get_attribute("class") or ""
    assert "is-on" in cell_class, (
        f"Slot [day=1, slot=10] expected is-on after save+reload, got class: {cell_class!r}"
    )

    # Cleanup: restore to the slot the fixture originally set
    _save_slots('{"0": [16]}')
    page.wait_for_timeout(300)


# ── References (single-reference.php) ────────────────────────────────────────
# A separate feature from tutor applicant references shown on the applicant
# dashboard (test_applicant_references_not_sent) — this is the actual external
# reference-provider form. No crc32 URL validation here (unlike testimonials);
# gated purely by the reference_status field.

@pytest.mark.recruitment
def test_reference_form_loads_for_incomplete(page: Page, base_url: str, api_key: str):
    """
    The reference form (single-reference.php) loads and shows the ACF
    competency form for an Incomplete reference record. Uses a real record
    from the local pool of 1,188+ Incomplete references (production-synced)
    via owl_get_test_status_record — no dev-site setup needed.
    Covers: 'Reference form loads at /reference/{id}-1/ for Incomplete status'.
    """
    record = get_test_status_record(base_url, api_key, "reference", "Incomplete")

    page.goto(record["url"], wait_until="domcontentloaded")

    assert page.url.rstrip("/") == record["url"].rstrip("/"), (
        f"Expected to stay on the reference page, got redirected to: {page.url}"
    )
    expect(page.locator("h1")).to_contain_text("Owl Tutors Reference request")
    expect(page.locator("form#acf-form")).to_be_visible()

    write_detail("test_reference_form_loads_for_incomplete", {
        "message": f"Reference {record['post_id']} form loaded correctly",
    })


@pytest.mark.recruitment
def test_reference_revisiting_submitted_url_redirects_away(page: Page, base_url: str, api_key: str):
    """
    Revisiting a Submitted (or Reviewed) reference's URL redirects away
    (single-reference.php redirects to https://owltutors.co.uk/ via a plain
    JS location change once reference_status is no longer Incomplete) rather
    than showing the form again — a single-use link.
    Covers: 'Revisiting a submitted reference URL redirects away'.
    """
    record = get_test_status_record(base_url, api_key, "reference", "Submitted")
    reference_path = record["url"].split("owltutors.test", 1)[-1].rstrip("/")

    page.goto(record["url"], wait_until="domcontentloaded")
    # The redirect is a plain client-side `window.location.href` change
    # (single-reference.php), not a server-side Location header — wait for
    # the URL to actually change rather than expecting navigation during goto().
    page.wait_for_url(lambda url: reference_path not in url, timeout=15000)

    assert reference_path not in page.url, (
        f"Expected navigation away from the reference page, still on: {page.url}"
    )

    write_detail("test_reference_revisiting_submitted_url_redirects_away", {
        "message": f"Submitted reference {record['post_id']} correctly redirected away to {page.url}",
    })


@pytest.mark.recruitment
def test_reference_form_submission_sets_submitted(page: Page, base_url: str, api_key: str):
    """
    Submitting the reference form (required fields: referee first/last name +
    6 competency ratings) triggers ot_save_references_on_front_end()
    (acf/save_post priority 20, reference-mgmt.php), which sets
    reference_status=Submitted and is_reference_ready=1. There is no distinct
    "thank you" page — the page simply reloads, re-evaluates reference_status,
    and (now Submitted) immediately JS-redirects away exactly like revisiting
    an already-submitted reference, so that redirect is the success signal.

    Uses a real Incomplete reference from the local pool; resets it back to
    Incomplete afterward via owl_reset_status_field so repeated local runs
    don't deplete the pool. Does not reverse the referee name/competency
    field values the submission also wrote (accepted side effect).
    Covers: 'Reference form submission sets reference_status=Submitted'.
    """
    record = get_test_status_record(base_url, api_key, "reference", "Incomplete")
    reference_path = record["url"].split("owltutors.test", 1)[-1].rstrip("/")
    group = "acf-field_59f8bbaa75a0e"

    try:
        page.goto(record["url"], wait_until="domcontentloaded")
        expect(page.locator("form#acf-form")).to_be_visible()

        page.locator(f"#{group}-field_59f8bbb275a0f-field_59f8bbc275a10").fill("Automated")
        page.locator(f"#{group}-field_59f8bbb275a0f-field_59f8bbc675a11").fill("Test Referee")

        for field_id in [
            "field_59f8bc0575a18",  # interaction
            "field_59f8bc1775a19",  # knowledge
            "field_59f8bc3175a1b",  # planning_and_organising
            "field_59f8bc4175a1d",  # teaching_ability
            "field_59f99f7b49f82",  # problem_solving
            "field_59f99f8c49f83",  # integrity
        ]:
            page.locator(f"#{group}-field_59f8bbf775a17-{field_id}").select_option(index=1)

        page.locator("button:has-text('Submit reference')").click()

        # Same redirect-away behaviour as revisiting an already-Submitted reference.
        page.wait_for_url(lambda url: reference_path not in url, timeout=20000)
        assert reference_path not in page.url, (
            f"Expected navigation away after submission, still on: {page.url}"
        )
    finally:
        reset_status_field(base_url, api_key, record["post_id"], "reference_status", "Incomplete")

    write_detail("test_reference_form_submission_sets_submitted", {
        "message": f"Reference {record['post_id']} submitted successfully, reset back to Incomplete",
    })


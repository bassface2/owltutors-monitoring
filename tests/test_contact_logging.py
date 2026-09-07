"""
Tests for the Client/Tutor Contact Logging feature's entry points
(includes/job-mgmt.php, includes/metaboxes.php, includes/client-post-mgmt.php),
documented in docs/client-mgmt.md, docs/metaboxes.md, and
docs/client-post-mgmt.md. Requires a real staff (administrator/owl-role)
session — see admin_credentials in conftest.py.

Not yet covered here: the legacy tutor-list quick-add form
(ot_inline_tutor_contact_add_callback() in tutor-mgmt.php) — a separate,
older code path with its own markup, needing its own investigation pass; see
docs/TESTING_SYSTEM.md's Tier 2 notes.
"""
import uuid
from playwright.sync_api import Page, expect
from utils.auth import auth_headers
from utils.create_test_job import create_test_job
from utils.get_test_contact_log_entries import get_test_contact_log_entries
from utils.wp_admin_login import login_wp_admin
from utils.cleanup import delete_test_posts
from utils.details import write_detail
import pytest
import requests


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


def _submit_contact_log_form(page: Page, container, notes: str):
    """Fill and submit the shared .contact_log_form inside the given
    container (a metabox or a jobs-list modal), then wait for it to switch
    to the History tab and show the new entry — see ot_admin.js's
    .submit_contact_log click handler."""
    container.locator(".contact_log_method").select_option(index=1)
    container.locator(".contact_log_notes").fill(notes)
    container.locator(".submit_contact_log").click()

    history_panel = container.locator('.job_contact_tab_content[data-tab="history"]')
    expect(history_panel).to_contain_text(notes, timeout=15000)


@pytest.mark.misc
def test_client_contact_log_modal_renders_in_job_edit_metabox(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, admin_credentials, cleanup_after
):
    """
    The 'Log client contact' metabox on the job edit screen actually renders
    the contact-log form (tabs + form fields), rather than being silently
    dropped — regression coverage for the documented nested-<form>-inside-
    WordPress's-own-form HTML5 parsing bug (docs/client-mgmt.md Known
    Issues), which previously deleted the whole modal with zero visible
    errors, only catchable by looking at the rendered page in a real
    browser.
    """
    job = create_test_job(base_url, api_key, stage=3, tutor_id=meet_now_tutor_id)
    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)

    page.goto(f"{base_url}/wp-admin/post.php?post={job['job_id']}&action=edit", wait_until="domcontentloaded")

    metabox = page.locator("#job_meta_box_client_contact_log")
    expect(metabox).to_be_visible(timeout=15000)
    expect(metabox.locator(".contact_log_form")).to_have_count(1)
    expect(metabox.locator(".contact_log_method")).to_be_visible()
    expect(metabox.locator(".contact_log_notes")).to_be_visible()
    expect(metabox.locator(".submit_contact_log")).to_be_visible()

    write_detail("test_client_contact_log_modal_renders_in_job_edit_metabox", {
        "message": f"Client contact log metabox rendered correctly on job {job['job_id']} edit screen",
        "job_id": job["job_id"],
    })


@pytest.mark.misc
def test_tutor_contact_log_entry_via_job_edit_metabox(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, admin_credentials, cleanup_after
):
    """
    Staff can add a tutor contact-log entry from the 'Log tutor contact'
    metabox on a Stage 4 job's edit screen, and the entry shows up in the
    History tab immediately after submitting — exercises the AJAX path
    (ot_job_contact_log_add_callback('tutor')) end to end, distinct from
    the native user-edit.php ACF-repeater save path.
    """
    job = create_test_job(base_url, api_key, stage=4, tutor_id=meet_now_tutor_id)
    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)

    page.goto(f"{base_url}/wp-admin/post.php?post={job['job_id']}&action=edit", wait_until="domcontentloaded")

    metabox = page.locator("#job_meta_box_tutor_contact_log")
    expect(metabox).to_be_visible(timeout=15000)

    notes = f"Automated tutor contact log test {uuid.uuid4().hex[:8]}"
    _submit_contact_log_form(page, metabox, notes)

    write_detail("test_tutor_contact_log_entry_via_job_edit_metabox", {
        "message": f"Tutor contact log entry added and confirmed in History tab on job {job['job_id']}",
        "job_id": job["job_id"],
    })


@pytest.mark.misc
def test_client_contact_log_entry_via_jobs_list(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, admin_credentials, cleanup_after
):
    """
    Staff can add a client contact-log entry from the inline modal opened
    via the 'Log contact' button on the jobs admin list screen
    (edit.php?post_type=jobs) — the second of the feature's three
    documented entry points, sharing the same underlying form/AJAX action
    as the job-edit metabox but opened from a different admin screen.

    Sorted by ID descending so the just-created job (highest ID in the
    system) is on page 1 without needing to search/paginate.
    """
    job = create_test_job(base_url, api_key, stage=3, tutor_id=meet_now_tutor_id)
    job_id = job["job_id"]
    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)

    page.goto(
        f"{base_url}/wp-admin/edit.php?post_type=jobs&orderby=ID&order=desc",
        wait_until="domcontentloaded",
    )

    trigger_btn = page.locator(f'.show_job_contact_log[value="{job_id}"][data-type="job_contact_log"]')
    expect(trigger_btn).to_be_visible(timeout=15000)
    trigger_btn.click()

    modal = page.locator(f'.admin_inline_modal[value="{job_id}"][data-type="job_contact_log"]')
    expect(modal).to_be_visible(timeout=5000)

    notes = f"Automated jobs-list contact log test {uuid.uuid4().hex[:8]}"
    _submit_contact_log_form(page, modal, notes)

    write_detail("test_client_contact_log_entry_via_jobs_list", {
        "message": f"Client contact log entry added via jobs-list modal and confirmed for job {job_id}",
        "job_id": job_id,
    })


def _add_native_contact_log_row(page: Page, tab_field_key: str, repeater_field_key: str, notes: str):
    """
    Adds one row to the native ACF Contact repeater on a user-edit.php
    screen (docs/client-post-mgmt.md Part 2) and saves via the real
    'Update User' form submit -- a meaningfully different interaction shape
    from the AJAX job-screen forms above: the whole Contact section starts
    hidden inside an ACF tab (only revealed by clicking its tab button), and
    "Add Row" clones a template row (data-id="acfcloneindex") into a new
    real one via ACF's own JS, entirely client-side (no AJAX for this step).

    Deliberately leaves the Date field untouched -- owl_crm_contact_repeater_after_save()
    (client-post-mgmt.php) only checks whether the submitted row COUNT grew,
    never validates individual field values, so a filled date isn't needed
    to prove a new row was genuinely persisted. Also deliberately skips the
    Author field: it's a real, user-selectable Select2 AJAX picker here
    (unlike the job-screen forms, which resolve the author server-side) --
    exactly the difference docs/TESTING_SYSTEM.md flagged as needing this
    investigation before writing this test -- and author is optional for
    the save logic above, so there's nothing to gain from driving it here.
    """
    # ACF renders each tab trigger twice (a secondary jump-nav list at the top
    # of the tab group, plus the inline anchor in the tab's own row) -- both
    # do the same thing, so .first is enough.
    tab_button = page.locator(f"a.acf-tab-button[data-key='{tab_field_key}']").first
    tab_button.click()

    repeater = page.locator(f"tr.acf-field-repeater[data-key='{repeater_field_key}']")
    expect(repeater).to_be_visible(timeout=10000)

    repeater.locator("a.acf-repeater-add-row").click()
    new_row = repeater.locator("tr.acf-row:not(.acf-clone)").last
    expect(new_row).to_be_visible(timeout=5000)

    new_row.locator("td[data-name='method'] select").select_option(index=1)
    new_row.locator("td[data-name='notes'] textarea").fill(notes)

    # user-edit.php redirects back to the SAME URL after saving, so there's
    # no URL change to wait on -- plain wait_for_load_state() after the click
    # can resolve against the pre-save page if navigation hasn't started yet
    # by the time the wait begins (found 2 Sept 2026: the row was genuinely
    # persisted server-side every time, confirmed by querying it directly
    # moments later, but a read immediately after this call sometimes still
    # saw the pre-save state). expect_navigation() blocks until the actual
    # navigation event fires, regardless of URL.
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator("#submit").click()


@pytest.mark.misc
def test_client_contact_log_entry_via_user_profile(
    page: Page, base_url: str, api_key: str, admin_credentials, cleanup_after
):
    """
    Staff can add a client contact-log entry via the native ACF repeater on
    the client's own user-edit.php profile screen -- the third of the
    feature's three documented entry points, and the one previously left
    'investigated, not written' (docs/TESTING_SYSTEM.md) because it needed
    the real admin screen inspected first: unlike the AJAX job-screen forms
    (test_client_contact_log_entry_via_jobs_list etc.), this is ACF's own
    default repeater UI reached through a hidden tab, with a real
    user-selectable Author field.

    Uses a fresh disposable client (owl_create_test_client) rather than a
    shared fixture, so the new entry can be asserted as the ONLY entry
    rather than needing to diff against a pre-existing count.
    """
    resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_client", "api_key": api_key},
        headers=auth_headers(base_url),
        timeout=15,
    )
    resp.raise_for_status()
    client = resp.json()
    assert client.get("success"), f"owl_create_test_client failed: {client}"
    client_id = client["client_id"]

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    page.goto(f"{base_url}/wp-admin/user-edit.php?user_id={client_id}", wait_until="domcontentloaded")

    notes = f"Automated native-profile client contact log test {uuid.uuid4().hex[:8]}"
    # Client Contact tab field key — ot_contact_log_entity_config()['client'] (job-mgmt.php)
    _add_native_contact_log_row(
        page,
        tab_field_key="field_635a4c1b24273",
        repeater_field_key="field_627936bbc90f9",
        notes=notes,
    )

    fields = get_test_contact_log_entries(base_url, api_key, "client", client_id)
    assert fields["count"] == 1, (
        f"Expected exactly 1 contact log entry on fresh disposable client {client_id}, got {fields}"
    )
    assert fields["entries"][0]["notes"] == notes, (
        f"Persisted entry's notes don't match what was submitted: {fields['entries'][0]}"
    )

    write_detail("test_client_contact_log_entry_via_user_profile", {
        "message": f"Native-profile contact log entry persisted for client {client_id}",
        "client_id": client_id,
    })


@pytest.mark.misc
def test_tutor_contact_log_entry_via_user_profile(
    page: Page, base_url: str, api_key: str, tutor_credentials, meet_now_tutor_id, admin_credentials
):
    """
    Mirrors test_client_contact_log_entry_via_user_profile but for a tutor's
    user-edit.php profile — confirms ot_contact_log_entity_config() resolves
    correctly for the 'tutor' entity type (different field keys, no
    freshness_field), not just 'client'.

    Uses the shared, permanent test tutor (meet_now_tutor_id) rather than a
    disposable account — a usable test tutor needs real ACF profile data
    that a bare owl_create_test_client-style endpoint doesn't set up (see
    docs/TESTING_SYSTEM.md Test Accounts) — so this reads the entry count
    before and after, rather than asserting count == 1, since the shared
    account already accumulates real contact history across runs.
    """
    tutor_id = meet_now_tutor_id
    before = get_test_contact_log_entries(base_url, api_key, "tutor", tutor_id)
    before_count = before["count"]

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    page.goto(f"{base_url}/wp-admin/user-edit.php?user_id={tutor_id}", wait_until="domcontentloaded")

    notes = f"Automated native-profile tutor contact log test {uuid.uuid4().hex[:8]}"
    # Tutor Contact tab field key — ot_contact_log_entity_config()['tutor'] (job-mgmt.php)
    _add_native_contact_log_row(
        page,
        tab_field_key="field_635a4a66310b4",
        repeater_field_key="field_635a4a8d310b6",
        notes=notes,
    )

    after = get_test_contact_log_entries(base_url, api_key, "tutor", tutor_id)
    assert after["count"] == before_count + 1, (
        f"Expected contact log entry count to grow by exactly 1 for tutor {tutor_id} "
        f"(was {before_count}), got {after}"
    )
    assert after["entries"][-1]["notes"] == notes, (
        f"Newest persisted entry's notes don't match what was submitted: {after['entries'][-1]}"
    )

    write_detail("test_tutor_contact_log_entry_via_user_profile", {
        "message": f"Native-profile contact log entry persisted for tutor {tutor_id} ({before_count} -> {after['count']})",
        "tutor_id": tutor_id,
    })


@pytest.mark.misc
def test_tutor_contact_log_entry_via_tutor_list(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, tutor_credentials, admin_credentials
):
    """
    Staff can add a tutor contact-log entry from the 'Last contact' column
    quick-add form on the tutor admin list (/wp-admin/users.php?role=tutor)
    -- confirmed 1 Sept 2026 (docs/TESTING_SYSTEM.md) to be a genuinely
    separate, legacy code path (ot_inline_tutor_contact_add_callback() in
    tutor-mgmt.php) from the other five Contact Logging entry points, using
    a plain per-row inline form rather than ACF's tab/repeater UI or the
    shared job-screen AJAX markup.

    Found and fixed two real bugs while writing this (docs/client-mgmt.md
    Known Issues) -- the button was completely non-functional before today:
    js/ot_admin.js's click handler still queried a "Owl user" <select> the
    PHP markup had already stopped rendering (author is resolved server-side
    now), so .value on the resulting null threw before the AJAX call could
    ever fire; separately, the AJAX payload never included the nonce the
    callback requires. Both fixed directly rather than worked around, since
    a test that only exercises a broken button isn't real coverage.

    Writes to the same field key (field_635a4a8d310b6) the native-profile
    test above does, so this reuses the same before/after count pattern
    against the shared, accumulating tutor fixture.
    """
    tutor_id = meet_now_tutor_id
    before = get_test_contact_log_entries(base_url, api_key, "tutor", tutor_id)
    before_count = before["count"]

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    # Search rather than a bare role listing -- the tutor role list runs to
    # thousands of rows (real, synced production accounts), well past the
    # default per-page pagination, so the fixture tutor's row is very
    # unlikely to be on page 1 without narrowing it down.
    page.goto(
        f"{base_url}/wp-admin/users.php?role=tutor&s={tutor_credentials['email']}",
        wait_until="domcontentloaded",
    )

    date_input = page.locator(f"#tutor_contact_date{tutor_id}")
    expect(date_input).to_be_visible(timeout=15000)
    date_input.fill("2026-09-02")
    page.locator(f"#tutor_contact_method{tutor_id}").select_option(index=1)
    notes = f"Automated tutor-list contact log test {uuid.uuid4().hex[:8]}"
    page.locator(f"#tutor_contact_notes{tutor_id}").fill(notes)

    # The button's onclick="return confirm(...)" -- Playwright dismisses
    # native dialogs by default, which would silently abort the click.
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(lambda r: "admin-ajax.php" in r.url and r.request.method == "POST"):
        page.locator(f"button.update_tutor_contact_inline[value='{tutor_id}']").click()

    after = get_test_contact_log_entries(base_url, api_key, "tutor", tutor_id)
    assert after["count"] == before_count + 1, (
        f"Expected contact log entry count to grow by exactly 1 for tutor {tutor_id} "
        f"(was {before_count}), got {after}"
    )
    assert after["entries"][-1]["notes"] == notes, (
        f"Newest persisted entry's notes don't match what was submitted: {after['entries'][-1]}"
    )

    write_detail("test_tutor_contact_log_entry_via_tutor_list", {
        "message": f"Tutor-list contact log entry persisted for tutor {tutor_id} ({before_count} -> {after['count']})",
        "tutor_id": tutor_id,
    })

"""
Tests for admin-only job-screen metaboxes that need a real staff
(administrator/owl-role) session — see admin_credentials in conftest.py.
Documented in docs/metaboxes.md.
"""
from playwright.sync_api import Page, expect
from utils.create_test_job import create_test_job
from utils.create_test_legacy_client_fixture import create_test_legacy_client_fixture
from utils.get_test_job_fields import get_test_job_fields
from utils.schedule_test_event import schedule_test_event
from utils.wp_admin_login import login_wp_admin
from utils.cleanup import delete_test_posts
from utils.details import write_detail
import json
import pytest


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


@pytest.mark.misc
def test_job_scheduled_events_metabox_reschedule_and_unschedule(
    page: Page, base_url: str, api_key: str, meet_now_tutor_id, admin_credentials, cleanup_after
):
    """
    The 'Job scheduled events' metabox (job_scheduled_events_metabox_content(),
    docs/metaboxes.md) lets staff reschedule or unschedule a pending
    wp_schedule_single_event() entry. One of the few admin tools in
    metaboxes.php with real state-changing behaviour and (already, before
    this test existed) correct nonce handling on both actions.

    Both actions are plain full-page form POSTs (not AJAX) guarded by a
    native browser confirm() dialog — Playwright's default is to dismiss
    dialogs, which would silently abort the submission, so both are
    explicitly accepted here.
    """
    job = create_test_job(base_url, api_key, stage=3, tutor_id=meet_now_tutor_id)
    job_id = job["job_id"]
    schedule_test_event(base_url, api_key, hook="ot_jobs_schedule_stage_1_more_info_1", post_id=job_id)

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    page.goto(f"{base_url}/wp-admin/post.php?post={job_id}&action=edit", wait_until="domcontentloaded")

    metabox = page.locator("#job_scheduled_events_metabox")
    expect(metabox).to_be_visible(timeout=15000)
    expect(metabox).to_contain_text("Stage 1 more info 1")

    # ── Reschedule ──────────────────────────────────────────────────────
    page.on("dialog", lambda dialog: dialog.accept())
    metabox.locator("input[name='new_timestamp']").fill("2099-01-01 00:00")
    metabox.locator("button[name='edit_scheduled_event_timestamp_submit']").click()
    page.wait_for_load_state("domcontentloaded")

    metabox = page.locator("#job_scheduled_events_metabox")
    expect(metabox).to_contain_text("has been rescheduled", timeout=15000)

    # ── Unschedule ──────────────────────────────────────────────────────
    metabox.locator("button[name='delete_event']").click()
    page.wait_for_load_state("domcontentloaded")

    metabox = page.locator("#job_scheduled_events_metabox")
    expect(metabox).to_contain_text("has been unscheduled", timeout=15000)
    expect(metabox).to_contain_text("No scheduled events found")

    write_detail("test_job_scheduled_events_metabox_reschedule_and_unschedule", {
        "message": f"Successfully rescheduled then unscheduled a test event on job {job_id}",
        "job_id": job_id,
    })


@pytest.mark.misc
def test_student_client_metabox_shows_correct_name_order(
    page: Page, base_url: str, api_key: str, admin_credentials, cleanup_after
):
    """
    Regression test for the swapped first/last-name assignment fixed 1 Sept
    2026 in students_related_client_metabox_content() (includes/student-mgmt.php,
    docs/student-mgmt.md Known Issues). The bug printed the client's surname
    before their first name ("Winters Testbot-Aldous" instead of
    "Testbot-Aldous Winters"); both the assignment and the print order were
    inverted so it didn't cancel out.

    Uses deliberately distinct, non-symmetric first/last names (the fixture's
    own default) so a swapped order can't accidentally read the same as the
    correct one.
    """
    fixture = create_test_legacy_client_fixture(base_url, api_key)
    student_id = fixture["student_id"]
    expected_name = f"{fixture['first_name']} {fixture['last_name']}"

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    page.goto(f"{base_url}/wp-admin/post.php?post={student_id}&action=edit", wait_until="domcontentloaded")

    metabox = page.locator("#student_meta_box_student_client")
    expect(metabox).to_be_visible(timeout=15000)
    expect(metabox).to_contain_text(expected_name)

    write_detail("test_student_client_metabox_shows_correct_name_order", {
        "message": f"Client metabox on student {student_id} correctly showed '{expected_name}'",
        "student_id": student_id,
    })


@pytest.mark.misc
def test_legacy_client_students_metabox_scoped_to_client(
    page: Page, base_url: str, api_key: str, admin_credentials, cleanup_after
):
    """
    Regression test for the duplicate-array-key query bug fixed 1 Sept 2026
    in jobs_clientrelated_students_metabox_content() (includes/client-post-mgmt.php,
    docs/client-post-mgmt.md Known Issues). A duplicate 'meta_value' key
    silently dropped 'meta_key' => 'client' entirely, so the query matched
    every job in the system rather than just this client's -- the Students
    metabox then listed every student in the database, not just this
    client's own.

    Creates two independent legacy client/student/job fixtures and confirms
    client A's Students metabox names A's own student but not B's -- the
    scoping the fix restores, not just "the metabox renders something".

    SKIPPED -- found 2 Sept 2026 while first running this test: a second,
    independent bug sits underneath the one this test targets. The 'students'
    field this metabox reads via get_field('students', 'post_' . $job->ID)->ID
    has no ACF field definition at all on the Jobs post type any more (only
    the modern 'student_id' field does) -- so ->ID silently returns null for
    EVERY client with a linked job, real or fixture, and the metabox always
    shows one fixed, unrelated student name instead of the correct one. Not a
    flake and not fixable by adjusting this test's fixture -- see
    docs/client-post-mgmt.md Known Issues for the full reproduction. Needs a
    real fix decision (read student_id instead? for all jobs or only
    post-migration ones?) before this can pass; unskip once that lands.
    """
    pytest.skip(
        "Blocked on a second, independent bug: 'students' has no ACF field "
        "definition on the Jobs post type any more, so the metabox always "
        "shows the wrong (fixed) student name regardless of client -- see "
        "docs/client-post-mgmt.md Known Issues, found 2 Sept 2026."
    )
    client_a = create_test_legacy_client_fixture(base_url, api_key, first_name="Testbot-Ambrose", last_name="Testbot-Quill")
    client_b = create_test_legacy_client_fixture(base_url, api_key, first_name="Testbot-Rosalind", last_name="Testbot-Pryce")

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    page.goto(f"{base_url}/wp-admin/post.php?post={client_a['client_id']}&action=edit", wait_until="domcontentloaded")

    metabox = page.locator("#job_meta_box_client_students")
    expect(metabox).to_be_visible(timeout=15000)

    own_student_name = client_a["first_name"] + " Jr."
    foreign_student_name = client_b["first_name"] + " Jr."
    expect(metabox).to_contain_text(own_student_name)
    assert foreign_student_name not in metabox.inner_text(), (
        f"Client A's Students metabox listed client B's student ({foreign_student_name!r}) — "
        f"the scoping query is matching every job in the system again, not just this client's"
    )

    write_detail("test_legacy_client_students_metabox_scoped_to_client", {
        "message": f"Client {client_a['client_id']}'s Students metabox correctly showed only its own student",
        "client_id": client_a["client_id"],
    })


@pytest.mark.jobs
def test_make_client_user_stores_client_id_as_array(
    page: Page, base_url: str, api_key: str, admin_credentials, cleanup_after
):
    """
    Regression coverage for the client_id scalar-vs-array write inconsistency
    (docs/job-creation.md, docs/functions-php-index.md) — confirms
    ot_make_client_user_callback() (includes/functions.php) now stores the
    job's client_id as [$user_id], matching every other write site (e.g.
    owl_create_test_job's own update_field('client_id', [$client_user->ID], ...)),
    rather than the bare scalar it wrote before the fix applied alongside
    this test.

    Triggers the real wp_ajax_ot_make_client_user action (no nonce on this
    endpoint, but it requires a logged-in session — hence admin_credentials)
    against a fixture job whose legacy 'client' field points at a client post
    with a fresh email address that has no WP user yet, so the callback takes
    its user-creation branch rather than its early-exit "already exists"
    branch.
    """
    fixture = create_test_legacy_client_fixture(base_url, api_key)
    job_id = fixture["job_id"]

    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)
    resp = page.request.get(f"{base_url}/wp-admin/admin-ajax.php?action=ot_make_client_user&job_id={job_id}")
    assert resp.ok, f"ot_make_client_user AJAX call failed: {resp.status}"
    # utf-8-sig, not resp.json(): at least one included file in this legacy
    # code path may carry a BOM (see owl_system/CLAUDE.md's File Encoding
    # warning), which breaks strict JSON parsing before real headers/output.
    body = json.loads(resp.body().decode("utf-8-sig"))
    assert not body.get("exists"), (
        f"Expected the fixture's fresh email to have no existing WP user yet (early-exit branch "
        f"skipped, so client_id was never written) — response: {body}"
    )

    fields = get_test_job_fields(base_url, api_key, job_id)
    assert fields["client_id_is_array"], (
        f"Expected job {job_id}'s client_id to be stored as a single-item array ([$user_id]), "
        f"matching every other write site, but it was stored as a bare scalar. Full fields: {fields}"
    )

    write_detail("test_make_client_user_stores_client_id_as_array", {
        "message": f"job {job_id}'s client_id was correctly stored as [$user_id] after ot_make_client_user",
        "job_id": job_id,
    })

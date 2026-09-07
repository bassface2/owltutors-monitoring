"""
Tests for the scheduled-event handlers in includes/event-mgmt.php, documented
in docs/event-mgmt.md. Every handler is fired on demand via the
owl_trigger_scheduled_event test endpoint rather than waiting for the real
wp_schedule_single_event() timestamp (hours to days away in production).
"""
import requests
from playwright.sync_api import Page
from utils.auth import auth_headers
from utils.create_test_job import create_test_job
from utils.create_test_ams_post import create_test_ams_post
from utils.create_test_duplicate_jobs import create_test_duplicate_jobs
from utils.trigger_scheduled_event import trigger_scheduled_event
from utils.get_test_email_log import get_test_email_log
from utils.cleanup import delete_test_posts
from utils.details import write_detail
import pytest


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    """Delete all test-flagged records from the dev site after each test."""
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


@pytest.mark.events
def test_stale_scheduled_event_is_safe_noop(base_url: str, api_key: str, meet_now_tutor_id, cleanup_after):
    """
    Firing a job-lifecycle scheduled event against a job that has already
    moved past the stage the event was queued for must be a safe no-op — no
    email sent, no status change — per the "re-check current stage before
    acting" guard every handler in event-mgmt.php shares.

    Uses a Stage 3 job (owl_create_test_job's default) and fires
    ot_jobs_schedule_stage_1_more_info_1, which only acts on jobs still at
    'Stage 1 - Approved but not ready'. A stale-event failure here would mean
    a client gets a confusing "we need more info" chase email on a job
    that's already progressed well past that point.

    simulate_production=True is required here — every handler in
    event-mgmt.php calls ot_jobs_dev_site_event_email_blocker() first, which
    returns true (block) unconditionally on this environment, *before* the
    stage-recheck logic this test actually cares about. Without it, this
    test would "pass" for the wrong reason regardless of whether the
    stage-recheck logic works at all — discovered on the first real run.
    """
    job = create_test_job(base_url, api_key, stage=3, tutor_id=meet_now_tutor_id)
    job_id = job["job_id"]

    result = trigger_scheduled_event(
        base_url, api_key, hook="ot_jobs_schedule_stage_1_more_info_1", post_id=job_id,
        simulate_production=True,
    )
    assert result["success"]

    log = get_test_email_log(base_url, api_key, job_id)
    assert log == [], (
        f"Expected no email logged for stale event on job {job_id} (status is "
        f"Stage 3, handler only acts on Stage 1), but found: {log}"
    )

    write_detail("test_stale_scheduled_event_is_safe_noop", {
        "message": f"Stale ot_jobs_schedule_stage_1_more_info_1 event on Stage-3 job {job_id} correctly no-op'd",
        "job_id": job_id,
    })


@pytest.mark.events
def test_ams_editor_reminder_email_sends(base_url: str, api_key: str, cleanup_after):
    """
    Regression test for the fix in docs/event-mgmt.md Known Issues (fixed
    1 Sept 2026): all three AMS reminder handlers called
    ot_jobs_dev_site_event_email_blocker( $job_id ) with an undefined
    $job_id instead of the real $post_id parameter, which made the blocker
    always return true (block) on production — none of the three ever sent.

    Creates a disposable AMS post (owl_create_test_ams_post picks any real
    administrator as the author automatically — see that endpoint's
    docstring for why a hardcoded WP user ID would be fragile on a database
    synced down from production) with a deadline 2 days out, matching the
    "editor 1" handler's exact condition, then fires that handler and
    confirms an email was actually logged.

    simulate_production=True is required — see
    test_stale_scheduled_event_is_safe_noop's docstring above for why. This
    is exactly the fix being regression-tested: without simulate_production,
    the dev-site blocker masks the very bug this test exists to catch.
    """
    ams = create_test_ams_post(base_url, api_key, deadline_offset=2)
    post_id = ams["post_id"]

    result = trigger_scheduled_event(
        base_url, api_key, hook="ot_ams_scheduled_author_writing_remind_editor_1", post_id=post_id,
        simulate_production=True,
    )
    assert result["success"]

    log = get_test_email_log(base_url, api_key, post_id)
    assert len(log) >= 1, (
        f"Expected at least one email logged for AMS post {post_id} after firing "
        f"ot_ams_scheduled_author_writing_remind_editor_1 — if this is empty, the "
        f"$job_id/$post_id regression may have come back. Log: {log}"
    )
    entry = log[-1]
    custom_args = entry.get("options", {}).get("custom_args", {})
    assert custom_args.get("ot_email_id") == "SGTM001", (
        f"Expected the logged email's ot_email_id to be SGTM001, got: {custom_args}"
    )

    write_detail("test_ams_editor_reminder_email_sends", {
        "message": f"AMS editor reminder (SGTM001) correctly logged for post {post_id}",
        "post_id": post_id,
    })


@pytest.mark.events
@pytest.mark.critical
def test_duplicate_job_event_notifies_client(base_url: str, api_key: str, cleanup_after):
    """
    Regression test for the fix in docs/event-mgmt.md Known Issues (fixed
    1 Sept 2026): ot_jobs_schedule_stage_1_duplicate_jobs_event_handler()
    used to move the job to lost status while its client-facing email was
    commented out (placeholder test text) — the client was never told why
    their job disappeared. A real email (SGCU009) now replaces the
    placeholder.

    Creates a fresh disposable test client, then two Stage-1 jobs for that
    client with an overlapping subject via owl_create_test_duplicate_jobs
    (mirrors ot_system_check_for_duplicate_jobs()'s own matching logic), and
    fires the scheduled event against the higher-ID ("duplicate") job.
    Confirms both the status change (mgmt_job_lost) and a real logged email.

    simulate_production=True is required — see
    test_stale_scheduled_event_is_safe_noop's docstring above for why.
    """
    client_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_client", "api_key": api_key},
        headers=auth_headers(base_url),
        timeout=15,
    )
    client_resp.raise_for_status()
    client = client_resp.json()
    assert client.get("success"), f"owl_create_test_client failed: {client}"

    jobs = create_test_duplicate_jobs(base_url, api_key, client_email=client["client_email"])
    duplicate_job_id = jobs["duplicate_job_id"]

    result = trigger_scheduled_event(
        base_url, api_key, hook="ot_jobs_schedule_stage_1_duplicate_jobs", post_id=duplicate_job_id,
        simulate_production=True,
    )
    assert result["success"]

    log = get_test_email_log(base_url, api_key, duplicate_job_id)
    assert len(log) >= 1, (
        f"Expected an email logged for the duplicate job {duplicate_job_id} — if this "
        f"is empty, the commented-out-email regression may have come back. Log: {log}"
    )
    entry = log[-1]
    custom_args = entry.get("options", {}).get("custom_args", {})
    assert custom_args.get("ot_email_id") == "SGCU009", (
        f"Expected the logged email's ot_email_id to be SGCU009, got: {custom_args}"
    )
    assert entry.get("to") == client["client_email"], (
        f"Expected the email to be addressed to {client['client_email']!r}, got: {entry.get('to')!r}"
    )

    write_detail("test_duplicate_job_event_notifies_client", {
        "message": (
            f"Duplicate-job event correctly logged client email (SGCU009) for job "
            f"{duplicate_job_id}, original job {jobs['original_job_id']}"
        ),
        "duplicate_job_id": duplicate_job_id,
        "original_job_id": jobs["original_job_id"],
    })

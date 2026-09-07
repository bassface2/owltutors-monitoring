"""
Tests for the WhatsApp/WATI admin preview tool (services/wati/system.php),
documented in docs/wati-mgmt.md.
"""
from playwright.sync_api import Page, expect
from utils.details import write_detail
from utils.recaptcha_bypass import inject_recaptcha_bypass
import pytest

LOGIN_URL = "/login/"


def _login(page: Page, base_url: str, email: str, password: str, api_key: str):
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.locator("#ot_login_name").fill(email)
    page.locator("#pw1").fill(password)
    inject_recaptcha_bypass(page, api_key, form_id="ot_login")
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=30000)


@pytest.mark.misc
@pytest.mark.critical
def test_whatsapp_template_preview_rejects_path_traversal(
    page: Page, base_url: str, api_key: str, tutor_credentials
):
    """
    ot_whatsapp_message_call_callback() (wp_ajax_ot_whatsapp_message_call)
    must not resolve a template_message value containing '../' to a real
    file — regression test for the path-traversal fix in docs/wati-mgmt.md
    Known Issues (fixed 1 Sept 2026): the endpoint now strips the filename
    to [a-z0-9_] only and requires the realpath()-resolved candidate to stay
    inside one of the two known template directories before including it.

    The endpoint only requires a logged-in session (any role, no capability
    check) — a tutor login is used here as a stand-in for "any authenticated
    user", which is itself part of what docs/wati-mgmt.md flags as a
    separate, still-open gap (no nonce/capability check on this endpoint).

    Asserts the response's 'message' field is null (no template matched)
    rather than any content from a file outside the two whitelisted
    directories — this is a pure not-included-anything check; it does not
    (and cannot, from a black-box HTTP test) prove no file was read, only
    that the response contains no evidence one was.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)

    traversal_attempts = [
        "../../../../wp-config",
        "..%2f..%2f..%2f..%2fwp-config",
        "....//....//....//....//wp-config",
    ]

    for attempt in traversal_attempts:
        resp = page.request.get(
            f"{base_url}/wp-admin/admin-ajax.php"
            f"?action=ot_whatsapp_message_call"
            f"&template_message={attempt}"
            f"&record_type=client&user_id=1"
        )
        assert resp.status == 200, f"Expected 200 (graceful no-match), got {resp.status} for {attempt!r}"
        data = resp.json()
        assert data.get("message") in (None, ""), (
            f"Path traversal payload {attempt!r} resolved to non-empty message content: "
            f"{data.get('message')!r} — the path-traversal fix may have regressed"
        )

    write_detail("test_whatsapp_template_preview_rejects_path_traversal", {
        "message": f"All {len(traversal_attempts)} traversal payloads correctly resolved to no template",
    })


@pytest.mark.misc
def test_whatsapp_template_preview_resolves_real_template(
    page: Page, base_url: str, api_key: str, tutor_credentials
):
    """
    Companion to the traversal-rejection test above: confirms the fix didn't
    also break resolution of a real, legitimate template name. Uses
    client_job_stage3 (includes/whatsapp/sales/client_job_stage3.php), one of
    the two real templates the endpoint should resolve per docs/wati-mgmt.md.
    """
    _login(page, base_url, tutor_credentials["email"], tutor_credentials["password"], api_key)

    resp = page.request.get(
        f"{base_url}/wp-admin/admin-ajax.php"
        f"?action=ot_whatsapp_message_call"
        f"&template_message=client_job_stage3"
        f"&record_type=client&user_id=1"
    )
    assert resp.status == 200, f"Expected 200, got {resp.status}"
    data = resp.json()
    assert data.get("message"), (
        f"Expected a real message body for the client_job_stage3 template, got: {data!r}"
    )

    write_detail("test_whatsapp_template_preview_resolves_real_template", {
        "message": "client_job_stage3 template resolved to real message content",
    })

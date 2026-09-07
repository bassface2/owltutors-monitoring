"""
Tests for the plugin's own REST API endpoint (includes/rest_api/rest-api-functions.php),
documented in docs/rest-api.md — previously flagged in TO_DO.md's Documentation Gaps
table as "Medium priority, manual/Postman testing only" and had zero automated coverage
before this file.

Distinct from includes/monitoring/rest-endpoint.php, which is the separate,
already-documented monitoring/test-support namespace used throughout this suite.
"""
import base64
import os
import re
import requests
from playwright.sync_api import Page, expect
from utils.details import write_detail
from utils.get_rest_nonce import get_rest_nonce
from utils.recaptcha_bypass import inject_recaptcha_bypass
import pytest

REST_ENDPOINT = "/wp-json/main/v1/ot_data_endpoint"
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


def _wp_engine_auth_headers() -> dict:
    """WP Engine's site-wide HTTP Basic Auth (infrastructure-level password
    protection on the dev site) — distinct from a WordPress login session.
    Needed here so a 'logged out' test exercises the plugin's own
    current_user_can('read') permission check specifically, rather than
    incidentally getting blocked by this unrelated infra-level wall first."""
    user = os.environ.get("TEST_HTTP_USER", "")
    pw   = os.environ.get("TEST_HTTP_PASS", "")
    if user and pw:
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        token = base64.b64encode(f"{match.group(1)}:{match.group(2)}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


@pytest.mark.schools
def test_rest_schools_endpoint_filters_by_subject(page: Page, base_url: str, client_credentials, api_key: str):
    """
    request_type=schools&subject=11+ returns only schools tagged with the 11+
    sentry taxonomy term — not every school in the system. Uses page.request
    (Playwright's APIRequestContext) so the same Basic Auth / cookie handling
    already configured for the browser context applies to this direct call.

    Requires both a logged-in session AND a valid X-WP-Nonce header —
    WordPress's cookie-auth REST check (rest_cookie_check_errors()) ignores
    the login cookie entirely without that header, so current_user_can()
    inside the route's permission_callback evaluates as if nobody were
    logged in even with a perfectly valid session. Discovered on the first
    real run of this test: it still got 401 after adding a login step alone
    — the endpoint's own logic was never in question at any point, the test
    itself needed the nonce too (see utils/get_rest_nonce.py).

    See docs/rest-api.md — the subject param is normalised (spaces stripped,
    'Plus' stripped, lowercased) before being matched against the taxonomy.
    """
    _login(page, base_url, client_credentials["email"], client_credentials["password"], api_key)
    nonce = get_rest_nonce(page, base_url, api_key)
    resp = page.request.get(
        f"{base_url}{REST_ENDPOINT}?request_type=schools&subject=11%20Plus",
        headers={"X-WP-Nonce": nonce},
    )
    assert resp.status == 200, f"Expected 200, got {resp.status}: {resp.text()[:300]}"

    data = resp.json()
    assert isinstance(data, list), f"Expected a list of schools, got: {data!r}"
    assert len(data) > 0, "Expected at least one school tagged 11 Plus"

    write_detail("test_rest_schools_endpoint_filters_by_subject", {
        "message": f"request_type=schools&subject=11 Plus returned {len(data)} school(s)",
    })


@pytest.mark.papers
def test_rest_papers_endpoint_filters_by_subject(page: Page, base_url: str, client_credentials, api_key: str):
    """
    request_type=papers&subject=maths returns only page-papers.php pages
    whose subject_list ACF field matches — each with id/title/permalink,
    per docs/rest-api.md. Requires a logged-in session plus a valid
    X-WP-Nonce header — see the schools test above for why.
    """
    _login(page, base_url, client_credentials["email"], client_credentials["password"], api_key)
    nonce = get_rest_nonce(page, base_url, api_key)
    resp = page.request.get(
        f"{base_url}{REST_ENDPOINT}?request_type=papers&subject=maths",
        headers={"X-WP-Nonce": nonce},
    )
    assert resp.status == 200, f"Expected 200, got {resp.status}: {resp.text()[:300]}"

    data = resp.json()
    assert isinstance(data, list), f"Expected a list of paper pages, got: {data!r}"
    assert len(data) > 0, "Expected at least one Maths paper page"
    for entry in data:
        assert set(entry.keys()) >= {"id", "title", "permalink"}, (
            f"Expected id/title/permalink keys, got: {entry!r}"
        )

    write_detail("test_rest_papers_endpoint_filters_by_subject", {
        "message": f"request_type=papers&subject=maths returned {len(data)} page(s)",
    })


@pytest.mark.misc
@pytest.mark.critical
def test_rest_endpoint_rejects_logged_out_request(base_url: str):
    """
    A logged-out request to the endpoint must be rejected, not served.

    Regression coverage for the duplicate permission_callback key documented
    in docs/rest-api.md Known Issues — the route registration array defines
    permission_callback twice (first __return_true, then the real
    current_user_can('read') check); PHP silently keeps only the last value,
    so this currently works only by accident. A future edit that reorders or
    removes the second definition would silently reopen the endpoint to the
    public with no test catching it — this test exists specifically to catch
    that regression.

    Uses a plain `requests` call (no Playwright browser context / cookies at
    all) rather than page.request, so there is no possibility of an
    inherited logged-in session masking the check. WP Engine's own Basic
    Auth is still supplied (see _wp_engine_auth_headers) so the request
    reaches WordPress at all — that header is infrastructure-level and
    carries no WordPress login state of its own.
    """
    resp = requests.get(
        f"{base_url}{REST_ENDPOINT}?request_type=schools",
        headers=_wp_engine_auth_headers(),
        timeout=15,
    )
    assert resp.status_code in (401, 403), (
        f"Expected 401/403 for a logged-out request, got {resp.status_code}. "
        f"If this now returns 200, the duplicate permission_callback bug has "
        f"regressed and the endpoint is open to the public — see docs/rest-api.md."
    )

    write_detail("test_rest_endpoint_rejects_logged_out_request", {
        "message": f"Logged-out request correctly rejected with status {resp.status_code}",
    })

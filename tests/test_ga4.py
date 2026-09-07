"""
GA4 / Analytics smoke tests.

The sessionStorage/dataLayer script in inc/header-DL.php runs on production
(owltutors.co.uk), staging (otdev1602) and local (owltutors.test) — loosened
27 Aug 2026 (owl_system docs/TESTING_CHANGELOG.md) once it was confirmed that
script is purely client-side (sessionStorage + a dataLayer push) with no
network call to Google of its own; the actual GTM container loader
(inc/header-GTM.php, the only thing that talks to Google) kept its
production-only gate, so nothing real analytics-related ever fires outside
production regardless of where these tests run.
"""
import pytest
from playwright.sync_api import Page, expect
from urllib.parse import urlparse
from utils.details import write_detail

HOMEPAGE_URL   = "/"
CONTACT_URL    = "/contact-us/"
_ALLOWED_DOMAIN_SUBSTRINGS = ("owltutors.co.uk", "otdev1602", "owltutors.test")


def _require_ga4_enabled_domain(base_url: str):
    """Skip this test if we're not running against an environment header-DL.php
    actually outputs the tracking script for."""
    if not any(d in base_url for d in _ALLOWED_DOMAIN_SUBSTRINGS):
        pytest.skip(
            f"GA4 tracking script is not output on this environment — "
            f"skipping against {base_url}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# sessionStorage keys set on first page load
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.analytics
def test_ga4_session_storage_set_on_load(page: Page, base_url: str):
    """
    On first page load, header-DL.php sets initial_url and traffic_source_r in
    sessionStorage (the ga_client_id key is only set if a _ga cookie is present,
    so that key is checked separately in test_ga4_client_id_in_contact_form).

    Covers: 'initial_url, traffic_source_r, ga_client_id in sessionStorage on load'.
    """
    _require_ga4_enabled_domain(base_url)

    # Fresh context — sessionStorage is empty on first navigation
    page.goto(f"{base_url}{HOMEPAGE_URL}")
    page.wait_for_load_state("domcontentloaded")

    initial_url = page.evaluate("sessionStorage.getItem('initial_url')")
    traffic_source = page.evaluate("sessionStorage.getItem('traffic_source_r')")

    assert initial_url, "sessionStorage['initial_url'] not set after first page load"
    assert traffic_source, "sessionStorage['traffic_source_r'] not set after first page load"
    assert any(d in initial_url for d in _ALLOWED_DOMAIN_SUBSTRINGS), (
        f"initial_url should be on a recognised owltutors domain, got: {initial_url!r}"
    )

    write_detail("test_ga4_session_storage_set_on_load", {
        "message": f"initial_url={initial_url!r}  traffic_source_r={traffic_source!r}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# ga_client_id hidden input on contact form
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.analytics
def test_ga4_client_id_in_contact_form(page: Page, base_url: str):
    """
    When a _ga cookie is present, header-DL.php parses it and stores the client
    ID in sessionStorage['ga_client_id'].  The contact form JS then copies this
    value into a hidden input so it is submitted with the job.

    This test injects a synthetic _ga cookie before navigating to the form, then
    checks the hidden input has a non-empty value.
    Covers: 'Contact form ga_client_id input non-empty when _ga cookie present'.
    """
    _require_ga4_enabled_domain(base_url)

    # Inject a synthetic _ga cookie matching the expected format: GA1.X.CID.TS
    # Domain must match the actual host being tested — owltutors.co.uk on
    # production, otdev1602... on staging, owltutors.test on local.
    page.context.add_cookies([{
        "name": "_ga",
        "value": "GA1.1.123456789.1700000000",
        "domain": urlparse(base_url).hostname,
        "path": "/",
    }])

    page.goto(f"{base_url}{CONTACT_URL}")
    page.wait_for_load_state("domcontentloaded")

    ga_client_id = page.evaluate("sessionStorage.getItem('ga_client_id')")
    assert ga_client_id, (
        "sessionStorage['ga_client_id'] not set despite _ga cookie being present"
    )

    # The contact form should have a hidden input that carries the ga_client_id to the server
    ga_input = page.locator("input[name*='ga_client_id'], input[id*='ga_client_id']")
    if ga_input.count() > 0:
        input_value = ga_input.first.get_attribute("value") or ""
        assert input_value, "ga_client_id hidden input exists but has empty value"

    write_detail("test_ga4_client_id_in_contact_form", {
        "message": f"ga_client_id={ga_client_id!r} set in sessionStorage from _ga cookie",
    })

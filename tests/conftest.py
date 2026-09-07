import base64
import json
import os
import re
import uuid as _uuid
import pytest
import requests
from playwright.sync_api import Browser

from utils.recaptcha_bypass import inject_recaptcha_bypass


_LIVE_DOMAIN   = "owltutors.co.uk"
_ALLOW_LIVE_ENV = "OWL_TEST_ALLOW_LIVE"

# WP Engine blocks the default `python-requests/x.x.x` User-Agent by default
# as a known scripting-library signature (found 7 Sept 2026 -- see
# owl_system/docs/TO_DO.md for the full investigation). Every `requests.post`/
# `.get()` call across tests/ and utils/ goes through a fresh `requests.Session()`
# under the hood, and each one re-reads this default at call time, so patching
# it once here -- before any test module or utils/ helper makes its first
# request -- covers every call site in the suite without editing them
# individually. scripts/recreate_staging_fixtures.py runs standalone (outside
# pytest, so this patch doesn't reach it) and sets its own header instead.
requests.utils.default_user_agent = lambda: "OwlTutorsSmokeTests/1.0"


def pytest_sessionstart(session):
    """Turn on the site-wide test_mode option before any test setup or collection
    runs (owl_system docs/TESTING_REBUILD_SPEC.md, Day 1).

    Deliberately raises on failure rather than letting the suite run un-suppressed:
    test_mode gates email suppression, Stripe test keys, and other real-side-effect
    behaviour, so a run silently proceeding without it risks real sends/charges.
    (SMS/WhatsApp suppression is separate and doesn't depend on this option at all
    — see ot_is_production_environment() in the plugin.)

    Best-effort skip (not a hard fail) when TEST_BASE_URL/OWL_TEST_API_KEY aren't
    set, or the target is the live domain — the base_url fixture raises its own
    clearer errors for those cases once tests actually start.
    """
    raw_url = os.environ.get("TEST_BASE_URL", "")
    api_key = os.environ.get("OWL_TEST_API_KEY", "")
    if not raw_url or not api_key:
        return
    if _LIVE_DOMAIN in raw_url and not os.environ.get(_ALLOW_LIVE_ENV):
        return

    import requests

    clean_url = re.sub(r"(https?://)[^:@]+:[^@]+@", r"\1", raw_url)
    headers = {}
    token = _basic_auth_token()
    if token:
        headers["Authorization"] = f"Basic {token}"

    try:
        resp = requests.post(
            f"{clean_url}/wp-admin/admin-ajax.php",
            data={"action": "owl_set_test_mode", "api_key": api_key},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"pytest_sessionstart: could not enable test_mode: {e}") from e

    if not data.get("success"):
        raise RuntimeError(f"pytest_sessionstart: owl_set_test_mode failed: {data}")

    # Stamp this run with the deployed version/commit SHA (Days 4-6). Written to
    # a file rather than kept in memory: reporter.py runs as a separate process
    # after the whole pytest session finishes (see .github/workflows/smoke-tests.yml).
    # Best-effort only -- a run should not fail just because this lookup failed.
    try:
        from utils.get_deploy_info import get_deploy_info
        deploy_info = get_deploy_info(clean_url, api_key)
        with open("deploy_info.json", "w") as f:
            json.dump(deploy_info, f, indent=2)
    except Exception as e:
        print(f"[pytest_sessionstart] could not fetch deploy info: {e}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Stash each phase's TestReport on the item (as rep_setup/rep_call/rep_teardown)
    so the _diagnostics fixture below can check the outcome after the test body
    has run — a fixture's own yield has no direct access to the test's result."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


@pytest.fixture(scope="session")
def base_url():
    raw = os.environ["TEST_BASE_URL"]
    # Hard block: prevent accidental form-submission tests against production.
    # The PHP dev gate lets form submissions through on live (jobs/users are created for real)
    # but silently skips test-flagging and rejects cleanup — leaving real data behind.
    # Set OWL_TEST_ALLOW_LIVE=1 only when running read-only tests (e.g. GA4) against live.
    if _LIVE_DOMAIN in raw and not os.environ.get(_ALLOW_LIVE_ENV):
        raise RuntimeError(
            f"\n\n*** SAFETY BLOCK — production site detected ***\n"
            f"TEST_BASE_URL contains '{_LIVE_DOMAIN}'.\n"
            f"Form-submission tests create real jobs and user accounts on production;\n"
            f"the PHP cleanup endpoint is dev-only so they cannot be deleted.\n\n"
            f"To run READ-ONLY tests against the live site (e.g. GA4 checks only):\n"
            f"  set {_ALLOW_LIVE_ENV}=1 and pass -k 'ga4' to restrict to those tests.\n"
            f"Never run the full suite against the live site.\n"
        )
    # Strip user:pass@ from the URL. Embedding credentials in the navigation URL
    # causes Chrome to include them when resolving relative paths, so fetch('/wp-admin/admin-ajax.php')
    # resolves to https://user:pass@host/... and Chrome refuses to construct the Request.
    # Auth is handled separately by http_credentials + inject_basic_auth.
    return re.sub(r"(https?://)[^:@]+:[^@]+@", r"\1", raw)


def _basic_auth_token() -> str | None:
    """Return a Basic Auth token, or None if no credentials are configured.
    Prefers TEST_HTTP_USER/TEST_HTTP_PASS over URL-embedded credentials to
    avoid regex breakage when the password contains special characters like '@'.

    .strip() on both -- found 3 Sept 2026: a GitHub Secret pasted with a
    trailing newline (easy to pick up from a "copy" button depending on the
    source page) is preserved verbatim in the secret's value, silently
    corrupting the Base64 token and producing a 403 on every request, while
    the exact same clipboard content pasted into a browser's single-line
    password field gets the newline stripped automatically -- so a manual
    browser login can succeed with credentials that still fail here unless
    guarded against explicitly.
    """
    user = os.environ.get("TEST_HTTP_USER", "").strip()
    pw   = os.environ.get("TEST_HTTP_PASS", "").strip()
    if user and pw:
        return base64.b64encode(f"{user}:{pw}".encode()).decode()
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        return base64.b64encode(f"{match.group(1)}:{match.group(2)}".encode()).decode()
    return None


def _auth_headers() -> dict:
    """Headers dict for raw `requests` calls: Basic Auth (if configured) plus
    a real User-Agent — see _basic_auth_token() above for the credential
    precedence."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; owltutors-monitoring/1.0)"}
    token = _basic_auth_token()
    if token:
        headers["Authorization"] = f"Basic {token}"
    return headers


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Test-environment-only: stop Chromium's third-party-cookie-phaseout
    trial from applying to this suite's runs.

    Found 7 Sept 2026 investigating the WooCommerce-native checkout cluster
    (test_dbs_checkout_completes_for_logged_in_tutor and others): every one
    of them fills the Stripe card fields fine, clicks "place order", then
    never reaches order-received within 30s. Diagnostics showed a wall of
    "Third-party cookie will be blocked" warnings plus repeated 401s from
    Stripe's own api.stripe.com/v1/consumers/sessions/lookup (Stripe's
    "Link" saved-payment-method feature) -- Stripe's Link integration is
    documented to sometimes hang the actual payment submission, not just
    degrade gracefully, when third-party storage access is blocked.
    GitHub Actions' headless Chromium enforces this far more aggressively
    by default than a normal local browser does.

    --test-third-party-cookie-phaseout=false is Chrome's own documented
    flag for exactly this situation -- automated tests that need
    third-party-cookie behaviour to match pre-phaseout Chrome, without
    disabling the wider Privacy Sandbox test infrastructure. Test-harness
    only; nothing about the live site's real Stripe/Link configuration
    changes.
    """
    args = list(browser_type_launch_args.get("args", []))
    args.append("--test-third-party-cookie-phaseout=false")
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Supply http_credentials so Playwright can respond to any 401 challenges."""
    user = os.environ.get("TEST_HTTP_USER", "").strip()
    pw   = os.environ.get("TEST_HTTP_PASS", "").strip()
    if not (user and pw):
        raw = os.environ.get("TEST_BASE_URL", "")
        match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
        if match:
            user, pw = match.group(1), match.group(2)
    if user and pw:
        return {**browser_context_args, "http_credentials": {"username": user, "password": pw}}
    return browser_context_args


@pytest.fixture(autouse=True)
def inject_basic_auth(page):
    """Intercept every request from the page and add the Authorization header.

    http_credentials alone is insufficient: WP Engine password protection can
    block JS-initiated XHR/fetch calls before issuing a 401 challenge, so the
    browser never gets a chance to retry with credentials. page.route() fires
    before the request leaves the browser and injects the header proactively,
    covering admin-ajax.php AJAX calls as well as normal navigations."""
    token = _basic_auth_token()
    if token:
        auth_header = f"Basic {token}"
        page.route(
            "**/*",
            lambda route: route.continue_(
                headers={**route.request.headers, "Authorization": auth_header}
            ),
        )

class _Step:
    """Named-step context manager -- see the `step` fixture below."""
    def __init__(self, request, name):
        self.request = request
        self.name = name

    def __enter__(self):
        self.request.node.current_step = self.name
        return self

    def __exit__(self, exc_type, exc, tb):
        return False  # never suppress -- let the failure propagate normally


@pytest.fixture
def step(request):
    """Named-step context manager for failure diagnostics (docs/TESTING_REBUILD_SPEC.md
    Days 4-6): `with step("filling contact form"): ...`.

    On failure, the last-entered step name is attached to the plain-English
    summary and the details.json entry, so a failure says *where* it happened
    without anyone reading the full traceback. Adoption is incremental --
    tests that don't use it simply have no step name in their failure summary.
    """
    def _make(name):
        return _Step(request, name)
    return _make


@pytest.fixture(autouse=True)
def _diagnostics(page, request):
    """Comprehensive network + JS diagnostics for every test, plus failure-only
    screenshot and plain-English summary (docs/TESTING_REBUILD_SPEC.md Days 4-6).

    Always (live -s output, unchanged from the log_ajax fixture this replaces):
    - prints admin-ajax.php responses/failures, console errors/warnings,
      unhandled JS page errors, and a DOM snapshot

    On failure only:
    - takes a screenshot (screenshots/{test_name}.png) -- previously screenshots
      were only ever taken on the success path, so a currently-failing test's
      screenshot (if the dashboard showed one at all) was stale from the last
      time it passed and showed nothing about the actual failure
    - writes a details.json entry (message, screenshot, step, and capped
      console/page/network error lists) that overwrites any stale pass-time
      entry, so the dashboard widget reflects the current failure
    """
    ajax_responses = []
    ajax_failed = []
    console_msgs = []
    console_errors = []
    page_errors = []
    failed_requests = []
    error_responses = []

    def on_response(response):
        if "admin-ajax.php" in response.url:
            try:
                body = response.text()
            except Exception:
                body = "<unreadable>"
            ajax_responses.append(f"  [response {response.status}] {response.url} -> {body[:300]}")
        # Browser-generated "Failed to load resource: ... 401 ()" console
        # messages carry no URL of their own -- added 7 Sept 2026 while
        # investigating the WooCommerce-native checkout cluster (repeated
        # 401s during Stripe Elements checkout, cause unknown) specifically
        # to recover which resource actually 4xx/5xx'd, not just that one did.
        if response.status >= 400:
            error_responses.append(f"  [response {response.status}] {response.request.method} {response.url}")

    def on_console(msg):
        line = f"[console:{msg.type}] {msg.text}"
        console_msgs.append(f"  {line}")
        if msg.type in ("error", "warning"):
            console_errors.append(line)

    def on_pageerror(err):
        page_errors.append(str(err))

    def on_requestfailed(req):
        failed_requests.append(f"{req.method} {req.url} — {req.failure}")
        if "admin-ajax.php" in req.url:
            ajax_failed.append(f"  [FAILED] {req.url} — {req.failure}")

    page.on("response", on_response)
    page.on("requestfailed", on_requestfailed)
    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    yield

    # ---- live diagnostics printout (unchanged behaviour) ----
    dom = {}
    try:
        dom = page.evaluate("""() => ({
            ajaxurl:      window.ajaxurl || null,
            formEl:       !!document.getElementById('tutorSearchForm'),
            resultsEl:    !!document.getElementById('tutor_results'),
            listingsCheck:!!document.getElementById('tutor-listings-page'),
            url:          window.location.href,
        })""")
    except Exception:
        pass

    lines = ajax_responses + ajax_failed
    if lines or error_responses or page_errors or dom:
        print(f"\n[diag: {request.node.name}]")
        for line in lines:
            print(line)
        for line in error_responses:
            print(line)
        for line in page_errors:
            print(f"  [pageerror] {line}")
        if dom:
            print(f"  [dom] {dom}")
    for msg in console_msgs:
        if "[console:error]" in msg or "[console:warning]" in msg:
            print(msg)

    # ---- failure-only screenshot + details.json entry ----
    report = getattr(request.node, "rep_call", None) or getattr(request.node, "rep_setup", None)
    if report is None or report.passed or report.skipped:
        return

    test_name = request.node.name.split("[")[0]

    screenshot_path = None
    try:
        os.makedirs("screenshots", exist_ok=True)
        candidate = f"screenshots/{test_name}.png"
        page.screenshot(path=candidate, timeout=10000)
        screenshot_path = candidate
    except Exception as e:
        print(f"[diagnostics] could not capture failure screenshot for {test_name}: {e}")

    step_name = getattr(request.node, "current_step", None)
    exception_text = str(report.longrepr) if report.longrepr else "Unknown failure"

    from utils.summarize import summarize_failure
    from utils.details import write_detail

    summary = summarize_failure(
        test_name=test_name,
        step=step_name,
        exception_text=exception_text,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests + error_responses,
    )

    write_detail(test_name, {
        "message":         summary,
        "screenshot":      screenshot_path,
        "step":            step_name,
        "console_errors":  console_errors[-10:],
        "page_errors":     page_errors[-10:],
        "failed_requests": (failed_requests + error_responses)[-10:],
    })


@pytest.fixture
def returning_client_login(page, base_url):
    """
    Submits the contact form once as a fresh UUID-email client, leaving the
    browser logged in via the auto-login ?new_client=true redirect.
    Because this fixture shares the same function-scoped `page` as the test
    that requests it, subsequent gotos in the test run as the authenticated
    client — no password or magic link needed.
    Both the setup job and any test job are flagged _ot_test_post=1 for cleanup.

    The PHP auto-login (wp_set_auth_cookie inside window.location.href redirect)
    may not propagate the cookie reliably in all environments. If the auto-login
    didn't take, the fixture falls back to the ot_test_force_login endpoint
    (job-mgmt.php) which sets the cookie via a normal HTTP redirect.
    """
    import urllib.parse

    fresh_email = f"testbot.client.{_uuid.uuid4().hex[:8]}@owltutors.co.uk"

    page.goto(f"{base_url}/contact-us/", wait_until="domcontentloaded")
    page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    # Wait for Maths specifically — the first DOM checkbox is "7 Plus" which is
    # hidden below the fold, so waiting for the generic selector times out.
    page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox'][value='Maths']",
        timeout=15000,
    )
    page.locator(
        "div[data-name='subject_list'] input[type='checkbox'][value='Maths']"
    ).check()
    page.locator("div[data-name='tuition_requirements_original'] textarea").fill(
        "Setup submission for client login test — automated"
    )
    page.locator("div[data-name='timing_details_-_original'] textarea").fill("Flexible")
    page.locator("input[name='acf[field_5edf8887fb5e7]']").fill("Owl")
    page.locator("input[name='acf[field_5edf8899fb5e8]']").fill("TestBot")
    page.locator("input[name='acf[field_5edf889ffb5e9]']").fill(fresh_email)
    page.locator("input[name='acf[field_5a573454bb670]']").fill("07700900000")
    page.locator(
        "div[data-name='i_confirm_there_are_no_health_and_safety_issues'] input[type='checkbox']"
    ).check()
    _key = os.environ.get("OWL_TEST_API_KEY", "")
    page.evaluate(
        """(k) => {
            document.getElementById('ot_test_post').value = '1';
            var i = document.createElement('input');
            i.type = 'hidden'; i.name = 'ot_test_api_key'; i.value = k;
            document.getElementById('tutor_request_form').appendChild(i);
        }""",
        _key,
    )
    page.locator("#contact_form_submit").click()
    page.wait_for_url(re.compile(r".*/jobs/"), timeout=90000)
    page.wait_for_load_state("domcontentloaded")

    # Verify the auto-login cookie was set. If not (e.g. returning_client path,
    # or the window.location.href Set-Cookie didn't propagate in this environment),
    # fall back to the ot_test_force_login endpoint which sets the cookie via a
    # normal wp_safe_redirect so the browser stores it reliably.
    if page.locator("a[href*='logout'], a[href*='log-out']").count() == 0:
        force_url = (
            f"{base_url}/?ot_test_force_login=1"
            f"&email={urllib.parse.quote(fresh_email)}"
            f"&key={urllib.parse.quote(_key)}"
        )
        page.goto(force_url, wait_until="domcontentloaded")
        page.wait_for_selector(
            "a[href*='logout'], a[href*='log-out']",
            timeout=10000,
        )

    yield {"email": fresh_email}


@pytest.fixture(scope="session")
def client_credentials():
    return {
        "email": os.environ["TEST_CLIENT_EMAIL"],
        "password": os.environ["TEST_CLIENT_PASSWORD"],
    }

@pytest.fixture(scope="session")
def admin_credentials():
    """Login credentials for a real staff (administrator/owl-role) account on
    the dev site — needed for any wp-admin screen (metaboxes, admin dashboard
    pages, native user-profile ACF forms). No prior fixture in this suite has
    ever logged in as staff; every existing test uses a client, tutor, or
    applicant session instead. Deliberately does NOT create a throwaway admin
    account on demand (unlike owl_create_test_client for clients) — minting
    new administrator-capable users automatically is a materially bigger
    security surface than disposable client/tutor accounts, so this points
    at one real, already-existing dev-only account instead.
    Set TEST_ADMIN_EMAIL and TEST_ADMIN_PASSWORD."""
    email    = os.environ.get("TEST_ADMIN_EMAIL", "")
    password = os.environ.get("TEST_ADMIN_PASSWORD", "")
    if not (email and password):
        pytest.skip("TEST_ADMIN_EMAIL/PASSWORD not set — skipping wp-admin tests")
    return {"email": email, "password": password}

@pytest.fixture(scope="session")
def api_key():
    return os.environ.get("OWL_TEST_API_KEY", "")

@pytest.fixture(scope="session")
def tutor_ids():
    """Pipe-separated WP user IDs of test tutors on the dev site (e.g. '123|456').
    Tests using this fixture are skipped when the env var is not set."""
    raw = os.environ.get("TEST_TUTOR_IDS", "")
    if not raw:
        pytest.skip("TEST_TUTOR_IDS not configured — skipping requested-tutors test")
    return [int(x.strip()) for x in raw.split("|") if x.strip().isdigit()]


def _new_authed_page(browser: Browser):
    """Create an independent browser context + page with Basic Auth injected.
    Used by session fixtures that need two simultaneous logged-in users
    (e.g. client creating a job while tutor applies in a separate window).
    Mirrors the auth setup in browser_context_args / inject_basic_auth."""
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    ctx_args = {}
    token = None
    if match:
        ctx_args["http_credentials"] = {
            "username": match.group(1),
            "password": match.group(2),
        }
        token = base64.b64encode(
            f"{match.group(1)}:{match.group(2)}".encode()
        ).decode()
    ctx = browser.new_context(**ctx_args)
    page = ctx.new_page()
    if token:
        auth_header = f"Basic {token}"
        page.route(
            "**/*",
            lambda route: route.continue_(
                headers={**route.request.headers, "Authorization": auth_header}
            ),
        )
    return ctx, page


@pytest.fixture(scope="session")
def tutor_credentials():
    """Login credentials for the test tutor (same person as TEST_MEET_NOW_TUTOR_ID).
    Needed for the real end-to-end Stage 3 flow: the tutor logs in and applies
    via the job URL so the applicant card is genuinely present.
    Set TEST_TUTOR_EMAIL and TEST_TUTOR_PASSWORD."""
    email    = os.environ.get("TEST_TUTOR_EMAIL", "")
    password = os.environ.get("TEST_TUTOR_PASSWORD", "")
    if not (email and password):
        pytest.skip(
            "TEST_TUTOR_EMAIL/PASSWORD not set — skipping Stage 3 end-to-end tests"
        )
    return {"email": email, "password": password}


@pytest.fixture(scope="session")
def meet_now_tutor_id():
    """WP user ID of a test tutor configured for meet-now:
    auto_swap_active=true, include_tutor_in_auto_swap=true, online delivery,
    availability outcome 1b.
    This ID is also used as the applicant in dynamically created Stage 3/4 test jobs.
    Set TEST_MEET_NOW_TUTOR_ID."""
    val = os.environ.get("TEST_MEET_NOW_TUTOR_ID", "")
    if not val:
        pytest.skip("TEST_MEET_NOW_TUTOR_ID not set — skipping meet-now and Stage 3/4 tests")
    return val


@pytest.fixture
def meet_now_eligible_tutor_id(page, base_url, api_key):
    """Picks a real, non-excluded tutor from the actual default /tutors/
    search results and forces their eligibility flags (include_tutor_in_auto_swap,
    auto_swap_active) true for the duration of the test, restoring their
    original values on teardown.

    Deliberately does NOT use TEST_MEET_NOW_TUTOR_ID / meet_now_tutor_id: that
    account is permanently on the site's excluded_tutors blocklist
    (get_field('excluded_tutors', 'option') in tutor-mgmt.php) and can never
    appear in real search results no matter what its eligibility flags are —
    forcing its flags true (the original fix attempt) had no effect. That,
    plus auto_swap_active being a real side effect of meet-now job creation
    with no automatic reset, were the two root causes of
    test_meet_now_button_visible_on_eligible_tutor's failure — not a timing
    flake (docs/TESTING_REBUILD_SPEC.md Days 9-10).

    Restoring afterward matters here specifically because, unlike
    meet_now_tutor_id, this touches a real (non-fixture) tutor account.
    """
    from utils.set_tutor_meet_now_eligible import set_tutor_meet_now_eligible

    page.goto(f"{base_url}/tutors/", wait_until="domcontentloaded")
    page.wait_for_selector(".add-to-cart", timeout=15000)
    candidate_id = page.locator(".add-to-cart").first.get_attribute("value")
    assert candidate_id, "No tutor cards found in default search results — cannot pick a candidate"

    result = set_tutor_meet_now_eligible(base_url, api_key, candidate_id)
    previous = result["previous"]

    yield candidate_id

    set_tutor_meet_now_eligible(base_url, api_key, candidate_id, **previous)


@pytest.fixture
def availability_eligible_tutor_id(page, base_url, api_key):
    """Finds a real tutor from the default /tutors/ search results who already
    has capacity > 0 and saved tutor_search_slots rows (most active tutors
    do), forces their availability-confirmation timestamp fresh, and restores
    their previous values on teardown.

    ot_tutor_availability_info_handler() (owl_system/includes/functions.php)
    only ever computes availability_outcome '1a'/'1b' -- the gate for
    p.availability_slots_summary to render at all -- when
    time_availability_date_availability_updated_unix is within the last 30
    days, on top of capacity > 0 and existing tutor_search_slots rows. Real
    (non-fixture) tutors' confirmation dates drift stale within weeks of
    nobody actively using them; as of 26 Aug 2026 only 4 of 2220 tutor
    accounts site-wide were within the 30-day window on local, and none of
    those 4 (all test-fixture accounts, including the excluded-from-search
    TEST_MEET_NOW_TUTOR_ID) appear in real search results. Capacity and
    slots aren't the blocker -- freshness is -- so this reuses
    owl_set_tutor_meet_now_eligible purely for its
    availability_updated_unix side effect (the same field
    set_tutor_meet_now_eligible's own docstring documents), tried against
    each visible candidate in turn until one actually renders the summary,
    rather than assuming the first search result has capacity/slots set.

    Skips if none of the tutors on the default listing qualify even after
    forcing freshness.
    """
    from utils.set_tutor_meet_now_eligible import set_tutor_meet_now_eligible

    page.goto(f"{base_url}/tutors/", wait_until="domcontentloaded")
    page.wait_for_selector(".add-to-cart", timeout=15000)
    candidate_ids = page.locator(".add-to-cart").evaluate_all("els => els.map(e => e.value)")

    chosen_id = None
    chosen_previous = None
    for candidate_id in candidate_ids:
        if not candidate_id:
            continue
        result = set_tutor_meet_now_eligible(base_url, api_key, candidate_id)
        previous = result["previous"]

        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".add-to-cart", timeout=15000)
        card = page.locator(f"article.author-card:has(.add-to-cart[value='{candidate_id}'])")
        card.locator("button.tutor_availability").hover()
        try:
            summary_text = (
                page.locator(".tooltip.tutor-tooltip p.availability_slots_summary")
                .text_content(timeout=2000)
                or ""
            ).strip()
        except Exception:
            summary_text = ""
        page.mouse.move(0, 0)  # close the tooltip before the next candidate

        if summary_text:
            chosen_id, chosen_previous = candidate_id, previous
            break
        set_tutor_meet_now_eligible(base_url, api_key, candidate_id, **previous)

    if not chosen_id:
        pytest.skip(
            "None of the tutors on the default /tutors/ listing render a "
            "non-empty availability summary even after forcing their "
            "confirmation timestamp fresh -- none currently has both "
            "capacity > 0 and saved tutor_search_slots rows; set both for a "
            "real tutor via the dashboard to enable this test"
        )

    yield chosen_id

    set_tutor_meet_now_eligible(base_url, api_key, chosen_id, **chosen_previous)


@pytest.fixture(scope="session")
def stage3_job(
    browser, base_url, api_key,
    tutor_credentials, meet_now_tutor_id,
):
    """Creates a Stage 3 test job via the realistic end-to-end flow.

    1. A logged-OUT client submits the contact form using a freshly generated
       UUID email, creating a brand-new WP account (client_created_job_no_pw_login=true,
       _ot_test_user=1). The job lands on 'Stage 2 - Ready no tutors'.
    2. The test tutor logs in in a separate browser context and submits the
       two-step application form.
    3. owl_advance_test_job marks the applicant as forwarded and sets Stage 3.
    4. The magic link is used once in a setup page to auto-login the new client
       and complete the #passwordModal set-password step, establishing a known
       password. Tests then use _login() with client_email + client_password.

    Yields a dict: {"job_id": str, "client_email": str, "client_password": str}.
    """
    import re as _re
    import uuid as _uuid
    import binascii
    from utils.advance_job import advance_test_job

    LOGIN_URL = "/login/"
    CLIENT_PASSWORD = "Owl1Tutor!Test2026"
    client_email = f"testbot.stage3.{_uuid.uuid4().hex[:8]}@owltutors.co.uk"

    # ── Step 1: logged-out client submits contact form ────────────────────
    client_ctx, client_page = _new_authed_page(browser)

    client_page.goto(f"{base_url}/contact-us/")
    client_page.locator("select[name='acf[field_64997c72bef9f]']").select_option(
        label="A tutor to provide tuition services"
    )
    client_page.wait_for_selector(
        "div[data-name='subject_list'] input[type='checkbox']", timeout=10000
    )

    # Japanese — may be below the fold
    japanese_cb = client_page.locator(
        "div[data-name='subject_list'] input[type='checkbox'][value='Japanese']"
    )
    if not japanese_cb.is_visible():
        client_page.locator(".below-fold-divider").click()
    japanese_cb.check()

    # IB Standard Level
    level_cb = client_page.locator(
        "div[data-name='japanese_level'] input[type='checkbox'][value='IB Standard Level']"
    )
    level_cb.wait_for(state="visible", timeout=5000)
    level_cb.check()

    # Online delivery
    client_page.locator(
        "div[data-name='tuition_delivery'] input[type='checkbox'][value='Online']"
    ).check()

    client_page.locator(
        "div[data-name='tuition_requirements_original'] textarea"
    ).fill("Test requirements for automated end-to-end monitoring test -- Japanese IB")
    client_page.locator(
        "div[data-name='timing_details_-_original'] textarea"
    ).fill("Flexible timing")

    # Personal info — generated email creates a fresh account
    client_page.locator("input[name='acf[field_5edf8887fb5e7]']").fill("Owl")
    client_page.locator("input[name='acf[field_5edf8899fb5e8]']").fill("TestBot")
    client_page.locator("input[name='acf[field_5edf889ffb5e9]']").fill(client_email)
    client_page.locator("input[name='acf[field_5a573454bb670]']").fill("07700900000")
    client_page.locator(
        "div[data-name='i_confirm_there_are_no_health_and_safety_issues'] input[type='checkbox']"
    ).check()

    # Inject ot_test_post flag (suppresses emails, flags job and user for cleanup)
    client_page.evaluate(
        """(k) => {
            document.getElementById('ot_test_post').value = '1';
            const i = document.createElement('input');
            i.type = 'hidden'; i.name = 'ot_test_api_key'; i.value = k;
            document.getElementById('tutor_request_form').appendChild(i);
        }""",
        os.environ.get("OWL_TEST_API_KEY", ""),
    )

    client_page.locator("#contact_form_submit").click()
    client_page.wait_for_url(_re.compile(r".*/jobs/"), timeout=90000)
    job_id = _re.search(r"/jobs/(\d+)/", client_page.url).group(1)
    print(f"\n[stage3_job] job created: {job_id} (client: {client_email})")
    client_ctx.close()

    # ── Step 2: tutor logs in and applies in a separate context ───────────
    tutor_ctx, tutor_page = _new_authed_page(browser)

    tutor_page.goto(f"{base_url}{LOGIN_URL}")
    tutor_page.wait_for_selector("#ot_login")
    tutor_page.wait_for_load_state("domcontentloaded")
    tutor_page.locator("#ot_login_name").fill(tutor_credentials["email"])
    tutor_page.locator("#pw1").fill(tutor_credentials["password"])
    inject_recaptcha_bypass(tutor_page, api_key, form_id="ot_login")
    tutor_page.locator("#login_submit").click()
    tutor_page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=90000)

    tutor_page.goto(f"{base_url}/jobs/{job_id}/")

    tutor_page.locator("p.applyforrole a").click()
    tutor_page.wait_for_selector("div.app_form_wrapper", state="visible", timeout=10000)

    tutor_page.locator("textarea#stage2_why_am_i_suitable").fill(
        "Experienced Japanese IB tutor. Automated test application."
    )
    tutor_page.locator("select#stage2_delivery").select_option("Online")

    # Step 1: review — POSTs form, PHP re-renders review page
    tutor_page.locator("input.tutor_job_app_form_presubmit").click(timeout=90000)
    tutor_page.wait_for_load_state("domcontentloaded", timeout=30000)

    # Step 2: submit — checkbox must change to trigger the JS enable handler
    agree = tutor_page.locator("input#agree_terms")
    if agree.count() > 0:
        if not agree.is_checked():
            agree.check()
        else:
            agree.uncheck()
            agree.check()

    submit = tutor_page.locator("input.tutor_job_app_form_submit")
    submit.wait_for(state="visible", timeout=10000)
    submit.click(timeout=90000)
    tutor_page.wait_for_load_state("domcontentloaded", timeout=30000)
    tutor_ctx.close()
    print(f"\n[stage3_job] tutor applied to job {job_id}")

    # ── Step 3: advance to Stage 3 via monitoring endpoint ────────────────
    advance_test_job(base_url, api_key, job_id, meet_now_tutor_id)
    print(f"\n[stage3_job] job {job_id} advanced to Stage 3")

    # ── Step 4: use the connect button to set a known password ───────────
    # The wp_login action hook (owltheme/functions.php) fires during job creation
    # auto-login and sets last_login immediately, so the magic link skips
    # auto-login and renders the informational Stage 3 view instead. That view
    # still shows the "Connect with tutor" button; clicking it fires
    # ot_job_identify_modal which returns the set-password form because
    # using_default_pw=true on the fresh client. Fill it here to establish
    # known credentials that tests can then use with _login().
    crc32_val = binascii.crc32(str(job_id).encode()) & 0xffffffff
    magic_link_url = f"{base_url}/jobs/{job_id}/?job={crc32_val}&email={client_email}"

    setup_ctx, setup_page = _new_authed_page(browser)
    # domcontentloaded: the job page fires heavy AJAX on load; waiting for the
    # full load event times out on a cold local server. The connect button is
    # rendered server-side so it's present immediately after HTML parse.
    setup_page.goto(magic_link_url, wait_until="domcontentloaded")
    setup_page.wait_for_selector("button.connect_with_tutor", timeout=15000)
    setup_page.locator("button.connect_with_tutor").first.click()
    setup_page.wait_for_selector("#passwordModal.show, .dash_modal.show", timeout=15000)
    setup_page.locator("#inlinepassword").fill(CLIENT_PASSWORD)
    setup_page.locator("#passwordModal button[type='submit']").click()
    setup_page.wait_for_url(lambda url: "client_set_pw=true" in url, timeout=30000)
    setup_ctx.close()
    print(f"\n[stage3_job] password set for {client_email}")

    # ── Step 5: set client_status=Active ──────────────────────────────────
    # New clients are Inactive by default. Active status causes
    # ot_job_identify_modal to return the accept-terms form rather than the
    # add-payment-method form, enabling the full Stage 4 connect flow.
    import requests as _requests
    _headers = _auth_headers()
    _resp = _requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_set_client_active", "api_key": api_key, "email": client_email},
        headers=_headers,
        timeout=15,
    )
    _resp.raise_for_status()
    import json as _json
    _data = _json.loads(_resp.content.decode("utf-8-sig"))
    if not _data.get("success"):
        raise RuntimeError(f"owl_set_client_active failed: {_data}")
    print(f"\n[stage3_job] client {client_email} set to Active")

    yield {"job_id": job_id, "client_email": client_email, "client_password": CLIENT_PASSWORD, "tutor_id": meet_now_tutor_id}



@pytest.fixture(scope="session")
def magic_link_params(base_url, api_key, meet_now_tutor_id):
    """Dynamically creates a Stage 3 test job with an auto-generated never-logged-in
    test client, then computes the magic link params in Python.

    The magic link formula (from single-jobs.php) is:
        ?job=crc32(job_id)&email={client_email}
    Python equivalent: binascii.crc32(str(job_id).encode()) & 0xffffffff

    The fresh client is flagged _ot_test_user=1 (cleanup endpoint deletes them).
    No TEST_MAGIC_LINK_* env vars needed — fully self-contained."""
    import binascii
    from utils.create_test_job import create_test_job
    # Pass empty client_email so the endpoint auto-creates a never-logged-in client
    result = create_test_job(
        base_url=base_url,
        api_key=api_key,
        stage=3,
        tutor_id=meet_now_tutor_id,
        client_email="",
    )
    job_id       = result["job_id"]
    client_email = result["client_email"]
    crc32_val    = binascii.crc32(str(job_id).encode()) & 0xffffffff
    return {"job_id": job_id, "crc32": str(crc32_val), "email": client_email}


@pytest.fixture
def live_job_with_timesheet(browser, base_url, api_key, meet_now_tutor_id, tutor_credentials, client_credentials):
    """Creates a real Live-status ('Live - Client confirmed live') EB job owned
    by the static client_credentials account, then drives the actual tutor
    timesheet wizard (utils/timesheet_wizard.py — same helpers used by
    test_eb_job_timesheet_submission_creates_timesheet_and_redirects) in a
    separate browser context to submit a genuine timesheet against it.

    Exists to exercise ot_single_job_feedback_to_client()'s "Timesheet
    feedback" section (job-mgmt.php) — the real, already-working mechanism
    that distinguishes a Live job's client view from a Stage 4 one (only Live
    calls it, see single-jobs.php). Two earlier-flagged code paths
    ($live_jobs in page-dashboard.php, $friendly_status in
    ot_client_active_tutors()) turned out to be cosmetically dead, not this —
    see docs/TESTING_SYSTEM.md.

    The submitted timesheet has no fixture concept of its own (it's created
    by real production code, same as every other timesheet-wizard test), so
    this flags it _ot_test_post=1 via the new owl_flag_test_timesheet endpoint
    once submitted, so owl_delete_test_posts (triggered by the cleanup_after
    fixture) removes it along with the job.
    """
    import requests
    from utils.create_test_job import create_test_job
    from utils.timesheet_wizard import (
        submit_student_name_if_shown,
        complete_goal_wizard_via_skip,
        fill_and_submit_timesheet_form,
    )

    job = create_test_job(
        base_url, api_key, stage=5, tutor_id=meet_now_tutor_id,
        client_email=client_credentials["email"], job_type="EB job",
    )
    job_id = job["job_id"]

    ctx, tutor_page = _new_authed_page(browser)
    try:
        tutor_page.goto(f"{base_url}/login/")
        tutor_page.locator("#ot_login_name").fill(tutor_credentials["email"])
        tutor_page.locator("#pw1").fill(tutor_credentials["password"])
        inject_recaptcha_bypass(tutor_page, api_key, form_id="ot_login")
        tutor_page.locator("#login_submit").click()
        tutor_page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)

        tutor_page.goto(f"{base_url}/jobs/{job_id}/#timesheet", wait_until="domcontentloaded")
        submit_student_name_if_shown(tutor_page)
        complete_goal_wizard_via_skip(tutor_page)
        fill_and_submit_timesheet_form(tutor_page, submit_type="submit_for_invoicing")
        tutor_page.wait_for_url(lambda url: "/dashboard/tutoring-section" in url, timeout=20000)
    finally:
        ctx.close()

    fields_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_get_test_job_fields", "api_key": api_key, "job_id": job_id},
        headers=_auth_headers(),
        timeout=15,
    )
    fields_resp.raise_for_status()
    fields = fields_resp.json()
    timesheet_id = fields.get("most_recent_timesheet_id")
    assert timesheet_id, f"owl_get_test_job_fields returned no most_recent_timesheet_id: {fields}"

    flag_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_flag_test_timesheet", "api_key": api_key, "timesheet_id": timesheet_id},
        headers=_auth_headers(),
        timeout=15,
    )
    flag_resp.raise_for_status()
    assert flag_resp.json().get("success"), f"owl_flag_test_timesheet failed: {flag_resp.json()}"

    yield {
        "job_id": job_id,
        "timesheet_id": timesheet_id,
        "client_email": client_credentials["email"],
        "client_password": client_credentials["password"],
    }

    # client_credentials is a shared, persistent test account (unlike the
    # auto-created disposable clients most fixtures use) — clean up explicitly
    # rather than letting the Live job + timesheet accumulate on it run after run.
    requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_delete_test_posts", "api_key": api_key},
        headers=_auth_headers(),
        timeout=15,
    )


@pytest.fixture(scope="session")
def preapplicant_credentials(browser, base_url, api_key):
    """Create a fresh pre-applicant for this test session via the registration form.

    Does NOT set _ot_test_user=1. This is a session fixture — flagging the user
    would cause cleanup_after (used by per-test fixtures like test_tutor_registration_submits)
    to delete the account mid-session, breaking all tests that depend on this fixture.
    UUID-based emails accumulate on the dev site; clean up old testbot.preapp.* accounts
    manually via WP admin when needed.
    No TEST_PREAPPLICANT_EMAIL/PASSWORD env vars required.
    """
    import uuid as _uuid

    APPLICATION_URL = "/tutor-section/application/"
    email    = f"testbot.preapp.{_uuid.uuid4().hex[:8]}@owltutors.co.uk"
    password = "Owl1Tutor!Test2026"

    ctx, reg_page = _new_authed_page(browser)
    reg_page.goto(f"{base_url}{APPLICATION_URL}")
    reg_page.wait_for_selector("#signupform", state="visible", timeout=10000)
    reg_page.locator("#email").fill(email)
    reg_page.locator("#pw1").fill(password)
    reg_page.evaluate("document.getElementById('signupform').submit()")
    reg_page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)
    assert "register-errors" not in reg_page.url, (
        f"preapplicant_credentials: registration failed — {reg_page.url}"
    )
    ctx.close()

    yield {"email": email, "password": password}


@pytest.fixture(scope="session")
def applicant_credentials(browser, base_url, api_key):
    """Create a fresh applicant for this test session by running the full application flow.

    Registers a new pre-applicant (no _ot_test_user=1 flag — flagging would cause
    cleanup_after to delete the account mid-session), fills all 9 form sections via
    complete_application_form(), and submits. The system promotes the pre-applicant
    to 'applicant' role on successful submission.

    UUID-based emails accumulate on the dev site; clean up old testbot.applicant.*
    accounts manually via WP admin when needed.
    No TEST_APPLICANT_EMAIL/PASSWORD env vars required — fully self-creating.
    """
    from pathlib import Path as _Path
    from utils.apply import complete_application_form as _complete_form

    APPLICATION_URL = "/tutor-section/application/"
    qts_pdf = str(_Path(__file__).parent / "fixtures" / "test_qts.pdf")
    import uuid as _uuid
    email    = f"testbot.applicant.{_uuid.uuid4().hex[:8]}@owltutors.co.uk"
    password = "Owl1Tutor!Test2026"

    ctx, page = _new_authed_page(browser)
    page.goto(f"{base_url}{APPLICATION_URL}")
    page.wait_for_selector("#signupform", state="visible", timeout=10000)
    page.locator("#email").fill(email)
    page.locator("#pw1").fill(password)
    page.evaluate("document.getElementById('signupform').submit()")
    page.wait_for_url(re.compile(r".*/tutor-section/application/"), timeout=30000)
    assert "register-errors" not in page.url, (
        f"applicant_credentials: registration failed — {page.url}"
    )

    _complete_form(page, base_url, qts_pdf)

    # Verify promotion actually happened. The applicant form has
    # div.applicationFormContainer; the pre-applicant form does not.
    page.goto(f"{base_url}{APPLICATION_URL}")
    page.wait_for_load_state("networkidle")
    assert page.locator("div.applicationFormContainer").count() > 0, (
        "applicant_credentials: form submit did not promote user to 'applicant'. "
        "Run with --headed to debug. Check the submit step in apply.py."
    )

    ctx.close()
    yield {"email": email, "password": password}

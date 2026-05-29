import base64
import os
import re
import pytest


@pytest.fixture(scope="session")
def base_url():
    raw = os.environ["TEST_BASE_URL"]
    # Strip user:pass@ from the URL. Embedding credentials in the navigation URL
    # causes Chrome to include them when resolving relative paths, so fetch('/wp-admin/admin-ajax.php')
    # resolves to https://user:pass@host/... and Chrome refuses to construct the Request.
    # Auth is handled separately by http_credentials + inject_basic_auth.
    return re.sub(r"(https?://)[^:@]+:[^@]+@", r"\1", raw)


def _basic_auth_token() -> str | None:
    """Return a Basic Auth token from TEST_BASE_URL credentials, or None."""
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        return base64.b64encode(f"{match.group(1)}:{match.group(2)}".encode()).decode()
    return None


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Supply http_credentials so Playwright can respond to any 401 challenges."""
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        return {
            **browser_context_args,
            "http_credentials": {"username": match.group(1), "password": match.group(2)},
        }
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

@pytest.fixture(autouse=True)
def log_ajax(page, request):
    """Comprehensive network + JS diagnostics for every test.

    Captures:
    - admin-ajax.php responses (status + body)
    - admin-ajax.php requests that fail/abort before getting a response
    - all browser console messages (all levels)
    - unhandled JS page errors
    - a DOM snapshot after the test (ajaxurl value + key element presence)
    """
    responses = []
    failed_requests = []
    console_msgs = []
    page_errors = []

    def on_response(response):
        if "admin-ajax.php" in response.url:
            try:
                body = response.text()
            except Exception:
                body = "<unreadable>"
            responses.append(f"  [response {response.status}] {response.url} → {body[:300]}")

    def on_requestfailed(req):
        if "admin-ajax.php" in req.url:
            failed_requests.append(f"  [FAILED] {req.url} — {req.failure}")

    page.on("response", on_response)
    page.on("requestfailed", on_requestfailed)
    page.on("console", lambda msg: console_msgs.append(f"  [console:{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: page_errors.append(f"  [pageerror] {err}"))

    yield

    # DOM snapshot — only meaningful if page navigated somewhere
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

    lines = responses + failed_requests
    if lines or page_errors or dom:
        print(f"\n[diag: {request.node.name}]")
        for line in lines:
            print(line)
        for line in page_errors:
            print(line)
        if dom:
            print(f"  [dom] {dom}")
    # Always print console — filter to errors/warnings to keep output manageable
    for msg in console_msgs:
        if any(t in msg for t in ("[console:error]", "[console:warning]")):
            print(msg)


@pytest.fixture(scope="session")
def client_credentials():
    return {
        "email": os.environ["TEST_CLIENT_EMAIL"],
        "password": os.environ["TEST_CLIENT_PASSWORD"],
    }

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

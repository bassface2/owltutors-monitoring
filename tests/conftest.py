import base64
import os
import re
import pytest


@pytest.fixture(scope="session")
def base_url():
    return os.environ["TEST_BASE_URL"]


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
    """Log every admin-ajax.php response: status, action, and truncated body.

    Runs for every test so failing tests show exactly what the server returned.
    Output is captured by pytest and printed only on failure (-s shows always)."""
    responses = []

    def on_response(response):
        if "admin-ajax.php" in response.url:
            try:
                body = response.text()
            except Exception:
                body = "<unreadable>"
            responses.append(
                f"  [{response.status}] {response.url} → {body[:300]}"
            )

    page.on("response", on_response)
    page.on("console", lambda msg: print(f"  [console:{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
    yield
    if responses:
        print(f"\n[ajax log for {request.node.name}]")
        for line in responses:
            print(line)


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

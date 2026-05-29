import os
import re
import pytest


@pytest.fixture(scope="session")
def base_url():
    return os.environ["TEST_BASE_URL"]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Pass HTTP Basic Auth credentials to every browser context.
    Credentials are extracted from TEST_BASE_URL if present
    (e.g. https://user:pass@otdev1602.wpengine.com), ensuring AJAX
    requests made by the page also carry the auth header."""
    raw = os.environ.get("TEST_BASE_URL", "")
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        return {
            **browser_context_args,
            "http_credentials": {
                "username": match.group(1),
                "password": match.group(2),
            },
        }
    return browser_context_args

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

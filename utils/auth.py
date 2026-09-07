import base64
import os
import re

_UA = {"User-Agent": "Mozilla/5.0 (compatible; owltutors-monitoring/1.0)"}


def auth_headers(base_url: str = "") -> dict:
    """Basic Auth header (+ a real User-Agent) for raw `requests` calls against
    a WP Engine Basic-Auth-protected environment (e.g. otdev1602).

    Prefers TEST_HTTP_USER/TEST_HTTP_PASS -- avoids regex breakage when the
    password contains special characters such as '@' -- falling back to
    credentials embedded in TEST_BASE_URL (or the passed-in base_url).
    Returns just the User-Agent header, with no Authorization key, when
    neither is configured (e.g. against local/unprotected environments).
    """
    user = os.environ.get("TEST_HTTP_USER", "").strip()
    pw = os.environ.get("TEST_HTTP_PASS", "").strip()
    if user and pw:
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {token}", **_UA}
    raw = os.environ.get("TEST_BASE_URL", base_url)
    match = re.match(r"https?://([^:@]+):([^@]+)@", raw)
    if match:
        token = base64.b64encode(f"{match.group(1)}:{match.group(2)}".encode()).decode()
        return {"Authorization": f"Basic {token}", **_UA}
    return dict(_UA)


def is_basic_auth_configured(base_url: str = "") -> bool:
    """True when TEST_HTTP_USER/PASS or credentials embedded in TEST_BASE_URL
    are available -- i.e. the target environment is gated by platform-level
    HTTP Basic Auth (e.g. otdev1602), as opposed to local/production which
    aren't. Used to skip tests that specifically need an *unauthenticated*
    request (e.g. simulating a real incoming webhook) on such environments."""
    return "Authorization" in auth_headers(base_url)

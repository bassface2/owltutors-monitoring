import base64
import os
import re
import requests


def _parse_base_url(base_url: str):
    """Return (clean_url, auth_tuple_or_None) stripping credentials from the URL."""
    match = re.match(r"(https?://)([^:@]+):([^@]+)@(.+)", base_url)
    if match:
        clean = match.group(1) + match.group(4)
        auth = (match.group(2), match.group(3))
        return clean, auth
    return base_url, None


def delete_test_posts(base_url: str) -> int:
    """Delete all test-flagged job posts on the dev site. Returns count deleted."""
    api_key = os.environ.get("OWL_TEST_API_KEY", "")
    if not api_key:
        raise RuntimeError("OWL_TEST_API_KEY environment variable is not set")

    clean_url, auth = _parse_base_url(base_url)

    # Send Authorization header proactively on the first request.
    # requests auth= is reactive (retries on 401 only); WP Engine can return 403
    # directly without issuing a challenge, so the retry never fires.
    headers = {}
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    resp = requests.post(
        f"{clean_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_delete_test_posts", "api_key": api_key},
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    import json as _json
    data = _json.loads(resp.content.decode('utf-8-sig'))
    if not data.get("success"):
        raise RuntimeError(f"Cleanup endpoint error: {data.get('error', 'unknown')}")
    return data


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TEST_BASE_URL", "")
    if not url:
        print("Usage: python utils/cleanup.py <base_url>")
        sys.exit(1)
    result = delete_test_posts(url)
    print(
        f"Deleted {result.get('deleted_jobs', 0)} job(s), "
        f"{result.get('deleted_students', 0)} student(s), "
        f"{result.get('deleted_users', 0)} user(s)"
    )

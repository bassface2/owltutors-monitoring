#!/usr/bin/env python3
"""
Repairs staging/CI test fixture accounts via the owl_repair_test_fixtures
AJAX endpoint (owl_system) instead of SSH.

Replaces recreate_staging_fixtures.sh's SSH-based approach as of 5 Sept
2026, to test whether removing the SSH connection burst -- confirmed by
WP Engine support to trigger their automated brute-force protection and
block the runner's IP -- is the actual and complete cause of the
otdev1602 403 issue (see owl_system/docs/TO_DO.md). If this script's own
plain HTTP request also gets blocked, that rules out "it's specifically
about SSH connections" as the complete explanation.

The old SSH script (recreate_staging_fixtures.sh) is left in place, unused
by CI, for manual debugging if ever needed.

Env vars (same source-of-truth pattern as tests/conftest.py -- prefers
real environment variables, set by GitHub Secrets in CI):
  TEST_BASE_URL, OWL_TEST_API_KEY, TEST_CLIENT_EMAIL, TEST_CLIENT_PASSWORD
  TEST_TUTOR_EMAIL, TEST_TUTOR_PASSWORD   - optional, both required together
  TEST_MEET_NOW_TUTOR_ID                  - optional, drift-detection only
  TEST_HTTP_USER, TEST_HTTP_PASS          - optional, WP Engine Basic Auth

Usage: python scripts/recreate_staging_fixtures.py
Exit code 0 on success, 1 on failure (missing required env vars, the
request itself failing, or the endpoint reporting success=false).
"""
import base64
import os
import re
import sys

import requests


def main() -> int:
    base_url = os.environ.get("TEST_BASE_URL", "")
    api_key = os.environ.get("OWL_TEST_API_KEY", "")
    client_email = os.environ.get("TEST_CLIENT_EMAIL", "")
    client_password = os.environ.get("TEST_CLIENT_PASSWORD", "")
    if not (base_url and api_key and client_email and client_password):
        print(
            "Error: TEST_BASE_URL, OWL_TEST_API_KEY, TEST_CLIENT_EMAIL, and "
            "TEST_CLIENT_PASSWORD must all be set.",
            file=sys.stderr,
        )
        return 1

    clean_url = re.sub(r"(https?://)[^:@]+:[^@]+@", r"\1", base_url)

    # WP Engine blocks the default `python-requests/x.x.x` User-Agent as a
    # known scripting-library signature (found 7 Sept 2026 -- see
    # owl_system/docs/TO_DO.md). This runs standalone, outside pytest, so it
    # can't rely on conftest.py's process-wide patch and needs its own header.
    headers = {"User-Agent": "OwlTutorsSmokeTests/1.0"}
    http_user = os.environ.get("TEST_HTTP_USER", "").strip()
    http_pass = os.environ.get("TEST_HTTP_PASS", "").strip()
    if http_user and http_pass:
        token = base64.b64encode(f"{http_user}:{http_pass}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    data = {
        "action": "owl_repair_test_fixtures",
        "api_key": api_key,
        "client_email": client_email,
        "client_password": client_password,
    }
    tutor_email = os.environ.get("TEST_TUTOR_EMAIL", "")
    tutor_password = os.environ.get("TEST_TUTOR_PASSWORD", "")
    if tutor_email and tutor_password:
        data["tutor_email"] = tutor_email
        data["tutor_password"] = tutor_password
        meet_now_id = os.environ.get("TEST_MEET_NOW_TUTOR_ID", "")
        if meet_now_id:
            data["meet_now_tutor_id"] = meet_now_id

    try:
        resp = requests.post(
            f"{clean_url}/wp-admin/admin-ajax.php", data=data, headers=headers, timeout=15
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        print(f"Error: request failed: {e}", file=sys.stderr)
        return 1

    if not result.get("success"):
        print(f"Error: owl_repair_test_fixtures failed: {result}", file=sys.stderr)
        return 1

    client = result["client"]
    print(f"== Test client: {client['email']} ==")
    print(f"  {client['status']} -- ID {client['id']}, roles: {', '.join(client['roles'])}")

    tutor = result.get("tutor")
    if tutor:
        print(f"\n== Test tutor: {tutor['email']} ==")
        if tutor["status"] == "exists":
            print(f"  exists -- ID {tutor['id']}, roles: {', '.join(tutor['roles'])}")
            if "id_mismatch_warning" in tutor:
                print(f"  WARNING: {tutor['id_mismatch_warning']}", file=sys.stderr)
        else:
            print(f"  MISSING -- {tutor.get('error', '')}", file=sys.stderr)
    else:
        print("\n(TEST_TUTOR_EMAIL/PASSWORD not set -- skipping tutor fixture check)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

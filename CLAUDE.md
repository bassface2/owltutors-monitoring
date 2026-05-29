# owltutors-monitoring — Claude Code Instructions

## Project Context

This repo contains Playwright smoke tests that run daily against the Owl Tutors dev site (`otdev1602.wpengine.com`) via GitHub Actions. Results are committed to the `results` branch and displayed in the WordPress admin monitoring widget.

---

## Git — NEVER Push Without Asking

**Always ask the user before running `git push` or any command that sends code to GitHub.**

Committing locally is fine. Pushing triggers the GitHub Actions workflow and cannot be easily undone — always confirm first.

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `TEST_BASE_URL` | Dev site URL with embedded Basic Auth credentials: `https://user:pass@otdev1602.wpengine.com` |
| `OWL_TEST_API_KEY` | 32-char secret — authenticates the test flag and cleanup endpoint. Defined in `wp-config.php` on the dev server and as a GitHub Actions Secret. **Never commit this value.** |
| `TEST_CLIENT_EMAIL` / `TEST_CLIENT_PASSWORD` | Credentials for the test client account used in auth tests |

---

## Key Files

| File | Role |
|---|---|
| `tests/conftest.py` | Shared fixtures: `base_url`, `browser_context_args` (Basic Auth), `client_credentials`, `api_key` |
| `tests/test_*.py` | Individual test modules — one per site area |
| `utils/cleanup.py` | Calls the WP cleanup endpoint after data-creating tests |
| `utils/details.py` | Writes per-test metadata (job IDs, screenshots) to `details.json` |
| `utils/reporter.py` | Converts pytest JSON report to `results.json` for the dashboard widget |
| `.github/workflows/smoke-tests.yml` | Scheduled daily at 7am UTC; manual trigger available |

---

## Basic Auth and AJAX

The dev site is protected by WP Engine platform-level HTTP Basic Auth. The `browser_context_args` fixture in `conftest.py` handles this by setting both:

- `http_credentials` — responds to 401 challenges
- `extra_http_headers: {Authorization: Basic ...}` — proactively includes the header on every request, including JS-initiated AJAX calls to `admin-ajax.php`

Both are required. `http_credentials` alone does not cover XHR/fetch requests that WP Engine blocks before issuing a challenge.

`utils/cleanup.py` extracts credentials from the base URL and passes them as `auth=` to `requests.post`.

---

## Adding a New Test

1. Add the test function to the relevant `tests/test_<area>.py`
2. Add the function name to the `$manifest` array in `owl_system/includes/dashboard/dashboard-main.php`
3. If the test creates data, use the `cleanup_after` fixture and ensure records are flagged with `_ot_test_post = 1`
4. Update the Current Tests table in `owl_system/docs/TESTING_SYSTEM.md`

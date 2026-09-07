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
| `TEST_MEET_NOW_TUTOR_ID` | Unlocks 10 of the 12 new P1 tests. WP user ID of a tutor with `auto_swap_active=true`, `include_tutor_in_auto_swap=true`, online delivery, availability outcome `1b`. Used as applicant in all dynamically created test jobs. |
| `TEST_PREAPPLICANT_EMAIL` / `TEST_PREAPPLICANT_PASSWORD` | Credentials for a permanent test pre-applicant account |

All Stage 3, Stage 4, and magic-link test jobs are created on demand by session fixtures via the `owl_create_test_job` AJAX endpoint. No static job IDs needed. Magic-link `?job=` param is computed in Python as `binascii.crc32(str(job_id).encode()) & 0xffffffff`.

---

## Key Files

| File | Role |
|---|---|
| `tests/conftest.py` | Shared fixtures: `base_url`, `browser_context_args` (Basic Auth), `client_credentials`, `api_key` |
| `tests/test_*.py` | Individual test modules — one per site area |
| `utils/cleanup.py` | Calls the WP cleanup endpoint after data-creating tests |
| `utils/details.py` | Writes per-test metadata (job IDs, screenshots) to `details.json` |
| `utils/reporter.py` | Converts pytest JSON report to `results.json` for the dashboard widget |
| `utils/check_critical_regressions.py` | CI-only: diffs critical-test status vs. the last run, emails on new failures (Day 8) |
| `utils/get_test_manifest.py` | Calls `owl_get_test_manifest` to read the dashboard widget's manifest (Days 11-12) |
| `tests/test_manifest_drift.py` | Asserts the manifest and the actual pytest test functions match 1:1 (Days 11-12) |
| `.github/workflows/smoke-tests.yml` | Scheduled daily at 7am UTC; manual trigger available (optionally scoped to a `pytest_markers` filter, which skips the results-branch push and regression alert). `--video=retain-on-failure`, then a critical-regression check, then the results-branch push, then a video artifact upload (7-day retention) |

---

## Basic Auth and AJAX

The dev site is protected by WP Engine platform-level HTTP Basic Auth. The `browser_context_args` fixture in `conftest.py` handles this by setting both:

- `http_credentials` — responds to 401 challenges
- `extra_http_headers: {Authorization: Basic ...}` — proactively includes the header on every request, including JS-initiated AJAX calls to `admin-ajax.php`

Both are required. `http_credentials` alone does not cover XHR/fetch requests that WP Engine blocks before issuing a challenge.

`utils/cleanup.py` extracts credentials from the base URL and passes them as `auth=` to `requests.post`.

---

## Adding a New Test

1. Add the test function to the relevant `tests/test_<area>.py`. Mark it `@pytest.mark.critical` if a failure has a real consequence (money not taken, a parent not contacted, staff blocked) — see the Day 7 note in `owl_system/docs/TESTING_SYSTEM.md`
2. Add the function name to `ot_get_test_manifest()` in `owl_system/includes/dashboard/dashboard-main.php`, with a `label`, `critical` flag, and the right area group. **Not optional** — `tests/test_manifest_drift.py` fails the suite if a test function and a manifest entry don't both exist (docs/TESTING_REBUILD_SPEC.md Days 11-12)
3. If the test creates data, use the `cleanup_after` fixture and ensure records are flagged with `_ot_test_post = 1`
4. Update the Current Tests table in `owl_system/docs/TESTING_SYSTEM.md`
5. Add or update the plain-English manual-run instructions at `owl_system/docs/testing-manual/<group-slug>/<test_name>.md` (group slug = the manifest group from step 2, lowercased with hyphens) — this is a source file for the generated staff guide at `owl_system/docs/guides/testing.md`; **any test that changes and doesn't get its instructions reviewed will leave that guide silently wrong.** After editing, regenerate it: `wp eval-file scripts/build-testing-guide.php --path="C:/laragon/www/owltutors" --user=1` (run from the `owl_system` plugin directory)

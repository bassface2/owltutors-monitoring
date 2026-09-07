import pytest

# Throwaway diagnostic, not a permanent test -- delete after use. Checks
# whether otdev1602's /login/ page actually serves Google's test site key
# client-side, to distinguish "the fix isn't being delivered" from "the test
# key itself doesn't work for reCAPTCHA v3" (see owl_system/docs/TO_DO.md,
# reCAPTCHA entry, 7 Sept 2026).
EXPECTED_TEST_SITE_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"


@pytest.mark.diagnostic
def test_zzz_recaptcha_site_key_diagnostic(page, base_url):
    page.goto(f"{base_url}/login/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)  # let enqueued scripts settle

    site_key = page.evaluate(
        "window.recaptcha_verify_args ? window.recaptcha_verify_args.site_key : 'UNDEFINED'"
    )
    script_src = page.evaluate(
        """() => {
            const s = document.querySelector('script[src*="recaptcha/api.js"]');
            return s ? s.src : 'NOT FOUND';
        }"""
    )
    print(f"\n[DIAGNOSTIC] recaptcha_verify_args.site_key = {site_key!r}")
    print(f"[DIAGNOSTIC] google-recaptcha script src      = {script_src!r}")

    assert site_key == EXPECTED_TEST_SITE_KEY, (
        f"Expected the test site key {EXPECTED_TEST_SITE_KEY!r}, "
        f"got {site_key!r} -- the fix isn't reaching the browser (cache/delivery issue)."
    )

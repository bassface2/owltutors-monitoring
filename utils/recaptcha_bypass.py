from playwright.sync_api import Page


def inject_recaptcha_bypass(page: Page, api_key: str, form_id: str = "ot_login"):
    """Injects the hidden field recaptcha_verify.js's otTestBypassActive()
    checks for, so the login/registration form submits directly instead of
    waiting on grecaptcha.execute() -- which hangs indefinitely against
    Google's real v3 service for headless CI traffic, with no test key pair
    that reliably passes it (owl_system/docs/TO_DO.md, reCAPTCHA entry,
    7 Sept 2026).

    Must be called before the submit button is clicked. Mirrors the same
    page.evaluate()-injected-hidden-field pattern already used for the
    contact form's ot_test_api_key field (conftest.py's stage3_job/
    returning_client_login) -- nothing is rendered server-side for this;
    the field only exists because the test put it there.

    The real security boundary is server-side (Login.php's
    is_test_recaptcha_bypass(): hash_equals(OWL_TEST_API_KEY, ...) + a
    dev/staging domain check) -- this field alone does nothing against a
    real login if the key doesn't match.

    form_id: the form this bypass needs to live inside ("ot_login" for
    login, "signupform" for tutor/pre-applicant registration).
    """
    page.evaluate(
        """([formId, key]) => {
            const form = document.getElementById(formId);
            if (!form) return;
            let el = document.getElementById('ot_test_api_key');
            if (!el) {
                el = document.createElement('input');
                el.type = 'hidden';
                el.id = 'ot_test_api_key';
                el.name = 'ot_test_api_key';
                form.appendChild(el);
            }
            el.value = key;
        }""",
        [form_id, api_key],
    )

import hashlib
import hmac
import json
import time
import requests
import pytest
from playwright.sync_api import Page, expect

from utils.auth import auth_headers, is_basic_auth_configured
from utils.details import write_detail

LOGIN_URL = "/login/"

_BASIC_AUTH_SKIP_REASON = (
    "Target environment is gated by platform-level HTTP Basic Auth (e.g. "
    "otdev1602) -- it blocks this deliberately unauthenticated request before "
    "WordPress/REST routing ever sees it, the same as it would a real Stripe "
    "webhook. Only runs where there's no such gate (local/production)."
)

# Real local-environment webhook signing secrets, from the switch block in
# services/stripe/system.php's ot_handle_stripe_webhook_connection() — the
# 'http://owltutors.test' case. Not a live secret in the sense of gating
# anything sensitive: it only lets us construct a validly-*signed* payload for
# our own local endpoint, the same thing the real Stripe CLI would do.
PLATFORM_WEBHOOK_SECRET = "whsec_e25879af2e512df33b06748bb2c354dcb9781d8449074b4e479cb793b391e080"
CONNECT_WEBHOOK_SECRET = "whsec_e25879af2e512df33b06748bb2c354dcb9781d8449074b4e479cb793b391e080"


def _stripe_signed_headers(payload_bytes: bytes, secret: str) -> dict:
    """Replicates \\Stripe\\Webhook::constructEvent()'s expected signature:
    Stripe-Signature: t=<unix ts>,v1=<hex hmac-sha256(secret, f'{ts}.{payload}')>
    """
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "Stripe-Signature": f"t={timestamp},v1={signature}",
    }


def _fake_event(object_type: str, event_type: str, timesheet_id: str = "999999999") -> bytes:
    """A structurally valid Stripe event pointing at a timesheet ID that does
    not exist. ot_stripe_webhook_check() (system.php) finds no
    stripe_invoice_id for it and returns false, so both webhook handlers take
    their early-exit {'ignored': true, 'reason': 'Not billed in Stripe!'} path
    with a 200 — exercising real signature verification without triggering
    any of the (heavier, side-effecting) per-event-type business logic."""
    return json.dumps({
        "id": "evt_test_" + object_type,
        "object": "event",
        "type": event_type,
        "data": {
            "object": {
                "id": ("in_test" if object_type == "invoice" else "po_test"),
                "object": object_type,
                "status": "open",
                "metadata": {"timesheet_id": timesheet_id},
            }
        },
    }).encode()


@pytest.mark.tutors
@pytest.mark.critical
@pytest.mark.skipif(is_basic_auth_configured(), reason=_BASIC_AUTH_SKIP_REASON)
def test_platform_webhook_returns_200_for_valid_signed_payload(base_url: str):
    """
    /wp-json/owl/v1/stripe-webhook-platform accepts a genuinely-signed Stripe
    event (real HMAC-SHA256 over the raw payload using the actual local
    webhook secret from system.php's switch block) and returns 200 —
    confirms \\Stripe\\Webhook::constructEvent() signature verification is
    wired correctly for this environment. Uses a nonexistent timesheet_id so
    the handler's own early-exit path is taken, not the full per-event logic.
    Covers: 'Platform webhook endpoint returns 200 for valid signed payload'.
    """
    payload = _fake_event("invoice", "invoice.created")
    headers = _stripe_signed_headers(payload, PLATFORM_WEBHOOK_SECRET)

    resp = requests.post(
        f"{base_url}/wp-json/owl/v1/stripe-webhook-platform",
        data=payload,
        headers=headers,
        timeout=15,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("ignored") is True, f"Expected the early-exit ignored response, got: {data}"

    write_detail("test_platform_webhook_returns_200_for_valid_signed_payload", {
        "message": f"Signed invoice.created event accepted, response: {data}",
    })


@pytest.mark.tutors
@pytest.mark.skipif(is_basic_auth_configured(), reason=_BASIC_AUTH_SKIP_REASON)
def test_webhook_invalid_signature_returns_400_not_500(base_url: str):
    """
    Regression test: a webhook payload with an invalid signature must return
    400 (WordPress's ot_handle_stripe_webhook_connection() correctly catches
    Stripe's SignatureVerificationException and returns a 400 WP_REST_Response),
    not a PHP fatal 500.

    Found and fixed 28 Aug 2026 while verifying this exact scenario: all three
    handlers (platform, connect, owl_plus in services/stripe/system.php) took
    that 400 WP_REST_Response and immediately did $event['type'] on it without
    checking what they'd gotten back — "Cannot use object of type
    WP_REST_Response as array", an uncaught fatal turning every malformed or
    invalid-signature webhook request into a 500. Fixed with an
    `instanceof WP_REST_Response` guard in all three handlers.
    Covers a gap the doc's original 'returns 200 for a valid signed payload'
    wording didn't — the failure path is equally important here since Stripe
    retries on 5xx but not on 4xx.
    """
    payload = _fake_event("invoice", "invoice.created")
    resp = requests.post(
        f"{base_url}/wp-json/owl/v1/stripe-webhook-platform",
        data=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bogus"},
        timeout=15,
    )
    assert resp.status_code == 400, (
        f"Expected 400 for an invalid signature, got {resp.status_code}: {resp.text[:300]}"
    )

    write_detail("test_webhook_invalid_signature_returns_400_not_500", {
        "message": "Invalid-signature webhook correctly rejected with 400 (not a 500 fatal)",
    })


@pytest.mark.tutors
@pytest.mark.skipif(is_basic_auth_configured(), reason=_BASIC_AUTH_SKIP_REASON)
def test_connect_webhook_returns_200_for_valid_signed_payload(base_url: str):
    """
    /wp-json/owl/v1/stripe-webhook-connect accepts a genuinely-signed Stripe
    Connect event and returns 200. Same signature-verification approach and
    safe early-exit path as the platform webhook test above.
    Covers: 'Connect webhook endpoint returns 200 for valid signed payload'.
    """
    payload = _fake_event("payout", "payout.paid")
    headers = _stripe_signed_headers(payload, CONNECT_WEBHOOK_SECRET)

    resp = requests.post(
        f"{base_url}/wp-json/owl/v1/stripe-webhook-connect",
        data=payload,
        headers=headers,
        timeout=15,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("ignored") is True, f"Expected the early-exit ignored response, got: {data}"

    write_detail("test_connect_webhook_returns_200_for_valid_signed_payload", {
        "message": f"Signed payout.paid event accepted, response: {data}",
    })


@pytest.mark.tutors
@pytest.mark.critical
def test_add_card_checkout_session_returns_stripe_session(page: Page, base_url: str, client_credentials):
    """
    A logged-in client's 'Add payment method' action fires ot_create_checkout_session
    (type=add_payment_method) via AJAX. The response contains a real Stripe
    Checkout Session ID (cs_...) — not literally a URL: the front-end
    (ot_logged_in_client.js) uses Stripe.js's stripe.redirectToCheckout({sessionId})
    to navigate to Stripe's hosted page from that ID, rather than the server
    returning session.url directly. Calls the AJAX action directly (same
    direct-AJAX pattern used elsewhere in this suite) rather than driving the
    dynamically-loaded payment tab UI just to click one button.
    Covers: 'Add card — ot_create_checkout_session returns a Stripe Checkout
    session' (doc wording corrected 28 Aug 2026 — see TESTING_CHANGELOG.md).
    """
    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("domcontentloaded")
    page.locator("#ot_login_name").fill(client_credentials["email"])
    page.locator("#pw1").fill(client_credentials["password"])
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=90000)

    resp = page.request.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        form={"action": "ot_create_checkout_session", "type": "add_payment_method"},
    )
    assert resp.status == 200, f"ot_create_checkout_session returned {resp.status}"
    data = resp.json()
    assert data.get("id", "").startswith("cs_"), (
        f"Expected a Stripe Checkout Session ID (cs_...), got: {data}"
    )

    write_detail("test_add_card_checkout_session_returns_stripe_session", {
        "message": f"ot_create_checkout_session returned session {data['id']}",
    })


def _create_and_login_disposable_client(page: Page, base_url: str, api_key: str) -> dict:
    resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_create_test_client", "api_key": api_key},
        headers=auth_headers(base_url),
        timeout=15,
    )
    resp.raise_for_status()
    client = resp.json()
    assert client.get("success"), f"owl_create_test_client failed: {client}"

    page.goto(f"{base_url}{LOGIN_URL}")
    expect(page.locator("#ot_login")).to_be_visible()
    page.wait_for_load_state("domcontentloaded")
    page.locator("#ot_login_name").fill(client["client_email"])
    page.locator("#pw1").fill(client["client_password"])
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: LOGIN_URL not in url, timeout=90000)

    return client


def _create_checkout_session_and_get_url(page: Page, base_url: str, api_key: str) -> str:
    resp = page.request.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        form={"action": "ot_create_checkout_session", "type": "add_payment_method"},
    )
    session_id = resp.json()["id"]

    resp = page.request.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        form={"action": "owl_get_test_checkout_session_url", "api_key": api_key, "session_id": session_id},
    )
    data = resp.json()
    assert data.get("success"), f"owl_get_test_checkout_session_url failed: {data}"
    return data["url"]


def _fill_stripe_hosted_checkout_card(page: Page, card_number: str):
    """Fills Stripe's hosted Checkout page (not the embedded Card Element used
    in test_group_tuition.py) — separate cardNumber/cardExpiry/cardCvc inputs,
    plus billing name/address (billing_address_collection: required for
    add_payment_method)."""
    page.locator("#cardNumber").fill(card_number)
    page.locator("#cardExpiry").fill("12/34")
    page.locator("#cardCvc").fill("123")
    billing_name = page.locator("#billingName")
    if billing_name.count() > 0:
        billing_name.fill("Owl TestBot")
    page.locator("#billingAddressLine1").fill("1 Test Street")
    page.locator("#billingLocality").fill("London")
    page.locator("#billingPostalCode").fill("SW1A 1AA")
    country = page.locator("#billingCountry")
    if country.count() > 0:
        country.select_option("GB")
    page.locator('button[type="submit"], .SubmitButton').first.click()


@pytest.mark.tutors
@pytest.mark.critical
def test_post_checkout_return_saves_card_and_sets_client_active(
    page: Page, base_url: str, api_key: str
):
    """
    Completing a real Stripe-hosted Checkout (setup mode, test card) and
    returning to ?setup_payment=true&session_id={id} triggers
    ot_stripe_update_ot_records() (hooked in header.php on every page load),
    which saves the card (last_4_digits_of_card, card_expiry), sets
    payment_method='Card Payment', and sets client_status='Active'.

    Uses a fresh disposable client (owl_create_test_client) rather than the
    shared client_credentials fixture, since this permanently mutates
    Stripe/billing state that other tests assume stays at its default.
    ot_create_checkout_session() only returns the session ID (the real
    front-end uses stripe.redirectToCheckout({sessionId}) client-side); the
    new owl_get_test_checkout_session_url endpoint resolves the real
    Stripe-hosted URL server-side so Playwright can navigate there directly,
    without ever exposing the live Stripe secret key to test code.
    Covers: 'Post-checkout return saves card and sets client_status=Active'.
    """
    client = _create_and_login_disposable_client(page, base_url, api_key)
    checkout_url = _create_checkout_session_and_get_url(page, base_url, api_key)

    page.goto(checkout_url, wait_until="domcontentloaded")
    _fill_stripe_hosted_checkout_card(page, "4242424242424242")

    # Stripe redirects to success_url (?setup_payment=true&session_id=...),
    # which header.php detects and calls ot_stripe_update_ot_records() inline
    # on that same page load — which itself then redirects on to the
    # customer metadata's stored referrer_url (?payment_method_added=true&
    # from_stripe=true...). Both hops can complete before Playwright's next
    # poll, so page.wait_for_url() (which waits for a *future* navigation
    # event) can miss them entirely if they already happened by the time it's
    # called — poll page.url directly instead.
    for _ in range(30):
        if "checkout.stripe.com" not in page.url:
            break
        page.wait_for_timeout(1000)
    else:
        pytest.fail(f"Still on Stripe's hosted checkout after 30s: {page.url}")
    page.wait_for_load_state("networkidle")

    fields_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_get_test_client_fields", "api_key": api_key, "client_id": client["client_id"]},
        headers=auth_headers(base_url),
        timeout=15,
    )
    fields = fields_resp.json()
    assert fields.get("client_status") == "Active", f"Expected client_status=Active, got: {fields}"
    assert fields.get("payment_method") == "Card Payment", f"Expected payment_method='Card Payment', got: {fields}"
    assert fields.get("last_4_digits_of_card") == "4242", f"Expected last 4 digits 4242, got: {fields}"

    write_detail("test_post_checkout_return_saves_card_and_sets_client_active", {
        "message": f"Client {client['client_email']}: card saved, client_status=Active",
    })


@pytest.mark.tutors
def test_prepaid_card_rejected(page: Page, base_url: str, api_key: str):
    """
    A prepaid test card (Stripe's documented 5105 1051 0510 5100 — a
    Mastercard with funding='prepaid', per Stripe's testing docs) is accepted
    by Stripe's hosted Checkout (setup mode doesn't distinguish card funding
    type at that layer), but ot_stripe_update_ot_records() detects
    card->funding == 'prepaid' server-side, detaches it, sets
    payment_method='--None--', and sets stripe_used_prepay_card=1.

    Confirmed directly against the Stripe API (not assumed) before writing
    this: the previously-remembered "4000 0566 5566 5556" test card actually
    returns funding='debit' now, not 'prepaid' — verified via
    Stripe\\PaymentMethod::all() against a real customer created by the
    other checkout tests in this file. 5105... is documented current at
    docs.stripe.com/testing (28 Aug 2026).
    Covers: 'Prepaid card rejected — stripe_used_prepay_card=1, error shown'.
    """
    client = _create_and_login_disposable_client(page, base_url, api_key)
    checkout_url = _create_checkout_session_and_get_url(page, base_url, api_key)

    page.goto(checkout_url, wait_until="domcontentloaded")
    _fill_stripe_hosted_checkout_card(page, "5105105105105100")

    for _ in range(30):
        if "checkout.stripe.com" not in page.url:
            break
        page.wait_for_timeout(1000)
    else:
        pytest.fail(f"Still on Stripe's hosted checkout after 30s: {page.url}")
    page.wait_for_load_state("networkidle")

    fields_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_get_test_client_fields", "api_key": api_key, "client_id": client["client_id"]},
        headers=auth_headers(base_url),
        timeout=15,
    )
    fields = fields_resp.json()
    assert fields.get("stripe_used_prepay_card") is True, f"Expected stripe_used_prepay_card=True, got: {fields}"
    assert fields.get("payment_method") == "--None--", f"Expected payment_method='--None--', got: {fields}"

    write_detail("test_prepaid_card_rejected", {
        "message": f"Client {client['client_email']}: prepaid card correctly rejected, stripe_used_prepay_card=True",
    })

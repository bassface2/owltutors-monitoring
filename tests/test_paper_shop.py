import re
import requests
from playwright.sync_api import Page, expect
from utils.auth import auth_headers
from utils.cleanup import delete_test_posts
from utils.details import write_detail
from utils.wc_checkout import complete_native_wc_checkout
import pytest

# Generic exam papers page — confirm this URL is correct before first run
PAPERS_URL = "/exam-papers/"


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


@pytest.mark.papers
def test_papers_load(page: Page, base_url: str):
    """Paper cards render in the catalogue grid."""
    page.goto(f"{base_url}{PAPERS_URL}")
    expect(page.locator("#exam_paper_links .paper-card")).not_to_have_count(0)
    write_detail("test_papers_load", {
        "message": "Exam papers catalogue loaded with paper cards visible",
    })


@pytest.mark.papers
def test_papers_ajax_filter(page: Page, base_url: str):
    """Selecting a subject filter returns a non-empty result set via AJAX."""
    page.goto(f"{base_url}{PAPERS_URL}")
    # Select the second option (index 1) — index 0 is "All subjects"
    page.locator("#paper_subject_filter").select_option(index=1)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#exam_paper_links .paper-card")).not_to_have_count(0)
    write_detail("test_papers_ajax_filter", {
        "message": "Exam papers AJAX filter returned results for selected subject",
    })


@pytest.mark.papers
def test_papers_load_more(page: Page, base_url: str):
    """Clicking 'Load more papers' appends additional paper cards via AJAX."""
    page.goto(f"{base_url}{PAPERS_URL}")
    page.wait_for_selector("#exam_paper_links .paper-card", timeout=10000)
    initial_count = page.locator("#exam_paper_links .paper-card").count()
    page.locator("#load_more_papers").scroll_into_view_if_needed()
    page.locator("#load_more_papers").click()
    page.wait_for_function(
        f"document.querySelectorAll('#exam_paper_links .paper-card').length > {initial_count}",
        timeout=15000,
    )
    total_count = page.locator("#exam_paper_links .paper-card").count()
    # Scroll to the first newly loaded card
    page.locator("#exam_paper_links .paper-card").nth(initial_count).scroll_into_view_if_needed()
    write_detail("test_papers_load_more", {
        "message": f"Load More clicked — {initial_count} initial papers expanded to {total_count}, scrolled to newly loaded content",
    })


@pytest.mark.papers
@pytest.mark.critical
def test_general_basket_checkout_flow(page: Page, base_url: str, api_key: str, cleanup_after):
    """
    The ordinary (non-CEM/DBS) paper-purchase flow, distinct from the
    native-cart-only CEM/DBS checkout tests: add a paper to the sessionStorage
    basket via .ot-add-to-cart, confirm cross-sell suggestions render on the
    basket page, then complete a real Stripe-test-mode checkout.

    The click handler and sessionStorage logic (.ot-add-to-cart -> addToCart()
    -> sessionStorage['ot_cart_items']) live in owl_system/js/ot_cart.js, NOT
    in any theme JS file — the reason this test went unwritten for so long
    ("not found in any theme JS file by name/content search") was simply
    that the earlier search never looked in the plugin's own js/ directory.

    Two distinct WooCommerce UIs in one flow, confirmed directly rather than
    assumed: the basket/cart page (/basket/) renders via the *classic*
    [woocommerce_cart] shortcode (page-basket.php), with real .cross-sells
    and a.checkout-button markup -- unlike /checkout/, which runs the
    Blocks/React checkout (see docs/woocommerce.md and
    utils/wc_checkout.py's complete_native_wc_checkout()). The sessionStorage
    cart only syncs into WooCommerce's real cart when the floating widget's
    own "Checkout" button (#ot-cart-checkout) is clicked -- it calls
    ot_add_to_cart_bulk via AJAX first, so simply navigating to /basket/
    without going through that button leaves WC's real cart empty.
    """
    page.goto(f"{base_url}{PAPERS_URL}", wait_until="domcontentloaded")
    try:
        page.locator("#ot_local_storage_accept").click(timeout=3000)
    except Exception:
        pass
    page.wait_for_selector(".ot-add-to-cart", timeout=10000)

    add_btn = page.locator(".ot-add-to-cart").first
    product_name = add_btn.get_attribute("data-product-name")
    add_btn.click()
    page.wait_for_timeout(1500)

    cart_items = page.evaluate("JSON.parse(sessionStorage.getItem('ot_cart_items') || '[]')")
    assert len(cart_items) == 1, f"Expected 1 item in the sessionStorage basket, got: {cart_items}"

    # Sync sessionStorage -> real WC cart (ot_add_to_cart_bulk) and land on /basket/
    page.locator("#ot-cart-checkout").click()
    page.wait_for_url(lambda u: "/basket/" in u, timeout=15000)

    cross_sells = page.locator(".cross-sells")
    expect(cross_sells).to_be_visible(timeout=10000)

    page.locator("a.checkout-button").first.click()
    page.wait_for_url(lambda u: "/checkout/" in u, timeout=15000)

    unique = re.sub(r"[^0-9]", "", str(id(page)))[-8:]
    email = f"testbot.basket.{unique}@owltutors.co.uk"
    order_id = complete_native_wc_checkout(page, base_url, email)

    order_resp = requests.post(
        f"{base_url}/wp-admin/admin-ajax.php",
        data={"action": "owl_get_test_order_fields", "api_key": api_key, "order_id": order_id},
        headers=auth_headers(base_url),
        timeout=15,
    )
    order_resp.raise_for_status()
    order = order_resp.json()
    assert order.get("success"), f"owl_get_test_order_fields failed: {order}"
    assert order["status"] in ("processing", "completed"), f"Expected a paid order status, got: {order['status']}"
    assert len(order["items"]) >= 1, f"Expected at least 1 line item, got: {order['items']}"
    if product_name:
        # data-product-name (HTML-attribute-escaped) renders a real em-dash for
        # the theme's " — " separator; the order line item's name (WC's own
        # get_name(), a plain DB string) uses a bare hyphen for the same
        # character -- found while validating this test. Not a real
        # discrepancy, just two different escaping paths for the same title,
        # so normalise dash characters before comparing rather than drop the
        # check entirely.
        normalise = lambda s: re.sub(r"[‒-―−]", "-", s)
        item_names = [normalise(item["name"]) for item in order["items"]]
        assert any(normalise(product_name) in name for name in item_names), (
            f"Expected the added paper ({product_name!r}) among the order's line items, got: {item_names}"
        )

    write_detail("test_general_basket_checkout_flow", {
        "message": f"Order {order_id} created via sessionStorage basket checkout, cross-sells rendered, status={order['status']}",
        "order_id": order_id,
    })

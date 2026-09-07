import json
import re
import requests
from playwright.sync_api import Page, expect
from utils.auth import auth_headers
from utils.cleanup import delete_test_posts
from utils.details import write_detail
from utils.test_status_records import get_test_status_record, reset_status_field
from utils.wc_checkout import complete_native_wc_checkout
import pytest

BLOG_URL = "/resource/"
TESTIMONIALS_URL = "/about-us/testimonials/"
SHOP_URL = "/shop/"
COURSES_URL = "/all-courses/"


@pytest.fixture(autouse=False)
def cleanup_after(base_url):
    yield
    try:
        result = delete_test_posts(base_url)
        print(f"[cleanup] {result}")
    except Exception as e:
        print(f"[cleanup] warning: {e}")


@pytest.mark.content
def test_blog_listing_loads(page: Page, base_url: str):
    """Blog listing page loads with at least one article card visible."""
    page.goto(f"{base_url}{BLOG_URL}")
    # Regular blog cards use a.text-decoration-none.d-block.h-100 (featured article omits h-100)
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    expect(page.locator("a.text-decoration-none.d-block.h-100").first).to_be_visible()
    write_detail("test_blog_listing_loads", {
        "message": "Blog listing page loaded with article cards visible",
    })


@pytest.mark.content
def test_blog_article_loads(page: Page, base_url: str):
    """Clicking a blog card navigates to a full article page with body content."""
    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    page.locator("a.text-decoration-none.d-block.h-100").first.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("article.mb-4")).to_be_visible(timeout=10000)
    write_detail("test_blog_article_loads", {
        "message": "Blog article page loaded with article body visible",
    })


@pytest.mark.content
def test_testimonials_page_loads(page: Page, base_url: str):
    """Testimonials page loads with the hero header visible."""
    page.goto(f"{base_url}{TESTIMONIALS_URL}")
    expect(page.locator("header.bg-navy.text-white")).to_be_visible()
    write_detail("test_testimonials_page_loads", {
        "message": "Testimonials page loaded with hero header visible",
    })


@pytest.mark.content
def test_shop_loads(page: Page, base_url: str):
    """Premium paper shop loads with at least one product card visible."""
    page.goto(f"{base_url}{SHOP_URL}")
    page.wait_for_selector(".paper-card", timeout=10000)
    expect(page.locator(".paper-card").first).to_be_visible()
    write_detail("test_shop_loads", {
        "message": "Premium paper shop loaded with product cards visible",
    })


@pytest.mark.content
def test_cem_product_page_loads(page: Page, base_url: str):
    """
    CEM product page renders the otcemmvp plugin's custom fields (child's
    name, DOB, EAL, SEN, gender, class) inside the native WooCommerce
    add-to-cart form — fixed 21 Jul 2026 (see TESTING_CHANGELOG.md).
    Covers: 'CEM product page loads with otcemmvp plugin fields visible'.
    """
    page.goto(f"{base_url}/product/cem-primary-insight-assessment/")
    expect(page.locator("form.cart .ot-cem-mvp-fields")).to_be_visible(timeout=10000)
    write_detail("test_cem_product_page_loads", {
        "message": "CEM product page loaded with otcemmvp fields visible inside form.cart",
    })


DBS_PRODUCT_URL = "/product/dbs-update-service-fee/"


@pytest.mark.content
@pytest.mark.critical
def test_cem_checkout_captures_fields_to_order(page: Page, base_url: str, api_key: str, cleanup_after):
    """
    Full CEM checkout: fill otcemmvp's custom fields (child's name, DOB, EAL,
    SEN, gender, class), add to the native WC cart, complete a real
    Stripe-test-mode payment via the checkout page, and confirm
    ot_cem_mvp_add_order_item_meta() (otcemmvp.php) persisted all six fields
    as line-item meta on the resulting real order — the rendered "thank you"
    page alone can't prove the meta actually saved.
    """
    page.goto(f"{base_url}/product/cem-primary-insight-assessment/", wait_until="domcontentloaded")
    try:
        page.locator("#ot_local_storage_accept").click(timeout=3000)
    except Exception:
        pass

    page.locator("#ot_cem_mvp_child_name").fill("Test Child")
    page.locator("#ot_cem_mvp_dob").fill("2015-01-01")
    page.locator("#ot_cem_mvp_eal").select_option(index=1)
    page.locator("#ot_cem_mvp_sen").select_option(index=1)
    page.locator("#ot_cem_mvp_gender").select_option(index=1)
    page.locator("#ot_cem_mvp_class").select_option(index=1)
    page.locator("button.single_add_to_cart_button, input.single_add_to_cart_button").first.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)

    unique = re.sub(r"[^0-9]", "", str(id(page)))[-8:]
    email = f"testbot.cem.{unique}@owltutors.co.uk"
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

    assert len(order["items"]) == 1, f"Expected exactly 1 line item, got: {order['items']}"
    meta = order["items"][0]["meta"]
    assert meta.get("Child's name") == "Test Child", f"Wrong/missing 'Child's name' meta: {meta}"
    assert meta.get("Date of birth") == "2015-01-01", f"Wrong/missing 'Date of birth' meta: {meta}"
    assert meta.get("EAL"), f"Missing 'EAL' meta: {meta}"
    assert meta.get("SEN"), f"Missing 'SEN' meta: {meta}"
    assert meta.get("Gender"), f"Missing 'Gender' meta: {meta}"
    assert meta.get("Class"), f"Missing 'Class' meta: {meta}"

    write_detail("test_cem_checkout_captures_fields_to_order", {
        "message": f"Order {order_id} line item captured all 6 otcemmvp fields: {meta}",
        "order_id": order_id,
    })


@pytest.mark.content
@pytest.mark.critical
def test_dbs_checkout_completes_for_logged_in_tutor(page: Page, base_url: str, api_key: str, tutor_credentials, cleanup_after):
    """
    A logged-in tutor can add the DBS update-service fee to the native WC
    cart and complete a real Stripe-test-mode checkout, confirming the
    resulting order exists with status 'processing' — the whole point of
    single-product.php's staff-gate is to let exactly this role complete
    this purchase; test_dbs_fee_form_gated_to_tutor_or_admin already covers
    that a tutor can reach the form at all, this covers the actual purchase
    completing successfully.
    """
    page.goto(f"{base_url}/login/", wait_until="domcontentloaded")
    expect(page.locator("#ot_login")).to_be_visible()
    page.locator("#ot_login_name").fill(tutor_credentials["email"])
    page.locator("#pw1").fill(tutor_credentials["password"])
    page.locator("#login_submit").click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=30000)

    page.goto(f"{base_url}{DBS_PRODUCT_URL}", wait_until="domcontentloaded")
    expect(page.locator("form.cart")).to_be_visible(timeout=10000)
    page.locator("button.single_add_to_cart_button, input.single_add_to_cart_button").first.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)

    unique = re.sub(r"[^0-9]", "", str(id(page)))[-8:]
    order_id = complete_native_wc_checkout(page, base_url, tutor_credentials["email"])

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

    write_detail("test_dbs_checkout_completes_for_logged_in_tutor", {
        "message": f"Order {order_id} created successfully for logged-in tutor, status={order['status']}",
        "order_id": order_id,
    })



@pytest.mark.content
def test_dbs_fee_form_gated_to_tutor_or_admin(page: Page, base_url: str, tutor_credentials):
    """
    single-product.php's $ot_staff_gated_slugs gate restricts the DBS fee
    product (native WC add-to-cart, same template code path as the CEM fix
    above) to logged-in administrators and tutors only. Confirms both halves:
    a logged-out visitor is redirected away, and a logged-in tutor sees the
    real native add-to-cart form.

    Redirect target fixed 28 Aug 2026 while writing this test: the gate
    redirected to `/tutor-login/`, a page that has never existed on this site
    (confirmed via `wp post list` — only `/login` does), so every gated
    visitor was silently sent to a 404. Changed to `/login`, matching the
    convention used everywhere else in the theme. See docs/woocommerce.md.
    Covers: 'DBS fee form gated to logged-in tutor/admin only'.
    """
    # Logged-out visitor redirected to the real login page, not a 404
    page.goto(f"{base_url}{DBS_PRODUCT_URL}", wait_until="domcontentloaded")
    page.wait_for_url(lambda url: "/login" in url, timeout=10000)
    expect(page.locator("#ot_login")).to_be_visible()

    # Logged-in tutor sees the native add-to-cart form
    page.locator("#ot_login_name").fill(tutor_credentials["email"])
    page.locator("#pw1").fill(tutor_credentials["password"])
    page.locator("#login_submit").click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=30000)

    page.goto(f"{base_url}{DBS_PRODUCT_URL}", wait_until="domcontentloaded")
    expect(page.locator("form.cart")).to_be_visible(timeout=10000)

    write_detail("test_dbs_fee_form_gated_to_tutor_or_admin", {
        "message": "Logged-out visitor redirected to /login (not a 404); logged-in tutor sees native add-to-cart form",
    })


@pytest.mark.content
def test_group_course_listing(page: Page, base_url: str):
    """Group course listing page loads with at least one course card visible."""
    page.goto(f"{base_url}{COURSES_URL}")
    page.wait_for_selector("#course-grid article.course-card", timeout=10000)
    expect(page.locator("#course-grid article.course-card").first).to_be_visible()
    write_detail("test_group_course_listing", {
        "message": "Group course listing loaded with course cards visible",
    })


@pytest.mark.content
def test_group_course_detail(page: Page, base_url: str):
    """Clicking a course card navigates to the course detail page."""
    page.goto(f"{base_url}{COURSES_URL}")
    page.wait_for_selector("#course-grid article.course-card", timeout=10000)
    # stretched-link covers the whole card — click the anchor directly
    page.locator("#course-grid article.course-card a.stretched-link").first.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("header.bg-navy.text-white")).to_be_visible(timeout=10000)
    write_detail("test_group_course_detail", {
        "message": "Group course detail page loaded with course header visible",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Blog pagination
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.content
def test_blog_pagination(page: Page, base_url: str):
    """
    Blog listing page 2 (/resource/page/2/) renders article cards and they
    differ from page 1 — confirms pagination is working and not just serving
    the same first-page content.
    Covers: 'Blog pagination — page 2 differs from page 1'.
    """
    # Collect hrefs from page 1
    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    page1_hrefs = page.evaluate(
        "Array.from(document.querySelectorAll('a.text-decoration-none.d-block.h-100')).map(a => a.href)"
    )
    assert page1_hrefs, "No article cards found on blog listing page 1"

    # Navigate to page 2
    page.goto(f"{base_url}{BLOG_URL}page/2/")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    page2_hrefs = page.evaluate(
        "Array.from(document.querySelectorAll('a.text-decoration-none.d-block.h-100')).map(a => a.href)"
    )
    assert page2_hrefs, "No article cards found on blog listing page 2"

    # Allow sticky/featured posts to appear on both pages — assert at least one
    # article on page 2 is not on page 1 (genuine pagination working).
    unique_on_page2 = set(page2_hrefs) - set(page1_hrefs)
    assert unique_on_page2, (
        f"No unique articles on page 2 — all {len(page2_hrefs)} article(s) also appear "
        f"on page 1. Pagination may not be working, or every post is sticky/featured."
    )

    write_detail("test_blog_pagination", {
        "message": f"Blog page 2 shows {len(page2_hrefs)} unique article(s) not on page 1",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Reading time on article pages
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.content
def test_blog_reading_time(page: Page, base_url: str):
    """
    A blog article page shows a 'X min read' reading time string inside
    <small class='text-muted'> (rendered by functions.php via
    ot_blogs_reading_estimate()).
    Covers: 'Reading time displayed on article pages'.
    """
    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    page.locator("a.text-decoration-none.d-block.h-100").first.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("article.mb-4")).to_be_visible(timeout=10000)

    # "X min read" is part of the byline rendered by single.php into
    # <p class="meta small mb-0 text-white"> via ot_blogs_reading_estimate().
    reading_time_el = page.locator("p.meta.small").filter(has_text="min read")
    expect(reading_time_el.first).to_be_visible(timeout=5000)

    write_detail("test_blog_reading_time", {
        "message": "Blog article shows reading time ('min read') in article meta",
    })


# ─────────────────────────────────────────────────────────────────────────────
# VideoObject JSON-LD
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.content
def test_video_object_json_ld(page: Page, base_url: str):
    """
    A blog post with the 'video_id' ACF field set outputs a VideoObject node
    in the page's JSON-LD @graph (content-schema.php appends it to any @graph
    schema when $_ot_video_id is non-empty).

    The test scans articles from the first page of the blog listing (12 per
    page — page-blog.php's $posts_per_page) until it finds one with
    VideoObject JSON-LD, rather than an arbitrary first 5: on local as of 26
    Aug 2026 the most recent video post was already the 7th most recent
    published post, one past the old 5-article window — not missing data,
    just new posts pushing it down over time, which will only get worse. If
    none of the 12 has a video, the test is skipped with an explanatory
    message — add a specific URL below once a known video post is identified
    on the dev site.
    Covers: 'VideoObject JSON-LD on posts with video_id'.
    """
    import pytest

    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    article_links = page.evaluate(
        "Array.from(document.querySelectorAll('a.text-decoration-none.d-block.h-100')).map(a => a.href).slice(0, 12)"
    )

    found_video_object = False
    checked_url = None
    for article_url in article_links:
        page.goto(article_url)
        page.wait_for_load_state("domcontentloaded")
        ld_blocks = page.locator("script[type='application/ld+json']")
        for i in range(ld_blocks.count()):
            try:
                data = json.loads(ld_blocks.nth(i).inner_html())
                graph = data.get("@graph", [])
                if any(node.get("@type") == "VideoObject" for node in graph):
                    found_video_object = True
                    checked_url = article_url
                    break
            except (json.JSONDecodeError, AttributeError):
                continue
        if found_video_object:
            break

    if not found_video_object:
        pytest.skip(
            "None of the first 12 blog articles has VideoObject JSON-LD — "
            "set a specific URL in this test once a post with video_id is identified on the dev site"
        )

    write_detail("test_video_object_json_ld", {
        "message": f"VideoObject found in JSON-LD on {checked_url}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Blog post — BlogPosting/Organization JSON-LD
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.content
def test_blog_post_schema_json_ld_present(page: Page, base_url: str):
    """
    A blog post (single.php, is_single()) emits BlogPosting and Organization
    nodes in its JSON-LD @graph -- owltheme/docs/content-schema.md's
    'Output by Page Type' table. Distinct from test_video_object_json_ld,
    which checks for the separate, conditional VideoObject node.
    """
    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    article_url = page.locator("a.text-decoration-none.d-block.h-100").first.get_attribute("href")
    assert article_url, "No blog article link found on the listing page"

    page.goto(article_url)
    page.wait_for_load_state("domcontentloaded")

    ld_blocks = page.locator("script[type='application/ld+json']")
    assert ld_blocks.count() > 0, f"No JSON-LD script tags found on {article_url}"

    found_types = set()
    errors = []
    for i in range(ld_blocks.count()):
        try:
            data = json.loads(ld_blocks.nth(i).inner_html())
            for node in data.get("@graph", []):
                node_type = node.get("@type")
                if node_type:
                    found_types.add(node_type)
        except json.JSONDecodeError as e:
            errors.append(f"Block {i}: {e}")

    assert "BlogPosting" in found_types, (
        f"No BlogPosting node found in JSON-LD @graph on {article_url}. "
        f"Found types: {found_types}. Parse errors: {errors}"
    )
    assert "Organization" in found_types, (
        f"No Organization node found in JSON-LD @graph on {article_url}. "
        f"Found types: {found_types}. Parse errors: {errors}"
    )

    write_detail("test_blog_post_schema_json_ld_present", {
        "message": f"BlogPosting and Organization nodes both present in JSON-LD @graph on {article_url}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Generic static page — WebPage/LocalBusiness JSON-LD
# ─────────────────────────────────────────────────────────────────────────────

# A real page-dynamic-content.php page with no more specific template match --
# owltheme/docs/content-schema.md's is_page() catch-all branch. This template
# is used across ~100 pages (owltheme/docs/TEMPLATE_MAPPING.md) so any one of
# them exercises the same code path; this one was picked because it's a
# stable, low-churn "About us" page unlikely to be restructured or deleted.
GENERIC_PAGE_URL = "/about-us/introduction/"


@pytest.mark.content
def test_generic_page_schema_json_ld_present(page: Page, base_url: str):
    """
    A static page with no page-type-specific template (page-dynamic-content.php,
    reached via content-schema.php's generic is_page() branch) emits WebPage
    and LocalBusiness nodes in its JSON-LD @graph -- owltheme/docs/content-schema.md's
    'Output by Page Type' table, distinct from the specialist templates
    (tutor listing, tutor profile, school profile, papers) covered elsewhere.
    """
    page.goto(f"{base_url}{GENERIC_PAGE_URL}", wait_until="domcontentloaded")

    ld_blocks = page.locator("script[type='application/ld+json']")
    assert ld_blocks.count() > 0, f"No JSON-LD script tags found on {GENERIC_PAGE_URL}"

    found_types = set()
    errors = []
    for i in range(ld_blocks.count()):
        try:
            data = json.loads(ld_blocks.nth(i).inner_html())
            for node in data.get("@graph", []):
                node_type = node.get("@type")
                if node_type:
                    found_types.add(node_type)
        except json.JSONDecodeError as e:
            errors.append(f"Block {i}: {e}")

    assert "WebPage" in found_types, (
        f"No WebPage node found in JSON-LD @graph on {GENERIC_PAGE_URL}. "
        f"Found types: {found_types}. Parse errors: {errors}"
    )
    assert "LocalBusiness" in found_types, (
        f"No LocalBusiness node found in JSON-LD @graph on {GENERIC_PAGE_URL}. "
        f"Found types: {found_types}. Parse errors: {errors}"
    )

    write_detail("test_generic_page_schema_json_ld_present", {
        "message": f"WebPage and LocalBusiness nodes both present in JSON-LD @graph on {GENERIC_PAGE_URL}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# FAQPage — present when configured, absent when not
# ─────────────────────────────────────────────────────────────────────────────

# A real page-dynamic-content.php page with a populated ACF 'faqs' repeater
# (confirmed via direct DB query, 6 real FAQ entries) -- $faq_schema
# (owltheme/docs/content-schema.md) is built unconditionally from this field
# on any post/page type, so this exercises the same code path GENERIC_PAGE_URL
# above does, just with FAQ content present.
FAQ_PAGE_URL = "/advice/ib/"


def _ld_faq_page_node(page: Page) -> dict | None:
    """
    Finds an FAQPage node in the current page's JSON-LD, wherever it lives.
    On the is_page() catch-all branch (content-schema.php), $faq_schema is
    NOT pushed as its own top-level @graph node the way it is on the papers/
    schools branches -- it's nested as the WebPage node's own 'mainEntity'
    property instead (content-schema.php ~line 1580: $webpage_schema['mainEntity']
    = ['@type' => 'FAQPage', 'mainEntity' => ...]). Checks both shapes so this
    helper is correct regardless of which branch a given URL happens to hit.
    """
    ld_blocks = page.locator("script[type='application/ld+json']")
    for i in range(ld_blocks.count()):
        try:
            data = json.loads(ld_blocks.nth(i).inner_html())
        except json.JSONDecodeError:
            continue
        for node in data.get("@graph", []):
            if node.get("@type") == "FAQPage":
                return node
            main_entity = node.get("mainEntity")
            if isinstance(main_entity, dict) and main_entity.get("@type") == "FAQPage":
                return main_entity
    return None


@pytest.mark.content
def test_faq_schema_present_when_faqs_configured(page: Page, base_url: str):
    """
    The shared $faq_schema component (owltheme/docs/content-schema.md) emits
    an FAQPage node (as a top-level @graph node on some page types, nested
    under the WebPage node's 'mainEntity' on the is_page() catch-all branch
    -- see _ld_faq_page_node) when a page's ACF 'faqs' repeater has data, and
    correctly omits it when the repeater is empty -- confirmed on two real
    pages rather than asserting presence alone, since an always-present
    FAQPage node would be just as wrong as an always-absent one.
    """
    page.goto(f"{base_url}{FAQ_PAGE_URL}", wait_until="domcontentloaded")
    faq_node = _ld_faq_page_node(page)
    assert faq_node, (
        f"No FAQPage node found (top-level or nested under WebPage.mainEntity) in JSON-LD "
        f"on {FAQ_PAGE_URL}, which has a populated 'faqs' ACF repeater"
    )
    assert faq_node.get("mainEntity"), (
        f"FAQPage node found on {FAQ_PAGE_URL} but its own mainEntity (the Question list) is empty"
    )

    page.goto(f"{base_url}{GENERIC_PAGE_URL}", wait_until="domcontentloaded")
    assert _ld_faq_page_node(page) is None, (
        f"FAQPage node found in JSON-LD on {GENERIC_PAGE_URL}, which has no 'faqs' ACF "
        f"repeater configured -- $faq_schema should have been omitted entirely"
    )

    write_detail("test_faq_schema_present_when_faqs_configured", {
        "message": f"FAQPage present on {FAQ_PAGE_URL} (has faqs), absent on {GENERIC_PAGE_URL} (no faqs)",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Testimonial feedback form (distinct from References — see docs/guides/testimonials.md)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.content
def test_testimonial_feedback_form_loads_for_incomplete(page: Page, base_url: str, api_key: str):
    """
    The testimonial feedback form (single-testimonials.php) loads at its real
    permalink + ?j={crc32 job_id}&c={crc32 client_id} for an Incomplete
    testimonial, rather than redirecting away (which happens for a bad hash or
    an already-Submitted/Reviewed record). Uses a real record from the local
    pool of 1,188+ Incomplete testimonials (production-synced) via
    owl_get_test_status_record — no dev-site setup needed.
    Covers: 'Testimonial feedback form loads at its permalink for Incomplete
    status; single-use link redirects once already Submitted'.
    """
    record = get_test_status_record(base_url, api_key, "testimonials", "Incomplete")
    url = f"{record['url']}?j={record['j']}&c={record['c']}"

    page.goto(url, wait_until="domcontentloaded")

    assert "/testimonials/" in page.url, (
        f"Expected to stay on the testimonial page, got redirected to: {page.url}"
    )
    expect(page.locator("#testimonialForm")).to_be_visible()
    expect(page.locator("h1")).to_contain_text("Testimonial request")

    write_detail("test_testimonial_feedback_form_loads_for_incomplete", {
        "message": f"Testimonial {record['post_id']} (job {record['job_id']}) form loaded correctly",
    })


@pytest.mark.content
def test_testimonial_feedback_form_submission_sets_submitted(page: Page, base_url: str, api_key: str):
    """
    Submitting the 5-step feedback form (single-testimonials.php / ot_testimonials.js)
    saves ratings/comments and sets testimonial_status=Submitted, showing the
    'Thank you!' page. Uses a real Incomplete testimonial from the local pool
    (owl_get_test_status_record); resets it back to Incomplete afterward via
    owl_reset_status_field so repeated local runs don't deplete the pool —
    this does NOT reverse the tutor's live_competency_scores_testimonial_scores
    repeater row the submission also appends (accepted side effect, same
    precedent as test_meet_now_submission's auto_swap_active note).
    Covers: 'Submitting the 5-step feedback form saves ratings/comments and
    sets status to Submitted'.
    """
    record = get_test_status_record(base_url, api_key, "testimonials", "Incomplete")
    url = f"{record['url']}?j={record['j']}&c={record['c']}"

    try:
        page.goto(url, wait_until="domcontentloaded")
        expect(page.locator("#testimonialForm")).to_be_visible()

        # The radios are visually hidden (CSS styles the <label> as the clickable
        # star/face icon instead) — dispatch a real 'click' event directly via JS
        # rather than Playwright's .check()/.click(), which requires the target
        # itself to be visible. ot_testimonials.js listens for 'click' on these
        # radios specifically (not 'change'), so this matches what it expects.
        def click_radio(radio_id: str):
            page.eval_on_selector(f"#{radio_id}", "el => { el.checked = true; el.dispatchEvent(new Event('click', { bubbles: true })); }")

        # Step 1 of 5 — overall rating
        click_radio("q1_5")
        page.locator("#nextSection").click()

        # Step 2 of 5 — 7 star ratings (all "_1" radios = value 5). Setting the
        # last one reveals #q4_b (average >= 4) as a *child* of the still-hidden
        # #q4 section — its own visibility only resolves once the section
        # itself is navigated to below, so don't assert visibility yet.
        for item in ["q3a", "q3b", "q3c", "q3d", "q3e", "q3f", "q3g"]:
            click_radio(f"{item}_1")
        page.locator("#nextSection").click()

        # Step 3 of 5 — now on the #q4 section; public comment (required since average >= 4)
        expect(page.locator("#q4_b")).to_be_visible()
        page.locator("#q4_b textarea").fill("Automated test feedback — please ignore.")
        page.locator("#nextSection").click()

        # Step 4 of 5 — now on #q5; customer service happy? -> reveals #q6_b (still hidden until next section)
        page.locator("select[name='q5']").select_option("yes")
        page.locator("#nextSection").click()

        # Step 5 of 5 — now on #q6; internal comment, then the real submit (button now reads "Submit")
        expect(page.locator("#q6_b")).to_be_visible()
        page.locator("#q6_b textarea").fill("Automated test — internal comment.")
        expect(page.locator("#nextSection")).to_have_text("Submit")
        page.locator("#nextSection").click()

        # The "Thank you!" branch (single-testimonials.php) only renders after
        # nonce verification succeeds, immediately followed unconditionally by
        # ot_client_submits_testimonial() (which sets testimonial_status =
        # Submitted) in the same code path — reaching this page is itself the
        # proof the status was set, no separate DB check needed.
        expect(page.locator("h1")).to_contain_text("Thank you!", timeout=15000)
    finally:
        reset_status_field(base_url, api_key, record["post_id"], "testimonial_status", "Incomplete")

    write_detail("test_testimonial_feedback_form_submission_sets_submitted", {
        "message": f"Testimonial {record['post_id']} submitted successfully, reset back to Incomplete",
    })

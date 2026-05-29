import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

BLOG_URL = "/resource/"
TESTIMONIALS_URL = "/about-us/testimonials/"
SHOP_URL = "/shop/"
COURSES_URL = "/all-courses/"


def test_blog_listing_loads(page: Page, base_url: str):
    """Blog listing page loads with at least one article card visible."""
    page.goto(f"{base_url}{BLOG_URL}")
    # Regular blog cards use a.text-decoration-none.d-block.h-100 (featured article omits h-100)
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    expect(page.locator("a.text-decoration-none.d-block.h-100").first).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/blog_listing.png")
    write_detail("test_blog_listing_loads", {
        "message": "Blog listing page loaded with article cards visible",
        "screenshot": "screenshots/blog_listing.png",
    })


def test_blog_article_loads(page: Page, base_url: str):
    """Clicking a blog card navigates to a full article page with body content."""
    page.goto(f"{base_url}{BLOG_URL}")
    page.wait_for_selector("a.text-decoration-none.d-block.h-100", timeout=10000)
    page.locator("a.text-decoration-none.d-block.h-100").first.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("article.mb-4")).to_be_visible(timeout=10000)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/blog_article.png")
    write_detail("test_blog_article_loads", {
        "message": "Blog article page loaded with article body visible",
        "screenshot": "screenshots/blog_article.png",
    })


def test_testimonials_page_loads(page: Page, base_url: str):
    """Testimonials page loads with the hero header visible."""
    page.goto(f"{base_url}{TESTIMONIALS_URL}")
    expect(page.locator("header.bg-navy.text-white")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/testimonials.png")
    write_detail("test_testimonials_page_loads", {
        "message": "Testimonials page loaded with hero header visible",
        "screenshot": "screenshots/testimonials.png",
    })


def test_shop_loads(page: Page, base_url: str):
    """Premium paper shop loads with at least one product card visible."""
    page.goto(f"{base_url}{SHOP_URL}")
    page.wait_for_selector(".paper-card", timeout=10000)
    expect(page.locator(".paper-card").first).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/shop.png")
    write_detail("test_shop_loads", {
        "message": "Premium paper shop loaded with product cards visible",
        "screenshot": "screenshots/shop.png",
    })


def test_group_course_listing(page: Page, base_url: str):
    """Group course listing page loads with at least one course card visible."""
    page.goto(f"{base_url}{COURSES_URL}")
    page.wait_for_selector("#course-grid article.course-card", timeout=10000)
    expect(page.locator("#course-grid article.course-card").first).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/course_listing.png")
    write_detail("test_group_course_listing", {
        "message": "Group course listing loaded with course cards visible",
        "screenshot": "screenshots/course_listing.png",
    })


def test_group_course_detail(page: Page, base_url: str):
    """Clicking a course card navigates to the course detail page."""
    page.goto(f"{base_url}{COURSES_URL}")
    page.wait_for_selector("#course-grid article.course-card", timeout=10000)
    # stretched-link covers the whole card — click the anchor directly
    page.locator("#course-grid article.course-card a.stretched-link").first.click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("header.bg-navy.text-white")).to_be_visible(timeout=10000)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/course_detail.png")
    write_detail("test_group_course_detail", {
        "message": "Group course detail page loaded with course header visible",
        "screenshot": "screenshots/course_detail.png",
    })

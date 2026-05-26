import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

SCHOOLS_URL = "/school-entrance-guide/"
SCHOOL_PROFILE_URL = "/schools/westminster/"


def _dismiss_cookies(page: Page):
    """Dismiss the cookie consent banner if it is present."""
    try:
        page.locator("#ot_local_storage_accept").click(timeout=3000)
    except Exception:
        pass


def test_school_listing_page_loads(page: Page, base_url: str):
    """School entrance guide listing page loads and the filter form is visible."""
    page.goto(f"{base_url}{SCHOOLS_URL}")
    expect(page.locator("#school_entry_points")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/school_listing_page.png")
    write_detail("test_school_listing_page_loads", {
        "message": "School entrance guide listing page loaded with filter form visible",
        "screenshot": "screenshots/school_listing_page.png",
    })


def test_school_text_search_ajax(page: Page, base_url: str):
    """Inline AJAX text search returns matching schools in the dropdown."""
    page.goto(f"{base_url}{SCHOOLS_URL}")
    _dismiss_cookies(page)
    page.locator("#school-search-form input[name='school_name']").fill("Westminster")
    page.wait_for_selector("#school_search_results a.list-group-item", timeout=10000)
    expect(page.locator("#school_search_results a.list-group-item").first).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/school_text_search.png")
    write_detail("test_school_text_search_ajax", {
        "message": "School AJAX text search returned results for 'Westminster'",
        "screenshot": "screenshots/school_text_search.png",
    })


def test_school_filter_form_returns_results(page: Page, base_url: str):
    """Multi-select filter form returns matching school cards when submitted."""
    page.goto(f"{base_url}{SCHOOLS_URL}")
    _dismiss_cookies(page)
    page.select_option("#school_entry_points", label="11 Plus")
    page.locator("form[name='school_search_form'] button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("article.school_result_box", timeout=15000)
    expect(page.locator("article.school_result_box").first).to_be_visible()
    page.locator("article.school_result_box").first.scroll_into_view_if_needed()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/school_filter_results.png")
    write_detail("test_school_filter_form_returns_results", {
        "message": "School filter form returned results for 11 Plus entry point",
        "screenshot": "screenshots/school_filter_results.png",
    })


def test_school_profile_loads(page: Page, base_url: str):
    """Westminster school profile loads correctly via the AJAX text search."""
    page.goto(f"{base_url}{SCHOOLS_URL}")
    _dismiss_cookies(page)
    page.locator("#school-search-form input[name='school_name']").fill("Westminster")
    page.wait_for_selector("#school_search_results a.list-group-item", timeout=10000)
    page.locator("#school_search_results a.list-group-item").first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    expect(page.locator("section#overview")).to_be_visible(timeout=15000)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/school_profile.png")
    write_detail("test_school_profile_loads", {
        "message": "Westminster school profile loaded with overview section visible",
        "screenshot": "screenshots/school_profile.png",
    })

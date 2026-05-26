import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

# Generic exam papers page — confirm this URL is correct before first run
PAPERS_URL = "/exam-papers/"


def test_papers_load(page: Page, base_url: str):
    """Paper cards render in the catalogue grid."""
    page.goto(f"{base_url}{PAPERS_URL}")
    expect(page.locator("#exam_paper_links .paper-card")).not_to_have_count(0)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/papers_load.png")
    write_detail("test_papers_load", {
        "message": "Exam papers catalogue loaded with paper cards visible",
        "screenshot": "screenshots/papers_load.png",
    })


def test_papers_ajax_filter(page: Page, base_url: str):
    """Selecting a subject filter returns a non-empty result set via AJAX."""
    page.goto(f"{base_url}{PAPERS_URL}")
    # Select the second option (index 1) — index 0 is "All subjects"
    page.locator("#paper_subject_filter").select_option(index=1)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#exam_paper_links .paper-card")).not_to_have_count(0)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/papers_ajax_filter.png")
    write_detail("test_papers_ajax_filter", {
        "message": "Exam papers AJAX filter returned results for selected subject",
        "screenshot": "screenshots/papers_ajax_filter.png",
    })


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
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/papers_load_more.png")
    write_detail("test_papers_load_more", {
        "message": f"Load More clicked — {initial_count} initial papers expanded to {total_count}, scrolled to newly loaded content",
        "screenshot": "screenshots/papers_load_more.png",
    })

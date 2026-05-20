from playwright.sync_api import Page, expect

# TODO: confirm the paper catalogue URL and CSS selectors against the live markup

def test_papers_load(page: Page, base_url: str):
    """Papers render on the catalogue page."""
    page.goto(f"{base_url}/exam-papers/")
    expect(page.locator(".paper-card")).not_to_have_count(0)

def test_papers_ajax_filter(page: Page, base_url: str):
    """Clicking a subject filter returns a non-empty result set."""
    page.goto(f"{base_url}/exam-papers/")
    page.locator(".filter-btn").first.click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".paper-card")).not_to_have_count(0)

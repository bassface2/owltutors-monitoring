from playwright.sync_api import Page, expect

# Generic exam papers page — confirm this URL is correct before first run
PAPERS_URL = "/exam-papers/"


def test_papers_load(page: Page, base_url: str):
    """Paper cards render in the catalogue grid."""
    page.goto(f"{base_url}{PAPERS_URL}")
    expect(page.locator("#exam_paper_links .paper-card-BROKEN")).not_to_have_count(0)


def test_papers_ajax_filter(page: Page, base_url: str):
    """Selecting a subject filter returns a non-empty result set via AJAX."""
    page.goto(f"{base_url}{PAPERS_URL}")
    # Select the second option (index 1) — index 0 is "All subjects"
    page.locator("#paper_subject_filter").select_option(index=1)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#exam_paper_links .paper-card-BROKEN")).not_to_have_count(0)

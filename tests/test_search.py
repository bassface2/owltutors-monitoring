import os
from playwright.sync_api import Page, expect
from utils.details import write_detail

TUTORS_URL = "/tutors/"


def _dismiss_cookies(page: Page):
    """Dismiss the cookie consent banner if it is present."""
    try:
        page.locator("#ot_local_storage_accept").click(timeout=3000)
    except Exception:
        pass  # banner not present or already dismissed


# ── Existing core tests ──────────────────────────────────────────────────────

def test_tutor_search_page_loads(page: Page, base_url: str):
    """Search page loads and the search form is visible."""
    page.goto(f"{base_url}{TUTORS_URL}")
    expect(page.locator("#tutorSearchForm")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/tutor_search_page.png")
    write_detail("test_tutor_search_page_loads", {
        "message": "Tutor search page loaded with form visible",
        "screenshot": "screenshots/tutor_search_page.png",
    })


def test_tutor_search_returns_results(page: Page, base_url: str):
    """Tutor listing AJAX search returns results — at least one tutor card loads."""
    page.goto(f"{base_url}{TUTORS_URL}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".add-to-cart", timeout=15000)
    expect(page.locator(".add-to-cart").first).to_be_visible()
    page.locator("#tutor_results").scroll_into_view_if_needed()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/tutor_search_results.png")
    write_detail("test_tutor_search_returns_results", {
        "message": "Tutor search returned results via AJAX",
        "screenshot": "screenshots/tutor_search_results.png",
    })


def test_tutor_profile_loads(page: Page, base_url: str):
    """A tutor profile page loads correctly from the search results."""
    page.goto(f"{base_url}{TUTORS_URL}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("article.author-card", timeout=15000)
    page.locator("article.author-card a[href*='/tutor/']").first.click()
    expect(page.locator(".tutor-hero--profile")).to_be_visible(timeout=10000)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/tutor_profile.png")
    write_detail("test_tutor_profile_loads", {
        "message": "Tutor profile page loaded successfully",
        "screenshot": "screenshots/tutor_profile.png",
    })


# ── Option A: UI progressive reveal ─────────────────────────────────────────

def test_subject_with_levels_reveals_level_dropdown(page: Page, base_url: str):
    """Selecting a subject that has levels makes the level dropdown visible."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)
    page.select_option("#hero_subject", label="English")
    expect(page.locator("#hero_level_col")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_level_dropdown.png")
    write_detail("test_subject_with_levels_reveals_level_dropdown", {
        "message": "Level dropdown appeared after selecting English",
        "screenshot": "screenshots/search_level_dropdown.png",
    })


def test_school_entrance_subject_reveals_school_filter(page: Page, base_url: str):
    """Selecting a school-entrance subject promotes the school autocomplete into the hero row."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)
    page.select_option("#hero_subject", label="11 Plus")
    expect(page.locator("#hero_school_col")).to_be_visible()
    # Type a school name and select the first autocomplete result
    page.locator("#filter_school").fill("Westminster")
    page.wait_for_selector("#school_list a.dropdown-item", timeout=10000)
    page.locator("#school_list a.dropdown-item").first.click()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_school_filter.png")
    write_detail("test_school_entrance_subject_reveals_school_filter", {
        "message": "School filter appeared and school selected after choosing 11 Plus",
        "screenshot": "screenshots/search_school_filter.png",
    })


def test_home_delivery_reveals_location_filter(page: Page, base_url: str):
    """Clicking the Home delivery button makes the location autocomplete visible."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)
    page.select_option("#hero_subject", label="English")
    page.locator("button.js-mode[data-value='Home']").click()
    expect(page.locator("#hero_location_col")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_location_filter.png")
    write_detail("test_home_delivery_reveals_location_filter", {
        "message": "Location filter appeared after selecting Home delivery",
        "screenshot": "screenshots/search_location_filter.png",
    })


def test_detailed_filters_reveal_sen_and_badges(page: Page, base_url: str):
    """Clicking 'Show all search options' reveals the SEN and badges selects, which can be set."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)
    page.locator("#filters_toggle").click()
    expect(page.locator("#filter_item_sen")).to_be_visible()
    expect(page.locator("#filter_item_badges")).to_be_visible()
    page.select_option("#filter_sen", index=1)
    page.select_option("#filter_badge", index=1)
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_detailed_filters.png")
    write_detail("test_detailed_filters_reveal_sen_and_badges", {
        "message": "SEN and badges filters visible and filled via detailed panel",
        "screenshot": "screenshots/search_detailed_filters.png",
    })


def test_availability_grid_appears_and_accepts_input(page: Page, base_url: str):
    """Selecting a subject reveals the availability grid; slots can be checked."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)
    page.select_option("#hero_subject", label="English")
    expect(page.locator("#hero_availability_col")).to_be_visible()
    # Grid is inside a collapsed Bootstrap accordion — expand it first
    page.locator("button[data-bs-target='#collapseOne']").click()
    page.wait_for_selector("#collapseOne.show", timeout=5000)
    page.locator("div.cell:has(.avail-cell[data-row='Morning'][data-col='0'])").click()
    page.locator("div.cell:has(.avail-cell[data-row='Evening'][data-col='4'])").click()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_availability.png")
    write_detail("test_availability_grid_appears_and_accepts_input", {
        "message": "Availability grid appeared and Monday morning + Friday evening selected",
        "screenshot": "screenshots/search_availability.png",
    })


# ── Option B: full pipeline search ──────────────────────────────────────────

def test_full_search_subject_level_home_location(page: Page, base_url: str):
    """Full pipeline: English + GCSE + Home delivery + London location → AJAX results render."""
    page.goto(f"{base_url}{TUTORS_URL}")
    _dismiss_cookies(page)

    # Subject
    page.select_option("#hero_subject", label="English")
    expect(page.locator("#hero_level_col")).to_be_visible()

    # Level
    page.select_option("select.subject_level[data-subject='English']", index=1)

    # Home delivery
    page.locator("button.js-mode[data-value='Home']").click()
    expect(page.locator("#hero_location_col")).to_be_visible()

    # Location autocomplete
    page.locator("#filter_location").fill("Balham")
    page.wait_for_selector("#location_list a.dropdown-item", timeout=10000)
    page.locator("#location_list a.dropdown-item").first.click()

    # Submit
    page.locator("#tutor_filter").click()

    # Wait for either tutor cards or the no-results alert
    page.wait_for_selector(
        "#tutor_results article.author-card, #tutor_results .alert-info",
        timeout=20000,
    )

    page.locator("#tutor_results").scroll_into_view_if_needed()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/search_full_pipeline.png")
    write_detail("test_full_search_subject_level_home_location", {
        "message": "Full pipeline search ran: English, Home delivery, Balham",
        "screenshot": "screenshots/search_full_pipeline.png",
    })

import os
from playwright.sync_api import Page, expect
from utils.details import write_detail


def test_homepage_loads(page: Page, base_url: str):
    """Homepage loads and the hero section is visible."""
    page.goto(f"{base_url}/")
    expect(page.locator(".tutor-hero--homepage")).to_be_visible()
    os.makedirs("screenshots", exist_ok=True)
    page.screenshot(path="screenshots/homepage.png")
    write_detail("test_homepage_loads", {
        "message": "Homepage loaded with hero section visible",
        "screenshot": "screenshots/homepage.png",
    })

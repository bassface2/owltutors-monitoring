"""
Smoke test for the admin Reports/Data dashboard pages routed through
includes/dashboard/dashboard-mgmt.php, documented in docs/dashboard-mgmt.md.
Requires a real staff (administrator/owl-role) session — see
admin_credentials in conftest.py.
"""
from playwright.sync_api import Page, expect
from utils.wp_admin_login import login_wp_admin
from utils.details import write_detail
import pytest

# Every ?page= value registered by plugin_admin_add_dashboard_page()
# (docs/dashboard-mgmt.md) reachable via a plain GET. kpi_efficiency has no
# menu link but is still a real routed page. tutor_landing_pages lives under
# the separate 'Owl Settings' menu, not 'Owl Data' — included here anyway
# since it goes through the same admin.php?page= routing mechanism.
DASHBOARD_PAGES = [
    "kpis_home", "kpis2_home", "data_home",
    "kpi_recruitment", "kpi_marketing", "kpi_sales", "kpi_operations",
    "kpi_education", "kpi_efficiency",
    "job_management", "timesheet_management", "client_management",
    "recruitment_management", "marketing_management", "sales_management",
    "tutor_engagement", "seo_report",
    "billing_invoice_actions", "billing_payment_actions",
    "billing_analysis_actions",
    "dev_info", "content_analysis", "systems_testing", "ams_dashboard",
    "stripe_tools",
    "tutor_landing_pages",
]


@pytest.mark.misc
@pytest.mark.parametrize("page_slug", DASHBOARD_PAGES)
def test_admin_reports_and_data_pages_load_without_fatal(
    page: Page, base_url: str, api_key: str, admin_credentials, page_slug: str
):
    """
    Every admin Reports/Data page renders without a PHP fatal or a blank
    response — a parametrised smoke test that would have caught the
    kpi_efficiency orphan-page situation (no menu link, but still a real
    routed page) immediately had it existed earlier.

    Read-only GET requests only. Some pages (billing/Xero/Stripe tools) may
    make their own real, read-only third-party API calls to render report
    data (e.g. listing live unpaid invoices) — this test does not submit any
    form or trigger any of those pages' own action buttons, only loads them.

    Logs in once per parametrised instance since admin_credentials/page are
    function-scoped in this suite's fixture setup; acceptable overhead for a
    smoke test that's expected to run infrequently, not on every commit.
    """
    login_wp_admin(page, base_url, admin_credentials["email"], admin_credentials["password"], api_key)

    resp = page.goto(f"{base_url}/wp-admin/admin.php?page={page_slug}", wait_until="domcontentloaded")
    assert resp is not None and resp.status < 500, (
        f"?page={page_slug} returned HTTP {resp.status if resp else 'no response'}"
    )

    body_text = page.locator("body").inner_text()
    assert "There has been a critical error" not in body_text, (
        f"?page={page_slug} rendered a PHP fatal error page"
    )
    assert body_text.strip() != "", f"?page={page_slug} rendered a blank page"

    write_detail(f"test_admin_reports_and_data_pages_load_without_fatal[{page_slug}]", {
        "message": f"?page={page_slug} loaded with status {resp.status}",
    })

"""Optional browser QA. Run against an already running mock-only local demo."""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", help="Path to an installed Chrome/Edge executable")
    parser.add_argument("--check-live-controls", action="store_true", help="Inspect live controls without starting a live run")
    parser.add_argument("--out", type=Path, default=Path("artifacts/demo-preview"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1050}, device_scale_factor=1)
        errors=[]
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(args.url + "/") else route.abort())
        page.goto(args.url,wait_until="networkidle")
        page.locator("#run:not([disabled])").wait_for()
        assert page.locator(".preset-icon").first.inner_text() == "↘"
        assert page.locator(".run-arrow").inner_text() == "↗"
        assert page.locator('#mode option[value="mock"]').inner_text() == "Mock · no API calls"
        assert page.locator(".scenario input:checked").count() == 6
        assert page.locator("#advanced").get_attribute("open") is None
        page.locator("#preset-repeat").click()
        assert page.locator("#candidate").input_value() == "mock-baseline"
        page.locator("#preset-regression").click()
        page.locator(".case-picker > summary").click()
        page.locator("#case-search").fill("privacy")
        assert page.locator(".scenario").count() == 4
        page.locator("#case-search").fill("")
        page.locator("#clear-cases").click()
        assert page.locator("#run").is_disabled()
        page.locator("#reset-cases").click()
        assert page.locator(".scenario input:not(:checked):disabled").count() == 14
        page.locator(".case-picker > summary").click()
        page.screenshot(path=str(args.out / "desktop-ready.png"),full_page=True)
        page.locator("#run").click()
        page.get_by_text("Results saved", exact=True).wait_for()
        assert page.locator("#decision").inner_text() == "Blocked"
        assert page.locator("#progress-count").inner_text() == "12 / 12"
        assert page.locator(".casecard[open]").count() >= 1
        page.locator('[data-filter="changed"]').click()
        assert 0 < page.locator(".casecard").count() < 6
        page.locator('[data-filter="review"]').click()
        assert page.locator(".casecard").count() == 3
        page.locator('[data-filter="all"]').click()
        first=page.locator(".casecard").first
        if first.get_attribute("open") is None:
            first.locator("summary").click()
        page.screenshot(path=str(args.out / "desktop-results.png"),full_page=True)
        with page.expect_download() as download:
            page.locator("#downloads a").filter(has_text="comparison.json").click()
        download.value.save_as(str(args.out / "downloaded-comparison.json"))
        page.set_viewport_size({"width":375,"height":812})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(args.out / "mobile-results.png"),full_page=True)
        page.set_viewport_size({"width":1440,"height":1050})
        page.locator("#preset-repeat").click()
        page.locator("#run").click()
        page.get_by_text("Results saved",exact=True).wait_for()
        assert page.locator("#decision").inner_text() == "Pass"
        if args.check_live_controls:
            page.set_viewport_size({"width":1440,"height":1050})
            page.locator("#mode").select_option("groq")
            assert page.locator(".scenario input:checked").count() == 1
            assert page.locator("#run").is_disabled()
            assert page.locator("#judge").is_enabled()
            page.locator("#confirm-live").check()
            assert page.locator("#run").is_enabled()
            page.locator("#confirm-live").uncheck()
            assert page.locator("#run").is_disabled()
        assert not errors, errors
        browser.close()
    print("Browser QA passed: presets, search, selection limit, result filters, both mock gates, download, mobile layout, no page errors.")


if __name__ == "__main__":
    main()

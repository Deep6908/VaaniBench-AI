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
        assert page.locator(".scenario input:checked").count() == 6
        page.screenshot(path=str(args.out / "desktop-ready.png"),full_page=True)
        page.locator("#run").click()
        page.get_by_text("Results saved", exact=True).wait_for()
        assert page.locator("#decision").inner_text() == "Blocked"
        assert page.locator("#progress-count").inner_text() == "12 / 12"
        page.locator(".casecard").first.locator("summary").click()
        page.screenshot(path=str(args.out / "desktop-results.png"),full_page=True)
        with page.expect_download() as download:
            page.locator("#downloads a").filter(has_text="comparison.json").click()
        download.value.save_as(str(args.out / "downloaded-comparison.json"))
        page.set_viewport_size({"width":375,"height":812})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(args.out / "mobile-results.png"),full_page=True)
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
    print("Browser QA passed: six-case mock comparison, progress, details, download, mobile width, no page errors.")


if __name__ == "__main__":
    main()

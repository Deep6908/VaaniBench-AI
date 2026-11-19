"""Optional browser QA. Run against an already running mock-only local demo."""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", help="Path to an installed Chrome/Edge executable")
    parser.add_argument("--check-live-controls", action="store_true", help="Inspect live controls without starting a live run")
    parser.add_argument("--check-hosted", action="store_true", help="Check refresh recovery and recorded evidence")
    parser.add_argument("--check-owner-ui", action="store_true", help="Local-only throwaway-password sign-in UI check")
    parser.add_argument('--check-redeploy',action='store_true',help='Simulate standby bootstrap and check automatic UI recovery')
    parser.add_argument("--out", type=Path, default=Path("artifacts/demo-preview"))
    args = parser.parse_args()
    if args.check_owner_ui:
        from urllib.parse import urlsplit
        assert urlsplit(args.url).hostname in {"127.0.0.1","localhost"}, "Owner UI test is local-only"
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1050}, device_scale_factor=1)
        errors=[]
        page.on("pageerror", lambda error: errors.append(str(error)))
        bootstrap_blocked=[False]
        def route_request(route):
            if not route.request.url.startswith(args.url+'/'): return route.abort()
            if args.check_redeploy and route.request.url.endswith('/api/bootstrap') and not bootstrap_blocked[0]:
                bootstrap_blocked[0]=True
                return route.fulfill(status=503,content_type='application/json',body='{"error":"Deployment handoff in progress"}')
            route.continue_()
        page.route('**/*',route_request)
        page.goto(args.url,wait_until="networkidle")
        if args.check_redeploy:
            expect(page.locator('#error')).to_contain_text('Deployment is finishing')
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
        if args.check_hosted:
            for _ in range(50):
                if page.evaluate("sessionStorage.getItem('vaanibench_active_job')"):
                    break
                page.wait_for_timeout(50)
            else:
                raise AssertionError("Hosted active job was not saved for refresh recovery")
            page.reload(wait_until="networkidle")
        page.get_by_text("Results saved",exact=True).wait_for()
        assert page.locator("#decision").inner_text() == "Pass"
        if args.check_hosted:
            assert page.locator("#session-label").inner_text()=="Public demo"
            page.locator("#recorded-evidence").click()
            page.get_by_text("Recorded Groq benchmark · no new API calls",exact=True).wait_for()
            assert page.locator(".casecard").count()==3
        if args.check_owner_ui:
            page.locator("#owner-auth").click()
            page.locator("#owner-password").fill("temporary browser-only test password")
            page.keyboard.press("Escape")
            assert page.locator("#owner-password").input_value()==""
            page.locator("#owner-auth").click()
            page.locator("#owner-password").fill("temporary browser-only test password")
            page.locator("#submit-login").click()
            page.get_by_text("Owner session",exact=True).wait_for()
            assert page.locator("#owner-password").input_value()==""
            page.locator('#history-panel > summary').click()
            page.locator('#preset-repeat').click()
            page.locator('#run').click()
            page.get_by_text('Results saved',exact=True).wait_for()
            page.locator('#history-refresh').click()
            page.locator('#history-list button').first.wait_for()
            page.locator('#history-search').fill('mock-baseline')
            page.locator('#history-refresh').click()
            page.locator('#history-list button').first.click()
            assert page.locator('#decision').inner_text()=='Pass'
            page.locator('#history-compare').click()
            expect(page.locator('#history-comparison')).to_contain_text('Pass')
            with page.expect_download() as saved_download:
                page.locator('#downloads a').filter(has_text='comparison.json').click()
            assert saved_download.value.suggested_filename=='comparison.json'
            page.locator('#run').click()
            page.locator('#cancel-run:not([hidden])').click()
            page.get_by_text('Attention required',exact=True).wait_for()
            assert page.locator('#error').is_visible()
            page.locator('#history-status').select_option('cancelled')
            page.locator('#history-refresh').click()
            expect(page.locator('#history-list')).to_contain_text('cancelled')
            page.locator("#owner-auth").click()
            page.get_by_text("Public demo",exact=True).wait_for()
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

"""BigBasket seller portal (Sambandh / nucleus). Flutter web app: drawn on a canvas, so we switch on
Flutter's accessibility layer to get real, clickable elements.

Implemented: email + OTP login, session reuse. TODO: report download (needs report details)."""
import re
import time
from playwright.sync_api import sync_playwright
from .. import db
from .base import Adapter

URL = "https://nucleus.bigbasket.com/#/onboarding"
DASH = "https://nucleus.bigbasket.com/#/dashboard"
DOWNLOAD_API = "https://nucleus.bigbasket.com/stitch/vendor/download/?group_id={}"
LIST_API = "https://nucleus.bigbasket.com/stitch/vendor/transactions/?page=1&page_size=20&group=0"
DONE = 4   # transaction status for "Completed"
REPORT_WAIT_SECONDS = 15 * 60


def _enable_semantics(pg):
    """Switch on Flutter's accessibility layer (once per page load)."""
    if pg.locator("flt-semantics-placeholder").count() == 0:
        pg.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=60000)
    pg.locator("flt-semantics-placeholder").dispatch_event("click")
    pg.wait_for_timeout(1500)


def _logged_in(pg):
    """Logged-out users are bounced to #/onboarding (the sign-in / OTP flow lives there, and it always
    shows 'Sign In'), so being anywhere else means we're in."""
    return "onboarding" not in pg.url


def _type_into(pg, box, text):
    """Flutter ignores Playwright's fill(); focus the field by clicking, then type like a keyboard."""
    box.click()
    pg.wait_for_timeout(400)
    pg.keyboard.press("ControlOrMeta+A")
    pg.keyboard.press("Backspace")
    pg.keyboard.type(text, delay=70)
    pg.wait_for_timeout(500)


def _btn(pg, name):
    return pg.get_by_role("button", name=re.compile(name, re.I))


def _on_login_screen(pg):
    return (_btn(pg, r"^sign in$").count() or _btn(pg, r"^verify$").count()
            or _btn(pg, r"resend").count() or pg.get_by_role("textbox").count()) > 0


class BigBasketAdapter(Adapter):
    def run(self, ctx):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            kw = {"viewport": {"width": 1280, "height": 800}}
            if ctx.session_file.exists():
                kw["storage_state"] = str(ctx.session_file)
            context = browser.new_context(**kw)
            pg = context.new_page()
            try:
                ctx.log("Opening BigBasket portal")
                landing = DASH if ctx.session_file.exists() else URL
                pg.goto(landing, wait_until="domcontentloaded")
                _enable_semantics(pg)
                pg.wait_for_timeout(4000)

                if _logged_in(pg):
                    ctx.log("Existing session still valid")
                else:
                    if landing == DASH:
                        ctx.log("Saved session expired, signing in again")
                        pg.goto(URL)
                        pg.wait_for_timeout(3000)
                    self._login(ctx, pg)

                context.storage_state(path=str(ctx.session_file))
                self._open_view_reports(ctx, pg)
                files = [self._generate_and_download(ctx, pg, context)]
                if db.get_setting("keep_browser_open", "1") == "1":
                    ctx.log("Done. The browser stays open - close the Chrome window when you're done.")
                    self._wait_until_closed(ctx, pg, context)
                return files
            except Exception:
                try:
                    pg.screenshot(path=str(ctx.out_dir / "error.png"))
                    ctx.log(f"Saved screenshot: {ctx.out_dir / 'error.png'}")
                except Exception:
                    pass
                raise
            finally:
                browser.close()

    def _open_view_reports(self, ctx, pg):
        """Sidebar: Analytics Overview -> View Reports. The sidebar isn't in Flutter's accessibility
        tree, so click by position (the window size is fixed at 1280x800)."""
        ctx.log("Opening Analytics Overview > View Reports")
        pg.mouse.click(148, 289)
        pg.wait_for_timeout(1500)
        pg.mouse.click(127, 399)
        pg.wait_for_timeout(4000)

    def _transactions(self, context):
        r = context.request.get(LIST_API)
        if not r.ok:
            raise RuntimeError(f"Could not read the report list (HTTP {r.status})")
        return r.json()["data"]["transactions"]

    def _generate_and_download(self, ctx, pg, context):
        """View Reports page -> Generate -> fill the form -> Submit -> wait -> download the CSV."""
        start, end = ctx.params["start_date"], ctx.params["end_date"]
        hint = (ctx.account.get("report_hint") or "gamma").strip()
        email = ctx.account["login_id"].lower()
        before = max([t["id"] for t in self._transactions(context)] or [0])

        ctx.log(f"Generating report '{hint}' for {start} to {end}, all cities")
        pg.mouse.click(652, 252)                       # Generate
        pg.wait_for_timeout(3000)
        pg.mouse.click(888, 248)                       # Select Report
        pg.wait_for_timeout(800)
        pg.keyboard.type(hint, delay=100)
        pg.wait_for_timeout(1500)
        pg.mouse.click(700, 298)                       # first match
        pg.wait_for_timeout(2500)
        # The end-date box rejects typing once a start date is set, so fill end first, then start.
        pg.mouse.click(860, 357); pg.wait_for_timeout(1200); pg.keyboard.type(end, delay=100)
        pg.wait_for_timeout(800)
        pg.mouse.click(860, 302); pg.wait_for_timeout(1200); pg.keyboard.type(start, delay=100)
        pg.wait_for_timeout(800)
        pg.mouse.click(889, 505)                       # >>  all cities
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(ctx.out_dir / "form_filled.png"))
        pg.mouse.click(1132, 679)                      # Submit
        pg.wait_for_timeout(2000)
        pg.screenshot(path=str(ctx.out_dir / "after_submit.png"))   # shows the "Report queued" popup
        pg.mouse.click(1062, 375)                      # the popup's X - back to the report list
        pg.wait_for_timeout(1500)
        ctx.log("Report requested, waiting for BigBasket to build it")

        deadline = time.time() + REPORT_WAIT_SECONDS
        last = None
        while time.time() < deadline:
            pg.wait_for_timeout(5000)
            mine = [t for t in self._transactions(context) if t["id"] > before
                    and (not t.get("downloader_email") or t["downloader_email"].lower() == email)
                    and hint.lower() in (t.get("report_display_name", "") + t.get("report_slug", "")).lower()]
            if not mine:
                if time.time() > deadline - REPORT_WAIT_SECONDS + 90:
                    pg.screenshot(path=str(ctx.out_dir / "error.png"))
                    raise RuntimeError("BigBasket did not accept the report request - check the dates and report name")
                continue
            t = max(mine, key=lambda x: x["id"])
            if t["status"] != last:
                ctx.log(f"Report status code: {t['status']}")
                last = t["status"]
            if t["status"] == DONE and t.get("is_downloadable"):
                break
        else:
            raise RuntimeError("Report was not ready after 15 minutes")

        ctx.log(f"Report ready ({t.get('row_count', '?')} rows), downloading")
        try:
            path = self._download_via_api(ctx, context, t)
        except Exception as e:
            ctx.log(f"Direct download failed ({e}); trying the download button instead")
            path = self._download_via_click(ctx, pg)
        ctx.log(f"Downloaded {path.name}")
        return path

    def _download_via_api(self, ctx, context, t):
        """The download button just calls this endpoint, which redirects to the file on S3."""
        r = context.request.get(DOWNLOAD_API.format(t["transaction_id"]), max_redirects=0)
        url = r.headers.get("location")
        if r.status not in (301, 302, 303, 307) or not url:
            raise RuntimeError(f"unexpected response HTTP {r.status}")
        f = context.request.get(url)
        if not f.ok:
            raise RuntimeError(f"file fetch HTTP {f.status}")
        name = url.split("?")[0].rsplit("/", 1)[-1] or f"report_{t['transaction_id']}.csv"
        path = ctx.out_dir / name
        path.write_bytes(f.body())
        return path

    def _download_via_click(self, ctx, pg):
        pg.mouse.click(1262, 252)                      # refresh the list so the new row is on top
        pg.wait_for_timeout(3000)
        with pg.expect_download(timeout=60000) as d:
            pg.mouse.click(1259, 383)                  # download arrow on the top (newest) row
        path = ctx.out_dir / d.value.suggested_filename
        d.value.save_as(str(path))
        return path

    def _wait_until_closed(self, ctx, pg, context):
        """Keep the window open until the user closes it (needed while setting up / exploring)."""
        try:
            while not pg.is_closed():
                pg.wait_for_timeout(1000)
        except Exception:
            pass
        try:
            context.storage_state(path=str(ctx.session_file))
        except Exception:
            pass
        ctx.log("Browser closed")

    def _login(self, ctx, pg):
        ctx.log(f"Signing in as {ctx.account['login_id']}")
        if _btn(pg, r"^sign in$").count():
            _btn(pg, r"^sign in$").first.click()
            pg.wait_for_timeout(1500)
        _type_into(pg, pg.get_by_role("textbox").first, ctx.account["login_id"])
        _btn(pg, r"^verify$").first.click()
        ctx.log("Email submitted, waiting for OTP screen")
        pg.wait_for_timeout(3000)

        otp = ctx.ask_otp(f"Enter the OTP BigBasket emailed to {ctx.account['login_id']}")
        # Flutter only activates a field on a real pointer tap, and an overlay button blocks Playwright's
        # click(), so tap the first of the six boxes with a raw mouse click, then type.
        field = pg.locator("input#one-time-code")
        box = field.first.bounding_box() if field.count() else None
        if box:
            pg.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
        else:
            pg.mouse.click(726, 360)
        pg.wait_for_timeout(500)
        pg.keyboard.type(otp, delay=150)
        pg.wait_for_timeout(1000)
        try:
            pg.screenshot(path=str(ctx.out_dir / "otp_entered.png"))
        except Exception:
            pass
        pg.wait_for_timeout(500)
        submit = _btn(pg, r"^(sign in|verify|submit|login|continue|confirm)")
        if submit.count():
            submit.first.click()

        for _ in range(40):            # up to ~40s for the dashboard to appear
            pg.wait_for_timeout(1000)
            if _logged_in(pg):
                return
        raise RuntimeError("Dashboard did not appear after OTP - wrong/expired OTP or portal changed")

"""BigBasket seller portal (Sambandh / nucleus). Flutter web app: drawn on a canvas, so we switch on
Flutter's accessibility layer to get real, clickable elements.

Implemented: email + OTP login, session reuse. TODO: report download (needs report details)."""
import re
from playwright.sync_api import sync_playwright
from .base import Adapter

URL = "https://nucleus.bigbasket.com/#/onboarding"


def _enable_semantics(pg):
    pg.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=60000)
    pg.locator("flt-semantics-placeholder").dispatch_event("click")
    pg.wait_for_timeout(1500)


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
                pg.goto(URL, wait_until="domcontentloaded")
                _enable_semantics(pg)
                pg.wait_for_timeout(3000)

                if _on_login_screen(pg):
                    self._login(ctx, pg)
                else:
                    ctx.log("Existing session still valid")

                context.storage_state(path=str(ctx.session_file))
                ctx.log("Logged in. Report download not configured yet.")
                return []
            except Exception:
                try:
                    pg.screenshot(path=str(ctx.out_dir / "error.png"))
                    ctx.log(f"Saved screenshot: {ctx.out_dir / 'error.png'}")
                except Exception:
                    pass
                raise
            finally:
                browser.close()

    def _login(self, ctx, pg):
        ctx.log(f"Signing in as {ctx.account['login_id']}")
        if _btn(pg, r"^sign in$").count():
            _btn(pg, r"^sign in$").first.click()
            pg.wait_for_timeout(1500)
        box = pg.get_by_role("textbox").first
        box.fill(ctx.account["login_id"])
        _btn(pg, r"^verify$").first.click()
        ctx.log("Email submitted, waiting for OTP screen")
        pg.wait_for_timeout(3000)

        otp = ctx.ask_otp(f"Enter the OTP BigBasket emailed to {ctx.account['login_id']}")
        boxes = pg.get_by_role("textbox")
        n = boxes.count()
        if n > 1:                      # one box per digit
            for i, d in enumerate(otp[:n]):
                boxes.nth(i).fill(d)
        elif n == 1:
            boxes.first.fill(otp)
        else:
            pg.keyboard.type(otp, delay=80)
        pg.wait_for_timeout(500)
        submit = _btn(pg, r"^(verify|submit|login|continue|confirm)")
        if submit.count():
            submit.first.click()

        for _ in range(30):            # up to ~30s for the login screen to go away
            pg.wait_for_timeout(1000)
            if not _on_login_screen(pg):
                return
        raise RuntimeError("Still on login screen after OTP - wrong/expired OTP or portal changed")

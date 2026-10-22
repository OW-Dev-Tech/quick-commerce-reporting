import time
from .base import Adapter


class MockAdapter(Adapter):
    def run(self, ctx):
        ctx.log(f"Opening portal for {ctx.account['brand']} / {ctx.account['platform']} as {ctx.account['login_id']}")
        time.sleep(1)
        if not ctx.session_file.exists():
            ctx.log("Session missing/expired -> OTP required")
            otp = ctx.ask_otp(f"OTP sent to {ctx.account['login_id']}")
            ctx.log(f"Got OTP ({len(otp)} digits), logging in")
            time.sleep(1)
            ctx.session_file.write_text("{}")
        ctx.log("Navigating to sales report, applying filters")
        time.sleep(1)
        f = ctx.out_dir / "sales_report.csv"
        f.write_text("date,sku,units,gmv\n2026-10-22,SKU1,10,1200\n")
        ctx.log(f"Downloaded {f.name}")
        return [f]

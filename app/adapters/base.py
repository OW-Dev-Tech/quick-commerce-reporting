from pathlib import Path
from .. import db

SESSIONS = db.DATA / "sessions"
SESSIONS.mkdir(exist_ok=True)


class Ctx:
    """Handed to adapters by the runner."""
    def __init__(self, account, password, out_dir, log, ask_otp):
        self.account, self.password, self.out_dir = account, password, Path(out_dir)
        self.log, self.ask_otp = log, ask_otp
        self.session_file = SESSIONS / f"{account['brand']}__{account['platform']}.json".replace(" ", "_")


class Adapter:
    """Subclass and implement run(ctx) -> list[Path] of downloaded files.

    Real adapters: launch Playwright headed, reuse ctx.session_file as storage_state,
    detect logged-out state, then call ctx.ask_otp('Enter OTP sent to ...') and type it in.
    Save state with context.storage_state(path=ctx.session_file) after login.
    """
    def run(self, ctx):
        raise NotImplementedError

import json, queue, threading, traceback
from pathlib import Path
from datetime import datetime, date, timedelta
from . import db, secrets_store, sheets
from .adapters import get_adapter
from .adapters.base import Ctx

_jobs = queue.Queue()
_otp = {}  # run_id -> {"event": Event, "value": str}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def yesterday():
    return str(date.today() - timedelta(days=1))


def enqueue(account_id, start=None, end=None, force=False):
    running = db.q("SELECT id FROM runs WHERE account_id=? AND day=? AND status IN ('queued','running','waiting_otp')",
                   (account_id, str(date.today())))
    if running:
        return running[0]["id"]
    start, end = start or yesterday(), end or start or yesterday()
    rid = db.x("INSERT INTO runs(account_id,day,status,started,start_date,end_date,force) VALUES(?,?,?,?,?,?,?)",
               (account_id, str(date.today()), "queued", _now(), start, end, 1 if force else 0))
    _jobs.put(rid)
    return rid


def enqueue_all(start=None, end=None, force=False):
    return [enqueue(a["id"], start, end, force) for a in db.q("SELECT id FROM accounts")]


def submit_otp(run_id, value):
    o = _otp.get(run_id)
    if not o:
        return False
    o["value"] = value
    o["event"].set()
    return True


def _worker():
    # One at a time: headed browser windows + OTP prompts shouldn't overlap.
    while True:
        rid = _jobs.get()
        _execute(rid)


def _already_done(run):
    """What this account already downloaded for these dates, so a re-run only does what's missing.
    Returns ({kind: path of a file that still exists}, ref of the last sales report for re-download).
    A forced run ignores existing files but can still re-download the sales report without
    generating a new one (the portal limits generation)."""
    done = {}
    if not run["force"]:
        sales = db.q("SELECT path FROM downloads WHERE account_id=? AND kind='sales' AND start_date=? AND end_date=? ORDER BY id DESC",
                     (run["account_id"], run["start_date"], run["end_date"]))
        ads = db.q("SELECT path FROM downloads WHERE account_id=? AND kind='ads' AND day=? ORDER BY id DESC",
                   (run["account_id"], str(date.today())))
        for kind, rows in (("sales", sales), ("ads", ads)):
            hit = next((r["path"] for r in rows if Path(r["path"]).exists()), None)
            if hit:
                done[kind] = hit
    ref = db.q("SELECT ref FROM downloads WHERE account_id=? AND kind='sales' AND start_date=? AND end_date=? AND ref!='' ORDER BY id DESC LIMIT 1",
               (run["account_id"], run["start_date"], run["end_date"]))
    return done, (ref[0]["ref"] if ref else "")


def _execute(rid):
    run = db.q("SELECT * FROM runs WHERE id=?", (rid,))[0]
    acct = db.q("SELECT * FROM accounts WHERE id=?", (run["account_id"],))
    def log(line):
        db.x("INSERT INTO logs(run_id,ts,line) VALUES(?,?,?)", (rid, _now(), line))
    if not acct:
        db.x("UPDATE runs SET status='failed', finished=? WHERE id=?", (_now(), rid)); return
    acct = acct[0]
    db.x("UPDATE runs SET status='running' WHERE id=?", (rid,))

    def ask_otp(prompt):
        ev = threading.Event()
        _otp[rid] = {"event": ev, "value": ""}
        db.x("UPDATE runs SET status='waiting_otp' WHERE id=?", (rid,))
        log(f"WAITING FOR OTP: {prompt}")
        if not ev.wait(timeout=600):
            raise TimeoutError("OTP not entered within 10 minutes")
        db.x("UPDATE runs SET status='running' WHERE id=?", (rid,))
        return _otp.pop(rid)["value"]

    out = db.DATA / "output" / str(date.today()) / f"{acct['brand']}__{acct['platform']}".replace(" ", "_")
    out.mkdir(parents=True, exist_ok=True)
    try:
        done, ref = _already_done(run)
        ctx = Ctx(acct, secrets_store.get_password(acct["brand"], acct["platform"]), out, log, ask_otp,
                  {"start_date": run["start_date"], "end_date": run["end_date"], "done": done, "reuse_ref": ref})
        files = get_adapter(acct["platform"]).run(ctx)
        brand = db.q("SELECT sheet_id FROM brands WHERE name=?", (acct["brand"],))
        sheets.push_report(brand[0]["sheet_id"] if brand else "", acct["platform"], files, log)
        for it in ctx.result.get("items", []):
            db.x("INSERT INTO downloads(account_id,kind,start_date,end_date,day,ref,path,created) VALUES(?,?,?,?,?,?,?,?)",
                 (acct["id"], it["kind"], run["start_date"], run["end_date"], str(date.today()), str(it.get("ref", "")), str(it["path"]), _now()))
        warnings = ctx.result.get("warnings", [])
        db.x("UPDATE runs SET status=?, finished=?, files=? WHERE id=?",
             ("partial" if warnings else "done", _now(), json.dumps([str(f) for f in files]), rid))
        if warnings:
            log("Finished with problems: " + "; ".join(warnings) + " - press 'Finish remaining' to retry just those")
        else:
            log("Done")
    except Exception as e:
        log(f"FAILED: {e}")
        log("TRACE\n" + traceback.format_exc())
        db.x("UPDATE runs SET status='failed', finished=? WHERE id=?", (_now(), rid))


def start():
    # A previous session may have died mid-run; don't leave those looking active.
    db.x("UPDATE runs SET status='failed', finished=? WHERE status IN ('queued','running','waiting_otp')", (_now(),))
    threading.Thread(target=_worker, daemon=True).start()

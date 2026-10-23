import json, queue, threading, traceback
from datetime import datetime, date
from . import db, secrets_store, sheets
from .adapters import get_adapter
from .adapters.base import Ctx

_jobs = queue.Queue()
_otp = {}  # run_id -> {"event": Event, "value": str}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def enqueue(account_id):
    running = db.q("SELECT id FROM runs WHERE account_id=? AND day=? AND status IN ('queued','running','waiting_otp')",
                   (account_id, str(date.today())))
    if running:
        return running[0]["id"]
    rid = db.x("INSERT INTO runs(account_id,day,status,started) VALUES(?,?,?,?)",
               (account_id, str(date.today()), "queued", _now()))
    _jobs.put(rid)
    return rid


def enqueue_all():
    return [enqueue(a["id"]) for a in db.q("SELECT id FROM accounts")]


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
        ctx = Ctx(acct, secrets_store.get_password(acct["brand"], acct["platform"]), out, log, ask_otp)
        files = get_adapter(acct["platform"]).run(ctx)
        brand = db.q("SELECT sheet_id FROM brands WHERE name=?", (acct["brand"],))
        sheets.push_report(brand[0]["sheet_id"] if brand else "", acct["platform"], files, log)
        db.x("UPDATE runs SET status='done', finished=?, files=? WHERE id=?",
             (_now(), json.dumps([str(f) for f in files]), rid))
        log("Done")
    except Exception as e:
        log(f"FAILED: {e}")
        log("TRACE\n" + traceback.format_exc())
        db.x("UPDATE runs SET status='failed', finished=? WHERE id=?", (_now(), rid))


def start():
    # A previous session may have died mid-run; don't leave those looking active.
    db.x("UPDATE runs SET status='failed', finished=? WHERE status IN ('queued','running','waiting_otp')", (_now(),))
    threading.Thread(target=_worker, daemon=True).start()

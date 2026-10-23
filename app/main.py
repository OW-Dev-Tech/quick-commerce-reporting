import json, re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from . import db, runner, secrets_store, shared_config
from .adapters import PLATFORMS

sched = BackgroundScheduler()


def reschedule():
    hh, mm = db.get_setting("schedule_time", "10:00").split(":")
    sched.add_job(runner.enqueue_all, "cron", hour=int(hh), minute=int(mm), id="daily", replace_existing=True)


@asynccontextmanager
async def lifespan(app):
    try:
        shared_config.pull()
    except Exception as e:
        print("Shared config pull failed:", e)
    runner.start(); sched.start(); reschedule()
    yield
    sched.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def sheet_id(v):
    """Accept a full Google Sheet link or a bare ID."""
    m = re.search(r"/d/([A-Za-z0-9_-]+)", v or "")
    return m.group(1) if m else (v or "").strip()


def _push():
    try:
        shared_config.push()
    except Exception as e:
        print("Shared config push failed:", e)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/settings")
def settings_page():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    rows = db.q("""SELECT a.id account_id, a.brand, a.platform, a.login_id,
        (SELECT id FROM runs r WHERE r.account_id=a.id AND r.day=? ORDER BY r.id DESC LIMIT 1) run_id,
        (SELECT status FROM runs r WHERE r.account_id=a.id AND r.day=? ORDER BY r.id DESC LIMIT 1) status,
        (SELECT files FROM runs r WHERE r.account_id=a.id AND r.day=? ORDER BY r.id DESC LIMIT 1) files,
        (SELECT start_date FROM runs r WHERE r.account_id=a.id AND r.day=? ORDER BY r.id DESC LIMIT 1) start_date,
        (SELECT end_date FROM runs r WHERE r.account_id=a.id AND r.day=? ORDER BY r.id DESC LIMIT 1) end_date
        FROM accounts a ORDER BY a.brand, a.platform""", (str(date.today()),) * 5)
    labels = {p["id"]: p["label"] for p in PLATFORMS}
    for r in rows:
        r["status"] = r["status"] or "not_run"
        r["files"] = [Path(f).name for f in json.loads(r["files"] or "[]")]
        r["platform_label"] = labels.get(r["platform"].lower(), r["platform"])
        last = db.q("SELECT line FROM logs WHERE run_id=? AND line NOT LIKE 'TRACE%' ORDER BY id DESC LIMIT 1", (r["run_id"],)) if r["run_id"] else []
        r["message"] = last[0]["line"] if last else ""
    return {"cells": rows, "shared": shared_config.enabled(), "yesterday": runner.yesterday(),
            "schedule_time": db.get_setting("schedule_time", "10:00")}


class RunReq(BaseModel):
    start_date: str = ""
    end_date: str = ""


def _dates(r: RunReq):
    for d in (r.start_date, r.end_date):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise HTTPException(400, "Dates must look like 2026-10-22")
    if r.start_date and r.end_date and r.start_date > r.end_date:
        raise HTTPException(400, "Start date can't be after end date")
    return r.start_date or None, r.end_date or None


@app.post("/api/run/{account_id}")
def run_one(account_id: int, r: RunReq = RunReq()):
    return {"run_id": runner.enqueue(account_id, *_dates(r))}


@app.post("/api/run-all")
def run_all(r: RunReq = RunReq()):
    return {"run_ids": runner.enqueue_all(*_dates(r))}


class Otp(BaseModel):
    value: str


@app.post("/api/runs/{rid}/otp")
def otp(rid: int, body: Otp):
    if not runner.submit_otp(rid, body.value.strip()):
        raise HTTPException(404, "Run is not waiting for OTP")
    return {"ok": True}


@app.get("/api/runs/{rid}/logs")
def logs(rid: int):
    run = db.q("SELECT * FROM runs WHERE id=?", (rid,))
    if not run:
        raise HTTPException(404)
    return {"run": run[0], "logs": db.q("SELECT ts,line FROM logs WHERE run_id=? ORDER BY id", (rid,))}


@app.post("/api/runs/{rid}/open-folder")
def open_folder(rid: int):
    import os, subprocess, sys
    run = db.q("SELECT files FROM runs WHERE id=?", (rid,))
    files = json.loads(run[0]["files"]) if run else []
    folder = Path(files[0]).parent.resolve() if files else None
    if not folder or not folder.is_dir() or (db.DATA / "output").resolve() not in folder.parents:
        raise HTTPException(404, "Folder not found")
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
    return {"ok": True}


@app.get("/api/runs/{rid}/files/{name}")
def download(rid: int, name: str):
    run = db.q("SELECT files FROM runs WHERE id=?", (rid,))
    for f in json.loads(run[0]["files"] if run else "[]"):
        if Path(f).name == name:
            return FileResponse(f, filename=name)
    raise HTTPException(404)


# ---- settings / config ----
@app.get("/api/config")
def config():
    accts = db.q("SELECT * FROM accounts ORDER BY brand, platform")
    for a in accts:
        a["has_password"] = secrets_store.has_password(a["brand"], a["platform"])
    return {"brands": db.q("SELECT * FROM brands ORDER BY name"), "accounts": accts,
            "schedule_time": db.get_setting("schedule_time", "10:00"),
            "shared_sheet_id": db.get_setting("shared_sheet_id"),
            "keep_browser_open": db.get_setting("keep_browser_open", "1") == "1", "platforms": PLATFORMS,
            "service_account_present": shared_config.SA_PATH.exists(),
            "shared_enabled": shared_config.enabled()}


class Brand(BaseModel):
    name: str
    sheet_id: str = ""


class Account(BaseModel):
    brand: str
    platform: str
    login_id: str
    notes: str = ""
    password: str = ""
    report_hint: str = ""
    ads_report: bool = True


@app.post("/api/brands")
def save_brand(b: Brand):
    db.x("INSERT INTO brands(name,sheet_id) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET sheet_id=excluded.sheet_id",
         (b.name.strip(), sheet_id(b.sheet_id)))
    _push(); return {"ok": True}


@app.delete("/api/brands/{name}")
def del_brand(name: str):
    db.x("DELETE FROM accounts WHERE brand=?", (name,)); db.x("DELETE FROM brands WHERE name=?", (name,))
    _push(); return {"ok": True}


@app.post("/api/accounts")
def save_account(a: Account):
    db.x("""INSERT INTO accounts(brand,platform,login_id,notes,report_hint,ads_report) VALUES(?,?,?,?,?,?)
            ON CONFLICT(brand,platform) DO UPDATE SET login_id=excluded.login_id, notes=excluded.notes,
            report_hint=excluded.report_hint, ads_report=excluded.ads_report""",
         (a.brand, a.platform.strip(), a.login_id.strip(), a.notes, a.report_hint.strip(), 1 if a.ads_report else 0))
    if a.password:
        secrets_store.set_password(a.brand, a.platform.strip(), a.password)
    _push(); return {"ok": True}


@app.delete("/api/accounts/{aid}")
def del_account(aid: int):
    db.x("DELETE FROM accounts WHERE id=?", (aid,)); _push(); return {"ok": True}


class Prefs(BaseModel):
    schedule_time: str
    shared_sheet_id: str = ""
    keep_browser_open: bool = True


@app.post("/api/prefs")
def prefs(p: Prefs):
    db.set_setting("keep_browser_open", "1" if p.keep_browser_open else "0")
    db.set_setting("schedule_time", p.schedule_time); db.set_setting("shared_sheet_id", sheet_id(p.shared_sheet_id))
    reschedule(); return {"ok": True}


@app.post("/api/sync")
def sync():
    try:
        return {"message": shared_config.pull()}
    except Exception as e:
        raise HTTPException(500, str(e))

"""Shared config sync via a Google Sheet (tabs: brands, accounts).

Holds only non-secret data. Passwords/sessions stay on each laptop.
Last-write-wins: pull on startup / "Sync" button, push after every edit.
"""
import os
from pathlib import Path
from . import db

SA_PATH = Path(os.environ.get("GOOGLE_SA_JSON", db.DATA / "service_account.json"))


def enabled():
    return bool(db.get_setting("shared_sheet_id")) and SA_PATH.exists()


def _book():
    import gspread
    return gspread.service_account(filename=str(SA_PATH)).open_by_key(db.get_setting("shared_sheet_id"))


def _tab(book, name, header):
    import gspread
    try:
        return book.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(name, 200, len(header))
        ws.append_row(header)
        return ws


def pull():
    if not enabled():
        return "shared sheet not configured"
    book = _book()
    brands = _tab(book, "brands", ["name", "sheet_id"]).get_all_records()
    accts = _tab(book, "accounts", ["brand", "platform", "login_id", "notes", "report_hint", "ads_report"]).get_all_records()
    db.x("DELETE FROM brands")
    for b in brands:
        db.x("INSERT INTO brands(name, sheet_id) VALUES(?,?)", (b["name"], str(b.get("sheet_id", ""))))
    keep = []
    for a in accts:
        db.x("""INSERT INTO accounts(brand,platform,login_id,notes,report_hint,ads_report) VALUES(?,?,?,?,?,?)
                ON CONFLICT(brand,platform) DO UPDATE SET login_id=excluded.login_id, notes=excluded.notes,
                report_hint=excluded.report_hint, ads_report=excluded.ads_report""",
             (a["brand"], a["platform"], a["login_id"], a.get("notes", ""), str(a.get("report_hint", "")), int(a.get("ads_report", 1) or 0)))
        keep.append((a["brand"], a["platform"]))
    for r in db.q("SELECT id,brand,platform FROM accounts"):
        if (r["brand"], r["platform"]) not in keep:
            db.x("DELETE FROM accounts WHERE id=?", (r["id"],))
    return f"pulled {len(brands)} brands, {len(accts)} accounts"


def push():
    if not enabled():
        return
    book = _book()
    bws = _tab(book, "brands", ["name", "sheet_id"])
    aws = _tab(book, "accounts", ["brand", "platform", "login_id", "notes", "report_hint", "ads_report"])
    bws.clear(); aws.clear()
    bws.update("A1", [["name", "sheet_id"]] + [[b["name"], b["sheet_id"]] for b in db.q("SELECT * FROM brands ORDER BY name")])
    aws.update("A1", [["brand", "platform", "login_id", "notes", "report_hint", "ads_report"]] +
               [[a["brand"], a["platform"], a["login_id"], a["notes"], a["report_hint"], a["ads_report"]] for a in db.q("SELECT * FROM accounts ORDER BY brand,platform")])

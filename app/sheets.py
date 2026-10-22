"""Pushes a downloaded report into the brand's Google Sheet (tab = platform)."""
import csv
from . import shared_config


def push_report(brand_sheet_id, platform, files, log):
    if not brand_sheet_id or not shared_config.enabled():
        log("Sheet push skipped (no brand sheet ID or service account)")
        return
    import gspread
    gc = gspread.service_account(filename=str(shared_config.SA_PATH))
    book = gc.open_by_key(brand_sheet_id)
    try:
        ws = book.worksheet(platform)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(platform, 1000, 20)
    for f in files:
        if str(f).endswith(".csv"):
            rows = list(csv.reader(open(f)))
            ws.clear(); ws.update("A1", rows)
            log(f"Pushed {len(rows)-1} rows to sheet tab '{platform}'")

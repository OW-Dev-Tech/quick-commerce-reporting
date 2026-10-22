import sqlite3, threading
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
_lock = threading.RLock()
_conn = sqlite3.connect(DATA / "app.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY, name TEXT UNIQUE, sheet_id TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, brand TEXT, platform TEXT, login_id TEXT, notes TEXT DEFAULT '', UNIQUE(brand, platform));
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, account_id INTEGER, day TEXT, status TEXT, started TEXT, finished TEXT, files TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, line TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
""")


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def x(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def get_setting(k, default=""):
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    return r[0]["v"] if r else default


def set_setting(k, v):
    x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

"""SQLite storage. Every row is scoped to an `owner` so visitors of a public
demo never see each other's records."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("AMANA_DB", os.path.join(os.path.dirname(__file__), "amana.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners(
  owner TEXT PRIMARY KEY, pin_hash TEXT, lock_seconds INTEGER DEFAULT 60, created_at TEXT);
CREATE TABLE IF NOT EXISTS records(
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, order_no TEXT NOT NULL,
  version INTEGER NOT NULL, data_json TEXT NOT NULL, original_json TEXT NOT NULL,
  field_hashes TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  created_at TEXT NOT NULL, is_sample INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, order_no TEXT NOT NULL,
  agreement_hash TEXT NOT NULL, data_json TEXT NOT NULL, hash TEXT NOT NULL,
  evidence_hash TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS followups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, order_no TEXT NOT NULL,
  text TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def ensure_owner(owner: str):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO owners(owner, created_at) VALUES(?,?)", (owner, now()))


def get_owner(owner: str):
    with conn() as c:
        return c.execute("SELECT * FROM owners WHERE owner=?", (owner,)).fetchone()


def set_owner_field(owner: str, field: str, value):
    assert field in ("pin_hash", "lock_seconds")
    with conn() as c:
        c.execute(f"UPDATE owners SET {field}=? WHERE owner=?", (value, owner))


def wipe_owner(owner: str):
    with conn() as c:
        for t in ("records", "payments", "followups"):
            c.execute(f"DELETE FROM {t} WHERE owner=?", (owner,))

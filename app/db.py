"""SQLite-Setup. Eine Datei, WAL-Mode, kurze Connections per Request."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "./data/mydealz.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mydealz_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published TIMESTAMP
);

CREATE TABLE IF NOT EXISTS groups (
    name TEXT PRIMARY KEY,
    alpha REAL NOT NULL DEFAULT 0,   -- Klicks
    beta  REAL NOT NULL DEFAULT 0,   -- Impressionen ohne Klick
    manual_override TEXT,            -- 'allow' | 'block' | NULL
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deal_groups (
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    group_name TEXT NOT NULL REFERENCES groups(name),
    PRIMARY KEY (deal_id, group_name)
);

CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS impressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    counted INTEGER NOT NULL DEFAULT 0  -- bereits in beta verbucht?
);

CREATE TABLE IF NOT EXISTS feed_pulls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pulled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_deals_first_seen ON deals(first_seen);
CREATE INDEX IF NOT EXISTS idx_impressions_deal ON impressions(deal_id, counted);
CREATE INDEX IF NOT EXISTS idx_clicks_deal ON clicks(deal_id);
"""


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL;")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()

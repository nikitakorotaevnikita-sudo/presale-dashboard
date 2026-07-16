import sqlite3
from datetime import datetime, timezone

from src.models import StatusEvent, EVENT_FIELDS, DIMENSION_ATTR

_COLS = ", ".join(EVENT_FIELDS)
_PLACEHOLDERS = ", ".join("?" for _ in EVENT_FIELDS)


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


_REAL_FIELDS = ("duration_rd", "work_duration_rd", "hours")
_INT_FIELDS = ("month",)


def _col_type(f):
    if f in _REAL_FIELDS:
        return "REAL"
    if f in _INT_FIELDS:
        return "INTEGER"
    return "TEXT"


def init_db(conn):
    cols_ddl = ", ".join(f"{f} {_col_type(f)}" for f in EVENT_FIELDS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS status_events ({cols_ddl});
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, uploaded_at TEXT, row_count INTEGER, uploaded_by TEXT
        );
    """)
    # миграция: добавить недостающие колонки в уже существующую таблицу
    existing = {r[1] for r in conn.execute("PRAGMA table_info(status_events)")}
    for f in EVENT_FIELDS:
        if f not in existing:
            conn.execute(f"ALTER TABLE status_events ADD COLUMN {f} {_col_type(f)}")
    conn.commit()


def replace_events(conn, events, filename, uploaded_by):
    rows = [tuple(getattr(e, f) for f in EVENT_FIELDS) for e in events]
    with conn:  # транзакция: всё или ничего
        conn.execute("DELETE FROM status_events")
        conn.executemany(
            f"INSERT INTO status_events ({_COLS}) VALUES ({_PLACEHOLDERS})", rows)
        conn.execute(
            "INSERT INTO uploads (filename, uploaded_at, row_count, uploaded_by) "
            "VALUES (?, ?, ?, ?)",
            (filename, datetime.now(timezone.utc).isoformat(), len(rows), uploaded_by))


def load_events(conn):
    cur = conn.execute(f"SELECT {_COLS} FROM status_events")
    return [StatusEvent(**dict(row)) for row in cur.fetchall()]


def last_upload(conn):
    row = conn.execute(
        "SELECT filename, uploaded_at, row_count, uploaded_by "
        "FROM uploads ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


ALLOWED_ATTRS = set(DIMENSION_ATTR.values())


def distinct_values(conn):
    out = {}
    for dim, attr in DIMENSION_ATTR.items():
        assert attr in ALLOWED_ATTRS  # имена колонок только из кода, не из ввода
        cur = conn.execute(
            f"SELECT DISTINCT {attr} FROM status_events "
            f"WHERE {attr} != '' ORDER BY {attr}")
        out[dim] = [r[0] for r in cur.fetchall()]
    return out

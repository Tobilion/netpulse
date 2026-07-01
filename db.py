"""SQLite storage layer for NetPulse.

Two tables:
    measurements -- one row per successful measurement cycle
    outages      -- one row per failed cycle (network down / speed test failed)
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netpulse.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_cloudflare_ms REAL,
    loss_cloudflare_pct REAL,
    ping_google_ms REAL,
    loss_google_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements (timestamp);

CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_outages_ts ON outages (timestamp);
"""


def _iso(ts):
    """Normalize a timestamp (datetime or str) to an ISO-8601 string."""
    if isinstance(ts, datetime):
        return ts.replace(microsecond=0).isoformat(sep=" ")
    return str(ts)


@contextmanager
def get_connection(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=DEFAULT_DB_PATH):
    """Create tables if they don't exist."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_measurement(data, db_path=DEFAULT_DB_PATH):
    """Insert a measurement row.

    data keys: timestamp, download_mbps, upload_mbps,
               ping_cloudflare_ms, loss_cloudflare_pct,
               ping_google_ms, loss_google_pct
    Returns the new row id.
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO measurements
               (timestamp, download_mbps, upload_mbps,
                ping_cloudflare_ms, loss_cloudflare_pct,
                ping_google_ms, loss_google_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _iso(data["timestamp"]),
                data.get("download_mbps"),
                data.get("upload_mbps"),
                data.get("ping_cloudflare_ms"),
                data.get("loss_cloudflare_pct"),
                data.get("ping_google_ms"),
                data.get("loss_google_pct"),
            ),
        )
        return cur.lastrowid


def insert_outage(timestamp, reason, db_path=DEFAULT_DB_PATH):
    """Insert an outage row. Returns the new row id."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO outages (timestamp, reason) VALUES (?, ?)",
            (_iso(timestamp), reason),
        )
        return cur.lastrowid


def get_measurements(since=None, db_path=DEFAULT_DB_PATH):
    """Return measurement rows (as dicts), newest last.

    since: optional datetime/ISO string -- only rows at or after this time.
    """
    init_db(db_path)
    query = "SELECT * FROM measurements"
    params = []
    if since is not None:
        query += " WHERE timestamp >= ?"
        params.append(_iso(since))
    query += " ORDER BY timestamp ASC"
    with get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_outages(since=None, db_path=DEFAULT_DB_PATH):
    """Return outage rows (as dicts), newest last."""
    init_db(db_path)
    query = "SELECT * FROM outages"
    params = []
    if since is not None:
        query += " WHERE timestamp >= ?"
        params.append(_iso(since))
    query += " ORDER BY timestamp ASC"
    with get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_stats(since=None, db_path=DEFAULT_DB_PATH):
    """Aggregate stats: averages, uptime %, counts."""
    measurements = get_measurements(since=since, db_path=db_path)
    outages = get_outages(since=since, db_path=db_path)
    total_cycles = len(measurements) + len(outages)
    uptime_pct = (len(measurements) / total_cycles * 100) if total_cycles else None

    def avg(key):
        vals = [m[key] for m in measurements if m[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "measurement_count": len(measurements),
        "outage_count": len(outages),
        "uptime_pct": round(uptime_pct, 2) if uptime_pct is not None else None,
        "avg_download_mbps": avg("download_mbps"),
        "avg_upload_mbps": avg("upload_mbps"),
        "avg_ping_ms": avg("ping_cloudflare_ms"),
    }

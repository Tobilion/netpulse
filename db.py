"""SQLite storage layer for NetPulse.

Two tables:
    measurements -- one row per successful measurement cycle
    outages      -- one row per failed cycle (network down / speed test failed)
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime


def get_default_db_path():
    """DB path for this process.

    ``NETPULSE_DB`` overrides the default (useful for tests against a
    copy). When unset, the file beside db.py is used, so existing
    commands behave exactly as before.
    """
    env = os.environ.get("NETPULSE_DB")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "netpulse.db")


DEFAULT_DB_PATH = get_default_db_path()

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_cloudflare_ms REAL,
    loss_cloudflare_pct REAL,
    ping_google_ms REAL,
    loss_google_pct REAL,
    loaded_ms REAL,
    jitter_ms REAL,
    server TEXT,
    client TEXT,
    engine TEXT,
    server_idle_ms REAL,
    server_loaded_ms REAL,
    server_jitter_ms REAL,
    server_target TEXT
);
CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements (timestamp);

CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_outages_ts ON outages (timestamp);

CREATE TABLE IF NOT EXISTS failed_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_cloudflare_ms REAL,
    loss_cloudflare_pct REAL,
    ping_google_ms REAL,
    loss_google_pct REAL,
    loaded_ms REAL,
    jitter_ms REAL,
    server TEXT,
    client TEXT,
    engine TEXT,
    reason TEXT,
    server_idle_ms REAL,
    server_loaded_ms REAL,
    server_jitter_ms REAL,
    server_target TEXT
);
CREATE INDEX IF NOT EXISTS idx_failed_ts ON failed_tests (timestamp);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Programming errors (NameError, TypeError, ...) are NOT network events.
-- They are recorded here so they never count as outages or failed tests.
CREATE TABLE IF NOT EXISTS logger_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT,
    message TEXT,
    context TEXT,
    traceback TEXT
);
CREATE INDEX IF NOT EXISTS idx_logger_errors_ts ON logger_errors (timestamp);

-- Cycles that were deliberately skipped (e.g. engine rate-limited).
-- Not a measurement and not an outage.
CREATE TABLE IF NOT EXISTS skipped_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_skipped_ts ON skipped_runs (timestamp);
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


# New columns added without deleting existing data. Pre-existing rows keep
# NULL values, which the dashboard renders as "–" (never invented numbers).
_MIGRATION_COLUMNS = {
    "loaded_ms": "REAL",
    "jitter_ms": "REAL",
    "server": "TEXT",
    "client": "TEXT",
    "engine": "TEXT",
    # Latency measured against the test server itself (Ookla), kept
    # separate from the 1.1.1.1 numbers so both can be labelled.
    "server_idle_ms": "REAL",
    "server_loaded_ms": "REAL",
    "server_jitter_ms": "REAL",
    "server_target": "TEXT",
    # Flagged rows are kept but excluded from averages/health by default.
    "flagged": "INTEGER DEFAULT 0",
    "flag_reason": "TEXT",
    # Why the primary engine was not used (e.g. Ookla rate limit).
    "fallback_reason": "TEXT",
}

_FAILED_TEST_MIGRATION_COLUMNS = {
    "server_idle_ms": "REAL",
    "server_loaded_ms": "REAL",
    "server_jitter_ms": "REAL",
    "server_target": "TEXT",
    "fallback_reason": "TEXT",
}


def init_db(db_path=DEFAULT_DB_PATH):
    """Create tables if they don't exist and apply additive migrations."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(measurements)").fetchall()
        }
        for col, kind in _MIGRATION_COLUMNS.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE measurements ADD COLUMN {col} {kind}")
        failed_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(failed_tests)").fetchall()
        }
        for col, kind in _FAILED_TEST_MIGRATION_COLUMNS.items():
            if col not in failed_cols:
                conn.execute(f"ALTER TABLE failed_tests ADD COLUMN {col} {kind}")


def get_setting(key, default=None, db_path=DEFAULT_DB_PATH):
    """Read a setting value. Returns default when missing."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value, db_path=DEFAULT_DB_PATH):
    """Write a setting value (NULL removes it)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )


def insert_measurement(data, db_path=DEFAULT_DB_PATH):
    """Insert a measurement row.

    Required key: timestamp. Optional keys: download_mbps, upload_mbps,
    ping_cloudflare_ms, loss_cloudflare_pct, ping_google_ms,
    loss_google_pct, loaded_ms, jitter_ms, server, client, engine,
    server_idle_ms, server_loaded_ms, server_jitter_ms, server_target,
    fallback_reason.
    Missing optional keys are stored as NULL (rendered as "\u2013").
    Returns the new row id.
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO measurements
               (timestamp, download_mbps, upload_mbps,
                ping_cloudflare_ms, loss_cloudflare_pct,
                ping_google_ms, loss_google_pct,
                loaded_ms, jitter_ms, server, client, engine,
                server_idle_ms, server_loaded_ms, server_jitter_ms, server_target,
                fallback_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _iso(data["timestamp"]),
                data.get("download_mbps"),
                data.get("upload_mbps"),
                data.get("ping_cloudflare_ms"),
                data.get("loss_cloudflare_pct"),
                data.get("ping_google_ms"),
                data.get("loss_google_pct"),
                data.get("loaded_ms"),
                data.get("jitter_ms"),
                data.get("server"),
                data.get("client"),
                data.get("engine"),
                data.get("server_idle_ms"),
                data.get("server_loaded_ms"),
                data.get("server_jitter_ms"),
                data.get("server_target"),
                data.get("fallback_reason"),
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


def insert_failed_test(data, db_path=DEFAULT_DB_PATH):
    """Insert a failed/partial row (ping worked, transfer failed).

    Stored separately from outages so it is visible in the Log but not
    counted in outage totals or uptime. Returns the new row id.
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO failed_tests
               (timestamp, download_mbps, upload_mbps,
                ping_cloudflare_ms, loss_cloudflare_pct,
                ping_google_ms, loss_google_pct,
                loaded_ms, jitter_ms, server, client, engine, reason,
                server_idle_ms, server_loaded_ms, server_jitter_ms, server_target,
                fallback_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _iso(data["timestamp"]),
                data.get("download_mbps"),
                data.get("upload_mbps"),
                data.get("ping_cloudflare_ms"),
                data.get("loss_cloudflare_pct"),
                data.get("ping_google_ms"),
                data.get("loss_google_pct"),
                data.get("loaded_ms"),
                data.get("jitter_ms"),
                data.get("server"),
                data.get("client"),
                data.get("engine"),
                data.get("reason"),
                data.get("server_idle_ms"),
                data.get("server_loaded_ms"),
                data.get("server_jitter_ms"),
                data.get("server_target"),
                data.get("fallback_reason"),
            ),
        )
        return cur.lastrowid


def classify_outage(row):
    """Read-time class for legacy outages (never rewrite rows).

    "internal_error"  programming error (NameError, TypeError, ...) - the
                      network was never really tested, so it is neither an
                      outage nor a failed test.
    "failed_test"     a transfer failure while ping worked.
    "outage"         the network was unreachable.
    """
    reason = (row.get("reason") or "") if isinstance(row, dict) else ""
    if is_internal_error_reason(reason):
        return "internal_error"
    if reason.startswith("Speed test failed:"):
        return "failed_test"
    return "outage"


# Programming exceptions that mean "the tool broke", not "the network broke".
INTERNAL_ERROR_KINDS = (
    "NameError", "TypeError", "ImportError", "ModuleNotFoundError",
    "AttributeError", "SyntaxError", "IndentationError", "KeyError",
    "IndexError", "UnboundLocalError", "ZeroDivisionError", "RecursionError",
    "AssertionError", "NotImplementedError", "StopIteration",
)


def is_internal_error_reason(reason):
    """True when a stored reason describes a programming error."""
    if not reason:
        return False
    text = str(reason)
    # Reasons are stored as "Speed test failed: <ExceptionType>: <message>"
    # or "<ExceptionType>: <message>".
    for kind in INTERNAL_ERROR_KINDS:
        if text.startswith(kind + ":") or (": " + kind + ":") in text:
            return True
    return False


def insert_logger_error(kind, message, context=None, traceback_text=None,
                        timestamp=None, db_path=DEFAULT_DB_PATH):
    """Record a programming error. Never an outage, never a failed test."""
    init_db(db_path)
    ts = timestamp or datetime.now().replace(microsecond=0)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO logger_errors
               (timestamp, kind, message, context, traceback)
               VALUES (?, ?, ?, ?, ?)""",
            (_iso(ts), kind, message, context, traceback_text),
        )
        return cur.lastrowid


def get_logger_errors(limit=50, db_path=DEFAULT_DB_PATH):
    """Recent internal errors, newest first."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM logger_errors ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_recent_internal_errors(since_minutes=60, db_path=DEFAULT_DB_PATH):
    """How many internal errors were logged in the recent window."""
    init_db(db_path)
    cutoff = (datetime.now() - timedelta(minutes=since_minutes)).replace(microsecond=0)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM logger_errors WHERE timestamp >= ?",
            (_iso(cutoff),),
        ).fetchone()
    return row[0]


def count_consecutive_internal_errors(db_path=DEFAULT_DB_PATH):
    """Internal errors logged since the last successful measurement.

    This is what drives the dashboard banner: a burst of programming
    errors means the tool is broken, not that the network is.
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        last_ok = conn.execute(
            "SELECT MAX(timestamp) FROM measurements"
        ).fetchone()[0]
        if last_ok:
            row = conn.execute(
                "SELECT COUNT(*) FROM logger_errors WHERE timestamp > ?",
                (last_ok,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM logger_errors").fetchone()
    return row[0]


def insert_skipped_run(reason, timestamp=None, db_path=DEFAULT_DB_PATH):
    """Record a deliberately skipped cycle (not a measurement/outage)."""
    init_db(db_path)
    ts = timestamp or datetime.now().replace(microsecond=0)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO skipped_runs (timestamp, reason) VALUES (?, ?)",
            (_iso(ts), reason),
        )
        return cur.lastrowid


def get_skipped_runs(limit=50, db_path=DEFAULT_DB_PATH):
    """Recently skipped cycles, newest first."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM skipped_runs ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def flag_measurement(row_id, reason, db_path=DEFAULT_DB_PATH):
    """Flag a measurement so it is excluded from averages and health."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE measurements SET flagged = 1, flag_reason = ? WHERE id = ?",
            (reason, row_id),
        )


def unflag_measurement(row_id, db_path=DEFAULT_DB_PATH):
    """Clear a measurement flag."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE measurements SET flagged = 0, flag_reason = NULL WHERE id = ?",
            (row_id,),
        )


def flagged_measurements(db_path=DEFAULT_DB_PATH):
    """All flagged measurements (for the Log's flagged list)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM measurements WHERE flagged = 1 ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_failed_tests(since=None, db_path=DEFAULT_DB_PATH):
    """Return failed_test rows, newest last."""
    init_db(db_path)
    query = "SELECT * FROM failed_tests"
    params = []
    if since is not None:
        query += " WHERE timestamp >= ?"
        params.append(_iso(since))
    query += " ORDER BY timestamp ASC"
    with get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_measurements(since=None, db_path=DEFAULT_DB_PATH, include_flagged=False):
    """Return measurement rows (as dicts), newest last.

    since: optional datetime/ISO string -- only rows at or after this time.
    include_flagged: include rows a user flagged as not representative.
    Flagged rows are excluded by default so averages, the health score and
    the trends never use them.
    """
    init_db(db_path)
    query = "SELECT * FROM measurements"
    params = []
    where = []
    if since is not None:
        where.append("timestamp >= ?")
        params.append(_iso(since))
    if not include_flagged:
        where.append("(flagged IS NULL OR flagged = 0)")
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY timestamp ASC"
    with get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_outages(since=None, db_path=DEFAULT_DB_PATH):
    """Return outage rows (as dicts), newest last, with read-time type.

    Legacy "Speed test failed:" rows classify as "failed_test" without
    rewriting them; the dashboard excludes those from outage totals.
    """
    init_db(db_path)
    query = "SELECT * FROM outages"
    params = []
    if since is not None:
        query += " WHERE timestamp >= ?"
        params.append(_iso(since))
    query += " ORDER BY timestamp ASC"
    with get_connection(db_path) as conn:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    for row in rows:
        row["type"] = classify_outage(row)
    return rows


def get_stats(since=None, db_path=DEFAULT_DB_PATH, engine=None,
              include_flagged=False):
    """Aggregate stats: averages, uptime %, counts.

    Averages compare within the same engine: by default the latest
    engine's measurements (NULL is its own group) -- but when that
    group has fewer than 20 samples, all measurements are used so the
    numbers stay stable. ``engine="all"|"ookla"|"python"`` forces a
    selection. ``engine`` + ``sample_count`` report the group used.

    Flagged rows are excluded unless ``include_flagged`` is set.
    """
    measurements = get_measurements(since=since, db_path=db_path,
                                    include_flagged=include_flagged)
    outages = get_outages(since=since, db_path=db_path)
    if engine and engine != "all":
        if engine == "ookla":
            measurements = [
                m for m in measurements
                if (m.get("engine") or "").lower().startswith("ookla")
            ]
        elif engine == "python":
            measurements = [
                m for m in measurements
                if (m.get("engine") or "").lower().startswith("speedtest")
            ]
    # Failed/partial transfers are not outages, and internal errors are
    # not network events at all: exclude both from uptime and totals.
    true_outages = [o for o in outages if o.get("type") == "outage"]
    failed_tests = [o for o in outages if o.get("type") == "failed_test"]
    internal_errors = [o for o in outages if o.get("type") == "internal_error"]
    total_cycles = len(measurements) + len(true_outages)
    uptime_pct = (
        (len(measurements) / total_cycles * 100) if total_cycles else None
    )

    latest_engine = measurements[-1].get("engine") if measurements else None
    same_engine = [
        m for m in measurements if m.get("engine") == latest_engine
    ]
    if engine in ("all", "ookla", "python"):
        sample_rows = measurements
        sample_engine = engine if engine != "all" else latest_engine
    elif len(same_engine) < 20:
        sample_rows = measurements
        sample_engine = latest_engine
    else:
        sample_rows = same_engine
        sample_engine = latest_engine

    def avg(key, rows):
        vals = [m[key] for m in rows if m[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "measurement_count": len(measurements),
        "outage_count": len(true_outages),
        "failed_test_count": len(failed_tests),
        "internal_error_count": len(internal_errors),
        "uptime_pct": round(uptime_pct, 2) if uptime_pct is not None else None,
        "avg_download_mbps": avg("download_mbps", sample_rows),
        "avg_upload_mbps": avg("upload_mbps", sample_rows),
        "avg_ping_ms": avg("ping_cloudflare_ms", sample_rows),
        "engine": sample_engine,
        "sample_count": len(sample_rows),
    }

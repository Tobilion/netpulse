"""Unified Log query: measurements + failed tests + outages with filters."""

import csv
import io
import re
from datetime import datetime, timedelta

import db
import insights

TYPE_MEASUREMENT = "measurement"
TYPE_FAILED_TEST = "failed_test"
TYPE_OUTAGE = "outage"

RANGE_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}

SORTS = {
    # Newest first: timestamps are ISO strings, so descending works.
    "newest": lambda e: e["timestamp"],
    "oldest": lambda e: e["timestamp"],
    # Sort keys put rows without a speed last regardless of direction.
    "fastest": lambda e: (e.get("download_mbps") is None, -(e.get("download_mbps") or 0)),
    "slowest": lambda e: (e.get("download_mbps") is None, (e.get("download_mbps") or 0)),
}

# Only "newest" needs a descending pass; the speed sorts are ordered by
# their key (fastest = most negative first when ascending).
REVERSED_SORTS = {"newest"}


def mask_ip(text):
    """Mask the last octet of any IPv4 address in text."""
    if not text:
        return text
    return re.sub(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b", r"\1•••", str(text))


def parse_filters(args):
    """Read filter parameters from a request mapping."""
    rng = (args.get("range") or "7d").lower()
    since = None
    if rng == "custom":
        start = args.get("from")
        end = args.get("to")
        if start:
            try:
                since = datetime.fromisoformat(start)
            except ValueError:
                since = None
        if since is None:
            since = datetime.now() - timedelta(days=7)
        until = None
        if end:
            try:
                until = datetime.fromisoformat(end)
            except ValueError:
                until = None
    else:
        delta = RANGE_DELTAS.get(rng, RANGE_DELTAS["7d"])
        since = datetime.now() - delta if delta else None
        until = None

    kind = (args.get("type") or "all").lower()
    engine = (args.get("engine") or "all").lower()
    sort = (args.get("sort") or "newest").lower()

    def _num(name):
        raw = args.get(name)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "range": rng,
        "since": since,
        "until": until,
        "type": kind,
        "engine": engine,
        "sort": sort if sort in SORTS else "newest",
        "min_speed": _num("min_speed"),
        "max_speed": _num("max_speed"),
        "include_flagged": args.get("include_flagged") == "1",
    }


def _engine_matches(row_engine, wanted):
    if wanted == "all":
        return True
    eng = (row_engine or "").lower()
    if wanted == "ookla":
        return eng.startswith("ookla")
    if wanted == "python":
        return eng.startswith("speedtest")
    return eng == wanted


def _within(ts, since, until):
    try:
        when = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    if since and when < since:
        return False
    if until and when > until:
        return False
    return True


def _row_to_entry(row, kind):
    server = row.get("server")
    return {
        "kind": kind,
        "id": row.get("id"),
        "timestamp": row.get("timestamp"),
        "download_mbps": row.get("download_mbps"),
        "upload_mbps": row.get("upload_mbps"),
        "ping_cloudflare_ms": row.get("ping_cloudflare_ms"),
        "loss_cloudflare_pct": row.get("loss_cloudflare_pct"),
        "ping_google_ms": row.get("ping_google_ms"),
        "loss_google_pct": row.get("loss_google_pct"),
        "loaded_ms": row.get("loaded_ms"),
        "jitter_ms": row.get("jitter_ms"),
        "server_idle_ms": row.get("server_idle_ms"),
        "server_loaded_ms": row.get("server_loaded_ms"),
        "server_jitter_ms": row.get("server_jitter_ms"),
        "server_target": row.get("server_target"),
        "engine": row.get("engine"),
        "server": server,
        "client": row.get("client"),
        "reason": row.get("reason"),
        "flagged": bool(row.get("flagged")),
        "flag_reason": row.get("flag_reason"),
        "fallback_reason": row.get("fallback_reason"),
        # Where the measurement actually happened, e.g.
        # "Measured to Melbicom (Lagos, Nigeria)".
        "measured_to": server,
    }


def query_log(filters, db_path=db.DEFAULT_DB_PATH, limit=500):
    """Return (entries, medians_by_engine) for the filtered view."""
    measurements = db.get_measurements(db_path=db_path)
    failed_tests = db.get_failed_tests(db_path=db_path)
    outages = db.get_outages(db_path=db_path)

    entries = []
    for row in measurements:
        entries.append(_row_to_entry(row, TYPE_MEASUREMENT))
    for row in failed_tests:
        entries.append(_row_to_entry(row, TYPE_FAILED_TEST))
    for row in outages:
        # Legacy "Speed test failed" rows are failed tests, not outages.
        kind = TYPE_FAILED_TEST if row.get("type") == "failed_test" else TYPE_OUTAGE
        entries.append(_row_to_entry(row, kind))

    # Medians come from the full measurement set per engine (stable baseline),
    # excluding flagged rows so they match the averages elsewhere.
    medians = {}
    for row in measurements:
        if row.get("flagged"):
            continue
        eng = row.get("engine")
        if eng is None:
            continue
        medians.setdefault(eng, []).append(row.get("download_mbps"))
    medians = {k: insights.median(v) for k, v in medians.items()}

    out = []
    for entry in entries:
        if filters["type"] != "all" and entry["kind"] != filters["type"]:
            continue
        if not filters["include_flagged"] and entry.get("flagged"):
            continue
        if not _engine_matches(entry.get("engine"), filters["engine"]):
            continue
        if not _within(entry["timestamp"], filters["since"], filters["until"]):
            continue
        speed = entry.get("download_mbps")
        if filters["min_speed"] is not None:
            if speed is None or speed < filters["min_speed"]:
                continue
        if filters["max_speed"] is not None:
            if speed is None or speed > filters["max_speed"]:
                continue
        out.append(entry)

    out.sort(key=SORTS[filters["sort"]], reverse=filters["sort"] in REVERSED_SORTS)
    return out[:limit], medians


def to_csv(entries):
    """CSV of the filtered view. Client IPs stay masked."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "type", "id", "timestamp", "download_mbps", "upload_mbps",
        "idle_latency_1_1_1_1_ms", "loaded_latency_1_1_1_1_ms",
        "jitter_1_1_1_1_ms", "loss_1_1_1_1_pct",
        "idle_latency_server_ms", "loaded_latency_server_ms",
        "jitter_server_ms", "latency_target",
        "engine", "server", "client", "reason",
        "flagged", "flag_reason", "fallback_reason",
    ])
    for e in entries:
        writer.writerow([
            e.get("kind"), e.get("id"), e.get("timestamp"),
            e.get("download_mbps"), e.get("upload_mbps"),
            e.get("ping_cloudflare_ms"), e.get("loaded_ms"),
            e.get("jitter_ms"), e.get("loss_cloudflare_pct"),
            e.get("server_idle_ms"), e.get("server_loaded_ms"),
            e.get("server_jitter_ms"), e.get("server_target"),
            e.get("engine"), e.get("server"), mask_ip(e.get("client")),
            e.get("reason"),
            1 if e.get("flagged") else 0, e.get("flag_reason"),
            e.get("fallback_reason"),
        ])
    return buf.getvalue()

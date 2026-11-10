"""Flask dashboard server for NetPulse."""

import json
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

import db
import insights
import log_query
import logger

app = Flask(__name__)
# Local-only tool: pick up template edits without restarting the server.
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def _no_store_api_cache(response):
    """Keep the browser from caching API JSON — the dashboard polls live data,
    and a cached response would show stale "last measured" timestamps."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


RANGE_MAP = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


def _since_from_request():
    rng = request.args.get("range", "7d")
    delta = RANGE_MAP.get(rng, RANGE_MAP["7d"])
    return datetime.now() - delta if delta else None


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/data")
def api_data():
    since = _since_from_request()
    measurements = db.get_measurements(since=since)
    outages = db.get_outages(since=since)
    failed_tests = db.get_failed_tests(since=since)
    stats = db.get_stats(since=since, engine=request.args.get("engine"))

    # Hour-of-day average download speed
    hourly = {h: [] for h in range(24)}
    for m in measurements:
        if m["download_mbps"] is not None:
            hour = int(m["timestamp"][11:13])
            hourly[hour].append(m["download_mbps"])
    hourly_avg = [
        round(sum(v) / len(v), 2) if v else None for h, v in sorted(hourly.items())
    ]

    # Most recent measurement timestamp for the "last measured N min ago" hero pill
    last_measured = measurements[-1]["timestamp"] if measurements else None

    return jsonify({
        "stats": stats,
        "measurements": measurements,
        "outages": outages,
        "failed_tests": failed_tests,
        "hourly_avg_download": hourly_avg,
        "last_measured": last_measured,
    })


# ── Log (unified history + filters + CSV) ─────────────────────────────────
@app.route("/api/log")
def api_log():
    filters = log_query.parse_filters(request.args)
    entries, medians = log_query.query_log(filters)
    return jsonify({
        "entries": entries,
        "medians": medians,
        "filters": {
            "range": filters["range"],
            "type": filters["type"],
            "engine": filters["engine"],
            "sort": filters["sort"],
            "min_speed": filters["min_speed"],
            "max_speed": filters["max_speed"],
            "from": filters["since"].isoformat(sep=" ") if filters["since"] else None,
            "to": filters["until"].isoformat(sep=" ") if filters["until"] else None,
        },
    })


@app.route("/api/log.csv")
def api_log_csv():
    filters = log_query.parse_filters(request.args)
    entries, _ = log_query.query_log(filters)
    body = log_query.to_csv(entries)
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=netpulse-log.csv"},
    )


# ── Settings (advertised plan speed) ──────────────────────────────────────
@app.route("/api/settings")
def api_settings_get():
    return jsonify({"plan_speed_mbps": db.get_setting("plan_speed_mbps")})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    body = request.get_json(silent=True) or {}
    raw = body.get("plan_speed_mbps")
    if raw in (None, ""):
        db.set_setting("plan_speed_mbps", None)
        return jsonify({"plan_speed_mbps": None})
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Plan speed must be a number in Mbps."}), 400
    if value <= 0 or value > 100000:
        return jsonify({"error": "Plan speed must be a positive number of Mbps."}), 400
    db.set_setting("plan_speed_mbps", value)
    return jsonify({"plan_speed_mbps": value})


# ── Insights (health, compatibility, heatmap, % of plan) ─────────────────
@app.route("/api/insights")
def api_insights():
    range_key = request.args.get("range", "7d")
    delta = RANGE_MAP.get(range_key, RANGE_MAP["7d"])
    since = datetime.now() - delta if delta else None

    measurements = db.get_measurements(since=since)
    outages = db.get_outages(since=since)
    failed_tests = db.get_failed_tests(since=since)
    true_outages = [o for o in outages if o.get("type") != "failed_test"]

    plan_raw = db.get_setting("plan_speed_mbps")
    plan = float(plan_raw) if plan_raw else None

    latest = measurements[-1] if measurements else None
    latest_engine = latest.get("engine") if latest else None
    same_engine = [m for m in measurements if m.get("engine") == latest_engine]
    own_median = insights.median([m.get("download_mbps") for m in same_engine])
    target = plan if plan else own_median

    cycles = len(measurements) + len(true_outages)
    uptime = (len(measurements) / cycles * 100) if cycles else None

    health = insights.compute_health(
        uptime_pct=uptime,
        failed_test_count=len(failed_tests),
        cycle_count=cycles,
        download_mbps=latest.get("download_mbps") if latest else None,
        target_mbps=target,
        idle_latency_ms=latest.get("ping_cloudflare_ms") if latest else None,
        loss_pct=latest.get("loss_cloudflare_pct") if latest else None,
        jitter_ms=latest.get("jitter_ms") if latest else None,
    )

    week_ago = datetime.now() - timedelta(days=insights.WORSE_THAN_USUAL_WINDOW_DAYS)
    recent_same_engine = [
        m for m in db.get_measurements(since=week_ago)
        if m.get("engine") == latest_engine
    ]
    worse, median_7d = insights.worse_than_usual(
        latest.get("download_mbps") if latest else None,
        [m.get("download_mbps") for m in recent_same_engine],
    )

    heatmap = insights.build_heatmap(measurements, outages, days=90)

    pct_of_plan = None
    if plan and latest and latest.get("download_mbps") is not None:
        pct_of_plan = round(latest["download_mbps"] / plan * 100, 1)

    return jsonify({
        "health": health,
        "compatibility": insights.compute_compatibility(latest),
        "heatmap": heatmap,
        "worse_than_usual": {
            "is_worse": bool(worse),
            "median_mbps": median_7d,
            "ratio": insights.WORSE_THAN_USUAL_RATIO,
            "window_days": insights.WORSE_THAN_USUAL_WINDOW_DAYS,
            "download_mbps": latest.get("download_mbps") if latest else None,
        },
        "plan": {
            "plan_speed_mbps": plan,
            "target_mbps": target,
            "target_source": "plan" if plan else "same-engine median",
            "pct_of_plan": pct_of_plan,
            "own_median_mbps": own_median,
        },
        "latest": latest,
    })


# ── Light polling for new incidents (toast + Log prepend) ───────────────
@app.route("/api/updates")
def api_updates():
    """Rows newer than `since` (timestamp string) for live toasts."""
    since = request.args.get("since")
    try:
        cutoff = datetime.fromisoformat(since) if since else None
    except ValueError:
        cutoff = None

    def _new(rows, kind):
        out = []
        for r in rows:
            if cutoff is None:
                continue
            try:
                when = datetime.fromisoformat(r["timestamp"])
            except (TypeError, ValueError, KeyError):
                continue
            if when > cutoff:
                out.append({
                    "kind": kind,
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "reason": r.get("reason"),
                })
        return out

    outages = db.get_outages()
    failed = db.get_failed_tests()
    events = _new(outages, "outage") + _new(failed, "failed_test")
    events.sort(key=lambda e: e["timestamp"])
    latest_ts = None
    for group in (failed, outages):
        for r in group:
            if latest_ts is None or r["timestamp"] > latest_ts:
                latest_ts = r["timestamp"]
    return jsonify({"events": events, "latest_timestamp": latest_ts})


# ── On-demand live speed test ────────────────────────────────────────────
# A single background job runs at a time. The worker thread mutates the dict
# in place; the lock only guards start/cancel (start sets a fresh job).

_LIVE_JOB_LOCK = threading.Lock()
_live_job = None


# Dashboard-level watchdog safety net (live_sampler has its own child
# watchdog). Slow links may take ~60s; 150s is the hard ceiling.
# Configurable via NETPULSE_MAX_JOB_SECONDS / NETPULSE_STALL_SECONDS.
MAX_JOB_SECONDS = int(__import__("os").environ.get("NETPULSE_MAX_JOB_SECONDS", "150"))
_STALL_SECONDS = int(__import__("os").environ.get("NETPULSE_STALL_SECONDS", "30"))


def _watchdog(job, started_at):
    """Mark a stalled job failed; the worker's finally clears running."""
    time.sleep(5)
    while job.get("running"):
        now = time.monotonic()
        if now - started_at > MAX_JOB_SECONDS:
            job["cancel"] = True
            job["phase"] = "error"
            job["error"] = (
                f"Watchdog: test exceeded {MAX_JOB_SECONDS}s; reset. Try again."
            )
            return
        last = job.get("last_progress_at")
        if last is not None and now - last > _STALL_SECONDS:
            job["cancel"] = True
            job["phase"] = "error"
            job["error"] = (
                f"Watchdog: no progress for {_STALL_SECONDS}s; reset. Try again."
            )
            return
        time.sleep(5)


def _run_live_job():
    """Background worker: run one on-demand test and store the outcome.

    The finally block guarantees the job never stays stuck at running=true.
    """
    job = _live_job

    def on_phase(name):
        job["phase"] = name
        job["last_progress_at"] = time.monotonic()

    def on_progress(event):
        # Live samples drive the needle only; final stored values land in
        # job["download_mbps"]/["upload_mbps"] below.
        job["phase"] = event.get("phase", job["phase"])
        job["download_live_mbps"] = event.get("download_mbps")
        job["upload_live_mbps"] = event.get("upload_mbps")
        job["ping_live_ms"] = event.get("ping_ms")
        job["unloaded_ms"] = event.get("unloaded_ms", job.get("unloaded_ms"))
        job["loaded_ms"] = event.get("loaded_ms", job.get("loaded_ms"))
        job["jitter_ms"] = event.get("jitter_ms", job.get("jitter_ms"))
        job["last_progress_at"] = time.monotonic()

    def should_cancel():
        return bool(job["cancel"])

    try:
        threading.Thread(
            target=_watchdog, args=(job, job.get("started_at") or time.monotonic()),
            daemon=True,
        ).start()
        try:
            result = logger.run_live_cycle(
                on_phase=on_phase, should_cancel=should_cancel, on_progress=on_progress
            )
        except Exception as exc:
            if job.get("phase") != "error":
                job["phase"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
            return

        if result is None:
            if job.get("phase") != "error":
                job["phase"] = "idle"
            return

        if result["status"] == "failed":
            job["phase"] = "failed"
            job["error"] = result.get("reason")
            job["download_mbps"] = result.get("download_mbps")
            job["upload_mbps"] = result.get("upload_mbps")
            job["unloaded_ms"] = result.get("unloaded_ms")
            job["loaded_ms"] = result.get("loaded_ms")
            job["jitter_ms"] = result.get("jitter_ms")
            job["client"] = result.get("client")
            job["server"] = result.get("server")
            job["engine"] = result.get("engine")
            return

        if result["status"] == "outage":
            job["phase"] = "error"
            job["error"] = result.get("reason")
            job["client"] = result.get("client")
            job["server"] = result.get("server")
            job["engine"] = result.get("engine")
            return

        job["download_mbps"] = result["download_mbps"]
        job["upload_mbps"] = result["upload_mbps"]
        job["unloaded_ms"] = result["unloaded_ms"]
        job["loaded_ms"] = result["loaded_ms"]
        job["jitter_ms"] = result.get("jitter_ms")
        job["client"] = result["client"]
        job["server"] = result["server"]
        job["engine"] = result.get("engine")
        if job.get("phase") != "error":
            job["phase"] = "done"
    finally:
        # Never leave a stuck running flag behind.
        job["running"] = False
        job["last_progress_at"] = time.monotonic()


@app.route("/api/speedtest/start", methods=["POST"])
def api_speedtest_start():
    global _live_job
    with _LIVE_JOB_LOCK:
        if _live_job and _live_job.get("running"):
            return jsonify({"error": "A speed test is already running."}), 409

        try:
            import speedtest  # noqa: F401  (same venv check as main.py)
        except ModuleNotFoundError:
            return jsonify({
                "error": "The 'speedtest' module is missing. Start the server with "
                         "venv\\Scripts\\python.exe main.py serve instead of the "
                         "system Python."
            }), 400

        _live_job = {
            "running": True,
            "phase": "latency",
            "cancel": False,
            "download_mbps": None,
            "upload_mbps": None,
            "download_live_mbps": None,
            "upload_live_mbps": None,
            "ping_live_ms": None,
            "unloaded_ms": None,
            "loaded_ms": None,
            "jitter_ms": None,
            "client": None,
            "server": None,
            "engine": None,
            "error": None,
            "started_at": time.monotonic(),
            "last_progress_at": time.monotonic(),
        }
        threading.Thread(target=_run_live_job, daemon=True).start()
    return jsonify({"running": True})


@app.route("/api/speedtest/status")
def api_speedtest_status():
    global _live_job
    if not _live_job:
        return jsonify({"running": False, "phase": "idle"})
    return jsonify(_live_job)


@app.route("/api/speedtest/stream")
def api_speedtest_stream():
    """SSE stream of live samples for the current job.

    The frontend subscribes with EventSource after /start. Samples come
    only from real byte counters and real pings (see live_sampler.py);
    polling /status remains as a fallback. If the connection drops, the
    client shows an explicit error -- never simulated values.
    """

    def event_stream():
        last = None
        while True:
            job = _live_job
            if job is None:
                payload = {"running": False, "phase": "idle"}
            else:
                payload = dict(job)
            encoded = json.dumps(payload)
            if encoded != last or not job or not job.get("running"):
                yield f"data: {encoded}\n\n"
                last = encoded
            if job is None or not job.get("running"):
                return
            time.sleep(0.25)
            yield ": keep-alive\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.route("/api/speedtest/cancel", methods=["POST"])
def api_speedtest_cancel():
    global _live_job
    with _LIVE_JOB_LOCK:
        if _live_job:
            _live_job["cancel"] = True
    return jsonify({"cancelled": True})


@app.route("/api/speedtest/reset", methods=["POST"])
def api_speedtest_reset():
    """Clear a finished/stale job so the UI can start fresh."""
    global _live_job
    with _LIVE_JOB_LOCK:
        if _live_job and not _live_job.get("running"):
            _live_job = None
    return jsonify({"reset": True})

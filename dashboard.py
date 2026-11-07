"""Flask dashboard server for NetPulse."""

import json
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

import db
import logger

app = Flask(__name__)


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

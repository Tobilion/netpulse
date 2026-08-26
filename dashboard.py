"""Flask dashboard server for NetPulse."""

import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

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
    stats = db.get_stats(since=since)

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
        "hourly_avg_download": hourly_avg,
        "last_measured": last_measured,
    })


# ── On-demand live speed test ────────────────────────────────────────────
# A single background job runs at a time. The worker thread mutates the dict
# in place; the lock only guards start/cancel (start sets a fresh job).

_LIVE_JOB_LOCK = threading.Lock()
_live_job = None


def _run_live_job():
    """Background worker: run one on-demand test and store the outcome."""
    job = _live_job

    def on_phase(name):
        job["phase"] = name

    def should_cancel():
        return bool(job["cancel"])

    try:
        result = logger.run_live_cycle(on_phase=on_phase, should_cancel=should_cancel)
    except Exception as exc:
        job["phase"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["running"] = False
        return

    if result is None:
        job["phase"] = "idle"
        job["running"] = False
        return

    if result["status"] == "outage":
        job["phase"] = "error"
        job["error"] = result.get("reason")
        job["client"] = result.get("client")
        job["server"] = result.get("server")
        job["running"] = False
        return

    job["download_mbps"] = result["download_mbps"]
    job["upload_mbps"] = result["upload_mbps"]
    job["unloaded_ms"] = result["unloaded_ms"]
    job["loaded_ms"] = result["loaded_ms"]
    job["client"] = result["client"]
    job["server"] = result["server"]
    job["phase"] = "done"
    job["running"] = False


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
            "unloaded_ms": None,
            "loaded_ms": None,
            "client": None,
            "server": None,
            "error": None,
        }
        threading.Thread(target=_run_live_job, daemon=True).start()
    return jsonify({"running": True})


@app.route("/api/speedtest/status")
def api_speedtest_status():
    global _live_job
    if not _live_job:
        return jsonify({"running": False, "phase": "idle"})
    return jsonify(_live_job)


@app.route("/api/speedtest/cancel", methods=["POST"])
def api_speedtest_cancel():
    global _live_job
    with _LIVE_JOB_LOCK:
        if _live_job:
            _live_job["cancel"] = True
    return jsonify({"cancelled": True})

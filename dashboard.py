"""Flask dashboard server for NetPulse."""

from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

import db

app = Flask(__name__)

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

    return jsonify({
        "stats": stats,
        "measurements": measurements,
        "outages": outages,
        "hourly_avg_download": hourly_avg,
    })

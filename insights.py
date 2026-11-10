"""Derived insights: health score, compatibility, uptime heatmap.

Every threshold lives in ONE config object at the top of this file so it
can be audited and edited in one place.
"""

import statistics
from datetime import datetime, timedelta

# ── CONFIG ────────────────────────────────────────────────────────────────
# Health score weights (sum must be 1.0). These are the starting weights
# Tobi specified: reliability 35%, speed 30%, idle latency 20%, loss+jitter
# 15%. Recommendation (see the note in the review): on a slow link latency
# hurts more than speed, so consider latency 0.25 / stability 0.20.
HEALTH_WEIGHTS = {
    "reliability": 0.35,
    "speed": 0.30,
    "latency": 0.20,
    "stability": 0.15,
}

# Verdict bands on the 0-100 score.
HEALTH_BANDS = [
    (85, "excellent", "Excellent — everything is working well"),
    (70, "good", "Good — solid, minor room for improvement"),
    (50, "fair", "Fair — usable, but expect hiccups"),
    (0, "poor", "Poor — problems are likely"),
]

# How much a failed (partial) test counts against reliability, as a
# fraction of an outage. Failed tests are NOT outages, so this stays low.
FAILED_TEST_WEIGHT = 0.25

# Idle-latency quality scale (ms). These are NetPulse's own quality bands
# (not vendor minimum requirements): interactive use feels instant under
# ~30 ms, acceptable to ~50 ms, noticeably laggy to ~100 ms, painful beyond.
LATENCY_BANDS = {"excellent": 30.0, "good": 50.0, "fair": 100.0, "poor": 200.0}

# Packet loss quality scale (%): any loss is notable, >1% visibly breaks
# calls and games.
LOSS_BANDS = {"excellent": 0.0, "good": 0.5, "fair": 1.0, "poor": 2.0}

# Jitter quality scale (ms): jitter causes stutter more than raw latency.
JITTER_BANDS = {"excellent": 5.0, "good": 15.0, "fair": 30.0, "poor": 60.0}

# Compatibility thresholds per activity.
#   down_good / down_fair : minimum download Mbps for good / fair
#   ping_good / ping_fair  : idle latency ms ceiling for good / fair
#   jitter_good / jitter_fair, loss_good / loss_fair
#
# Sources:
#   Streaming — Netflix recommended internet speeds, fetched 2026-11-10:
#     https://help.netflix.com/en/node/306 (720p 3 Mbps, 1080p 5 Mbps, 4K 15 Mbps)
#   Browsing — floor set from the same published 720p baseline (a page plus
#     one 720p stream). Not a vendor "minimum" claim.
#   Video calls — Google Meet / Zoom published HD-video bandwidth figures
#     (~3.8 Mbps for HD video). NOT re-verified on 2026-11-10 (both vendor
#     pages were unreachable from this machine); check before trusting:
#     https://support.google.com/meet/answer/1622174
#     https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0063894
#   Gaming — driven by latency/jitter/loss (what actually breaks gameplay)
#     with a small bandwidth floor. The latency bands are NetPulse's own
#     quality scale (see LATENCY_BANDS), not a publisher's requirement.
COMPATIBILITY = {
    "browsing": {
        "label": "Browsing",
        "use": ["download", "ping"],
        "down_good": 3.0, "down_fair": 1.0,
        "ping_good": 100.0, "ping_fair": 250.0,
        "jitter_good": 30.0, "jitter_fair": 60.0,
        "loss_good": 0.5, "loss_fair": 2.0,
        "source": "https://help.netflix.com/en/node/306 (720p baseline)",
    },
    "gaming": {
        "label": "Gaming",
        "use": ["download", "ping", "jitter", "loss"],
        "down_good": 5.0, "down_fair": 1.0,
        "ping_good": 50.0, "ping_fair": 100.0,
        "jitter_good": 15.0, "jitter_fair": 30.0,
        "loss_good": 0.5, "loss_fair": 2.0,
        "source": "NetPulse latency/jitter/loss quality bands",
    },
    "streaming": {
        "label": "Streaming",
        # Bandwidth is what streaming needs; latency barely affects video.
        "use": ["download"],
        "down_good": 5.0, "down_fair": 3.0,
        "ping_good": 100.0, "ping_fair": 250.0,
        "jitter_good": 30.0, "jitter_fair": 60.0,
        "loss_good": 0.5, "loss_fair": 2.0,
        "source": "https://help.netflix.com/en/node/306 (1080p 5 / 720p 3 Mbps)",
    },
    "video_calls": {
        "label": "Video calls",
        "use": ["download", "ping", "jitter", "loss"],
        "down_good": 3.8, "down_fair": 1.5,
        "ping_good": 100.0, "ping_fair": 250.0,
        "jitter_good": 30.0, "jitter_fair": 60.0,
        "loss_good": 0.5, "loss_fair": 2.0,
        "source": "Meet/Zoom HD video bandwidth (unverified 2026-11-10)",
    },
}

# "Worse than usual" chip: below this fraction of the same-engine median.
WORSE_THAN_USUAL_RATIO = 0.5
WORSE_THAN_USUAL_WINDOW_DAYS = 7


# ── HELPERS ───────────────────────────────────────────────────────────────
def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _band(value, bands):
    """Score a value against a {band: ceiling} map (lower is better)."""
    if value is None:
        return None
    for name in ("excellent", "good", "fair", "poor"):
        if value <= bands[name]:
            return name
    return "poor"


def _band_score(value, bands):
    """Map a value to 0-100 using the band ceilings (linear between)."""
    if value is None:
        return None
    order = ["excellent", "good", "fair", "poor"]
    best = bands["excellent"]
    worst = bands["poor"]
    if value <= best:
        return 100.0
    if value >= worst:
        return 0.0
    for i in range(len(order) - 1):
        hi_band, lo_band = order[i], order[i + 1]
        hi, lo = bands[hi_band], bands[lo_band]
        if value <= hi:
            span = hi - lo
            if span <= 0:
                return 0.0
            return 100.0 * (hi - value) / span
    return 0.0


def median(values):
    """Median of a list, ignoring None. Returns None when empty."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return float(statistics.median(vals))


def verdict_for(score):
    """Verdict band + plain-language label for a 0-100 score."""
    for threshold, name, label in HEALTH_BANDS:
        if score >= threshold:
            return {"band": name, "label": label}
    return {"band": "poor", "label": HEALTH_BANDS[-1][2]}


# ── HEALTH SCORE ──────────────────────────────────────────────────────────
def compute_health(*, uptime_pct, failed_test_count, cycle_count,
                    download_mbps, target_mbps, idle_latency_ms,
                    loss_pct, jitter_ms):
    """Compute the 0-100 health score.

    Formula (documented for the "how this is calculated" tooltip):
      reliability = 0.60 * uptime_pct
                 + 0.40 * (100 - failed_test_penalty)
        where failed_test_penalty = min(100, failed_rate * 100
                                        * FAILED_TEST_WEIGHT)
      speed      = 100 * min(1, download / target)
        target = advertised plan speed when set, else the same-engine median
      latency    = 100 - scaled idle latency (LATENCY_BANDS)
      stability  = mean of scaled loss and scaled jitter
      score      = sum(weight * component)

    Components with no data are skipped and the remaining weights are
    re-normalised, so a missing metric never fabricates a low score.
    """
    uptime = _clamp(uptime_pct if uptime_pct is not None else 0.0)
    failed_rate = (failed_test_count / cycle_count) if cycle_count else 0.0
    penalty = min(100.0, failed_rate * 100.0 * FAILED_TEST_WEIGHT)
    reliability = 0.60 * uptime + 0.40 * (100.0 - penalty)

    speed_score = None
    if download_mbps is not None and target_mbps:
        speed_score = 100.0 * min(1.0, max(0.0, download_mbps / target_mbps))

    latency_score = _band_score(idle_latency_ms, LATENCY_BANDS)
    loss_score = _band_score(loss_pct, LOSS_BANDS)
    jitter_score = _band_score(jitter_ms, JITTER_BANDS)
    stability_score = None
    if loss_score is not None and jitter_score is not None:
        stability_score = (loss_score + jitter_score) / 2.0
    elif loss_score is not None:
        stability_score = loss_score
    elif jitter_score is not None:
        stability_score = jitter_score

    components = {
        "reliability": reliability,
        "speed": speed_score,
        "latency": latency_score,
        "stability": stability_score,
    }
    used = {k: v for k, v in components.items() if v is not None}
    weight_sum = sum(HEALTH_WEIGHTS[k] for k in used)
    if not used or weight_sum <= 0:
        score = 0.0
    else:
        score = sum(HEALTH_WEIGHTS[k] * v for k, v in used.items()) / weight_sum

    score = round(_clamp(score), 1)
    verdict = verdict_for(score)
    return {
        "score": score,
        "verdict": verdict["band"],
        "label": verdict["label"],
        "components": {k: (None if v is None else round(v, 1)) for k, v in components.items()},
        "weights": dict(HEALTH_WEIGHTS),
        "missing": [k for k, v in components.items() if v is None],
    }


# ── COMPATIBILITY ────────────────────────────────────────────────────────
def _level(value, good, fair, higher_is_worse=True):
    """Grade one metric: 'good' | 'fair' | 'poor' | None (no data).

    A metric inside its good threshold is fine; between good and fair it
    is only fair; beyond the fair threshold it is poor.
    """
    if value is None:
        return None
    if higher_is_worse:
        if value <= good:
            return "good"
        if value <= fair:
            return "fair"
        return "poor"
    if value >= good:
        return "good"
    if value >= fair:
        return "fair"
    return "poor"


_LEVEL_RANK = {"good": 0, "fair": 1, "poor": 2}


def compute_compatibility(latest):
    """good/fair/poor per activity from the latest measurement.

    Each available metric is graded on its own (good/fair/poor); the
    activity takes the worst grade of its metrics. Metrics with no data
    are skipped rather than counted as failures.
    """
    if not latest:
        return []
    download = latest.get("download_mbps")
    ping = latest.get("ping_cloudflare_ms")
    jitter = latest.get("jitter_ms")
    loss = latest.get("loss_cloudflare_pct")
    results = []
    for key, cfg in COMPATIBILITY.items():
        levels = {}
        reasons = []
        wanted = cfg.get("use", ["download", "ping", "jitter", "loss"])
        if "download" in wanted and download is not None:
            level = _level(download, cfg["down_good"], cfg["down_fair"], higher_is_worse=False)
            levels["download"] = level
            if level != "good":
                reasons.append(f"download {round(download, 1)} Mbps")
        for label, value, good, fair in (
            ("ping", ping, cfg["ping_good"], cfg["ping_fair"]),
            ("jitter", jitter, cfg["jitter_good"], cfg["jitter_fair"]),
            ("loss", loss, cfg["loss_good"], cfg["loss_fair"]),
        ):
            if label not in wanted or value is None:
                continue
            level = _level(value, good, fair)
            levels[label] = level
            if level != "good":
                reasons.append(f"{label} {round(value, 1)}")
        if not levels:
            status = "fair"
            reasons.append("no measurement data")
        else:
            status = max(levels.values(), key=lambda lvl: _LEVEL_RANK[lvl])
        results.append({
            "key": key,
            "label": cfg["label"],
            "status": status,
            "detail": ", ".join(reasons),
            "source": cfg["source"],
        })
    return results


# ── UPTIME HEATMAP ───────────────────────────────────────────────────────
def build_heatmap(measurements, outages, days=90, today=None):
    """Day-by-day uptime for the last `days` days.

    Days with no measurements are reported as "no_data" and never counted
    as 100% uptime. Failed tests are not outages and do not affect uptime.
    """
    today = today or datetime.now().date()
    start = today - timedelta(days=days - 1)
    per_day = {start + timedelta(days=i): {"ok": 0, "out": 0} for i in range(days)}
    for m in measurements:
        try:
            day = datetime.fromisoformat(m["timestamp"]).date()
        except (TypeError, ValueError):
            continue
        if day in per_day:
            per_day[day]["ok"] += 1
    for o in outages:
        if o.get("type") == "failed_test":
            continue
        try:
            day = datetime.fromisoformat(o["timestamp"]).date()
        except (TypeError, ValueError):
            continue
        if day in per_day:
            per_day[day]["out"] += 1
    out = []
    for day in sorted(per_day):
        ok = per_day[day]["ok"]
        bad = per_day[day]["out"]
        if ok == 0 and bad == 0:
            out.append({"date": day.isoformat(), "status": "no_data",
                        "uptime_pct": None, "measurements": 0, "outages": 0})
            continue
        total = ok + bad
        uptime = round(ok / total * 100, 2)
        if uptime >= 99:
            status = "excellent"
        elif uptime >= 95:
            status = "good"
        elif uptime >= 80:
            status = "fair"
        else:
            status = "poor"
        out.append({"date": day.isoformat(), "status": status,
                    "uptime_pct": uptime, "measurements": ok, "outages": bad})
    return out


# ── "WORSE THAN USUAL" ───────────────────────────────────────────────────
def worse_than_usual(download_mbps, same_engine_downloads, ratio=None):
    """True when a run is under `ratio` of the same-engine median."""
    if download_mbps is None:
        return False, None
    med = median(same_engine_downloads)
    if med is None or med <= 0:
        return False, med
    ratio = ratio if ratio is not None else WORSE_THAN_USUAL_RATIO
    return download_mbps < med * ratio, med

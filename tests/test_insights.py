"""Unit tests for the insights engine (health score, compatibility, heatmap)."""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import insights  # noqa: E402


def test_health_weights_sum_to_one():
    assert round(sum(insights.HEALTH_WEIGHTS.values()), 6) == 1.0


def test_health_perfect_connection_scores_high():
    health = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=100,
        download_mbps=100.0, target_mbps=100.0,
        idle_latency_ms=10.0, loss_pct=0.0, jitter_ms=2.0,
    )
    assert health["score"] >= 95
    assert health["verdict"] == "excellent"


def test_health_poor_connection_scores_low():
    health = insights.compute_health(
        uptime_pct=50.0, failed_test_count=20, cycle_count=100,
        download_mbps=0.3, target_mbps=20.0,
        idle_latency_ms=400.0, loss_pct=5.0, jitter_ms=90.0,
    )
    assert health["score"] < 50
    assert health["verdict"] == "poor"


def test_health_slow_link_latency_drags_score_down():
    """Same speed, worse latency -> lower score."""
    fast = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=10,
        download_mbps=5.0, target_mbps=5.0,
        idle_latency_ms=20.0, loss_pct=0.0, jitter_ms=5.0,
    )
    slow = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=10,
        download_mbps=5.0, target_mbps=5.0,
        idle_latency_ms=250.0, loss_pct=0.0, jitter_ms=5.0,
    )
    assert slow["score"] < fast["score"]


def test_health_failed_tests_count_lighter_than_outages():
    """A failed test must cost less than an equivalent outage."""
    with_failed = insights.compute_health(
        uptime_pct=100.0, failed_test_count=10, cycle_count=100,
        download_mbps=10.0, target_mbps=10.0,
        idle_latency_ms=20.0, loss_pct=0.0, jitter_ms=5.0,
    )
    with_outage = insights.compute_health(
        uptime_pct=90.0, failed_test_count=0, cycle_count=100,
        download_mbps=10.0, target_mbps=10.0,
        idle_latency_ms=20.0, loss_pct=0.0, jitter_ms=5.0,
    )
    assert with_failed["score"] > with_outage["score"]


def test_health_missing_component_is_skipped_not_zeroed():
    health = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=10,
        download_mbps=10.0, target_mbps=10.0,
        idle_latency_ms=None, loss_pct=None, jitter_ms=None,
    )
    assert "latency" in health["missing"]
    assert health["components"]["latency"] is None
    # Score reflects only reliability + speed, not a zero for latency.
    assert health["score"] > 70


def test_health_verdict_bands():
    assert insights.verdict_for(90)["band"] == "excellent"
    assert insights.verdict_for(75)["band"] == "good"
    assert insights.verdict_for(55)["band"] == "fair"
    assert insights.verdict_for(20)["band"] == "poor"


def test_compatibility_uses_published_netflix_tiers():
    """5 Mbps download = 1080p tier -> streaming good."""
    items = insights.compute_compatibility(
        {"download_mbps": 5.0, "ping_cloudflare_ms": 30.0, "jitter_ms": 5.0,
         "loss_cloudflare_pct": 0.0}
    )
    by_key = {i["key"]: i for i in items}
    assert by_key["streaming"]["status"] == "good"
    assert by_key["browsing"]["status"] == "good"
    assert by_key["gaming"]["status"] == "good"


def test_compatibility_grades_each_metric_separately():
    """Good bandwidth does not excuse latency: the worst metric decides."""
    items = insights.compute_compatibility(
        {"download_mbps": 20.0, "ping_cloudflare_ms": 180.0, "jitter_ms": 5.0,
         "loss_cloudflare_pct": 0.0}
    )
    by_key = {i["key"]: i for i in items}
    # Fast link, but 180 ms latency -> video calls only fair, not good.
    assert by_key["video_calls"]["status"] == "fair"
    # 180 ms is past gaming's fair ceiling (100 ms) -> poor.
    assert by_key["gaming"]["status"] == "poor"
    # Streaming only cares about throughput here, so it stays good.
    assert by_key["streaming"]["status"] == "good"


def test_compatibility_slow_link_is_honest():
    """1 Mbps + 200 ms ping on this network should not read as good."""
    items = insights.compute_compatibility(
        {"download_mbps": 1.0, "ping_cloudflare_ms": 200.0, "jitter_ms": 40.0,
         "loss_cloudflare_pct": 1.0}
    )
    by_key = {i["key"]: i for i in items}
    assert by_key["streaming"]["status"] in ("fair", "poor")
    assert by_key["gaming"]["status"] in ("fair", "poor")
    assert by_key["video_calls"]["status"] in ("fair", "poor")


def test_compatibility_empty_latest_is_empty_list():
    assert insights.compute_compatibility(None) == []


def test_heatmap_marks_missing_days_as_no_data():
    today = datetime(2026, 11, 10).date()
    start = datetime(2026, 11, 8, 9, 0).isoformat(sep=" ")
    measurements = [{"timestamp": start, "download_mbps": 5.0}]
    heat = insights.build_heatmap(measurements, [], days=5, today=today)
    assert len(heat) == 5
    by_date = {d["date"]: d for d in heat}
    assert by_date["2026-11-08"]["status"] != "no_data"
    assert by_date["2026-11-09"]["status"] == "no_data"
    assert by_date["2026-11-09"]["uptime_pct"] is None
    # A day with no data must never be counted as 100% uptime.
    assert by_date["2026-11-09"]["uptime_pct"] is None


def test_heatmap_failed_tests_do_not_affect_uptime():
    today = datetime(2026, 11, 10).date()
    measurements = [{"timestamp": "2026-11-10 09:00:00", "download_mbps": 5.0}]
    outages = [{"timestamp": "2026-11-10 10:00:00", "reason": "x", "type": "failed_test"}]
    heat = insights.build_heatmap(measurements, outages, days=1, today=today)
    assert heat[0]["uptime_pct"] == 100.0
    assert heat[0]["outages"] == 0


def test_worse_than_usual_uses_median():
    downloads = [5.0, 5.0, 5.0, 6.0, 4.0]  # median 5.0
    is_worse, med = insights.worse_than_usual(2.0, downloads)
    assert is_worse is True
    assert med == 5.0
    is_worse, _ = insights.worse_than_usual(4.5, downloads)
    assert is_worse is False


def test_worse_than_usual_ignores_none_and_empty():
    is_worse, med = insights.worse_than_usual(1.0, [])
    assert is_worse is False and med is None
    is_worse, med = insights.worse_than_usual(None, [5.0])
    assert is_worse is False


def test_band_score_discriminates_across_the_range():
    """Values above the 'good' ceiling must still score between 0 and 100."""
    assert insights._band_score(10, insights.LATENCY_BANDS) == 100.0
    mid = insights._band_score(115, insights.LATENCY_BANDS)
    assert 0 < mid < 100, f"115 ms should score in between, got {mid}"
    assert insights._band_score(500, insights.LATENCY_BANDS) == 0.0
    assert insights._band_score(None, insights.LATENCY_BANDS) is None


def test_band_score_is_monotonic():
    values = [insights._band_score(v, insights.LATENCY_BANDS)
              for v in (10, 40, 80, 120, 160, 200, 400)]
    assert values == sorted(values, reverse=True)


def test_health_uses_discriminating_latency():
    """A 120 ms link must not score the same as a 400 ms link."""
    good = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=10,
        download_mbps=10.0, target_mbps=10.0,
        idle_latency_ms=120.0, loss_pct=0.0, jitter_ms=5.0,
    )
    bad = insights.compute_health(
        uptime_pct=100.0, failed_test_count=0, cycle_count=10,
        download_mbps=10.0, target_mbps=10.0,
        idle_latency_ms=400.0, loss_pct=0.0, jitter_ms=5.0,
    )
    assert good["score"] > bad["score"]


def test_median_helper():
    assert insights.median([3, 1, 2]) == 2
    assert insights.median([1, 2, 3, 4]) == 2.5
    assert insights.median([None, 5]) == 5
    assert insights.median([]) is None

"""Pytest tests for the db module."""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


def make_measurement(ts=None, download=50.0):
    return {
        "timestamp": ts or datetime(2026, 7, 1, 12, 0, 0),
        "download_mbps": download,
        "upload_mbps": 12.5,
        "ping_cloudflare_ms": 15.2,
        "loss_cloudflare_pct": 0.0,
        "ping_google_ms": 18.1,
        "loss_google_pct": 0.0,
    }


def test_insert_and_query_measurement(db_path):
    row_id = db.insert_measurement(make_measurement(), db_path=db_path)
    assert row_id == 1

    rows = db.get_measurements(db_path=db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["download_mbps"] == 50.0
    assert row["upload_mbps"] == 12.5
    assert row["ping_cloudflare_ms"] == 15.2
    assert row["timestamp"].startswith("2026-07-01")


def test_insert_measurement_with_missing_optional_fields(db_path):
    db.insert_measurement({"timestamp": datetime(2026, 7, 1)}, db_path=db_path)
    row = db.get_measurements(db_path=db_path)[0]
    assert row["download_mbps"] is None
    assert row["ping_google_ms"] is None


def test_outage_recording(db_path):
    db.insert_outage(datetime(2026, 7, 1, 3, 0), "Network unreachable", db_path=db_path)
    outages = db.get_outages(db_path=db_path)
    assert len(outages) == 1
    assert outages[0]["reason"] == "Network unreachable"
    assert outages[0]["timestamp"].startswith("2026-07-01 03:00")


def test_date_filtering(db_path):
    base = datetime(2026, 7, 1, 0, 0, 0)
    for days_ago in (10, 5, 1):
        db.insert_measurement(
            make_measurement(ts=base - timedelta(days=days_ago)), db_path=db_path
        )
        db.insert_outage(base - timedelta(days=days_ago), "test", db_path=db_path)

    since = base - timedelta(days=7)
    assert len(db.get_measurements(since=since, db_path=db_path)) == 2
    assert len(db.get_outages(since=since, db_path=db_path)) == 2
    assert len(db.get_measurements(db_path=db_path)) == 3


def test_measurements_ordered_ascending(db_path):
    base = datetime(2026, 7, 1)
    db.insert_measurement(make_measurement(ts=base + timedelta(hours=2)), db_path=db_path)
    db.insert_measurement(make_measurement(ts=base), db_path=db_path)
    rows = db.get_measurements(db_path=db_path)
    assert rows[0]["timestamp"] <= rows[1]["timestamp"]


def test_stats(db_path):
    db.insert_measurement(make_measurement(download=40.0), db_path=db_path)
    db.insert_measurement(make_measurement(download=60.0), db_path=db_path)
    db.insert_outage(datetime(2026, 7, 1), "test outage", db_path=db_path)

    stats = db.get_stats(db_path=db_path)
    assert stats["measurement_count"] == 2
    assert stats["outage_count"] == 1
    assert stats["avg_download_mbps"] == 50.0
    assert stats["uptime_pct"] == pytest.approx(66.67, abs=0.01)


def test_stats_empty_db(db_path):
    stats = db.get_stats(db_path=db_path)
    assert stats["uptime_pct"] is None
    assert stats["avg_download_mbps"] is None
    assert stats["measurement_count"] == 0

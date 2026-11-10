"""Tests for the Log query (filters, unified list, CSV export) and settings."""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import log_query  # noqa: E402


@pytest.fixture
def seeded(tmp_path):
    path = str(tmp_path / "log.db")
    db.init_db(path)
    now = datetime.now()
    db.insert_measurement(
        {"timestamp": (now - timedelta(hours=1)).isoformat(sep=" "),
         "download_mbps": 5.0, "upload_mbps": 2.0, "ping_cloudflare_ms": 120.0,
         "engine": "ookla-cli 1.2.0.84", "server": "Melbicom (Lagos)",
         "client": "Covenant University · 203.0.113.•••"},
        db_path=path,
    )
    db.insert_measurement(
        {"timestamp": (now - timedelta(days=3)).isoformat(sep=" "),
         "download_mbps": 40.0, "upload_mbps": 9.0, "ping_cloudflare_ms": 90.0,
         "engine": "speedtest-cli 2.1.3 (python)", "server": "Old host"},
        db_path=path,
    )
    db.insert_failed_test(
        {"timestamp": (now - timedelta(hours=2)).isoformat(sep=" "),
         "download_mbps": 3.0, "upload_mbps": None, "engine": "ookla-cli 1.2.0.84",
         "reason": "upload failed"},
        db_path=path,
    )
    db.insert_outage(
        (now - timedelta(hours=3)).isoformat(sep=" "), "Network unreachable", db_path=path
    )
    db.insert_outage(
        (now - timedelta(days=4)).isoformat(sep=" "),
        "Speed test failed: legacy boom", db_path=path,
    )
    return path


def test_log_contains_all_three_kinds(seeded):
    filters = log_query.parse_filters({"range": "all"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    kinds = {e["kind"] for e in entries}
    assert kinds == {"measurement", "failed_test", "outage"}
    # Legacy "Speed test failed" rows are re-classified as failed tests.
    assert len([e for e in entries if e["kind"] == "failed_test"]) == 2
    assert len([e for e in entries if e["kind"] == "outage"]) == 1


def test_log_time_range_filter(seeded):
    filters = log_query.parse_filters({"range": "24h"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert all(e["kind"] != "measurement" or e["download_mbps"] == 5.0 for e in entries)
    filters = log_query.parse_filters({"range": "7d"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert any(e["download_mbps"] == 40.0 for e in entries)


def test_log_type_filter(seeded):
    filters = log_query.parse_filters({"range": "all", "type": "outage"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert entries and all(e["kind"] == "outage" for e in entries)


def test_log_engine_filter(seeded):
    filters = log_query.parse_filters({"range": "all", "engine": "ookla"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert entries
    assert all((e["engine"] or "").lower().startswith("ookla") for e in entries)


def test_log_speed_range_filter(seeded):
    filters = log_query.parse_filters({"range": "all", "min_speed": "10"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert [e["download_mbps"] for e in entries] == [40.0]
    filters = log_query.parse_filters({"range": "all", "max_speed": "4"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    assert [e["download_mbps"] for e in entries] == [3.0]


def test_log_sort(seeded):
    filters = log_query.parse_filters({"range": "all", "sort": "newest"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    stamps = [e["timestamp"] for e in entries]
    assert stamps == sorted(stamps, reverse=True)
    filters = log_query.parse_filters({"range": "all", "sort": "fastest"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    speeds = [e["download_mbps"] for e in entries if e["download_mbps"] is not None]
    assert speeds == sorted(speeds, reverse=True)


def test_log_csv_masks_client(seeded):
    filters = log_query.parse_filters({"range": "all"})
    entries, _ = log_query.query_log(filters, db_path=seeded)
    csv_text = log_query.to_csv(entries)
    assert "203.0.113.•••" in csv_text
    assert "203.0.113.45" not in csv_text
    assert csv_text.splitlines()[0].startswith("type,id,timestamp")


def test_log_medians_are_per_engine(seeded):
    filters = log_query.parse_filters({"range": "all"})
    _, medians = log_query.query_log(filters, db_path=seeded)
    assert medians["ookla-cli 1.2.0.84"] == 5.0
    assert medians["speedtest-cli 2.1.3 (python)"] == 40.0


def test_settings_round_trip(tmp_path):
    path = str(tmp_path / "settings.db")
    db.init_db(path)
    assert db.get_setting("plan_speed_mbps", db_path=path) is None
    db.set_setting("plan_speed_mbps", 25, db_path=path)
    assert float(db.get_setting("plan_speed_mbps", db_path=path)) == 25.0
    db.set_setting("plan_speed_mbps", None, db_path=path)
    assert db.get_setting("plan_speed_mbps", db_path=path) is None

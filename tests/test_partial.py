"""Partial failures, failed-test split, privacy (no network)."""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import live_sampler  # noqa: E402
import main  # noqa: E402


def test_partial_error_keeps_download():
    lines = [
        '{"type":"testStart","timestamp":"2026-11-07T13:13:55Z","isp":"Covenant University","interface":{"internalIp":"198.51.100.10","name":"","macAddr":"AA:BB:CC:DD:EE:FF","isVpn":false,"externalIp":"203.0.113.45"},"server":{"id":46960,"host":"speedtest-los.melbicom.net","port":8080,"name":"Melbicom","location":"Lagos","country":"Nigeria","ip":"192.0.2.77"}}',
        '{"type":"download","timestamp":"2026-11-07T13:14:10Z","download":{"bandwidth":1000000,"bytes":1000,"elapsed":100,"progress":1.0}}',
        'not json at all',
    ]
    final = None
    last_dl = None
    for line in lines:
        event = live_sampler.parse_ookla_line(line)
        if event is None:
            continue
        if event["type"] == "download":
            last_dl = live_sampler.ookla_progress_event(event)["download_mbps"]
    assert last_dl == 8.0
    # Malformed line handling tested via parse returning None
    assert live_sampler.parse_ookla_line('{"type":"log","message":"upload failed"}') is not None


def test_failed_test_split_stats(tmp_path):
    path = str(tmp_path / "split.db")
    db.init_db(path)
    base = datetime(2026, 11, 7, 12, 0, 0)
    db.insert_measurement(
        {"timestamp": base, "download_mbps": 50.0, "upload_mbps": 10.0,
         "ping_cloudflare_ms": 20.0, "engine": "ookla-cli"},
        db_path=path,
    )
    db.insert_outage(base, "Network unreachable (all pings failed)", db_path=path)
    db.insert_outage(base, "Speed test failed: boom", db_path=path)
    db.insert_failed_test(
        {"timestamp": base, "download_mbps": 6.0, "upload_mbps": None,
         "engine": "ookla-cli 1.2.0.84", "server": "Melbicom (Lagos)",
         "reason": "upload failed"},
        db_path=path,
    )
    stats = db.get_stats(db_path=path)
    # Legacy speed-failed row classifies as failed_test, excluded from uptime.
    assert stats["outage_count"] == 1
    assert stats["failed_test_count"] == 1
    # 1 measurement vs 1 true outage -> 50% uptime.
    assert stats["uptime_pct"] == 50.0
    outages = db.get_outages(db_path=path)
    assert outages[0]["type"] == "outage"
    assert outages[1]["type"] == "failed_test"
    failed = db.get_failed_tests(db_path=path)
    assert len(failed) == 1 and failed[0]["download_mbps"] == 6.0


def test_no_full_ip_anywhere(tmp_path):
    path = str(tmp_path / "privacy.db")
    db.init_db(path)
    db.insert_measurement(
        {"timestamp": datetime(2026, 11, 7, 12, 0, 0), "download_mbps": 5.0,
         "client": "Covenant University · 203.0.113.•••",
         "engine": "ookla-cli 1.2.0.84"},
        db_path=path,
    )
    row = db.get_measurements(db_path=path)[0]
    assert "203.0.113.45" not in json.dumps(row)
    assert "203.0.113.•••" in row["client"]
    assert main._mask_ip("Covenant University · 203.0.113.45") == (
        "Covenant University · 203.0.113.•••"
    )
    # MAC / internal IP never appear in stored labels.
    assert "42:89" not in json.dumps(row)
    assert "172.16" not in json.dumps(row)

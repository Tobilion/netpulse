"""Tests for the Ookla JSONL parser and engine fallback.

Mocked lines are copied from real Ookla 1.2.0.84 output captured
2026-11-07 (Lagos); no network or DB needed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import live_sampler  # noqa: E402
import ookla_source  # noqa: E402

TEST_START = '{"type":"testStart","timestamp":"2026-11-07T13:13:55Z","isp":"Covenant University","interface":{"internalIp":"198.51.100.10","name":"","macAddr":"AA:BB:CC:DD:EE:FF","isVpn":false,"externalIp":"203.0.113.45"},"server":{"id":46960,"host":"speedtest-los.melbicom.net","port":8080,"name":"Melbicom","location":"Lagos","country":"Nigeria","ip":"192.0.2.77"}}'
PING = '{"type":"ping","timestamp":"2026-11-07T13:13:56Z","ping":{"jitter":25.807,"latency":130.776,"progress":1.0}}'
DOWNLOAD = '{"type":"download","timestamp":"2026-11-07T13:14:10Z","download":{"bandwidth":198593,"bytes":2334778,"elapsed":13723,"latency":{"iqm":708.764},"progress":1.0}}'
UPLOAD = '{"type":"upload","timestamp":"2026-11-07T13:14:26Z","upload":{"bandwidth":309021,"bytes":4252273,"elapsed":14683,"latency":{"iqm":545.229},"progress":1.0}}'
RESULT = '{"type":"result","timestamp":"2026-11-07T13:14:29Z","ping":{"jitter":25.807,"latency":134.536,"low":130.776,"high":234.005},"download":{"bandwidth":198593,"bytes":2334778,"elapsed":13723,"latency":{"iqm":708.764,"low":114.374,"high":2076.334,"jitter":109.044}},"upload":{"bandwidth":309021,"bytes":4252273,"elapsed":14683,"latency":{"iqm":545.229,"low":88.345,"high":1812.148,"jitter":103.616}},"isp":"Covenant University","interface":{"internalIp":"198.51.100.10","name":"","macAddr":"AA:BB:CC:DD:EE:FF","isVpn":false,"externalIp":"203.0.113.45"},"server":{"id":46960,"host":"speedtest-los.melbicom.net","port":8080,"name":"Melbicom","location":"Lagos","country":"Nigeria","ip":"192.0.2.77"},"result":{"id":"efdcd633-b2f7-4e80-8822-5b966e54ff6a","url":"https://www.speedtest.net/result/c/efdcd633-b2f7-4e80-8822-5b966e54ff6a","persisted":true}}'


def test_parse_ping():
    event = live_sampler.parse_ookla_line(PING)
    assert event["type"] == "ping"
    progress = live_sampler.ookla_progress_event(event)
    assert progress == {"phase": "ping", "ping_ms": 130.776, "jitter_ms": 25.807}


def test_parse_download_bandwidth_bytes_to_mbps():
    event = live_sampler.parse_ookla_line(DOWNLOAD)
    progress = live_sampler.ookla_progress_event(event)
    assert progress["phase"] == "download"
    # 198593 B/s * 8 / 1e6 = 1.589 Mbps (rounded to 3 decimals live)
    assert progress["download_mbps"] == pytest.approx(1.589, abs=0.001)
    assert progress["upload_mbps"] is None


def test_parse_upload():
    event = live_sampler.parse_ookla_line(UPLOAD)
    progress = live_sampler.ookla_progress_event(event)
    assert progress["phase"] == "upload"
    assert progress["download_mbps"] is None
    assert progress["upload_mbps"] == pytest.approx(2.472, abs=0.001)
    # Ookla's loaded latency to the test server rides along as iqm.
    assert progress["loaded_latency_ms"] == 545.229


def test_result_to_final():
    event = live_sampler.parse_ookla_line(RESULT)
    final = live_sampler.result_to_final(
        event, "Covenant University · 203.0.113.•••",
        "Melbicom (Lagos, Nigeria)", "ookla-cli 1.2.0.84",
    )
    assert final["download_mbps"] == pytest.approx(1.59, abs=0.01)
    assert final["upload_mbps"] == pytest.approx(2.47, abs=0.01)
    assert final["ping_ms"] == 134.536
    assert final["jitter_ms"] == 25.807
    assert final["engine"] == "ookla-cli 1.2.0.84"


def test_labels_from_test_start():
    client, server = live_sampler.labels_from_test_start(
        live_sampler.parse_ookla_line(TEST_START)
    )
    assert client == "Covenant University · 203.0.113.•••"
    assert server == "Melbicom (Lagos, Nigeria)"


def test_malformed_lines_ignored():
    assert live_sampler.parse_ookla_line("") is None
    assert live_sampler.parse_ookla_line("not json") is None
    assert live_sampler.parse_ookla_line('{"foo":1}') is None
    assert live_sampler.parse_ookla_line('{"type":"log","message":"hi"}') is not None


def test_fallback_when_ookla_missing(monkeypatch):
    monkeypatch.setenv("NETPULSE_LIVE_SOURCE", "auto")
    monkeypatch.setattr(live_sampler, "find_ookla_binary", lambda: None)
    source = live_sampler.get_live_source()
    assert isinstance(source, live_sampler.SpeedtestCLILiveSource)


def test_explicit_ookla_requires_binary(monkeypatch):
    monkeypatch.setenv("NETPULSE_LIVE_SOURCE", "ookla")
    monkeypatch.setattr(live_sampler, "find_ookla_binary", lambda: None)
    monkeypatch.setattr(ookla_source, "find_ookla_binary", lambda: None)
    with pytest.raises(live_sampler.PreStartError):
        live_sampler.get_live_source()


def test_engine_column_round_trip(tmp_path):
    import db

    path = str(tmp_path / "engine.db")
    db.insert_measurement(
        {"timestamp": "2026-11-07 13:00:00", "download_mbps": 1.59,
         "engine": "ookla-cli 1.2.0.84"},
        db_path=path,
    )
    db.insert_measurement(
        {"timestamp": "2026-11-07 12:00:00", "download_mbps": 50.0},
        db_path=path,
    )
    rows = db.get_measurements(db_path=path)
    assert rows[1]["engine"] == "ookla-cli 1.2.0.84"
    assert rows[0]["engine"] is None  # old-style row -> rendered as "–"

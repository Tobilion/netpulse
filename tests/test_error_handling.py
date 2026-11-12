"""Internal errors, classification, flagging, rate-limit policy, watch safety."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import insights  # noqa: E402
import live_sampler  # noqa: E402
import logger  # noqa: E402
import main as cli  # noqa: E402


@pytest.fixture
def dbl(tmp_path):
    path = str(tmp_path / "errs.db")
    db.init_db(path)
    return path


# ── Classification ────────────────────────────────────────────────────────
def test_internal_error_reason_is_classified_as_internal_error(dbl):
    row = {"reason": "Speed test failed: NameError: name 'json' is not defined"}
    assert db.classify_outage(row) == "internal_error"


def test_legacy_speed_test_failed_is_a_failed_test(dbl):
    row = {"reason": "Speed test failed: ConfigRetrievalError: dns failed"}
    assert db.classify_outage(row) == "failed_test"


def test_network_unreachable_is_an_outage(dbl):
    row = {"reason": "Network unreachable (all pings failed)"}
    assert db.classify_outage(row) == "outage"


def test_internal_errors_never_count_toward_uptime(dbl):
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 10, 0),
                            "download_mbps": 10.0}, db_path=dbl)
    db.insert_outage(datetime(2026, 11, 10, 11, 0),
                     "Speed test failed: NameError: boom", db_path=dbl)
    stats = db.get_stats(db_path=dbl)
    assert stats["outage_count"] == 0
    assert stats["internal_error_count"] == 1
    assert stats["uptime_pct"] == 100.0


# ── Internal errors are logged, never recorded as outages ────────────────
def test_run_cycle_logs_internal_error_instead_of_outage(dbl, monkeypatch):
    def boom(*a, **kw):
        raise NameError("name 'json' is not defined")

    monkeypatch.setattr(logger, "run_ping", lambda host, count=10: (20.0, 0.0))
    monkeypatch.setattr(live_sampler, "get_live_source", boom)

    result = logger.run_cycle(db_path=dbl)
    assert result["status"] == "internal_error"
    assert db.get_outages(db_path=dbl) == []
    assert db.get_failed_tests(db_path=dbl) == []
    errors = db.get_logger_errors(db_path=dbl)
    assert len(errors) == 1
    assert errors[0]["kind"] == "NameError"
    assert "json" in errors[0]["message"]


def test_internal_error_banner_counts_consecutive_errors(dbl):
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 10, 0),
                            "download_mbps": 10.0}, db_path=dbl)
    assert db.count_consecutive_internal_errors(db_path=dbl) == 0
    db.insert_logger_error("TypeError", "bad type", db_path=dbl)
    db.insert_logger_error("TypeError", "bad type", db_path=dbl)
    assert db.count_consecutive_internal_errors(db_path=dbl) == 2


# ── Flagged rows ──────────────────────────────────────────────────────────
def test_flagged_rows_excluded_from_averages_by_default(dbl):
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 10, 0),
                            "download_mbps": 10.0, "engine": "ookla"},
                           db_path=dbl)
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 11, 0),
                            "download_mbps": 100.0, "engine": "ookla"},
                           db_path=dbl)
    db.flag_measurement(2, "measured to Germany", db_path=dbl)
    stats = db.get_stats(db_path=dbl)
    assert stats["avg_download_mbps"] == 10.0
    assert stats["sample_count"] == 1
    with_flagged = db.get_stats(db_path=dbl, include_flagged=True)
    assert with_flagged["avg_download_mbps"] == 55.0
    assert with_flagged["sample_count"] == 2


def test_flagged_rows_hidden_from_get_measurements(dbl):
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 10, 0),
                            "download_mbps": 10.0}, db_path=dbl)
    db.insert_measurement({"timestamp": datetime(2026, 11, 10, 11, 0),
                            "download_mbps": 99.0}, db_path=dbl)
    db.flag_measurement(2, "foreign server", db_path=dbl)
    rows = db.get_measurements(db_path=dbl)
    assert len(rows) == 1
    assert len(db.get_measurements(db_path=dbl, include_flagged=True)) == 2
    assert len(db.flagged_measurements(db_path=dbl)) == 1


# ── Server country rules ──────────────────────────────────────────────────
def test_server_country_parsing():
    assert live_sampler.server_country("Melbicom (Lagos, Nigeria)") == "nigeria"
    assert live_sampler.server_country("Interhost (Petah Tikva, Israel)") == "israel"
    assert live_sampler.server_country("no parens") is None


def test_server_is_local_uses_home_country(monkeypatch):
    monkeypatch.setenv("NETPULSE_HOME_COUNTRY", "Nigeria")
    assert live_sampler.server_is_local("Melbicom (Lagos, Nigeria)") is True
    assert live_sampler.server_is_local("RDTx (Falkenstein, Germany)") is False


# ── Rate limit / skip policy ──────────────────────────────────────────────
class _RateLimitedSource:
    name = "ookla-cli 1.2.0.84"

    def run(self, on_progress=None, should_cancel=None):
        raise live_sampler.RateLimitedError("Ookla CLI rate limit reached")


class _ForeignSource:
    name = "speedtest-cli 2.1.3 (python)"

    def run(self, on_progress=None, should_cancel=None):
        raise live_sampler.ForeignServerError(
            "speedtest-cli can only reach TKRZ Stadtwerke GmbH (Emsdetten, Germany)")


def test_rate_limited_primary_with_foreign_fallback_skips_the_cycle(dbl, monkeypatch):
    monkeypatch.setattr(logger, "run_ping", lambda host, count=10: (20.0, 0.0))
    monkeypatch.setattr(live_sampler, "get_live_source", lambda: _RateLimitedSource())
    monkeypatch.setattr(live_sampler, "SpeedtestCLILiveSource", _ForeignSource)
    result = logger.run_cycle(db_path=dbl)
    assert result["status"] == "skipped"
    assert db.get_measurements(db_path=dbl) == []
    assert db.get_outages(db_path=dbl) == []
    skipped = db.get_skipped_runs(db_path=dbl)
    assert len(skipped) == 1
    assert "rate-limited" in skipped[0]["reason"]


def test_foreign_server_alone_skips_the_cycle(dbl, monkeypatch):
    monkeypatch.setattr(logger, "run_ping", lambda host, count=10: (20.0, 0.0))
    monkeypatch.setattr(live_sampler, "get_live_source", lambda: _ForeignSource())
    result = logger.run_cycle(db_path=dbl)
    assert result["status"] == "skipped"
    assert db.get_measurements(db_path=dbl) == []
    assert db.get_outages(db_path=dbl) == []
    assert len(db.get_skipped_runs(db_path=dbl)) == 1


def test_rate_limit_backoff_grows_exponentially(monkeypatch):
    monkeypatch.setenv("NETPULSE_RATE_LIMIT_BACKOFF_SECONDS", "900")
    monkeypatch.setenv("NETPULSE_RATE_LIMIT_BACKOFF_MAX_SECONDS", "3600")
    live_sampler.clear_rate_limit()
    first = live_sampler.note_rate_limit()
    second = live_sampler.note_rate_limit()
    third = live_sampler.note_rate_limit()
    assert first == 900
    assert second == 1800
    assert third == 3600  # capped
    hits, remaining = live_sampler.rate_limit_state()
    assert hits == 3
    assert remaining > 0
    live_sampler.clear_rate_limit()
    assert live_sampler.rate_limit_state() == (0, 0.0)


def test_rate_limit_markers_detected():
    from ookla_source import _is_rate_limited
    assert _is_rate_limited("Limit reached: Too many requests received.")
    assert _is_rate_limited("rate limit exceeded")
    assert not _is_rate_limited("connection reset")
    assert not _is_rate_limited("")


# ── watch safety ──────────────────────────────────────────────────────────
def test_watch_refuses_short_interval():
    args = cli.argparse.Namespace(interval=3, force=False)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_watch(args)
    assert exc.value.code == 2


def test_watch_minimum_and_recommended_constants():
    assert cli.MIN_WATCH_INTERVAL == 10
    assert cli.RECOMMENDED_WATCH_INTERVAL == 30

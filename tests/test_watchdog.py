"""Stuck-job reset + watchdog + run_cycle engine tests (no network)."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dashboard  # noqa: E402
import db  # noqa: E402
import logger  # noqa: E402
import live_sampler  # noqa: E402


def test_dashboard_watchdog_marks_stalled(monkeypatch):
    job = {"running": True, "phase": "download", "cancel": False,
           "last_progress_at": time.monotonic() - 100}
    dashboard._STALL_SECONDS = 1
    dashboard._watchdog(job, time.monotonic())
    assert job["cancel"] is True
    assert job["phase"] == "error"
    assert "Watchdog" in job["error"]


def test_run_live_job_finally_clears_running(monkeypatch, tmp_path):
    """Even on exception the job must not stay running=true."""
    db_path = str(tmp_path / "w.db")

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(logger, "run_live_cycle", boom)
    dashboard._live_job = {
        "running": True, "phase": "latency", "cancel": False,
        "download_mbps": None, "upload_mbps": None,
        "download_live_mbps": None, "upload_live_mbps": None,
        "ping_live_ms": None, "unloaded_ms": None, "loaded_ms": None,
        "jitter_ms": None, "client": None, "server": None, "engine": None,
        "error": None, "started_at": time.monotonic(),
        "last_progress_at": time.monotonic(),
    }
    # run_live_cycle is monkeypatched; calling the worker directly
    # should land in error and clear running via finally.
    dashboard._run_live_job()
    assert dashboard._live_job["running"] is False
    assert dashboard._live_job["phase"] == "error"


def test_reset_clears_finished_job(monkeypatch):
    dashboard._live_job = {"running": False, "phase": "done"}
    # Simulate the endpoint body (lock + clear) without Flask context.
    with dashboard._LIVE_JOB_LOCK:
        if dashboard._live_job and not dashboard._live_job.get("running"):
            dashboard._live_job = None
    assert dashboard._live_job is None


def test_run_cycle_tags_engine(monkeypatch, tmp_path):
    path = str(tmp_path / "cycle.db")
    db.init_db(path)

    class FakeSource:
        name = "fake-engine 1.0"

        def run(self, on_progress=None, should_cancel=None):
            return {"download_mbps": 5.0, "upload_mbps": 2.0,
                    "client": "FakeISP · 1.2.3.•••", "server": "Fake (Lagos)",
                    "engine": "fake-engine 1.0"}

    monkeypatch.setattr(logger, "run_ping", lambda host, count=10: (20.0, 0.0))
    monkeypatch.setattr(live_sampler, "get_live_source", lambda: FakeSource())
    result = logger.run_cycle(db_path=path)
    assert result["status"] == "ok"
    assert result["engine"] == "fake-engine 1.0"
    rows = db.get_measurements(db_path=path)
    assert rows[0]["engine"] == "fake-engine 1.0"


def test_stats_compare_within_same_engine(tmp_path):
    path = str(tmp_path / "stats.db")
    db.init_db(path)
    db.insert_measurement(
        {"timestamp": "2026-11-07 10:00:00", "download_mbps": 100.0,
         "upload_mbps": 10.0, "ping_cloudflare_ms": 10.0, "engine": "old"},
        db_path=path,
    )
    db.insert_measurement(
        {"timestamp": "2026-11-07 11:00:00", "download_mbps": 1.0,
         "upload_mbps": 1.0, "ping_cloudflare_ms": 130.0, "engine": "ookla"},
        db_path=path,
    )
    # Latest engine has <20 samples -> all engines are used.
    stats = db.get_stats(db_path=path)
    assert stats["avg_download_mbps"] == 50.5
    assert stats["sample_count"] == 2
    # Explicit engine selection compares within that engine.
    ookla_only = db.get_stats(db_path=path, engine="ookla")
    assert ookla_only["avg_download_mbps"] == 1.0
    assert ookla_only["avg_ping_ms"] == 130.0
    assert ookla_only["sample_count"] == 1
    all_stats = db.get_stats(db_path=path, engine="all")
    assert all_stats["avg_download_mbps"] == 50.5


def test_mask_ip():
    assert live_sampler.mask_ip("ISP · 203.0.113.45") == "ISP · 203.0.113.•••"
    assert live_sampler.mask_ip(None) is None

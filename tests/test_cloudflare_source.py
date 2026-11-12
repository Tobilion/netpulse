"""Tests for the Cloudflare-edge fallback source."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cloudflare_source  # noqa: E402
import live_sampler  # noqa: E402
from sources_base import country_name, home_country, home_country_code  # noqa: E402


def test_country_naming():
    assert country_name("NG") == "Nigeria"
    assert country_name("DE") == "Germany"
    assert country_name("ZZ") == "ZZ"
    assert home_country_code() == "NG"


def test_source_labels_its_edge(monkeypatch):
    monkeypatch.setattr(cloudflare_source, "_fetch_trace",
                        lambda timeout=15: {"colo": "LOS", "loc": "NG"})
    monkeypatch.setattr(cloudflare_source, "measure_latency", lambda: 24.0)
    monkeypatch.setattr(cloudflare_source, "measure_download",
                        lambda *a, **k: (12.5, 2.0, 20_000_000))
    monkeypatch.setattr(cloudflare_source, "measure_upload",
                        lambda *a, **k: (4.25, 3.0, 2_000_000))
    src = cloudflare_source.CloudflareLiveSource()
    result = src.run()
    assert result["engine"] == "cloudflare-edge LOS"
    assert result["server"] == "Cloudflare LOS (Lagos, Nigeria)"
    assert result["download_mbps"] == 12.5
    assert result["upload_mbps"] == 4.25
    # A local edge is recognised as a local server.
    assert live_sampler.server_is_local(result["server"]) is True


def test_edge_label_names_the_edge_not_the_client(monkeypatch):
    """A London edge must not be labelled as if it were in Nigeria."""
    monkeypatch.setattr(cloudflare_source, "_fetch_trace",
                        lambda timeout=15: {"colo": "LHR", "loc": "NG"})
    monkeypatch.setattr(cloudflare_source, "measure_latency", lambda: 24.0)
    monkeypatch.setattr(cloudflare_source, "measure_download",
                        lambda *a, **k: (12.5, 2.0, 20_000_000))
    monkeypatch.setattr(cloudflare_source, "measure_upload",
                        lambda *a, **k: (4.25, 3.0, 2_000_000))
    result = cloudflare_source.CloudflareLiveSource().run()
    assert result["server"] == "Cloudflare LHR (London, United Kingdom)"
    assert "Nigeria" not in result["server"]


def test_source_reports_progress(monkeypatch):
    monkeypatch.setattr(cloudflare_source, "_fetch_trace",
                        lambda timeout=15: {"colo": "LOS", "loc": "NG"})
    monkeypatch.setattr(cloudflare_source, "measure_latency", lambda: 24.0)
    monkeypatch.setattr(cloudflare_source, "measure_download",
                        lambda *a, **k: (12.5, 2.0, 20_000_000))
    monkeypatch.setattr(cloudflare_source, "measure_upload",
                        lambda *a, **k: (4.25, 3.0, 2_000_000))
    events = []
    src = cloudflare_source.CloudflareLiveSource()
    src.run(on_progress=events.append)
    phases = [e["phase"] for e in events]
    assert "download" in phases and "upload" in phases
    speeds = [e.get("download_mbps") for e in events if e.get("download_mbps")]
    assert speeds and speeds[-1] == 12.5


def test_measurement_failure_is_not_faked(monkeypatch):
    monkeypatch.setattr(cloudflare_source, "_fetch_trace",
                        lambda timeout=15: {"colo": "LOS", "loc": "NG"})
    monkeypatch.setattr(cloudflare_source, "measure_latency", lambda: 24.0)
    monkeypatch.setattr(
        cloudflare_source, "measure_download",
        lambda *a, **k: (_ for _ in ()).throw(
            cloudflare_source.CloudflareError("download failed: reset")))
    src = cloudflare_source.CloudflareLiveSource()
    with pytest.raises(cloudflare_source.CloudflareError):
        src.run()


def test_upload_retry_after_reset(monkeypatch):
    """A mid-transfer reset must be retried, not reported as a failure."""
    calls = {"n": 0}

    class FakeResp:
        def read(self, n=1024):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("reset by peer")
        return FakeResp()

    monkeypatch.setattr(cloudflare_source.time, "sleep", lambda s: None)
    monkeypatch.setattr(cloudflare_source.urllib.request, "urlopen", flaky_urlopen)
    mbps, secs, nbytes = cloudflare_source.measure_upload(1_000_000)
    # The retry succeeded: the attempt counter shows it, and a real
    # (measured) value came back rather than an exception.
    assert calls["n"] == 2
    assert mbps > 0 and nbytes == 1_000_000


def test_upload_uses_octet_stream(monkeypatch):
    """The endpoint is much slower without the content type."""
    captured = {}

    class FakeResp:
        def read(self, n=1024):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.headers)
        captured["size"] = len(req.data or b"")
        return FakeResp()

    monkeypatch.setattr(cloudflare_source.urllib.request, "urlopen", fake_urlopen)
    cloudflare_source.measure_upload(1_000_000)
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers.get("content-type") == "application/octet-stream"
    assert captured["size"] == 1_000_000

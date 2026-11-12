"""Live speed-test source selection + Python byte-counter source.

Engine selection (auto): Ookla CLI if available, else the Python
speedtest-cli source. Fallback happens only when Ookla is missing or
fails before the test starts -- never mid-test.

Progress events passed to ``on_progress``:
    {"phase": "ping"|"download"|"upload",
     "download_mbps": float|None, "upload_mbps": float|None,
     "ping_ms": float|None, "jitter_ms": float|None}

Live samples drive the needle only. The returned final dict holds the
stored values (averages over the whole phase) plus ``engine``.
"""

import os
import threading
import time

from ookla_parse import (
    bandwidth_to_mbps,
    labels_from_test_start,
    ookla_progress_event,
    parse_ookla_line,
    result_to_final,
)
from cloudflare_source import CloudflareError, CloudflareLiveSource
from ookla_source import OoklaLiveSource, find_ookla_binary, kill_process_tree, mask_ip
from sources_base import (
    ForeignServerError,
    LiveDataSource,
    PartialTestError,
    PreStartError,
    RateLimitedError,
    SkippedRun,
    home_country,
    server_country,
    server_is_local,
    watchdog_seconds,
)


class SpeedtestCLILiveSource(LiveDataSource):
    """Python-native source using the installed speedtest-cli library.

    speedtest-cli (2.1.3) has no per-second JSONL progress, so live
    throughput is counted from real bytes: download bytes are counted
    in the HTTP response wrapper, upload bytes in the patched data
    reader. A sampler thread turns byte deltas into Mbps samples.
    Nothing here simulates a measurement.
    """

    name = "speedtest-cli 2.1.3 (python)"
    SAMPLE_INTERVAL_S = 0.25

    def run(self, on_progress=None, should_cancel=None):
        import speedtest

        def emit(event):
            if on_progress:
                on_progress(event)

        def cancelled():
            return bool(should_cancel and should_cancel())

        counter = _ByteCounter()
        counter_phase = {"phase": None}
        stop_sampling = threading.Event()

        def sampler():
            prev_bytes = 0
            prev_t = time.monotonic()
            while not stop_sampling.wait(self.SAMPLE_INTERVAL_S):
                now = time.monotonic()
                cur = counter.snapshot(counter_phase["phase"])
                dt = now - prev_t
                if dt > 0 and cur >= prev_bytes:
                    instant = (cur - prev_bytes) * 8.0 / dt / 1_000_000
                    phase = counter_phase["phase"]
                    if phase == "download":
                        emit({"phase": phase, "download_mbps": round(instant, 3),
                              "upload_mbps": None})
                    elif phase == "upload":
                        emit({"phase": phase, "download_mbps": None,
                              "upload_mbps": round(instant, 3)})
                prev_bytes, prev_t = cur, now

        sampler_thread = threading.Thread(target=sampler, daemon=True)
        sampler_thread.start()

        try:
            st = speedtest.Speedtest()
            client_label = server_label = None

            if cancelled():
                return None

            config = st.get_config()
            server = st.get_best_server()
            client = config.get("client", {})
            client_label = mask_ip(
                f"{client.get('isp') or 'Unknown ISP'} · {client.get('ip') or '?'}"
            )
            server_label = (
                f"{server.get('sponsor') or 'Unknown host'} "
                f"({server.get('name') or '?'}, {server.get('country') or '?'})"
            )
            # speedtest-cli picks the nearest server to the IP's geolocated
            # position, which for this network is usually thousands of km
            # away. Measuring to another country measures that country's
            # path, so refuse instead of storing a misleading row.
            if not server_is_local(server_label):
                raise ForeignServerError(
                    f"speedtest-cli can only reach {server_label} "
                    f"(home country: {home_country().title()})"
                )

            real_opener = st._opener
            st._opener = _CountingOpener(real_opener, counter)
            counter_phase["phase"] = "download"
            try:
                download_bits = st.download()
            finally:
                st._opener = real_opener
            if cancelled():
                return None

            orig_read = speedtest.HTTPUploaderData.read

            def patched_read(instance, n=10240):
                chunk = orig_read(instance, n)
                if chunk:
                    counter.add_upload(len(chunk))
                return chunk

            counter_phase["phase"] = "upload"
            counter.reset_upload()
            speedtest.HTTPUploaderData.read = patched_read
            try:
                upload_bits = st.upload()
            finally:
                speedtest.HTTPUploaderData.read = orig_read
            if cancelled():
                return None

        finally:
            counter_phase["phase"] = None
            stop_sampling.set()
            sampler_thread.join(timeout=2)

        return {
            "download_mbps": round(download_bits / 1_000_000, 2),
            "upload_mbps": round(upload_bits / 1_000_000, 2),
            "client": client_label,
            "server": server_label,
            "engine": self.name,
        }


# ── Rate-limit backoff ───────────────────────────────────────────────────
# Ookla refuses to run once its usage limit is hit. Instead of retrying
# every cycle (which keeps the limit tripped), back off exponentially:
# 15 min, 30 min, 60 min ... capped, and reset after a successful run.
_RATE_LIMIT = {"count": 0, "until": 0.0}


def _backoff_base():
    try:
        return int(os.environ.get("NETPULSE_RATE_LIMIT_BACKOFF_SECONDS", "900"))
    except ValueError:
        return 900


def _backoff_max():
    try:
        return int(os.environ.get("NETPULSE_RATE_LIMIT_BACKOFF_MAX_SECONDS", "3600"))
    except ValueError:
        return 3600


def rate_limit_state():
    """Current backoff state: (consecutive_hits, seconds_remaining)."""
    remaining = max(0.0, _RATE_LIMIT["until"] - time.monotonic())
    return _RATE_LIMIT["count"], remaining


def note_rate_limit():
    """Record a rate limit and extend the backoff window. Returns seconds."""
    _RATE_LIMIT["count"] += 1
    delay = min(_backoff_base() * (2 ** (_RATE_LIMIT["count"] - 1)), _backoff_max())
    _RATE_LIMIT["until"] = time.monotonic() + delay
    return delay


def clear_rate_limit():
    """Reset the backoff after a successful Ookla run."""
    _RATE_LIMIT["count"] = 0
    _RATE_LIMIT["until"] = 0.0


def get_live_source(name=None):
    """Return the live source.

    Explicit ``NETPULSE_LIVE_SOURCE=ookla`` requires Ookla. Explicit
    ``speedtestcli`` requires the Python source. Otherwise auto:
    Ookla when its binary is found and it is not in rate-limit backoff,
    else the Python source.
    """
    want = (name or os.environ.get("NETPULSE_LIVE_SOURCE", "")).lower()
    if want == "ookla":
        src = OoklaLiveSource()
        if not src._binary:
            raise PreStartError("Ookla CLI binary not found")
        return src
    if want in ("speedtestcli", "speedtest-cli", "python"):
        return SpeedtestCLILiveSource()
    if want in ("auto", ""):
        hits, remaining = rate_limit_state()
        if find_ookla_binary():
            if hits and remaining > 0:
                # Still backing off: use the fallback engine instead.
                return SpeedtestCLILiveSource()
            return OoklaLiveSource()
        return SpeedtestCLILiveSource()
    raise ValueError(f"Unknown live source: {want!r}")


class _ByteCounter:
    """Thread-safe download/upload byte totals."""

    def __init__(self):
        self._download = 0
        self._upload = 0
        self._lock = threading.Lock()

    def add_download(self, n):
        with self._lock:
            self._download += n

    def add_upload(self, n):
        with self._lock:
            self._upload += n

    def reset_upload(self):
        with self._lock:
            self._upload = 0

    def snapshot(self, phase):
        with self._lock:
            return self._download if phase == "download" else self._upload


class _CountingOpener:
    """Opener wrapper whose responses count download bytes."""

    def __init__(self, real_opener, counter):
        self._real = real_opener
        self._counter = counter

    def open(self, req, *args, **kwargs):
        resp = self._real.open(req, *args, **kwargs)
        return _CountingResponse(resp, self._counter)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _CountingResponse:
    """Response wrapper counting bytes as the consumer reads them."""

    def __init__(self, resp, counter):
        self._resp = resp
        self._counter = counter

    def read(self, size=-1):
        data = self._resp.read(size)
        if data:
            self._counter.add_download(len(data))
        return data

    def close(self):
        return self._resp.close()

    def __getattr__(self, name):
        return getattr(self._resp, name)


# Re-exports so existing callers/tests keep working after the split.
__all__ = [
    "LiveDataSource", "PreStartError", "PartialTestError", "watchdog_seconds",
    "SpeedtestCLILiveSource", "get_live_source", "mask_ip",
    "find_ookla_binary", "kill_process_tree", "OoklaLiveSource",
    "parse_ookla_line", "bandwidth_to_mbps", "ookla_progress_event",
    "labels_from_test_start", "result_to_final",
    "ForeignServerError", "RateLimitedError", "SkippedRun",
    "home_country", "server_country", "server_is_local",
    "CloudflareLiveSource", "CloudflareError",
]

"""One measurement cycle for NetPulse.

Runs a speed test (speedtest-cli) and pings 1.1.1.1 and 8.8.8.8.
If everything fails, records an outage instead of crashing.
"""

import platform
import re
import statistics
import subprocess
import threading
from datetime import datetime

import db
import live_sampler

PING_TARGETS = {
    "cloudflare": "1.1.1.1",
    "google": "8.8.8.8",
}
PING_COUNT = 10


def run_ping(host, count=PING_COUNT):
    """Ping a host. Returns (avg_latency_ms, packet_loss_pct) or (None, 100.0) on failure."""
    is_windows = platform.system().lower() == "windows"
    count_flag = "-n" if is_windows else "-c"
    cmd = ["ping", count_flag, str(count), host]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * 3 + 15
        )
        output = result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return None, 100.0

    loss_match = re.search(r"(\d+(?:\.\d+)?)% (?:packet )?loss", output)
    loss = float(loss_match.group(1)) if loss_match else 100.0

    avg = None
    # Linux/macOS: "rtt min/avg/max/mdev = 9.1/10.2/12.3/0.5 ms"
    unix_match = re.search(r"= [\d.]+/([\d.]+)/", output)
    if unix_match:
        avg = float(unix_match.group(1))
    else:
        # Windows: "Average = 23ms"
        win_match = re.search(r"Average = (\d+)ms", output)
        if win_match:
            avg = float(win_match.group(1))

    return avg, loss


def _jitter_from_samples(samples):
    """Jitter as standard deviation of single-ping samples (ms).

    Returns None when fewer than two samples exist so the UI can show
    "–" instead of inventing a value.
    """
    if not samples or len(samples) < 2:
        return None
    return round(float(statistics.stdev(samples)), 1)


def run_speed_test():
    """Run a speed test. Returns (download_mbps, upload_mbps). Raises on failure."""
    import speedtest  # imported lazily: the package is slow to import

    st = speedtest.Speedtest()
    st.get_best_server()
    download = st.download() / 1_000_000  # bits/s -> Mbps
    upload = st.upload() / 1_000_000
    return round(download, 2), round(upload, 2)


def _run_sampler_result(source):
    """Run a sampler with pre-start fallback to the Python source."""
    try:
        return source.run(on_progress=None, should_cancel=None)
    except live_sampler.PreStartError:
        if isinstance(source, live_sampler.SpeedtestCLILiveSource):
            raise
        return live_sampler.SpeedtestCLILiveSource().run(
            on_progress=None, should_cancel=None
        )


def _insert_failed(timestamp, partial, pings, loaded=None, jitter=None,
                   reason=None, db_path=db.DEFAULT_DB_PATH):
    try:
        db.insert_failed_test(
            {
                "timestamp": timestamp,
                "download_mbps": partial.get("download_mbps"),
                "upload_mbps": partial.get("upload_mbps"),
                "ping_cloudflare_ms": pings["cloudflare"]["avg"] if pings else None,
                "loss_cloudflare_pct": pings["cloudflare"]["loss"] if pings else None,
                "ping_google_ms": pings["google"]["avg"] if pings else None,
                "loss_google_pct": pings["google"]["loss"] if pings else None,
                "loaded_ms": loaded,
                "jitter_ms": jitter,
                "server": partial.get("server"),
                "client": partial.get("client"),
                "engine": partial.get("engine"),
                "reason": reason or partial.get("detail"),
            },
            db_path=db_path,
        )
    except Exception:
        pass


def run_cycle(db_path=db.DEFAULT_DB_PATH):
    """Run one full measurement cycle and store the result.

    Returns a dict describing what was recorded.
    """
    timestamp = datetime.now()

    pings = {}
    for name, host in PING_TARGETS.items():
        avg, loss = run_ping(host)
        pings[name] = {"avg": avg, "loss": loss}

    network_down = all(p["avg"] is None or p["loss"] >= 100 for p in pings.values())

    download = upload = None
    speed_error = None
    sampler_result = None
    if not network_down:
        try:
            source = live_sampler.get_live_source()
            sampler_result = _run_sampler_result(source)
            download = sampler_result["download_mbps"]
            upload = sampler_result["upload_mbps"]
        except live_sampler.PartialTestError as exc:
            # Ping worked, transfer half-finished: failed test, not outage.
            _insert_failed(
                timestamp, exc.partial, pings, reason=str(exc), db_path=db_path
            )
            return {
                "status": "failed",
                "reason": str(exc),
                "download_mbps": exc.partial.get("download_mbps"),
                "upload_mbps": exc.partial.get("upload_mbps"),
                "engine": exc.partial.get("engine"),
                "server": exc.partial.get("server"),
                "client": exc.partial.get("client"),
                "timestamp": timestamp,
            }
        except Exception as exc:  # speedtest-cli raises various exception types
            speed_error = f"{type(exc).__name__}: {exc}"

    if network_down:
        db.insert_outage(timestamp, "Network unreachable (all pings failed)", db_path=db_path)
        return {"status": "outage", "reason": "network down", "timestamp": timestamp}

    if download is None:
        db.insert_outage(timestamp, f"Speed test failed: {speed_error}", db_path=db_path)
        return {"status": "outage", "reason": speed_error, "timestamp": timestamp}

    data = {
        "timestamp": timestamp,
        "download_mbps": download,
        "upload_mbps": upload,
        "ping_cloudflare_ms": pings["cloudflare"]["avg"],
        "loss_cloudflare_pct": pings["cloudflare"]["loss"],
        "ping_google_ms": pings["google"]["avg"],
        "loss_google_pct": pings["google"]["loss"],
        "engine": sampler_result.get("engine") if sampler_result else None,
        "server": sampler_result.get("server") if sampler_result else None,
        "client": sampler_result.get("client") if sampler_result else None,
    }
    db.insert_measurement(data, db_path=db_path)
    return {"status": "ok", **data}


def run_live_cycle(on_phase=None, should_cancel=None, on_progress=None,
                   db_path=db.DEFAULT_DB_PATH):
    """Run one on-demand speed test for the dashboard widget.

    Reports progress through on_phase() (phase names) and on_progress(dict)
    with real live samples. Live samples drive the needle only; the
    returned final dict holds the stored values. Returns None if
    cancelled. Failures are recorded as outages, matching run_cycle().
    """
    timestamp = datetime.now()
    client_label = server_label = None

    def report(name):
        if on_phase:
            on_phase(name)

    def cancelled():
        return bool(should_cancel and should_cancel())

    live = {"phase": "latency", "download_mbps": None, "upload_mbps": None,
            "ping_ms": None, "unloaded_ms": None, "loaded_ms": None,
            "jitter_ms": None}

    def progress(payload):
        live.update(payload)
        if on_progress:
            on_progress(dict(live))

    try:
        source = live_sampler.get_live_source()
        report("latency")
        progress({"phase": "latency"})

        # Unloaded latency: five real single pings, streamed as they land.
        # Header shows the latest single ping; the tile shows the running
        # mean, so both converge to the same 1.1.1.1 source.
        samples = []
        failed = 0
        for _ in range(5):
            if cancelled():
                return None
            avg, _loss = run_ping(PING_TARGETS["cloudflare"], count=1)
            if avg is None:
                failed += 1
            else:
                samples.append(float(avg))
                progress({"phase": "latency", "ping_ms": float(avg),
                          "unloaded_ms": round(sum(samples) / len(samples), 1)})
        jitter = _jitter_from_samples(samples)
        unloaded = round(sum(samples) / len(samples), 1) if samples else None
        cf_loss = round(failed / 5 * 100, 1) if samples or failed else None
        progress({"phase": "latency", "unloaded_ms": unloaded, "jitter_ms": jitter})

        google_avg, google_loss = run_ping(PING_TARGETS["google"], count=5)
        if cancelled():
            return None
        if unloaded is None and (google_avg is None or google_loss >= 100):
            db.insert_outage(
                timestamp, "Network unreachable (all pings failed)", db_path=db_path
            )
            return {
                "status": "outage",
                "reason": "network down",
                "timestamp": timestamp,
                "client": None,
                "server": None,
            }

        partial_error = None
        # Loaded latency: single pings while the sampler saturates the link.
        loaded_samples = []
        loaded_done = threading.Event()
        progress({"phase": "download"})
        report("download")

        def loaded_sampler():
            while not loaded_done.is_set() and not cancelled():
                avg, _loss = run_ping(PING_TARGETS["cloudflare"], count=1)
                if avg is not None:
                    loaded_samples.append(float(avg))
                    progress({"ping_ms": float(avg),
                              "loaded_ms": round(
                                  sum(loaded_samples) / len(loaded_samples), 1
                              )})
            loaded_done.set()

        def merge_speed(event):
            phase = event.get("phase")
            if phase == "ping":
                # Ookla idle latency is to the test server, not 1.1.1.1.
                # Keep the header on the single 1.1.1.1 source; only
                # keep its jitter when 1.1.1.1 jitter is missing.
                if event.get("jitter_ms") is not None and live.get("jitter_ms") is None:
                    progress({"phase": "latency", "jitter_ms": event.get("jitter_ms")})
            elif phase == "upload":
                progress({"phase": "upload",
                          "upload_mbps": event.get("upload_mbps")})
                report("upload")
            else:
                progress({"phase": "download",
                          "download_mbps": event.get("download_mbps")})

        def run_with_fallback(primary):
            # Fallback only when the primary failed before any progress:
            # retry once with the Python source, never mid-test.
            try:
                return primary.run(on_progress=merge_speed, should_cancel=should_cancel)
            except live_sampler.PreStartError:
                if isinstance(primary, live_sampler.SpeedtestCLILiveSource):
                    raise
                fallback = live_sampler.SpeedtestCLILiveSource()
                return fallback.run(on_progress=merge_speed, should_cancel=should_cancel)
            except live_sampler.PartialTestError as exc:
                if exc.partial.get("download_mbps") is not None:
                    # Keep the partial; don't retry mid-test.
                    raise
                if isinstance(primary, live_sampler.SpeedtestCLILiveSource):
                    raise
                # No download at all before failure: pre-start-like, retry.
                fallback = live_sampler.SpeedtestCLILiveSource()
                return fallback.run(on_progress=merge_speed, should_cancel=should_cancel)

        loaded_thread = threading.Thread(target=loaded_sampler, daemon=True)
        loaded_thread.start()
        try:
            result = run_with_fallback(source)
        except live_sampler.PartialTestError as exc:
            partial_error = exc
            result = None
        finally:
            loaded_done.set()
            loaded_thread.join(timeout=3)
        if partial_error is not None:
            partial = partial_error.partial
            loaded_partial = (
                round(sum(loaded_samples) / len(loaded_samples), 1)
                if loaded_samples else None
            )
            ping_map = {
                "cloudflare": {"avg": unloaded, "loss": cf_loss},
                "google": {"avg": google_avg, "loss": google_loss},
            }
            _insert_failed(
                timestamp, partial, ping_map,
                loaded=loaded_partial, jitter=jitter,
                reason=str(partial_error), db_path=db_path,
            )
            return {
                "status": "failed",
                "reason": str(partial_error),
                "download_mbps": partial.get("download_mbps"),
                "upload_mbps": partial.get("upload_mbps"),
                "unloaded_ms": unloaded,
                "loaded_ms": loaded_partial,
                "jitter_ms": jitter,
                "client": partial.get("client"),
                "server": partial.get("server"),
                "engine": partial.get("engine"),
                "timestamp": timestamp,
            }
        if result is None or cancelled():
            return None
        client_label = result.get("client")
        server_label = result.get("server")
        engine_label = result.get("engine")
        # Ookla reports its own idle jitter; keep the 1.1.1.1 jitter when
        # present so DB semantics stay comparable across engines.
        if jitter is None and result.get("jitter_ms") is not None:
            jitter = result.get("jitter_ms")
        loaded = (
            round(sum(loaded_samples) / len(loaded_samples), 1)
            if loaded_samples else None
        )
        progress({"loaded_ms": loaded})

    except Exception as exc:  # speedtest-cli raises various exception types
        reason = f"Speed test failed: {type(exc).__name__}: {exc}"
        db.insert_outage(timestamp, reason, db_path=db_path)
        return {
            "status": "outage",
            "reason": reason,
            "timestamp": timestamp,
            "client": client_label,
            "server": server_label,
        }

    data = {
        "timestamp": timestamp,
        "download_mbps": result["download_mbps"],
        "upload_mbps": result["upload_mbps"],
        "ping_cloudflare_ms": unloaded,
        "loss_cloudflare_pct": cf_loss,
        "ping_google_ms": google_avg,
        "loss_google_pct": google_loss,
        "loaded_ms": loaded,
        "jitter_ms": jitter,
        "server": server_label,
        "client": client_label,
        "engine": engine_label,
    }
    db.insert_measurement(data, db_path=db_path)
    return {
        "status": "ok",
        "unloaded_ms": unloaded,
        "loaded_ms": loaded,
        "jitter_ms": jitter,
        "client": client_label,
        "server": server_label,
        "engine": engine_label,
        **data,
    }

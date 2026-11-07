"""Live speed-test data sources behind a small swappable interface.

Frontend contract (SSE events + /api/speedtest/status JSON) is identical
for every source. Engine choice never changes frontend code.

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

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time


def mask_ip(text):
    """Mask an IPv4 address in text: 203.0.113.45 -> 203.0.113.•••."""
    if not text:
        return text
    return re.sub(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b", r"\1•••", str(text))

WINGET_OOKLA_PATH = (
    r"C:\Users\tobil\AppData\Local\Microsoft\WinGet\Packages"
    r"\Ookla.Speedtest.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\speedtest.exe"
)


class PreStartError(RuntimeError):
    """Source failed before any test progress was emitted."""


class PartialTestError(RuntimeError):
    """Test failed after some progress; carries partial results."""

    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial  # {download_mbps, upload_mbps, client, server, engine, detail}


def _watchdog_seconds(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


class LiveDataSource:
    """Interface for a live speed-test source.

    run() blocks until the test finishes and returns:
        {"download_mbps": float, "upload_mbps": float,
         "client": str|None, "server": str|None, "engine": str}
    It calls on_progress(dict) as real samples become available and
    returns None when should_cancel() becomes true.
    """

    name = "unknown"

    def run(self, on_progress=None, should_cancel=None):
        raise NotImplementedError


def find_ookla_binary():
    """Locate the Ookla CLI binary.

    Order: NETPULSE_OOKLA_PATH, shutil.which("speedtest"), then the
    known winget path. The Python speedtest-cli shim (venv speedtest.exe)
    and any non-Ookla "speedtest" are rejected via --version output.
    Returns the path or None.
    """
    candidates = []
    env_path = os.environ.get("NETPULSE_OOKLA_PATH")
    if env_path:
        candidates.append(env_path)
    found = shutil.which("speedtest")
    if found:
        candidates.append(found)
    if os.path.exists(WINGET_OOKLA_PATH):
        candidates.append(WINGET_OOKLA_PATH)
    for cand in candidates:
        if cand and os.path.exists(cand) and _is_ookla_binary(cand):
            return cand
    return None


def _is_ookla_binary(path):
    """True when ``path --version`` identifies itself as Ookla."""
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (proc.stdout or "") + (proc.stderr or "")
    return "ookla" in out.lower()


def ookla_version(path):
    """Short version string like 'ookla-cli 1.2.0.84', or None."""
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    import re

    out = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", out)
    return f"ookla-cli {match.group(1)}" if match else "ookla-cli"


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


class OoklaLiveSource(LiveDataSource):
    """Ookla CLI source: `speedtest --format=jsonl --progress=yes`.

    --accept-license is passed so a fresh machine accepts on first run;
    acceptance persists after that. --accept-gdpr is deliberately not
    passed (no GDPR prompt was observed for this connection).

    Real shapes seen on 2026-11-07 (speedtest 1.2.0.84, Lagos):
      testStart: {"type","timestamp","isp","interface":{...,"externalIp"},
                  "server":{"id","host","name","location","country","ip"}}
      ping:      {"type","timestamp","ping":{"latency","jitter","progress"}}
      download:  {"type","timestamp","download":{"bandwidth","bytes",
                  "elapsed","progress"[, "latency":{"iqm"}]}}
      upload:    same keys under "upload"
      result:    {...,"ping":{"latency","jitter","low","high"},
                  "download":{"bandwidth",...},"upload":{...},"result":{...}}
    ``bandwidth`` is bytes/sec; Mbps = bandwidth * 8 / 1e6.
    """

    def __init__(self, binary=None):
        self._binary = binary or find_ookla_binary()
        self.name = "ookla-cli (version unknown)"
        if self._binary:
            ver = ookla_version(self._binary)
            if ver:
                self.name = ver

    # Watchdog limits for slow links: stall if no JSONL for this long,
    # fail if the whole run exceeds the maximum. Hitting either kills
    # the child tree so no orphan speedtest.exe survives.
    @property
    def STALL_SECONDS(self):
        return _watchdog_seconds("NETPULSE_STALL_SECONDS", 30)

    @property
    def MAX_RUNTIME_SECONDS(self):
        return _watchdog_seconds("NETPULSE_MAX_JOB_SECONDS", 150)

    def run(self, on_progress=None, should_cancel=None):
        binary = self._binary or find_ookla_binary()
        if not binary:
            raise PreStartError("Ookla CLI binary not found")

        def emit(event):
            if on_progress:
                on_progress(event)

        def cancelled():
            return bool(should_cancel and should_cancel())

        cmd = [binary, "--format=jsonl", "--progress=yes", "--accept-license"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except OSError as exc:
            raise PreStartError(f"Cannot start Ookla CLI: {exc}") from exc

        lines = queue.Queue()
        stderr_lines = []

        def reader():
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    lines.put(line)
            except Exception:
                pass
            lines.put(None)

        def err_reader():
            assert proc.stderr is not None
            try:
                for line in proc.stderr:
                    stderr_lines.append(line)
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=err_reader, daemon=True).start()

        client_label = server_label = None
        final = None
        seen_progress = False
        last_download_mbps = None
        last_upload_mbps = None
        log_events = []
        started = time.monotonic()
        last_line_at = started
        cancelled_result = False
        stall_reason = None
        try:
            while True:
                if cancelled():
                    _kill_process_tree(proc)
                    cancelled_result = True
                    break
                now = time.monotonic()
                if now - started > self.MAX_RUNTIME_SECONDS:
                    _kill_process_tree(proc)
                    stall_reason = (
                        f"Watchdog: test exceeded {self.MAX_RUNTIME_SECONDS}s max runtime"
                    )
                    break
                if now - last_line_at > self.STALL_SECONDS:
                    _kill_process_tree(proc)
                    stall_reason = (
                        f"Watchdog: no progress for {self.STALL_SECONDS}s"
                    )
                    break
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    break
                last_line_at = time.monotonic()
                event = parse_ookla_line(line)
                if event is None:
                    continue
                kind = event.get("type")
                if kind == "testStart":
                    client_label, server_label = labels_from_test_start(event)
                elif kind == "log":
                    msg = event.get("message")
                    if msg:
                        log_events.append(str(msg))
                elif kind in ("ping", "download", "upload"):
                    seen_progress = True
                    prog = ookla_progress_event(event)
                    if kind == "download":
                        last_download_mbps = prog.get("download_mbps")
                    elif kind == "upload":
                        last_upload_mbps = prog.get("upload_mbps")
                    emit(prog)
                elif kind == "result":
                    final = result_to_final(event, client_label, server_label, self.name)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)
        finally:
            _kill_process_tree(proc)
            # Collect stderr briefly so the tail is available for errors.
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

        if cancelled_result:
            return None
        detail_bits = []
        if log_events:
            detail_bits.append(" | ".join(log_events[-3:]))
        err_text = "".join(stderr_lines).strip()
        if err_text:
            detail_bits.append(err_text[-500:])
        detail = " ".join(detail_bits).strip()

        def _partial():
            return {
                "download_mbps": round(last_download_mbps, 2)
                if last_download_mbps is not None else None,
                "upload_mbps": round(last_upload_mbps, 2)
                if last_upload_mbps is not None else None,
                "client": client_label,
                "server": server_label,
                "engine": self.name,
                "detail": detail or None,
            }

        if stall_reason:
            if seen_progress:
                raise PartialTestError(stall_reason, _partial())
            raise RuntimeError(stall_reason)
        if proc.returncode not in (0, None):
            if not seen_progress and final is None:
                raise PreStartError(
                    f"Ookla CLI failed before start (rc={proc.returncode})"
                    + (f": {detail}" if detail else "")
                )
            if final is None:
                msg = f"Ookla CLI failed mid-test (rc={proc.returncode})"
                if detail:
                    msg += f": {detail}"
                raise PartialTestError(msg, _partial())
        if final is None:
            if not seen_progress:
                raise PreStartError("Ookla CLI produced no progress events")
            msg = "Ookla CLI finished without a result event"
            if detail:
                msg += f": {detail}"
            raise PartialTestError(msg, _partial())
        return final


def _kill_process_tree(proc):
    """Best-effort kill of the child tree; never leave orphans."""
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, Exception):
        try:
            proc.kill()
        except Exception:
            pass


def parse_ookla_line(line):
    """Parse one JSONL line; unknown/malformed lines return None."""
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or "type" not in obj:
        return None
    return obj


def bandwidth_to_mbps(bandwidth_bps):
    """Ookla bandwidth (bytes/sec) to Mbps; None-safe."""
    if bandwidth_bps is None:
        return None
    return round(float(bandwidth_bps) * 8.0 / 1_000_000, 3)


def labels_from_test_start(event):
    isp = event.get("isp") or "Unknown ISP"
    iface = event.get("interface") or {}
    server = event.get("server") or {}
    # Never store MAC or internal IP; mask the external IP at source.
    client = mask_ip(f"{isp} · {iface.get('externalIp') or '?'}")
    name = server.get("name") or "Unknown host"
    location = server.get("location") or "?"
    country = server.get("country") or "?"
    return client, f"{name} ({location}, {country})"


def ookla_progress_event(event):
    kind = event.get("type")
    if kind == "ping":
        ping = event.get("ping") or {}
        return {"phase": "ping", "ping_ms": ping.get("latency"),
                "jitter_ms": ping.get("jitter")}
    payload = event.get(kind) or {}
    mbps = bandwidth_to_mbps(payload.get("bandwidth"))
    if kind == "download":
        return {"phase": "download", "download_mbps": mbps, "upload_mbps": None}
    return {"phase": "upload", "download_mbps": None, "upload_mbps": mbps}


def result_to_final(event, client_label, server_label, engine_name):
    """Map an Ookla ``result`` event to the shared final-dict shape."""
    download = event.get("download") or {}
    upload = event.get("upload") or {}
    ping = event.get("ping") or {}
    if client_label is None or server_label is None:
        test_event = {"isp": event.get("isp"),
                      "interface": event.get("interface"),
                      "server": event.get("server")}
        c2, s2 = labels_from_test_start(test_event)
        client_label = client_label or c2
        server_label = server_label or s2
    download_mbps = bandwidth_to_mbps(download.get("bandwidth"))
    upload_mbps = bandwidth_to_mbps(upload.get("bandwidth"))
    final = {
        "download_mbps": round(download_mbps, 2) if download_mbps is not None else None,
        "upload_mbps": round(upload_mbps, 2) if upload_mbps is not None else None,
        "client": client_label,
        "server": server_label,
        "engine": engine_name,
        "ping_ms": ping.get("latency"),
        "jitter_ms": ping.get("jitter"),
    }
    return final


def get_live_source(name=None):
    """Return the live source.

    Explicit ``NETPULSE_LIVE_SOURCE=ookla`` requires Ookla. Explicit
    ``speedtestcli`` requires the Python source. Otherwise auto:
    Ookla when its binary is found, else the Python source.
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
        if find_ookla_binary():
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
